"""Guardrail PII — masque les données sensibles AVANT tout appel Azure OpenAI.

Principe AI Act (art. 9/15) : la PII ne quitte jamais le SI. Le LLM reçoit
des placeholders ([IBAN_MASQUE], [TEL_MASQUE]...) et travaille normalement.

Moteur hybride :
- regex (défaut)  : zéro dépendance, couvre IBAN, NIR, CB (validation Luhn),
                    téléphone FR, email — équivalent du Guardrail_PII VB.NET
                    du package UiPath.
- presidio        : si `presidio-analyzer`/`presidio-anonymizer` + le modèle
                    spaCy fr_core_news_md sont installés, bascule automatique
                    (détection NER en plus des regex : noms, adresses...).
    pip install presidio-analyzer presidio-anonymizer
    python -m spacy download fr_core_news_md

Interface unique : mask_pii(text) -> PIIResult — le reste du code ne change
pas quel que soit le moteur.

NOTE : ne pas appliquer à email_from si le routing en a besoin — le graph
ne masque que subject + body.
"""
import re
from dataclasses import dataclass, field
from typing import Dict

# ─── Patterns regex (alignés sur Guardrail_PII_InvokeCode.vb) ───────────
# Appliqués AVANT la détection CB : l'IBAN et le NIR contiennent des suites
# de chiffres qui passeraient parfois le test de Luhn (faux CB).
_PATTERNS_PRE_CB = [
    # IBAN FR (FR + 2 clés + 23 caractères, espaces/tirets tolérés)
    ("IBAN", re.compile(
        r"\bFR\d{2}(?:[ \-]?[A-Z0-9]{4}){5}[ \-]?[A-Z0-9]{3}\b", re.I)),
    # NIR (n° sécurité sociale) : 13 chiffres + clé optionnelle, 2A/2B Corse
    ("NIR", re.compile(
        r"\b[12]\s?\d{2}\s?(?:0[1-9]|1[0-2]|20)\s?(?:\d{2}|2[AB])"
        r"\s?\d{3}\s?\d{3}(?:\s?\d{2})?\b")),
]

# Appliqués APRÈS la détection CB (le n° de carte contient des paires de
# chiffres qui ressemblent à un téléphone).
_PATTERNS_POST_CB = [
    # Téléphone FR : +33/0033/0 + 9 chiffres, séparateurs tolérés
    ("TEL", re.compile(
        r"(?:\+33|0033|0)\s?[1-9](?:[ .\-]?\d{2}){4}\b")),
    # Email
    ("EMAIL", re.compile(
        r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)),
]

# Carte bancaire : candidate 13-19 chiffres → confirmée par Luhn
_CB_CANDIDATE = re.compile(r"\b(?:\d[ \-]?){13,19}\b")


def _luhn_ok(digits: str) -> bool:
    d = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(d) <= 19:
        return False
    checksum, parity = 0, len(d) % 2
    for i, n in enumerate(d):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        checksum += n
    return checksum % 10 == 0


@dataclass
class PIIResult:
    masked_text: str
    entities: Dict[str, int] = field(default_factory=dict)  # {"IBAN": 1, ...}
    engine: str = "regex"

    @property
    def total(self) -> int:
        return sum(self.entities.values())


# ─── Moteur regex ────────────────────────────────────────────────────────
def _mask_regex(text: str) -> PIIResult:
    entities: Dict[str, int] = {}
    out = text

    # 1) IBAN + NIR (avant CB : leurs chiffres peuvent passer Luhn par hasard)
    for label, pattern in _PATTERNS_PRE_CB:
        out, n = pattern.subn(f"[{label}_MASQUE]", out)
        if n:
            entities[label] = entities.get(label, 0) + n

    # 2) CB (validation Luhn — avant TEL qui mordrait dans le numéro)
    def _cb_sub(m: re.Match) -> str:
        if _luhn_ok(m.group(0)):
            entities["CB"] = entities.get("CB", 0) + 1
            return "[CB_MASQUE]"
        return m.group(0)

    out = _CB_CANDIDATE.sub(_cb_sub, out)

    # 3) Téléphone + email
    for label, pattern in _PATTERNS_POST_CB:
        out, n = pattern.subn(f"[{label}_MASQUE]", out)
        if n:
            entities[label] = entities.get(label, 0) + n

    return PIIResult(masked_text=out, entities=entities, engine="regex")


# ─── Moteur Presidio (optionnel, bascule auto si installé) ──────────────
_presidio = None


def _get_presidio():
    """Initialise Presidio FR une seule fois. Retourne None si indisponible."""
    global _presidio
    if _presidio is not None:
        return _presidio or None
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine

        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "fr", "model_name": "fr_core_news_md"}],
        })
        analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(),
                                  supported_languages=["fr"])
        _presidio = (analyzer, AnonymizerEngine())
    except Exception:
        _presidio = False  # indisponible — on ne retentera pas
    return _presidio or None


def _mask_presidio(text: str) -> PIIResult:
    analyzer, anonymizer = _get_presidio()
    results = analyzer.analyze(text=text, language="fr")
    anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
    entities: Dict[str, int] = {}
    for r in results:
        entities[r.entity_type] = entities.get(r.entity_type, 0) + 1
    return PIIResult(masked_text=anonymized.text, entities=entities,
                     engine="presidio")


# ─── Masquage nom client → [CLIENT_NAME] ────────────────────────────────
# Le nom est extrait de email_from (déterministe, pas de LLM) puis masqué
# dans sujet + corps. Le robot UiPath réinjecte la vraie valeur au moment
# de l'envoi via la carte de réinjection retournée par l'API.
_DISPLAY_NAME_RE = re.compile(r'^\s*"?([^"<@]+?)"?\s*<')


def extract_client_name(email_from: str) -> str:
    """Nom client depuis l'expéditeur. '' si non déterminable.

    - 'Marie Dupont <marie.dupont@x.fr>' → 'Marie Dupont'
    - 'marie.dupont@x.fr'                → 'Marie Dupont' (local-part)
    """
    if not email_from:
        return ""
    m = _DISPLAY_NAME_RE.match(email_from)
    if m:
        return m.group(1).strip()
    local = email_from.split("@")[0].strip()
    tokens = [t for t in re.split(r"[._\-+]", local) if t.isalpha() and len(t) >= 2]
    return " ".join(t.capitalize() for t in tokens) if tokens else ""


def mask_client_name(text: str, name: str) -> tuple:
    """Masque le nom complet + chaque token (≥3 car.) → [CLIENT_NAME].
    Retourne (texte_masqué, nb_occurrences)."""
    if not text or not name:
        return text, 0
    total = 0
    out = text
    patterns = [re.escape(name)] + [re.escape(t) for t in name.split() if len(t) >= 3]
    for p in patterns:
        out, n = re.subn(rf"\b{p}\b", "[CLIENT_NAME]", out, flags=re.I)
        total += n
    # Occurrences adjacentes ([CLIENT_NAME] [CLIENT_NAME] → [CLIENT_NAME])
    out = re.sub(r"\[CLIENT_NAME\](?:\s+\[CLIENT_NAME\])+", "[CLIENT_NAME]", out)
    return out, total


# ─── Interface publique ─────────────────────────────────────────────────
def mask_pii(text: str) -> PIIResult:
    """Masque la PII. Presidio si installé, sinon regex. Jamais d'exception :
    en cas d'échec Presidio, repli silencieux sur regex."""
    if not text:
        return PIIResult(masked_text=text or "")
    if _get_presidio():
        try:
            return _mask_presidio(text)
        except Exception:
            pass
    return _mask_regex(text)
