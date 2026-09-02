"""Schémas Pydantic — payloads d'entrée/sortie de l'API."""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ─── Entrée ────────────────────────────────────────────────────────────
class TriageRequest(BaseModel):
    """Email à trier (envoyé par UiPath ou un autre client)."""
    email_from: str = Field(..., description="Expéditeur (email ou nom)")
    email_subject: str = Field("", description="Sujet")
    # min_length retiré : un corps vide doit produire une réponse HITL structurée
    # (règle "entrée dégénérée"), pas une erreur 422.
    email_body: str = Field("", description="Corps (peut être vide → HITL direct)")
    email_received_at: Optional[datetime] = None
    job_id: Optional[str] = Field(None, description="Identifiant de traçabilité externe")
    message_id: Optional[str] = Field(
        None, description="Message-ID Outlook — clé d'idempotence (pas de double traitement)")


# ─── Détail par agent ──────────────────────────────────────────────────
class ClassificationResult(BaseModel):
    categorie: Literal["reclamation", "resiliation", "donnees_personnelles",
                       "demande", "information", "facturation",
                       "support_technique", "spam", "autre"]
    priorite: Literal["haute", "normale", "basse", "faible"]
    resume: str
    expediteur: Optional[str] = None
    action_suggeree: Optional[str] = None
    confiance: float = Field(..., ge=0.0, le=1.0)


class JudgeVerdict(BaseModel):
    """Sortie brute du LLM-as-a-judge — validée par Pydantic.

    Grille alignée sur le package UiPath : 4 critères 1-5 + verdict typé.
    """
    pertinence: int = Field(..., ge=1, le=5)
    ton: int = Field(..., ge=1, le=5)
    conformite: int = Field(..., ge=1, le=5)
    factualite: int = Field(..., ge=1, le=5)
    verdict: Literal["AUTO_SEND", "HUMAN_REVIEW", "REJECT"]
    feedback: str = ""
    issues: List[str] = Field(default_factory=list)

    @property
    def score_normalise(self) -> float:
        """Moyenne des 4 critères ramenée sur 0-1 (compat seuils existants)."""
        return (self.pertinence + self.ton + self.conformite + self.factualite) / 20.0


class CriticVerdict(BaseModel):
    approved: bool
    score: float = Field(..., ge=0.0, le=1.0)
    feedback: str
    issues: List[str] = Field(default_factory=list)
    # Détail judge v1.1 (None si fallback/erreur)
    verdict: Optional[Literal["AUTO_SEND", "HUMAN_REVIEW", "REJECT"]] = None
    scores: Optional[dict] = Field(
        None, description="Notes 1-5 : pertinence, ton, conformite, factualite")


class PIIReport(BaseModel):
    """Trace du guardrail PII — quelles entités ont été masquées avant l'appel LLM."""
    entities: dict = Field(default_factory=dict, description='ex. {"IBAN": 1, "TEL": 2}')
    total: int = 0
    engine: Literal["regex", "presidio", "none"] = "none"


class AgentTrace(BaseModel):
    agent: str
    duration_ms: int
    success: bool
    note: Optional[str] = None


# ─── Sortie ────────────────────────────────────────────────────────────
class TriageResponse(BaseModel):
    job_id: Optional[str] = None
    classification: ClassificationResult
    contexts_used: List[str] = Field(default_factory=list,
                                     description="Snippets RAG (vide en Phase 2 - placeholder)")
    draft_reply: str
    critic: CriticVerdict
    pii: PIIReport = Field(default_factory=PIIReport)
    prompt_versions: dict = Field(default_factory=dict)
    action: Literal["AUTO", "HITL", "MANUAL"]
    requires_human: bool
    decision_reason: str = Field(
        "seuils", description="Pourquoi cette action : seuils | rules_table:<cat> | degenerate_input")
    pii_reinjection: dict = Field(
        default_factory=dict,
        description="Carte placeholder → valeur réelle ({'[CLIENT_NAME]': 'Marie Dupont'}). "
                    "Le robot UiPath remplace dans draft_reply au moment de l'envoi.")
    tokens_in: int = 0
    tokens_out: int = 0
    llm_calls: int = 0
    cost_usd_estimate: float = 0.0
    duplicate: bool = Field(False, description="True si réponse servie depuis le cache d'idempotence")
    target_folder_hint: Optional[str] = None
    total_duration_ms: int
    agent_trace: List[AgentTrace]
