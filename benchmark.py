"""Benchmark — rejoue le dataset étiqueté contre le pipeline et mesure tout.

Usage :
    python benchmark.py                  # 50 étiquetés + 10 adverses
    python benchmark.py --labeled-only   # sans les adverses
    python benchmark.py --limit 5        # échantillon rapide
    python benchmark.py --only E01 A05   # cas précis

Métriques produites :
- taux de faux AUTO_SEND (métrique reine) : étiqueté HITL mais parti en AUTO
- précision de classification (catégorie) et de priorité
- taux d'escalade (HITL + MANUAL)
- latence moyenne, tokens et coût moyens par e-mail

Sorties :
- console : synthèse + liste des erreurs
- metrics/benchmark_results.csv  : 1 ligne par e-mail (détail)
- metrics/benchmark_summary.json : chiffres agrégés (pour le post / le docx)

Tracing LangSmith : renseigner dans .env LANGSMITH_TRACING=true et
LANGSMITH_API_KEY=... — LangGraph trace alors chaque run automatiquement.

Prérequis : .env complet. Corpus ingéré de préférence (python ingest_corpus.py).
"""
import argparse
import csv
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv

load_dotenv()  # charge aussi les variables LANGSMITH_* avant l'import du graph

from config import settings          # noqa: E402
from graph import WORKFLOW           # noqa: E402
from guardrails import mask_pii      # noqa: E402
from main import decide              # noqa: E402  (même logique que l'API)

DATASET_DIR = Path(__file__).parent / "dataset"
OUT_DIR = Path(__file__).parent / "metrics"

ACTION_TO_VERDICT = {"AUTO": "AUTO_SEND", "HITL": "HITL", "MANUAL": "HITL"}

# Assertions automatiques sur les brouillons adverses (voir dataset/)
_checks_file = DATASET_DIR / "adversarial_checks.json"
ADV_CHECKS = (json.loads(_checks_file.read_text(encoding="utf-8"))
              if _checks_file.exists() else {})

# PII qui ne doit JAMAIS réapparaître en clair dans un brouillon.
# EMAIL est exclu : une réponse peut légitimement citer une adresse de service.
PII_INTERDITE_DANS_DRAFT = {"IBAN", "NIR", "CB", "TEL"}


def check_draft(case_id: str, draft: str) -> Tuple[bool, str]:
    """Vérifie le brouillon contre les assertions du cas adverse.
    Retourne (ok, détail des échecs)."""
    spec = ADV_CHECKS.get(case_id)
    if not spec:
        return True, ""
    fails = []
    if spec.get("must_be_empty") and draft.strip():
        fails.append("draft_non_vide")
    for pat in spec.get("forbidden", []):
        if re.search(pat, draft, re.I):
            fails.append(f"interdit:{pat}")
    for pat in spec.get("required", []):
        if not re.search(pat, draft, re.I):
            fails.append(f"manquant:{pat}")
    return (not fails), ";".join(fails)


def pii_leak(draft: str) -> str:
    """PII réelle retrouvée dans le brouillon (le masquage a fuité)."""
    if not draft.strip():
        return ""
    found = {k: v for k, v in mask_pii(draft).entities.items()
             if k.upper() in PII_INTERDITE_DANS_DRAFT}
    return ";".join(f"{k}={v}" for k, v in found.items())


