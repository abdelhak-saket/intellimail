"""FastAPI — endpoint /v1/triage qui orchestre le LangGraph."""
import secrets
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

import hitl_api
import prompts
import rules
import runtime_config
import store
from config import settings
from graph import WORKFLOW
from metrics import log_email
from schemas import (AgentTrace, ClassificationResult, CriticVerdict,
                     PIIReport, TriageRequest, TriageResponse)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[IntelliMail] FastAPI ready — {settings.AZURE_OPENAI_ENDPOINT}")
    print(f"[IntelliMail] Deployments: classifier={settings.LLM_CLASSIFIER} "
          f"drafter={settings.LLM_DRAFTER} critic={settings.LLM_CRITIC}")
    print(f"[IntelliMail] Templates: {prompts.LOADED_VERSIONS}")
    yield


app = FastAPI(title="IntelliMail Triage Backend",
              version="0.3.0-secured",
              description="Orchestration multi-agent sécurisée "
                          "(Guardrail PII / Classifier / Researcher / Drafter / Judge)",
              lifespan=lifespan)


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    """Contrôle de clé d'API sur /v1/*.

    Désactivé si API_KEY est vide (développement local). Dès que l'API est
    exposée par un tunnel pour Copilot Studio ou Power Automate, l'URL devient
    publique : la clé est alors le seul rempart. /health et /docs restent
    ouverts pour que le connecteur puisse importer le schéma.
    """
    if settings.API_KEY and request.url.path.startswith("/v1"):
        envoye = (request.headers.get("x-api-key")
                  or request.headers.get("authorization", "").removeprefix("Bearer ").strip())
        if not secrets.compare_digest(envoye or "", settings.API_KEY):
            return JSONResponse(
                status_code=401,
                content={"detail": "Clé d'API absente ou invalide "
                                   "(en-tête x-api-key)."})
    return await call_next(request)


# Endpoints de la file HITL : consommés par Copilot Studio (connecteur
# personnalisé importé depuis /openapi.json) et par le robot UiPath.
app.include_router(hitl_api.router)


@app.get("/", include_in_schema=False)
def root():
    """Racine → documentation interactive (évite un 404 déroutant)."""
    return RedirectResponse("/docs")


@app.get("/health")
def health():
    cfg = runtime_config.current()
    return {"status": "ok", "version": app.version,
            "prompt_versions": prompts.LOADED_VERSIONS,
            "hitl_force_categories": sorted(cfg.hitl_force_set),
            "hitl_force_priorities": sorted(cfg.hitl_force_priority_set),
            "sensitive_rules": [label for label, _, _ in rules.SENSITIVE_PATTERNS]
                               if cfg.SENSITIVE_RULES_ENABLED else [],
            "output_guardrail": [label for label, _, _ in rules.DRAFT_FORBIDDEN]
                                if cfg.OUTPUT_GUARDRAIL_ENABLED else [],
            "runtime_config_overrides": runtime_config.metadata(),
            "hitl_queue": store.stats()}


# ─── Idempotence par message-id (cache mémoire TTL) ─────────────────────
# Un même email retraité par le robot (retry UiPath, redémarrage) renvoie la
# réponse déjà calculée : pas de double traitement, pas de double coût LLM.
_idem_lock = threading.Lock()
_idem_cache: "OrderedDict[str, tuple]" = OrderedDict()  # key -> (ts, TriageResponse)


def _idem_get(key: str):
    now = time.time()
    with _idem_lock:
        item = _idem_cache.get(key)
        if not item:
            return None
        ts, resp = item
        if now - ts > settings.IDEMPOTENCY_TTL_S:
            _idem_cache.pop(key, None)
            return None
        return resp


def _idem_put(key: str, resp) -> None:
    with _idem_lock:
        _idem_cache[key] = (time.time(), resp)
        while len(_idem_cache) > settings.IDEMPOTENCY_MAX_ENTRIES:
            _idem_cache.popitem(last=False)


# ─── Décision finale : règles déterministes puis seuils ─────────────────
def decide(final: dict) -> tuple:
    """Retourne (action, requires_human, reason).

    La table de règles déterministes (rules.py) est évaluée en premier :
    entrée dégénérée, catégorie forcée, priorité haute, opération sensible,
    rejet du judge. Si aucune règle ne s'applique, on retombe sur les seuils
    de confiance.
    """
    # Réglages effectifs : overrides de l'UI HITL s'il y en a, sinon .env
    cfg = runtime_config.current()

    forced = rules.evaluate(final, cfg)
    if forced:
        return forced

    confiance = float(final.get("confiance", 0.0))
    critic_approved = bool(final.get("critic_approved", False))
    if confiance >= cfg.SEUIL_AUTO and critic_approved:
        return "AUTO", False, "seuils"
    if confiance >= cfg.SEUIL_HITL:
        return "HITL", True, "seuils"
    return "MANUAL", True, "seuils"


