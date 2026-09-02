"""Prompts système des agents — chargés depuis templates/ (versionnés).

Industrialisation des templates :
- Chaque prompt vit dans templates/<agent>_v<MAJ.MIN>.txt
- Par défaut, la version la plus récente est chargée (tri sémantique)
- Une version peut être épinglée via .env : TEMPLATE_CLASSIFIER_VERSION=1.0
- Les versions chargées sont exposées dans LOADED_VERSIONS (logging/traçabilité)

Rétro-compatibilité : CLASSIFIER_SYSTEM, DRAFTER_SYSTEM, CRITIC_SYSTEM
restent importables comme avant (graph.py inchangé sur ce point).
"""
import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

TEMPLATES_DIR = Path(__file__).parent / "templates"

_VERSION_RE = re.compile(r"^(?P<name>[a-z_]+)_v(?P<maj>\d+)\.(?P<min>\d+)\.txt$")


def _available_versions(name: str) -> Dict[Tuple[int, int], Path]:
    """Toutes les versions disponibles pour un template donné."""
    out: Dict[Tuple[int, int], Path] = {}
    if not TEMPLATES_DIR.is_dir():
        return out
    for f in TEMPLATES_DIR.iterdir():
        m = _VERSION_RE.match(f.name)
        if m and m.group("name") == name:
            out[(int(m.group("maj")), int(m.group("min")))] = f
    return out


def load_template(name: str, version: Optional[str] = None) -> Tuple[str, str]:
    """Charge un template par nom. Retourne (contenu, version).

    version : "1.0" pour épingler, None pour la plus récente.
    L'épinglage peut aussi venir de l'env : TEMPLATE_<NAME>_VERSION.
    """
    version = version or os.getenv(f"TEMPLATE_{name.upper()}_VERSION")
    versions = _available_versions(name)
    if not versions:
        raise FileNotFoundError(
            f"Aucun template '{name}_vX.Y.txt' trouvé dans {TEMPLATES_DIR}")

    if version:
        maj, min_ = (int(x) for x in version.split("."))
        key = (maj, min_)
        if key not in versions:
            raise FileNotFoundError(
                f"Template {name} v{version} introuvable. "
                f"Disponibles : {sorted(versions)}")
    else:
        key = max(versions)

    content = versions[key].read_text(encoding="utf-8")
    return content, f"{key[0]}.{key[1]}"


# ─── Chargement au démarrage ────────────────────────────────────────────
CLASSIFIER_SYSTEM, _v_classifier = load_template("classifier")
DRAFTER_SYSTEM,    _v_drafter    = load_template("drafter")
JUDGE_SYSTEM,      _v_judge      = load_template("judge")

# Alias rétro-compatible (ancien nom utilisé par graph.py / tests)
CRITIC_SYSTEM = JUDGE_SYSTEM

LOADED_VERSIONS = {
    "classifier": _v_classifier,
    "drafter":    _v_drafter,
    "judge":      _v_judge,
}


RESEARCHER_NOTE = """[Phase 2 placeholder] Aucun RAG branché.
Phase 3 ajoutera ChromaDB + embeddings pour récupérer les 5 contextes
les plus proches (FAQ, procédures, réponses-types) et les passer ici."""