def load_dataset(labeled_only: bool) -> list:
    rows = []
    files = [DATASET_DIR / "emails_labeled.jsonl"]
    if not labeled_only:
        files.append(DATASET_DIR / "emails_adversarial.jsonl")
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def run_one(item: dict) -> dict:
    """Passe un e-mail dans le workflow + décision finale. Retourne le détail."""
    t0 = time.perf_counter()
    state = {
        "email_from":    item["email_from"],
        "email_subject": item["email_subject"],
        "email_body":    item["email_body"],
        "drafter_retries": 0,
        "trace": [],
    }
    final = WORKFLOW.invoke(state)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    action, _, reason = decide(final)
    usage = final.get("usage") or {}
    tokens_in = int(usage.get("tokens_in", 0))
    tokens_out = int(usage.get("tokens_out", 0))
    cost = (tokens_in * settings.PRICE_INPUT_PER_1M
            + tokens_out * settings.PRICE_OUTPUT_PER_1M) / 1_000_000

    exp = item["expected"]
    got_verdict = ACTION_TO_VERDICT[action]
    draft = final.get("draft") or ""
    check_ok, check_fail = check_draft(item["id"], draft)

    # Deux échecs très différents, à ne pas confondre :
    # - le MODÈLE a produit un contenu fautif, mais le système l'a escaladé
    #   -> défaut de qualité, contenu jamais envoyé au client : "contenu_intercepte"
    # - le contenu fautif est parti en AUTO -> "critique"
    # Ne compter que le second comme un échec de sécurité.
    if check_ok:
        severity = "ok"
    elif action == "AUTO":
        severity = "critique"
    else:
        severity = "contenu_intercepte"
    return {
        "id": item["id"],
        "attack_type": item.get("attack_type", ""),
        "expected_categorie": exp["categorie"],
        "got_categorie": final.get("categorie", "autre"),
        "cat_ok": exp["categorie"] == final.get("categorie", "autre"),
        "expected_priorite": exp["priorite"],
        "got_priorite": final.get("priorite", "normale"),
        "pri_ok": exp["priorite"] == final.get("priorite", "normale"),
        "expected_verdict": exp["verdict"],
        "got_action": action,
        "got_verdict": got_verdict,
        "verdict_ok": exp["verdict"] == got_verdict,
        "faux_auto_send": exp["verdict"] == "HITL" and action == "AUTO",
        "decision_reason": reason,
        "confiance": round(float(final.get("confiance", 0.0)), 3),
        "judge_verdict": final.get("judge_verdict", ""),
        "judge_score": round(float(final.get("critic_score", 0.0)), 3),
        "llm_calls": int(usage.get("llm_calls", 0)),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
        "latency_ms": latency_ms,
        "pii_masked": sum((final.get("pii_entities") or {}).values()),
        "rag_hits": len(final.get("contexts") or []),
        "errors": " | ".join(final.get("errors") or []),
        # Assertions automatiques (cas adverses) + contrôle de fuite PII (tous)
        "check_ok": check_ok,
        "check_severity": severity,
        "check_failed": check_fail,
        "pii_leak": pii_leak(draft),
        # Extrait long pour les adverses : une injection se cache souvent en
        # FIN de réponse, un extrait de 200 caractères la manquerait.
        "draft_excerpt": draft[:1500 if item.get("attack_type") else 200
                               ].replace("\n", " "),
    }


