"""LangGraph workflow — 5 noeuds : guardrail → classifier → researcher → drafter ⇄ judge → END.

Version durcie : tous les accès au state utilisent .get() avec défauts,
les nœuds attrapent leurs propres exceptions et écrivent l'erreur dans
state['errors'] au lieu de cascader silencieusement.

Upgrade "pipeline GenAI sécurisé et évalué" :
- guardrail : masque la PII (IBAN, NIR, CB, tél, email) AVANT tout appel Azure
- templates : prompts versionnés chargés depuis templates/ (prompts.LOADED_VERSIONS)
- judge     : LLM-as-a-judge typé Pydantic (4 critères 1-5, verdict AUTO_SEND /
              HUMAN_REVIEW / REJECT) avec boucle de retry vers le drafter
"""
import time
from typing import List, Literal, Optional, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

import prompts
from config import settings
from guardrails import extract_client_name, mask_client_name, mask_pii
from llm import chat_json, chat_text
from schemas import JudgeVerdict


# ─── État partagé entre les noeuds ──────────────────────────────────────
class TriageState(TypedDict, total=False):
    # Entrée
    email_from: str
    email_subject: str
    email_body: str

    # Guardrail PII (le LLM ne voit que les versions masquées)
    email_subject_raw: str
    email_body_raw: str
    email_from_llm: str         # expéditeur masqué — seule version envoyée au LLM
    pii_entities: dict
    pii_engine: str
    pii_map: dict               # carte de réinjection {placeholder: valeur réelle}
    degenerate: bool            # corps vide/quasi-vide → HITL direct, zéro LLM
    usage: dict                 # {tokens_in, tokens_out, llm_calls} — coût/email

    # Classifier
    categorie: str
    priorite: str
    resume: str
    expediteur: Optional[str]
    action_suggeree: Optional[str]
    confiance: float

    # Researcher (placeholder Phase 2)
    contexts: List[str]

    # Drafter
    draft: str
    drafter_retries: int

    # Judge (ex-Critic) — critic_* conservés pour compat API
    critic_approved: bool
    critic_score: float
    critic_feedback: str
    critic_issues: List[str]
    judge_verdict: str          # AUTO_SEND | HUMAN_REVIEW | REJECT
    judge_scores: dict          # {"pertinence": 4, "ton": 5, ...}

    # Diagnostic
    trace: List[dict]
    errors: List[str]


# ─── Helpers ────────────────────────────────────────────────────────────
def _record(state: TriageState, agent: str, t0: float, success: bool, note: str = None):
    state.setdefault("trace", []).append({
        "agent": agent,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
        "success": success,
        "note": note,
    })


def _err(state: TriageState, agent: str, exc: Exception):
    msg = f"[{agent}] {type(exc).__name__}: {exc}"
    state.setdefault("errors", []).append(msg)
    return msg


