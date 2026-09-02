"""Endpoints REST de la file de validation humaine.

Deux consommateurs, un seul contrat :
- **Copilot Studio** — connecteur personnalisé importé depuis /openapi.json.
  D'où le soin porté aux `operation_id`, `summary` et `description` : l'agent
  s'en sert pour choisir quel outil appeler. Un libellé flou = un agent qui
  appelle la mauvaise opération.
- **UiPath** — /v1/hitl/approved pour récupérer ce qu'il doit envoyer, puis
  /v1/hitl/sent pour confirmer. Le marquage est idempotent : un rejeu du robot
  ne renvoie pas deux fois le même e-mail au client.

Décision de conception — PII : le corps brut n'est **jamais** renvoyé par
défaut. Une conversation Copilot Studio est archivée dans Exchange ; y déverser
des IBAN reconstituerait hors du SI ce que le guardrail a masqué. Le brut n'est
accessible que sur `include_raw=true`, à réserver aux clients internes
(Streamlit, robot), et à ne pas exposer dans le connecteur de l'agent.
"""
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query

import rules
import store

router = APIRouter(prefix="/v1", tags=["HITL"])


# ─── Helpers de présentation ────────────────────────────────────────────
def _reason_label(reason: str) -> dict:
    """Traduit un motif technique en libellé métier + justification.
    C'est ce que l'agent lit à l'humain : « pourquoi ce cas est-il escaladé ? »
    """
    base = (reason or "seuils").split(":", 1)[0]
    label = {
        "rules_table": "Règle de catégorie",
        "priorite": "Urgence",
        "sensitive": "Opération sensible",
        "output_guardrail": "Garde-fou de sortie",
        "degenerate_input": "E-mail sans contenu exploitable",
        "judge_reject": "Brouillon rejeté par l'évaluateur",
        "seuils": "Score de confiance insuffisant",
    }.get(base, base)
    detail = (reason or "").split(":", 1)[-1].split("+")[0]
    return {"code": reason, "label": label,
            "why": rules.justification(detail) or ""}


def _summarize(case: dict) -> dict:
    """Vue courte d'un cas — sans PII brute."""
    r = _reason_label(case["decision_reason"])
    return {
        "case_id": case["id"],
        "received_at": case["created_at"],
        "email_from": case["email_from"],
        "subject": case["subject_masked"] or case["subject_raw"],
        "categorie": case["categorie"],
        "priorite": case["priorite"],
        "confiance": case["confiance"],
        "resume": case["resume"],
        "escalation_code": r["code"],
        "escalation_label": r["label"],
        "escalation_why": r["why"],
        "status": case["status"],
    }


# ─── File d'attente ─────────────────────────────────────────────────────
@router.get("/hitl/queue", operation_id="listPendingEmails",
            summary="Lister les e-mails en attente de validation humaine")
def list_queue(
    status: str = Query("pending", description="pending | validated | edited "
                                               "| rejected | sent | all"),
    categorie: str = Query("", description="Filtre catégorie, vide = toutes"),
    limit: int = Query(20, ge=1, le=200),
):
    """Retourne les e-mails escaladés, du plus ancien au plus récent.

    Chaque élément indique **pourquoi** il a été escaladé, en clair
    (`escalation_label` et `escalation_why`) et en code (`escalation_code`).
    Ne contient aucune donnée personnelle en clair.
    """
    cases = store.list_queue(status=status, categorie=categorie, limit=limit)
    return {"total": len(cases), "items": [_summarize(c) for c in cases]}


@router.get("/hitl/case/{case_id}", operation_id="getEmailCase",
            summary="Détail d'un e-mail escaladé, avec le brouillon proposé")
def get_case(
    case_id: int,
    include_raw: bool = Query(
        False, description="Inclure l'e-mail non masqué. À NE PAS activer "
                           "depuis un agent conversationnel : la PII serait "
                           "archivée dans l'historique de conversation."),
):
    """Détail complet : e-mail masqué, brouillon proposé, classification,
    notes de l'évaluateur, contextes documentaires utilisés, motif d'escalade.
    """
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(404, f"Cas {case_id} introuvable")

    import json as _json

    def j(v, d):
        try:
            return _json.loads(v) if v else d
        except Exception:
            return d

    out = _summarize(case)
    out.update({
        "subject_masked": case["subject_masked"],
        "body_masked": case["body_masked"],
        "draft": store.final_draft(case_id),
        "draft_original": case["draft"],
        "judge_verdict": case["judge_verdict"],
        "judge_scores": j(case["judge_scores"], {}),
        "pii_masked": j(case["pii_entities"], {}),
        "contexts_used": j(case["contexts"], []),
        "cost_usd": case["cost_usd"],
        "duration_ms": case["duration_ms"],
        "decisions": store.decisions_for(case_id),
    })
    if include_raw:
        out["subject_raw"] = case["subject_raw"]
        out["body_raw"] = case["body_raw"]
    return out


# ─── Décision humaine ───────────────────────────────────────────────────
@router.post("/hitl/decision", operation_id="recordHumanDecision",
             summary="Valider, corriger ou rejeter un brouillon")