@app.post("/v1/triage", response_model=TriageResponse)
def triage(req: TriageRequest):
    t0 = time.perf_counter()

    # Idempotence : même message-id (ou job_id) déjà traité → réponse cachée
    idem_key = req.message_id or req.job_id
    if idem_key:
        cached = _idem_get(idem_key)
        if cached is not None:
            return cached.model_copy(update={"duplicate": True})

    initial_state = {
        "email_from":    req.email_from,
        "email_subject": req.email_subject,
        "email_body":    req.email_body,
        "drafter_retries": 0,
        "trace": [],
    }

    try:
        final = WORKFLOW.invoke(initial_state)
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"LangGraph workflow failed: {type(e).__name__}: {e}")

    # Décision finale — règles déterministes puis seuils
    confiance = float(final.get("confiance", 0.0))
    critic_approved = bool(final.get("critic_approved", False))
    action, requires_human, decision_reason = decide(final)

    # Coût estimé de l'email (tokens cumulés sur les 3 agents, retries inclus)
    usage = final.get("usage") or {}
    tokens_in = int(usage.get("tokens_in", 0))
    tokens_out = int(usage.get("tokens_out", 0))
    cost_usd = (tokens_in * settings.PRICE_INPUT_PER_1M
                + tokens_out * settings.PRICE_OUTPUT_PER_1M) / 1_000_000

    # Carte de réinjection : uniquement les placeholders utiles au robot
    draft = final.get("draft", "")
    pii_reinjection = {ph: val for ph, val in (final.get("pii_map") or {}).items()
                       if ph in draft}

    response = TriageResponse(
        job_id=req.job_id,
        classification=ClassificationResult(
            categorie=final.get("categorie", "autre"),
            priorite=final.get("priorite", "normale"),
            resume=final.get("resume", ""),
            expediteur=final.get("expediteur"),
            action_suggeree=final.get("action_suggeree"),
            confiance=confiance,
        ),
        contexts_used=final.get("contexts", []),
        draft_reply=final.get("draft", ""),
        critic=CriticVerdict(
            approved=critic_approved,
            score=float(final.get("critic_score", 0.0)),
            feedback=final.get("critic_feedback", ""),
            issues=final.get("critic_issues", []),
            verdict=final.get("judge_verdict"),
            scores=final.get("judge_scores") or None,
        ),
        pii=PIIReport(
            entities=final.get("pii_entities", {}),
            total=sum((final.get("pii_entities") or {}).values()),
            engine=final.get("pii_engine", "none"),
        ),
        prompt_versions=prompts.LOADED_VERSIONS,
        action=action,
        requires_human=requires_human,
        decision_reason=decision_reason,
        pii_reinjection=pii_reinjection,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        llm_calls=int(usage.get("llm_calls", 0)),
        cost_usd_estimate=round(cost_usd, 6),
        target_folder_hint=None,  # UiPath gère le mapping catégorie -> dossier via son Routing
        total_duration_ms=int((time.perf_counter() - t0) * 1000),
        agent_trace=[AgentTrace(**t) for t in final.get("trace", [])],
    )

    if idem_key:
        _idem_put(idem_key, response)

    # File d'attente HITL : tout cas nécessitant un humain y entre (Phase 3).
    # Jamais bloquant — un échec de mise en file ne doit pas casser le triage.
    if requires_human:
        store.enqueue(response=response, final_state=final, request=req)

    # Métriques portfolio — une ligne CSV par email (jamais bloquant)
    judge_scores = final.get("judge_scores") or {}
    log_email({
        "job_id": req.job_id or "",
        "message_id": req.message_id or "",
        "categorie": response.classification.categorie,
        "priorite": response.classification.priorite,
        "confiance": round(confiance, 3),
        "pii_total": response.pii.total,
        "pii_entities": ";".join(f"{k}={v}" for k, v in response.pii.entities.items()),
        "pii_engine": response.pii.engine,
        "judge_verdict": final.get("judge_verdict", ""),
        "judge_pertinence": judge_scores.get("pertinence", ""),
        "judge_ton": judge_scores.get("ton", ""),
        "judge_conformite": judge_scores.get("conformite", ""),
        "judge_factualite": judge_scores.get("factualite", ""),
        "judge_score": round(float(final.get("critic_score", 0.0)), 3),
        "drafter_retries": final.get("drafter_retries", 0),
        "action": action,
        "requires_human": requires_human,
        "decision_reason": decision_reason,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost_usd, 6),
        "human_decision": "",   # rempli plus tard par l'UI HITL (Phase 3)
        "duration_ms": response.total_duration_ms,
        "errors": " | ".join(final.get("errors", [])),
        "tpl_classifier": prompts.LOADED_VERSIONS.get("classifier", ""),
        "tpl_drafter": prompts.LOADED_VERSIONS.get("drafter", ""),
        "tpl_judge": prompts.LOADED_VERSIONS.get("judge", ""),
    })
    return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT,
                reload=False, log_level=settings.LOG_LEVEL)
