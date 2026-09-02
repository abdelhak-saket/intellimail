"""File d'attente HITL et journal des décisions humaines (SQLite).

Deux tables, deux rôles distincts :

- `queue`     : un e-mail escaladé = une ligne, avec tout ce qu'il faut à
                l'agent pour décider (e-mail brut ET masqué, brouillon,
                classification, raison d'escalade, trace des agents).
- `decisions` : une action humaine = une ligne, jamais modifiée ni supprimée.
                Qui, quoi, quand, et le brouillon final s'il a été édité.
                C'est le deuxième étage de la piste d'audit — le premier étant
                `decision_reason`, qui trace la règle automatique appliquée.

SQLite (stdlib) plutôt qu'un CSV : écritures atomiques, lectures concurrentes
API/Streamlit, et un historique qui ne se corrompt pas quand deux processus
écrivent en même temps.

Le corps brut (`body_raw`) contient de la PII en clair : la base reste locale,
au même titre que le SI. Elle n'est jamais envoyée au LLM.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent / "hitl_queue.db"

# Chemin de base surchargeable, par THREAD et non globalement : en mode démo
# publique, chaque visiteur travaille sur sa propre copie. Streamlit exécute
# chaque session dans son propre thread, donc un `threading.local` isole les
# visiteurs sans qu'ils se marchent dessus. Une simple variable globale ferait
# fuiter la base d'un visiteur vers un autre.
_tls = threading.local()


def set_db_path(path) -> None:
    """Fixe la base à utiliser pour ce thread (mode démo)."""
    _tls.db_path = Path(path)


def current_db_path() -> Path:
    """Base effective : surcharge de session si présente, sinon la base locale."""
    return getattr(_tls, "db_path", None) or DB_PATH

STATUS_PENDING = "pending"
STATUS_VALIDATED = "validated"    # brouillon approuvé, en attente d'envoi
STATUS_EDITED = "edited"          # brouillon corrigé, en attente d'envoi
STATUS_REJECTED = "rejected"      # brouillon écarté, traitement manuel
STATUS_SENT = "sent"              # effectivement envoyé par le robot

# Statuts pour lesquels le robot doit envoyer une réponse
APPROVED_STATUSES = (STATUS_VALIDATED, STATUS_EDITED)

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    job_id          TEXT,
    message_id      TEXT UNIQUE,
    email_from      TEXT,
    subject_raw     TEXT,
    body_raw        TEXT,
    subject_masked  TEXT,
    body_masked     TEXT,
    draft           TEXT,
    categorie       TEXT,
    priorite        TEXT,
    resume          TEXT,
    confiance       REAL,
    action          TEXT,
    decision_reason TEXT,
    judge_verdict   TEXT,
    judge_scores    TEXT,
    pii_entities    TEXT,
    pii_reinjection TEXT,
    contexts        TEXT,
    agent_trace     TEXT,
    cost_usd        REAL,
    duration_ms     INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status);

CREATE TABLE IF NOT EXISTS decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id      INTEGER NOT NULL,
    decided_at    TEXT NOT NULL,
    decided_by    TEXT NOT NULL,
    decision      TEXT NOT NULL,
    final_draft   TEXT,
    comment       TEXT,
    FOREIGN KEY (queue_id) REFERENCES queue(id)
);
CREATE INDEX IF NOT EXISTS idx_decisions_queue ON decisions(queue_id);
"""


@contextmanager
def _conn():
    con = sqlite3.connect(current_db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with _lock, _conn() as con:
        con.executescript(_SCHEMA)
        # Migration légère : CREATE TABLE IF NOT EXISTS n'ajoute pas les
        # colonnes apparues après coup sur une base déjà créée.
        cols = {r["name"] for r in con.execute("PRAGMA table_info(queue)")}
        for name, ddl in (("sent_at", "TEXT"), ("sent_by", "TEXT")):
            if name not in cols:
                con.execute(f"ALTER TABLE queue ADD COLUMN {name} {ddl}")


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False) if value is not None else ""


def enqueue(*, response, final_state: dict, request) -> Optional[int]:
    """Ajoute un e-mail escaladé à la file. Ne lève jamais : l'échec de la
    mise en file ne doit pas faire échouer le triage.

    Idempotent sur message_id : un retour du même e-mail ne crée pas de doublon.
    Retourne l'id en file, ou None.
    """
    try:
        init()
        row = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "job_id": request.job_id or "",
            "message_id": request.message_id or request.job_id or None,
            "email_from": request.email_from,
            "subject_raw": final_state.get("email_subject_raw", ""),
            "body_raw": final_state.get("email_body_raw", ""),
            "subject_masked": final_state.get("email_subject", ""),
            "body_masked": final_state.get("email_body", ""),
            "draft": response.draft_reply,
            "categorie": response.classification.categorie,
            "priorite": response.classification.priorite,
            "resume": response.classification.resume,
            "confiance": response.classification.confiance,
            "action": response.action,
            "decision_reason": response.decision_reason,
            "judge_verdict": response.critic.verdict or "",
            "judge_scores": _j(response.critic.scores),
            "pii_entities": _j(response.pii.entities),
            "pii_reinjection": _j(response.pii_reinjection),
            "contexts": _j(response.contexts_used),
            "agent_trace": _j([t.model_dump() for t in response.agent_trace]),
            "cost_usd": response.cost_usd_estimate,
            "duration_ms": response.total_duration_ms,
            "status": STATUS_PENDING,
        }
        cols = ",".join(row)
        marks = ",".join("?" * len(row))
        with _lock, _conn() as con:
            cur = con.execute(
                f"INSERT OR IGNORE INTO queue ({cols}) VALUES ({marks})",
                list(row.values()))
            return cur.lastrowid or None
    except Exception as e:
        print(f"[store] mise en file échouée (non bloquant) : {e}")
        return None