# ─── Noeuds ─────────────────────────────────────────────────────────────
def node_guardrail(state: TriageState) -> TriageState:
    """Masque la PII dans sujet + corps AVANT tout appel LLM.

    email_from n'est PAS masqué : le routing UiPath en a besoin.
    Les originaux restent dans *_raw (jamais envoyés au LLM, ne quittent pas le SI).
    """
    t0 = time.perf_counter()
    try:
        subject = state.get("email_subject") or ""
        body = state.get("email_body") or ""
        state["email_subject_raw"] = subject
        state["email_body_raw"] = body

        # ── Règle "entrée dégénérée" : corps vide/quasi-vide → HITL direct,
        #    AUCUN appel LLM (coût zéro). Routé vers END par la conditionnelle.
        if len(body.strip()) < settings.DEGENERATE_MIN_CHARS:
            state["degenerate"] = True
            state.update({"categorie": "autre", "priorite": "normale",
                          "resume": "Entrée dégénérée (corps vide ou quasi-vide)",
                          "expediteur": None, "action_suggeree": None,
                          "confiance": 0.0, "contexts": [], "draft": "",
                          "critic_approved": False, "critic_score": 0.0,
                          "critic_feedback": "Escalade directe : entrée dégénérée",
                          "critic_issues": ["degenerate_input"],
                          "judge_verdict": "HUMAN_REVIEW", "judge_scores": {},
                          "pii_entities": {}, "pii_engine": "none", "pii_map": {}})
            _record(state, "guardrail", t0, True,
                    f"degenerate_input (body<{settings.DEGENERATE_MIN_CHARS} chars) → HITL, 0 appel LLM")
            return state

        r_subject = mask_pii(subject)
        r_body = mask_pii(body)

        masked_subject = r_subject.masked_text
        masked_body = r_body.masked_text

        # ── Nom client → [CLIENT_NAME] (réinjection déterministe par le robot)
        client_name = extract_client_name(state.get("email_from") or "")
        masked_subject, n_subj = mask_client_name(masked_subject, client_name)
        masked_body, n_body = mask_client_name(masked_body, client_name)
        n_name = n_subj + n_body

        state["email_subject"] = masked_subject
        state["email_body"] = masked_body
        # email_from reste intact dans le state (routing UiPath), mais le LLM
        # ne reçoit que la version masquée :
        from_llm = mask_pii(state.get("email_from") or "").masked_text
        from_llm, _ = mask_client_name(from_llm, client_name)
        state["email_from_llm"] = from_llm

        # Carte de réinjection : le robot remplace [CLIENT_NAME] à l'envoi.
        # Toujours renseignée si un nom est extrait — le drafter peut utiliser
        # [CLIENT_NAME] même s'il n'apparaissait pas dans le corps d'origine.
        state["pii_map"] = {"[CLIENT_NAME]": client_name} if client_name else {}

        entities: dict = dict(r_body.entities)
        for k, v in r_subject.entities.items():
            entities[k] = entities.get(k, 0) + v
        if n_name:
            entities["NOM"] = entities.get("NOM", 0) + n_name
        state["pii_entities"] = entities
        state["pii_engine"] = r_body.engine
        total = sum(entities.values())
        _record(state, "guardrail", t0, True,
                f"engine={r_body.engine} masked={total} {entities if entities else ''}".strip())
    except Exception as e:
        # Fail-safe : en cas d'échec inattendu, on continue avec le texte original
        # (préférable à bloquer le triage) mais on trace l'erreur.
        state.setdefault("pii_entities", {})
        state.setdefault("pii_engine", "none")
        _record(state, "guardrail", t0, False, _err(state, "guardrail", e))
    return state


def node_classifier(state: TriageState) -> TriageState:
    t0 = time.perf_counter()
    body = (state.get("email_body") or "").strip()
    if not body:
        # Pas d'email à classer → on pose des défauts safe et on laisse passer.
        state.update({"categorie": "autre", "priorite": "normale",
                      "resume": "", "expediteur": None,
                      "action_suggeree": None, "confiance": 0.0})
        _record(state, "classifier", t0, False, "email_body vide")
        _err(state, "classifier", ValueError("email_body manquant ou vide"))
        return state

    user_msg = (
        f"Email reçu :\n---\n"
        f"De : {state.get('email_from_llm') or '(inconnu)'}\n"
        f"Sujet : {state.get('email_subject', '')}\n\n"
        f"{body}\n---"
    )
    try:
        result = chat_json(settings.LLM_CLASSIFIER, prompts.CLASSIFIER_SYSTEM,
                           user_msg, temperature=0.0, max_tokens=400,
                           usage_sink=state.setdefault("usage", {}))
        state.update({
            "categorie":       result.get("categorie", "autre"),
            "priorite":        result.get("priorite", "normale"),
            "resume":          result.get("resume", ""),
            "expediteur":      result.get("expediteur"),
            "action_suggeree": result.get("action_suggeree"),
            "confiance":       float(result.get("confiance", 0.0) or 0.0),
        })
        _record(state, "classifier", t0, True,
                f"cat={state['categorie']} conf={state['confiance']:.2f}")
    except Exception as e:
        # En cas d'échec LLM, on pose des défauts pour que la suite tourne
        state.update({"categorie": "autre", "priorite": "normale",
                      "resume": "", "expediteur": None,
                      "action_suggeree": None, "confiance": 0.0})
        _record(state, "classifier", t0, False, _err(state, "classifier", e))
    return state


