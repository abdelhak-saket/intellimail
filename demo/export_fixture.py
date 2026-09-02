"""Exporte la file HITL locale vers une fixture versionnée pour la démo en ligne.

La démo publique (Streamlit Community Cloud) n'a ni backend, ni clé Azure, ni
base persistante : elle rejoue des cas figés. Ce script capture l'état réel de
votre base après un run — vrais brouillons, vrais motifs d'escalade, vraies
notes du judge — pour que la démo montre le système tel qu'il fonctionne, et
non des données inventées.

Usage :
    python seed_queue.py --reset --parallel 4   # remplir la file
    python demo/export_fixture.py               # capturer

Produit `demo/demo_fixture.json`, à committer.

Attention : les corps bruts contiennent la PII du dataset. Elle est synthétique
(aucun client réel), mais le fichier devient public — d'où le contrôle ci-dessous
qui refuse d'exporter si un e-mail hors dataset s'est glissé dans la file.
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import store  # noqa: E402

SORTIE = Path(__file__).parent / "demo_fixture.json"
DATASET = RACINE / "dataset"


def expediteurs_du_dataset() -> set:
    """Adresses présentes dans le dataset — les seules autorisées à l'export."""
    out = set()
    for nom in ("emails_labeled.jsonl", "emails_adversarial.jsonl"):
        f = DATASET / nom
        if f.exists():
            for ligne in f.read_text(encoding="utf-8").splitlines():
                if ligne.strip():
                    out.add(json.loads(ligne)["email_from"].strip().lower())
    return out


def main() -> int:
    base = store.current_db_path()
    if not base.exists():
        print(f"Base introuvable : {base}\n"
              f"Lancez d'abord l'API puis « python seed_queue.py --reset ».")
        return 1

    con = sqlite3.connect(base)
    con.row_factory = sqlite3.Row
    queue = [dict(r) for r in con.execute("SELECT * FROM queue ORDER BY id")]
    decisions = [dict(r) for r in con.execute("SELECT * FROM decisions ORDER BY id")]
    con.close()

    if not queue:
        print("La file est vide — rien à exporter.")
        return 1

    # Garde-fou : aucune adresse étrangère au dataset ne doit devenir publique
    autorisees = expediteurs_du_dataset()
    intrus = sorted({c["email_from"] for c in queue
                     if (c["email_from"] or "").strip().lower() not in autorisees})
    if intrus:
        print("EXPORT REFUSÉ — expéditeurs absents du dataset :")
        for a in intrus:
            print(f"  • {a}")
        print("\nCes e-mails ne viennent pas du jeu de test synthétique et "
              "deviendraient publics.\nPurgez la file "
              "(« python seed_queue.py --reset ») puis recommencez.")
        return 2

    fixture = {
        "_avertissement": "Données synthétiques. Aucun client réel. "
                          "Généré par demo/export_fixture.py.",
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "queue": queue,
        "decisions": decisions,
    }
    SORTIE.write_text(json.dumps(fixture, ensure_ascii=False, indent=1),
                      encoding="utf-8")

    motifs = {}
    for c in queue:
        motifs[c["decision_reason"]] = motifs.get(c["decision_reason"], 0) + 1
    print(f"Exporté : {len(queue)} cas, {len(decisions)} décision(s) "
          f"→ {SORTIE.relative_to(RACINE)}")
    print(f"Taille : {SORTIE.stat().st_size // 1024} Ko")
    print("\nMotifs d'escalade capturés :")
    for m, n in sorted(motifs.items(), key=lambda kv: -kv[1]):
        print(f"  {n:2}×  {m}")
    if len(motifs) < 5:
        print("\n⚠ Peu de motifs différents : relancez seed_queue.py sans "
              "--only pour une démo plus représentative.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
