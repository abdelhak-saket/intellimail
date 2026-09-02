"""Réglages modifiables à chaud par l'UI HITL, sans redémarrer l'API.

Pourquoi ce fichier
-------------------
`config.Settings` est chargé une fois à l'import : parfait pour les secrets et
les paramètres d'infrastructure, inutilisable pour les réglages métier que
l'agent humain doit pouvoir ajuster depuis l'écran de validation (seuils de
confiance, catégories à escalade forcée).

Ce module lit un JSON d'overrides et le relit automatiquement dès que le
fichier change (contrôle de mtime). Les valeurs absentes retombent sur
`settings`. Aucune dépendance, aucun redémarrage.

Toute modification est tracée : `updated_at` et `updated_by` sont écrits dans
le fichier — c'est un paramètre de décision, il doit être auditable.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from config import settings

CONFIG_FILE = Path(__file__).parent / "runtime_config.json"

# Clés pilotables depuis l'UI + leur valeur de repli (issue de .env)
_DEFAULTS_FROM_SETTINGS = {
    "SEUIL_AUTO":                "SEUIL_AUTO",
    "SEUIL_HITL":                "SEUIL_HITL",
    "CRITIC_APPROVE_THRESHOLD":  "CRITIC_APPROVE_THRESHOLD",
    "HITL_FORCE_CATEGORIES":     "HITL_FORCE_CATEGORIES",
    "HITL_FORCE_PRIORITIES":     "HITL_FORCE_PRIORITIES",
    "SENSITIVE_RULES_ENABLED":   "SENSITIVE_RULES_ENABLED",
    "OUTPUT_GUARDRAIL_ENABLED":  "OUTPUT_GUARDRAIL_ENABLED",
}

_lock = threading.Lock()
_cache: Dict[str, Any] = {}
# None = jamais chargé. Ne PAS initialiser à -1.0 : c'est la valeur sentinelle
# de « fichier absent », et la collision empêcherait le premier chargement
# quand aucun override n'existe (cache vide -> KeyError).
_cache_mtime: Optional[float] = None


def defaults() -> Dict[str, Any]:
    """Valeurs de référence issues de .env (aucun override appliqué)."""
    return {k: getattr(settings, attr) for k, attr in _DEFAULTS_FROM_SETTINGS.items()}


def _load() -> Dict[str, Any]:
    """Recharge le JSON si son mtime a changé. Jamais d'exception : un fichier
    corrompu ne doit pas bloquer le triage, on retombe sur les défauts."""
    global _cache, _cache_mtime
    try:
        mtime = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else -1.0
    except OSError:
        mtime = -1.0

    with _lock:
        if mtime != _cache_mtime:
            values = defaults()
            if mtime > 0:
                try:
                    raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                    for k in _DEFAULTS_FROM_SETTINGS:
                        if k in raw:
                            values[k] = raw[k]
                except Exception as e:
                    print(f"[runtime_config] JSON illisible, défauts appliqués : {e}")
            _cache, _cache_mtime = values, mtime
        return dict(_cache)


class _RuntimeSettings:
    """Vue lecture seule combinant overrides + settings.

    Expose la même interface que `config.settings` pour les clés pilotables
    (dont les propriétés `hitl_force_set` / `hitl_force_priority_set`), et
    délègue tout le reste à `settings`. Permet d'écrire `rules.evaluate(final,
    current())` sans changer la signature.
    """

    def __getattr__(self, name: str) -> Any:
        values = _load()
        if name in values:
            return values[name]
        return getattr(settings, name)

    @property
    def hitl_force_set(self) -> set:
        raw = _load()["HITL_FORCE_CATEGORIES"]
        return {c.strip().lower() for c in str(raw).split(",") if c.strip()}

    @property
    def hitl_force_priority_set(self) -> set:
        raw = _load()["HITL_FORCE_PRIORITIES"]
        return {p.strip().lower() for p in str(raw).split(",") if p.strip()}


_runtime = _RuntimeSettings()


def current() -> _RuntimeSettings:
    """Réglages effectifs (overrides + .env). À appeler à chaque requête."""
    return _runtime


def as_dict() -> Dict[str, Any]:
    """Valeurs effectives, pour affichage dans l'UI."""
    return _load()


def save(values: Dict[str, Any], updated_by: str = "hitl-ui") -> Dict[str, Any]:
    """Écrit les overrides. Seules les clés pilotables sont retenues.
    Retourne les valeurs effectives après écriture."""
    clean = {k: v for k, v in values.items() if k in _DEFAULTS_FROM_SETTINGS}
    clean["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    clean["updated_by"] = updated_by
    CONFIG_FILE.write_text(json.dumps(clean, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    return _load()


def reset() -> Dict[str, Any]:
    """Supprime les overrides : retour aux valeurs de .env."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
    return _load()


def metadata() -> Dict[str, str]:
    """Qui a modifié les réglages, et quand."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return {k: raw[k] for k in ("updated_at", "updated_by") if k in raw}
    except Exception:
        return {}