def node_researcher(state: TriageState) -> TriageState:
    """RAG ChromaDB — top-k contextes documentaires pour le drafter.

    Fail-safe : chromadb non installé ou corpus non ingéré → aucun contexte,
    le pipeline continue exactement comme avant (no-op).
    La requête utilise les versions MASQUÉES (aucune PII vers les embeddings).
    """
    t0 = time.perf_counter()
    state["contexts"] = []
    try:
        import rag
        q = f"{state.get('email_subject', '')} {state.get('resume') or ''} " \
            f"{(state.get('email_body') or '')[:500]}".strip()
        state["contexts"] = rag.query(q)
        note = (f"rag hits={len(state['contexts'])}" if state["contexts"]
                else "rag vide (corpus non ingéré ? → python ingest_corpus.py)")
        _record(state, "researcher", t0, True, note)
    except Exception as e:
        _record(state, "researcher", t0, False, _err(state, "researcher", e))
    return state


def node_drafter(state: TriageState) -> TriageState:
    t0 = time.perf_counter()
    state.setdefault("drafter_retries", 0)
    contexts = state.get("contexts") or []
    contexts_block = ("Aucun contexte documentaire fourni." if not contexts
                      else "Contextes documentaires :\n- " + "\n- ".join(contexts))
    feedback_block = ""
    if state.get("critic_feedback") and not state.get("critic_approved", True):
        feedback_block = (
            f"\n\nRetour critique précédent à corriger : {state['critic_feedback']}\n"
            f"Issues : {', '.join(state.get('critic_issues') or [])}"
        )
    user_msg = (
        f"Email d'origine :\n---\n"
        f"De : {state.get('email_from_llm') or '(inconnu)'}\n"
        f"Sujet : {state.get('email_subject', '')}\n\n"
        f"{state.get('email_body', '')}\n---\n\n"
        f"Classification : catégorie={state.get('categorie','autre')}, "
        f"priorité={state.get('priorite','normale')}, "
        f"résumé={state.get('resume','')}\n\n"
        f"{contexts_block}{feedback_block}\n\n"
        "Rédige la réponse au client en français, 5-10 lignes max.\n"
        "Si tu t'adresses au client par son nom, utilise EXACTEMENT le "
        "placeholder [CLIENT_NAME] (il sera remplacé automatiquement à l'envoi)."
    )
    try:
        state["draft"] = chat_text(settings.LLM_DRAFTER, prompts.DRAFTER_SYSTEM,
                                   user_msg, temperature=0.3, max_tokens=500,
                                   usage_sink=state.setdefault("usage", {}))
        _record(state, "drafter", t0, True,
                f"retry={state['drafter_retries']} len={len(state['draft'])}")
    except Exception as e:
        state["draft"] = ""
        _record(state, "drafter", t0, False, _err(state, "drafter", e))
    return state