def record_decision(
    case_id: int = Query(..., description="Identifiant du cas"),
    decision: Literal["validated", "edited", "rejected"] = Query(
        ..., description="validated = envoyer tel quel · edited = envoyer la "
                         "version corrigée · rejected = ne rien envoyer"),
    decided_by: str = Query(..., description="Identifiant de l'agent humain"),
    final_draft: str = Query("", description="Texte corrigé, requis si "
                                             "decision=edited"),
    comment: str = Query("", description="Motif, facultatif"),
):
    """Journalise la décision (append-only) et met le cas à jour.

    Le garde-fou de sortie est réappliqué au texte : si la version humaine
    contient un lien, un engagement commercial ou un discours méta-IA, la
    décision est refusée et l'agent doit corriger.
    """
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(404, f"Cas {case_id} introuvable")
    if decision == "edited" and not final_draft.strip():
        raise HTTPException(422, "final_draft est requis quand decision=edited")

    texte = final_draft if decision == "edited" else (
        final_draft or store.final_draft(case_id))
    if decision in store.APPROVED_STATUSES:
        alertes = rules.check_draft_output(texte)
        if alertes:
            raise HTTPException(422, {
                "message": "Garde-fou de sortie déclenché : ce texte ne peut "
                           "pas être envoyé en l'état.",
                "rules": [{"code": a, "why": rules.justification(a)}
                          for a in alertes]})

    store.record_decision(case_id, decision, decided_by,
                          texte if decision != "rejected" else "", comment)
    return {"ok": True, "case_id": case_id, "status": decision,
            "decided_by": decided_by,
            "next": ("en attente d'envoi par le robot"
                     if decision in store.APPROVED_STATUSES
                     else "aucun envoi, traitement manuel")}


# ─── Consommation par le robot ──────────────────────────────────────────
@router.get("/hitl/approved", operation_id="listApprovedForSending",
            summary="Brouillons approuvés en attente d'envoi (robot UiPath)")
def list_approved(limit: int = Query(50, ge=1, le=200)):
    """Cas validés ou corrigés par un humain et pas encore envoyés.

    `final_draft` est la version à envoyer. `pii_reinjection` donne les
    remplacements à opérer avant l'envoi (ex. `[CLIENT_NAME]` → `Marie Dupont`)
    — le robot doit les appliquer, l'API ne les applique jamais elle-même.
    """
    import json as _json
    out = []
    for c in store.list_approved(limit=limit):
        try:
            reinj = _json.loads(c["pii_reinjection"] or "{}")
        except Exception:
            reinj = {}
        out.append({
            "case_id": c["id"], "message_id": c["message_id"],
            "job_id": c["job_id"], "email_to": c["email_from"],
            "subject": c["subject_raw"], "final_draft": c["final_draft"],
            "pii_reinjection": reinj, "status": c["status"],
        })
    return {"total": len(out), "items": out}


@router.post("/hitl/sent", operation_id="markAsSent",
             summary="Confirmer l'envoi effectif d'une réponse")
def mark_sent(
    case_id: int = Query(...),
    sent_by: str = Query("uipath", description="Qui a envoyé"),
):
    """Idempotent : un rejeu du robot renvoie `already_sent` au lieu de
    provoquer un second envoi."""
    if not store.get_case(case_id):
        raise HTTPException(404, f"Cas {case_id} introuvable")
    ok = store.mark_sent(case_id, sent_by)
    return {"ok": True, "case_id": case_id,
            "result": "marked_sent" if ok else "already_sent"}


# ─── Base de connaissance (questions de l'agent humain) ─────────────────
@router.get("/kb/search", operation_id="searchProcedures",
            summary="Rechercher dans les procédures et FAQ internes")
def search_kb(
    q: str = Query(..., min_length=3, description="Question en langage naturel"),
    k: int = Query(3, ge=1, le=10),
):
    """Recherche sémantique dans le corpus documentaire (procédures de
    contestation, délais réglementaires, RGPD, résiliation...).

    Sert à répondre aux questions de l'agent humain pendant qu'il traite un
    cas : « quel est le délai de remboursement d'un trop-perçu ? »
    """
    try:
        import rag
        hits = rag.query(q, top_k=k)
    except Exception as e:
        raise HTTPException(503, f"Base documentaire indisponible : {e}")
    if not hits:
        return {"total": 0, "items": [],
                "message": "Aucun passage pertinent. Le corpus est-il ingéré "
                           "(python ingest_corpus.py) ?"}
    return {"total": len(hits), "items": hits}


# ─── Règles en vigueur (transparence pour l'agent) ──────────────────────
@router.get("/rules", operation_id="listEscalationRules",
            summary="Lister les règles d'escalade en vigueur")
def list_rules():
    """Les règles déterministes appliquées avant tout envoi automatique.
    Permet à l'agent d'expliquer la politique, pas seulement un cas précis."""
    return {
        "entree": [{"code": lab, "why": why}
                   for lab, _, why in rules.SENSITIVE_PATTERNS]
                  + [{"code": k, "why": rules.justification(k)} for k in
                     ("expediteur_automatique", "pii_sensible",
                      "piece_jointe_sans_contexte")],
        "sortie": [{"code": lab, "why": why}
                   for lab, _, why in rules.DRAFT_FORBIDDEN],
    }
