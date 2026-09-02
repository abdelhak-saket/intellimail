"""Logging métriques — une ligne CSV par email traité.

Fichier : metrics/metrics.csv (créé automatiquement, header inclus).
Sert de base aux chiffres portfolio : taux AUTO vs HITL, score judge moyen,
PII masquées, latence — et au suivi qualité par version de prompt.
"""
import csv
import threading
from datetime import datetime, timezone
from pathlib import Path

METRICS_DIR = Path(__file__).parent / "metrics"
METRICS_FILE = METRICS_DIR / "metrics.csv"

# Table de runs (1 email = 1 ligne) — directement branchable Power BI :
# date, catégorie, verdict, latence, coût, décision humaine.
_FIELDS = [
    "timestamp_utc", "job_id", "message_id",
    "categorie", "priorite", "confiance",
    "pii_total", "pii_entities", "pii_engine",
    "judge_verdict", "judge_pertinence", "judge_ton",
    "judge_conformite", "judge_factualite", "judge_score",
    "drafter_retries", "action", "requires_human", "decision_reason",
    "tokens_in", "tokens_out", "cost_usd", "human_decision",
    "duration_ms", "errors",
    "tpl_classifier", "tpl_drafter", "tpl_judge",
]

_lock = threading.Lock()


def _rotate_if_schema_changed() -> None:
    """Si le CSV existant a un ancien header, on l'archive (metrics_legacy_*.csv)
    pour garder chaque fichier cohérent colonne par colonne."""
    if not METRICS_FILE.exists():
        return
    try:
        with METRICS_FILE.open(encoding="utf-8") as f:
            header = f.readline().strip()
        if header and header != ",".join(_FIELDS):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            METRICS_FILE.rename(METRICS_DIR / f"metrics_legacy_{stamp}.csv")
    except Exception:
        pass


def log_email(row: dict) -> None:
    """Ajoute une ligne au CSV. Ne lève jamais — le logging ne doit pas
    faire échouer le triage."""
    try:
        METRICS_DIR.mkdir(exist_ok=True)
        _rotate_if_schema_changed()
        new_file = not METRICS_FILE.exists()
        with _lock, METRICS_FILE.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDS, extrasaction="ignore")
            if new_file:
                writer.writeheader()
            row.setdefault("timestamp_utc",
                           datetime.now(timezone.utc).isoformat(timespec="seconds"))
            writer.writerow(row)
    except Exception as e:
        print(f"[metrics] échec logging (non bloquant) : {e}")