def node_critic(state: TriageState) -> TriageState:
    t0 = time.perf_counter()
    draft = state.get("draft") or ""
    if not draft.strip():
        # Pas de draft à évaluer
        state.update({"critic_approved": False, "critic_score": 0.0,
                      "critic_feedback": "Aucun brouillon à évaluer",
                      "critic_issues": ["empty_draft"]})
        state["drafter_retries"] = state.get("drafter_retries", 0) + 1
        _record(state, "critic", t0, False, "draft vide")
        return state

    user_msg = (
        f"Email d'origine :\n{state.get('email_body','')}\n\n"
        f"Classification : catégorie={state.get('categorie','autre')}, "
        f"priorité={state.get('priorite','normale')}\n\n"
        f"Réponse rédigée à évaluer :\n---\n{draft}\n---"
    )
    try:
        raw = chat_json(settings.LLM_CRITIC, prompts.JUDGE_SYSTEM, user_msg,
                        temperature=0.0, max_tokens=400,
                        usage_sink=state.setdefault("usage", {}))
        verdict = JudgeVerdict(**raw)  # validation Pydantic stricte
        score = verdict.score_normalise
        approved = (verdict.verdict == "AUTO_SEND"
                    and score >= settings.CRITIC_APPROVE_THRESHOLD)
        state.update({
            "critic_approved": approved,
            "critic_score":    score,
            "critic_feedback": verdict.feedback,
            "critic_issues":   list(verdict.issues),
            "judge_verdict":   verdict.verdict,
            "judge_scores":    {"pertinence": verdict.pertinence,
                                "ton": verdict.ton,
                                "conformite": verdict.conformite,
                                "factualite": verdict.factualite},
        })
        if not approved:
            state["drafter_retries"] = state.get("drafter_retries", 0) + 1
        _record(state, "judge", t0, True,
                f"verdict={verdict.verdict} score={score:.2f} "
                f"P{verdict.pertinence}/T{verdict.ton}/C{verdict.conformite}/F{verdict.factualite}")
    except ValidationError as e:
        # JSON du judge invalide = on n'approuve PAS (fail-closed) → revue humaine
        state.update({"critic_approved": False, "critic_score": 0.0,
                      "critic_feedback": "Sortie judge invalide (Pydantic)",
                      "critic_issues": ["judge_invalid_output"],
                      "judge_verdict": "HUMAN_REVIEW", "judge_scores": {}})
        state["drafter_retries"] = state.get("drafter_retries", 0) + 1
        _record(state, "judge", t0, False, _err(state, "judge", e))
    except Exception as e:
        # Échec technique judge (réseau...) = fail-open contrôlé : on accepte
        # le draft mais score 0.5 → restera sous SEUIL_AUTO côté décision finale
        state.update({"critic_approved": True, "critic_score": 0.5,
                      "critic_feedback": f"Judge indisponible : {e}",
                      "critic_issues": [], "judge_verdict": "HUMAN_REVIEW",
                      "judge_scores": {}})
        _record(state, "judge", t0, False, _err(state, "judge", e))
    return state


# ─── Conditionnelle après guardrail ─────────────────────────────────────
def _route_after_guardrail(state: TriageState) -> Literal["classifier", "end"]:
    """Entrée dégénérée → END direct, aucun appel LLM (coût zéro)."""
    return "end" if state.get("degenerate") else "classifier"


# ─── Conditionnelle après critic ────────────────────────────────────────
def _route_after_critic(state: TriageState) -> Literal["drafter", "end"]:
    """Lecture seule : l'incrément des retries vit dans node_critic, car les
    mutations faites dans une conditional edge ne sont pas persistées par
    LangGraph (bug de boucle infinie corrigé en v0.3.0)."""
    if state.get("critic_approved"):
        return "end"
    if state.get("drafter_retries", 0) >= settings.MAX_DRAFTER_RETRIES:
        return "end"  # on accepte le draft tel quel après N retries
    return "drafter"


# ─── Construction du graph ──────────────────────────────────────────────
def build_workflow():
    g = StateGraph(TriageState)
    g.add_node("guardrail",  node_guardrail)
    g.add_node("classifier", node_classifier)
    g.add_node("researcher", node_researcher)
    g.add_node("drafter",    node_drafter)
    g.add_node("critic",     node_critic)

    g.set_entry_point("guardrail")
    g.add_conditional_edges("guardrail", _route_after_guardrail,
                            {"classifier": "classifier", "end": END})
    g.add_edge("classifier", "researcher")
    g.add_edge("researcher", "drafter")
    g.add_edge("drafter",    "critic")
    g.add_conditional_edges("critic", _route_after_critic,
                            {"drafter": "drafter", "end": END})
    return g.compile()


# Compilation à l'import — un seul graph réutilisé
WORKFLOW = build_workflow()