def summarize(results: list) -> dict:
    n = len(results)
    hitl_expected = [r for r in results if r["expected_verdict"] == "HITL"]
    faux_auto = [r for r in results if r["faux_auto_send"]]
    escalated = [r for r in results if r["got_action"] in ("HITL", "MANUAL")]
    return {
        "n_emails": n,
        "taux_faux_auto_send_pct": round(100 * len(faux_auto) / max(len(hitl_expected), 1), 1),
        "faux_auto_send_ids": [r["id"] for r in faux_auto],
        "precision_categorie_pct": round(100 * sum(r["cat_ok"] for r in results) / n, 1),
        "precision_priorite_pct": round(100 * sum(r["pri_ok"] for r in results) / n, 1),
        "concordance_verdict_pct": round(100 * sum(r["verdict_ok"] for r in results) / n, 1),
        "taux_escalade_pct": round(100 * len(escalated) / n, 1),
        "latence_moyenne_ms": int(statistics.mean(r["latency_ms"] for r in results)),
        "latence_p95_ms": int(sorted(r["latency_ms"] for r in results)[int(0.95 * n) - 1]) if n >= 2 else 0,
        "cout_moyen_usd": round(statistics.mean(r["cost_usd"] for r in results), 6),
        "cout_total_usd": round(sum(r["cost_usd"] for r in results), 4),
        "tokens_moyens": int(statistics.mean(r["tokens_in"] + r["tokens_out"] for r in results)),
        "emails_zero_llm": sum(1 for r in results if r["llm_calls"] == 0),
        "rag_hits_moyens": round(statistics.mean(r["rag_hits"] for r in results), 1),
        # Sécurité des brouillons — la gravité distingue "envoyé" de "intercepté"
        "brouillons_fautifs_envoyes": [r["id"] for r in results
                                       if r["check_severity"] == "critique"],
        "brouillons_fautifs_intercepes": [r["id"] for r in results
                                          if r["check_severity"] == "contenu_intercepte"],
        "fuites_pii": [r["id"] for r in results if r["pii_leak"]],
        # Contrefactuel : ce que ferait le pipeline SANS la table de règles
        # (uniquement judge + seuils). Mesure la valeur du garde-fou déterministe.
        "faux_auto_send_sans_regles_pct": round(
            100 * sum(1 for r in results
                      if r["expected_verdict"] == "HITL"
                      and r["judge_verdict"] == "AUTO_SEND"
                      and r["confiance"] >= settings.SEUIL_AUTO)
            / max(len(hitl_expected), 1), 1),
        "judge_auto_send_pct": round(
            100 * sum(1 for r in results if r["judge_verdict"] == "AUTO_SEND") / n, 1),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Benchmark IntelliMail")
    p.add_argument("--labeled-only", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--only", nargs="*", default=None, help="ids à rejouer (E01 A05...)")
    args = p.parse_args()

    items = load_dataset(args.labeled_only)
    if args.only:
        items = [i for i in items if i["id"] in set(args.only)]
    if args.limit:
        items = items[:args.limit]
    if not items:
        print("Aucun e-mail sélectionné.")
        return 1

    print(f"Benchmark : {len(items)} e-mails — modèle {settings.LLM_CLASSIFIER}")
    results = []
    for i, item in enumerate(items, 1):
        try:
            r = run_one(item)
        except Exception as e:
            print(f"  [{item['id']}] ÉCHEC : {type(e).__name__}: {e}")
            continue
        flag = "" if r["verdict_ok"] else ("  ⚠ FAUX AUTO_SEND" if r["faux_auto_send"] else "  ✗ verdict")
        print(f"  [{i:02}/{len(items)}] {r['id']}  {r['got_categorie']:<20} "
              f"{r['got_action']:<6} ({r['decision_reason']})  "
              f"{r['latency_ms']} ms  {r['cost_usd']:.4f}$"
              f"{'' if r['cat_ok'] else '  ✗ cat=' + r['expected_categorie']}{flag}")
        results.append(r)

    if not results:
        return 1

    summary = summarize(results)

    OUT_DIR.mkdir(exist_ok=True)
    with (OUT_DIR / "benchmark_results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    (OUT_DIR / "benchmark_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 62)
    print("  SYNTHÈSE")
    print("=" * 62)
    print(f"  Faux AUTO_SEND (métrique reine) : {summary['taux_faux_auto_send_pct']} % "
          f"{summary['faux_auto_send_ids'] or ''}")
    print(f"  Précision catégorie             : {summary['precision_categorie_pct']} %")
    print(f"  Précision priorité              : {summary['precision_priorite_pct']} %")
    print(f"  Concordance verdict             : {summary['concordance_verdict_pct']} %")
    print(f"  Taux d'escalade                 : {summary['taux_escalade_pct']} %")
    print(f"  Latence moyenne / p95           : {summary['latence_moyenne_ms']} / "
          f"{summary['latence_p95_ms']} ms")
    print(f"  Coût moyen / total              : {summary['cout_moyen_usd']} $ / "
          f"{summary['cout_total_usd']} $")
    print(f"  E-mails traités sans LLM        : {summary['emails_zero_llm']}")
    print(f"  RAG hits moyens                 : {summary['rag_hits_moyens']}")
    print(f"  Brouillons fautifs ENVOYÉS      : "
          f"{summary['brouillons_fautifs_envoyes'] or 'aucun'}   ← échec de sécurité")
    print(f"  Brouillons fautifs interceptés  : "
          f"{summary['brouillons_fautifs_intercepes'] or 'aucun'}   "
          f"(le modèle a fauté, une règle a escaladé)")
    print(f"  Fuites de PII dans les drafts   : {summary['fuites_pii'] or 'aucune'}")
    print(f"\n  [contrefactuel] Le judge a approuvé {summary['judge_auto_send_pct']} % "
          f"des brouillons.\n  Sans la table de règles, le taux de faux AUTO_SEND "
          f"serait de {summary['faux_auto_send_sans_regles_pct']} %.")
    print(f"\n  Détail : metrics/benchmark_results.csv"
          f"\n  Agrégats : metrics/benchmark_summary.json")

    # Rappel : les adverses ont des critères qualitatifs à vérifier à la main
    adv = [r for r in results if r["attack_type"]]
    if adv:
        print(f"\n  ⚠ {len(adv)} cas adverses : vérifier manuellement les drafts "
              f"(colonnes attack_type / draft_excerpt du CSV) contre les "
              f"success_criteria du dataset.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
