"""Mode démo publique — file d'attente isolée par visiteur, sans backend.

Pourquoi ce module
------------------
L'écran HITL déployé publiquement (Streamlit Community Cloud) pose trois
problèmes que ce module résout :

1. **Pas d'appel LLM.** L'app lit une file pré-calculée. Sans ce garde-fou, un
   visiteur pourrait déclencher des appels Azure facturés sur votre quota.
2. **Pas d'état partagé.** Sans isolation, le premier visiteur qui valide tout
   laisse une file vide au suivant. Chaque session reçoit sa propre copie de la
   base, dans un fichier temporaire.
3. **Pas de base persistante.** `hitl_queue.db` est exclu du dépôt : la base de
   session est reconstruite depuis `demo/demo_fixture.json`, versionné.

Activation : variable d'environnement `DEMO_MODE=true` (ou secret Streamlit).
"""
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

import store

FIXTURE = Path(__file__).parent / "demo" / "demo_fixture.json"
_PREFIXE = "intellimail_demo_"


def is_demo() -> bool:
    return os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes", "oui")


def fixture_disponible() -> bool:
    return FIXTURE.is_file()


def _chemin_session(session_id: str) -> Path:
    return Path(tempfile.gettempdir()) / f"{_PREFIXE}{session_id}.db"


def _charger_fixture(db: Path) -> int:
    """Crée la base de session et y injecte les cas figés. Retourne le nombre
    de cas chargés."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    queue = data.get("queue", [])
    decisions = data.get("decisions", [])

    store.set_db_path(db)
    store.init()          # crée le schéma + applique les migrations

    con = sqlite3.connect(db)
    try:
        for table, lignes in (("queue", queue), ("decisions", decisions)):
            if not lignes:
                continue
            # On n'insère que les colonnes réellement présentes dans le schéma :
            # la fixture peut venir d'une version antérieure du store.
            colonnes_schema = {r[1] for r in
                               con.execute(f"PRAGMA table_info({table})")}
            for ligne in lignes:
                cols = [c for c in ligne if c in colonnes_schema]
                marks = ",".join("?" * len(cols))
                con.execute(
                    f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) "
                    f"VALUES ({marks})", [ligne[c] for c in cols])
        con.commit()
    finally:
        con.close()
    return len(queue)


def preparer_session(session_id: str) -> Optional[Path]:
    """Prépare (ou retrouve) la base de ce visiteur et la rend active.

    Retourne le chemin, ou None si la fixture manque.
    """
    if not fixture_disponible():
        return None
    db = _chemin_session(session_id)
    if not db.exists():
        _charger_fixture(db)
    else:
        store.set_db_path(db)
    return db


def reinitialiser(session_id: str) -> None:
    """Efface la base du visiteur : la file repart de la fixture."""
    db = _chemin_session(session_id)
    if db.exists():
        try:
            db.unlink()
        except OSError:
            pass
    preparer_session(session_id)


def purger_anciennes(age_heures: float = 12.0) -> int:
    """Supprime les bases des sessions abandonnées. Appelé au démarrage pour
    éviter d'accumuler des fichiers dans le répertoire temporaire."""
    import time
    limite = time.time() - age_heures * 3600
    n = 0
    for f in Path(tempfile.gettempdir()).glob(f"{_PREFIXE}*.db"):
        try:
            if f.stat().st_mtime < limite:
                f.unlink()
                n += 1
        except OSError:
            pass
    return n


def info_fixture() -> dict:
    """Métadonnées de la fixture, pour affichage dans le bandeau."""
    if not fixture_disponible():
        return {}
    try:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        return {"genere_le": data.get("genere_le", ""),
                "cas": len(data.get("queue", []))}
    except Exception:
        return {}