def list_queue(status: str = STATUS_PENDING, categorie: str = "",
               limit: int = 200) -> List[Dict[str, Any]]:
    """Cas de la file, du plus ancien au plus récent (FIFO)."""
    init()
    sql = "SELECT * FROM queue WHERE 1=1"
    args: list = []
    if status and status != "all":
        sql += " AND status = ?"
        args.append(status)
    if categorie:
        sql += " AND categorie = ?"
        args.append(categorie)
    sql += " ORDER BY created_at ASC, id ASC LIMIT ?"
    args.append(limit)
    with _conn() as con:
        return [dict(r) for r in con.execute(sql, args)]


def get_case(queue_id: int) -> Optional[Dict[str, Any]]:
    init()
    with _conn() as con:
        r = con.execute("SELECT * FROM queue WHERE id = ?", (queue_id,)).fetchone()
        return dict(r) if r else None


def record_decision(queue_id: int, decision: str, decided_by: str,
                    final_draft: str = "", comment: str = "") -> None:
    """Journalise une décision humaine et met à jour le statut du cas.

    Le journal est en append-only : une décision n'est jamais écrasée, une
    reprise de dossier ajoute une ligne. C'est ce qui rend la piste d'audit
    opposable.
    """
    if decision not in (STATUS_VALIDATED, STATUS_EDITED, STATUS_REJECTED):
        raise ValueError(
            f"décision inconnue : {decision} — attendu "
            f"{STATUS_VALIDATED} | {STATUS_EDITED} | {STATUS_REJECTED}")
    init()
    with _lock, _conn() as con:
        con.execute(
            "INSERT INTO decisions (queue_id, decided_at, decided_by, decision,"
            " final_draft, comment) VALUES (?,?,?,?,?,?)",
            (queue_id,
             datetime.now(timezone.utc).isoformat(timespec="seconds"),
             decided_by, decision, final_draft, comment))
        con.execute("UPDATE queue SET status = ? WHERE id = ?", (decision, queue_id))


def final_draft(queue_id: int) -> str:
    """Texte à envoyer : la dernière version validée par un humain si elle
    existe, sinon le brouillon d'origine."""
    hist = decisions_for(queue_id)
    for d in reversed(hist):
        if d["decision"] in APPROVED_STATUSES and (d["final_draft"] or "").strip():
            return d["final_draft"]
    case = get_case(queue_id)
    return (case or {}).get("draft", "") or ""


def list_approved(limit: int = 100) -> List[Dict[str, Any]]:
    """Cas approuvés par un humain et pas encore envoyés — c'est ce que le
    robot UiPath vient chercher. Le brouillon retourné est la version finale
    (corrigée le cas échéant) et la carte de réinjection PII l'accompagne."""
    init()
    marks = ",".join("?" * len(APPROVED_STATUSES))
    with _conn() as con:
        rows = [dict(r) for r in con.execute(
            f"SELECT * FROM queue WHERE status IN ({marks}) AND sent_at IS NULL"
            f" ORDER BY id LIMIT ?", (*APPROVED_STATUSES, limit))]
    for r in rows:
        r["final_draft"] = final_draft(r["id"])
    return rows


def mark_sent(queue_id: int, sent_by: str = "uipath") -> bool:
    """Marque un cas comme effectivement envoyé. Idempotent : un second appel
    ne réécrit pas l'horodatage (protection contre le double envoi)."""
    init()
    with _lock, _conn() as con:
        cur = con.execute(
            "UPDATE queue SET status = ?, sent_at = ?, sent_by = ?"
            " WHERE id = ? AND sent_at IS NULL",
            (STATUS_SENT,
             datetime.now(timezone.utc).isoformat(timespec="seconds"),
             sent_by, queue_id))
        return cur.rowcount > 0


def decisions_for(queue_id: int) -> List[Dict[str, Any]]:
    init()
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM decisions WHERE queue_id = ? ORDER BY id", (queue_id,))]


def stats() -> Dict[str, Any]:
    """Compteurs pour l'en-tête de l'UI."""
    init()
    with _conn() as con:
        by_status = {r["status"]: r["n"] for r in con.execute(
            "SELECT status, COUNT(*) n FROM queue GROUP BY status")}
        by_reason = {r["decision_reason"]: r["n"] for r in con.execute(
            "SELECT decision_reason, COUNT(*) n FROM queue"
            " GROUP BY decision_reason ORDER BY n DESC")}
        total_dec = con.execute("SELECT COUNT(*) n FROM decisions").fetchone()["n"]
    return {"by_status": by_status, "by_reason": by_reason,
            "total_decisions": total_dec,
            "pending": by_status.get(STATUS_PENDING, 0)}


def export_decisions_csv(path: Path) -> int:
    """Exporte le journal joint à la file — alimente le dashboard Power BI."""
    import csv
    init()
    with _conn() as con:
        rows = [dict(r) for r in con.execute("""
            SELECT q.id, q.created_at, q.message_id, q.categorie, q.priorite,
                   q.confiance, q.action, q.decision_reason, q.judge_verdict,
                   q.cost_usd, q.duration_ms, q.status,
                   d.decided_at, d.decided_by, d.decision, d.comment
            FROM queue q LEFT JOIN decisions d ON d.queue_id = q.id
            ORDER BY q.id, d.id""")]
    if not rows:
        return 0
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return len(rows)
