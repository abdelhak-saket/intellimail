# Architecture & dépendances entre fichiers

Qui importe quoi, qui fait quoi, dans quel ordre ça s'exécute.

## Vue d'ensemble (graphe d'imports)

```
                        .env
                          │ (lu par pydantic-settings)
                          v
                     ┌──────────┐
                     │ config.py│  Settings (endpoint, deployments, seuils)
                     └────┬─────┘
          ┌───────────────┼───────────────┐
          v               v               v
     ┌────────┐      ┌─────────┐     ┌─────────┐
     │ llm.py │      │ graph.py│     │ main.py │
     └───┬────┘      └─────────┘     └─────────┘
         │ client Azure OpenAI (chat_json / chat_text)
         └──────────────► graph.py

 templates/*.txt ──► prompts.py ──► graph.py, main.py
 (prompts versionnés)  (loader)

 guardrails.py ─────► graph.py          (mask_pii, nœud d'entrée)
 schemas.py ────────► graph.py, main.py (JudgeVerdict / payloads API)
 metrics.py ────────► main.py           (log CSV par email)

 graph.py (WORKFLOW) ──► main.py, test_smoke.py, langgraph.json (Studio)
```

Règle de lecture : aucune dépendance circulaire ; `config.py`, `schemas.py`,
`guardrails.py`, `metrics.py` sont des feuilles (n'importent rien du projet) ;
`graph.py` est le cœur ; `main.py` est le seul point d'entrée HTTP.

## Rôle de chaque fichier

| Fichier | Rôle | Importe (projet) | Importé par |
|---|---|---|---|
| `config.py` | Configuration centralisée (lit `.env`) : credentials Azure, noms de déploiements, seuils AUTO/HITL, retries | — | `llm`, `graph`, `main` |
| `schemas.py` | Contrats Pydantic : `TriageRequest`/`TriageResponse` (API), `JudgeVerdict` (validation judge), `PIIReport` | — | `graph`, `main` |
| `templates/` | Prompts versionnés `<agent>_vX.Y.txt` (classifier, drafter, judge). v1.0 = originaux, v1.1 = durcis anti-injection | — | lus par `prompts` |
| `prompts.py` | Loader de templates : charge la dernière version (ou épinglée via `.env`), expose `LOADED_VERSIONS` | — | `graph`, `main` |
| `guardrails.py` | Masquage PII (IBAN, NIR, CB+Luhn, tél, email) avant tout appel LLM. Regex par défaut, Presidio si installé | — | `graph` |
| `llm.py` | Client Azure OpenAI singleton + helpers `chat_json` / `chat_text` | `config` | `graph` |
| `graph.py` | **Cœur** : state LangGraph + 5 nœuds (guardrail → classifier → researcher → drafter ⇄ critic) + routage retry. Exporte `WORKFLOW` | `config`, `prompts`, `guardrails`, `llm`, `schemas` | `main`, `test_smoke`, Studio |
| `metrics.py` | Append CSV `metrics/metrics.csv` : 1 ligne par email (catégorie, notes judge, PII, latence, versions de prompts) | — | `main` |
| `main.py` | FastAPI : `POST /v1/triage` (invoque `WORKFLOW`, applique les seuils, logge les métriques), `GET /health` | `config`, `graph`, `metrics`, `prompts`, `schemas` | — (point d'entrée) |
| `test_smoke.py` | Test bout en bout console, hors FastAPI (1 email avec PII) | `graph` | — |
| `langgraph.json` | Déclare `graph.py:WORKFLOW` pour LangGraph Studio (`langgraph dev`) | — | — |

## Séquence d'exécution d'une requête

```
UiPath / curl
   │  POST /v1/triage (email brut)
   v
main.py ── WORKFLOW.invoke(state) ──► graph.py
   1. guardrail   masque la PII (guardrails.mask_pii) — le LLM ne verra rien
   2. classifier  catégorie/priorité/confiance   (llm.chat_json + templates classifier)
   3. researcher  no-op (RAG Phase 3)
   4. drafter     brouillon de réponse           (llm.chat_text + templates drafter)
   5. critic      judge 4 critères 1-5, verdict  (llm.chat_json + templates judge,
   │              validé par schemas.JudgeVerdict) ⇄ retry drafter si refus (max 2)
   v
main.py  applique SEUIL_AUTO/SEUIL_HITL → action AUTO/HITL/MANUAL
   ├── metrics.log_email() → metrics/metrics.csv
   └── TriageResponse (JSON) → UiPath
```

## Fichiers annexes

- `UPGRADE.md` — détail de l'upgrade v0.3.0-secured (guardrail, judge, templates, bug retry corrigé)
- `STUDIO.md` — visualisation live avec LangGraph Studio
- `_backup_avant_upgrade/` — fichiers d'avant l'upgrade (rollback manuel possible)
- `metrics/` — créé au premier email traité
- `.env` / `.env.example` — credentials et réglages (jamais à committer / publier)
