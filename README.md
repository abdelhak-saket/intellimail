# IntelliMail Triage Backend

POC de triage d'e-mails clients (banque/assurance) : un e-mail entre, un pipeline
multi-agent LangGraph l'analyse et ressort un brouillon de réponse accompagné d'une
décision **AUTO** (envoi automatique), **HITL** (validation humaine) ou **MANUAL**
(traitement manuel). Consommé par UiPath via `POST /v1/triage`.

---

## 1. Comportement fonctionnel de bout en bout

### Vue d'ensemble

```
Outlook → UiPath → POST /v1/triage → LangGraph → réponse JSON → UiPath
                                                                  ├─ AUTO   : réinjecte la PII puis envoie le draft
                                                                  ├─ HITL   : file d'attente de validation (Phase 3)
                                                                  └─ MANUAL : laissé en Inbox
```

### Étape 0 — Réception et idempotence

L'API reçoit l'e-mail (`email_from`, `email_subject`, `email_body`, `message_id`).
Si le même `message_id` a déjà été traité (retry UiPath, redémarrage), la réponse
déjà calculée est renvoyée depuis un cache (champ `duplicate: true`) : pas de
double traitement, pas de double coût LLM.

### Étape 1 — Guardrail (déterministe, aucun LLM)

1. **Entrée dégénérée** : corps vide ou quasi-vide (< `DEGENERATE_MIN_CHARS`
   caractères) → escalade HITL immédiate, **zéro appel LLM**, coût zéro.
2. **Masquage PII** : IBAN, NIR, carte bancaire (validation Luhn), téléphone,
   email sont remplacés par des placeholders (`[IBAN_MASQUE]`...). La PII réelle
   ne quitte jamais le SI — le LLM ne voit que les versions masquées.
3. **Masquage du nom client** : le nom est extrait de l'expéditeur et remplacé
   par `[CLIENT_NAME]`. La réponse API contient une carte de réinjection
   (`pii_reinjection`) que le robot UiPath applique au moment de l'envoi.

### Étape 2 — Classifier (LLM)

Classe l'e-mail : catégorie (`reclamation`, `resiliation`, `donnees_personnelles`,
`demande`, `information`, `facturation`, `support_technique`, `spam`, `autre`),
priorité (`haute`/`normale`/`basse`), résumé, score de confiance 0-1.
Le contenu de l'e-mail est traité comme une donnée, jamais comme une instruction
(protection anti-injection dans le prompt).

### Étape 3 — Researcher (RAG ChromaDB)

Recherche les passages les plus pertinents du corpus documentaire (FAQ,
procédures, délais réglementaires — `corpus/`, 17 documents) et les fournit au
drafter. La requête utilise les versions masquées (aucune PII vers les
embeddings). Fail-safe : corpus non ingéré → le pipeline continue sans contexte.

### Étape 4 — Drafter ⇄ Judge (boucle LLM)

Le **drafter** rédige une réponse en français (5-10 lignes) à partir de l'e-mail
masqué, de la classification et des contextes RAG. Le **judge** (LLM-as-a-judge,
sortie Pydantic stricte) note 4 critères (pertinence, ton, conformité,
factualité, 1-5) et rend un verdict `AUTO_SEND` / `HUMAN_REVIEW` / `REJECT`.
Si refus, le drafter réessaie avec le feedback (max `MAX_DRAFTER_RETRIES`).
Sortie judge invalide = fail-closed → revue humaine.

### Étape 5 — Décision finale (déterministe, dans l'ordre)

Table de règles déterministes dans `rules.py` — aucune inférence, que du regex
et des listes, donc auditable et modifiable sans toucher au modèle.

| Priorité | Règle | Décision |
|---|---|---|
| 1 | Entrée dégénérée | HITL (`degenerate_input`) |
| 2 | Catégorie dans `HITL_FORCE_CATEGORIES` — réclamation, résiliation, données personnelles, **spam**, **autre** | HITL quel que soit le score (`rules_table:<cat>`) |
| 3 | Priorité dans `HITL_FORCE_PRIORITIES` (haute) | HITL (`priorite:haute`) |
| 4 | Opération sensible détectée dans l'e-mail reçu | HITL (`sensitive:<règle>`) |
| 5 | Garde-fou de sortie : le brouillon produit est suspect | HITL (`output_guardrail:<règle>`) |
| 6 | Verdict judge = REJECT | HITL (`judge_reject`) |
| 7 | confiance ≥ `SEUIL_AUTO` (0.85) **et** judge approuve | AUTO |
| 8 | confiance ≥ `SEUIL_HITL` (0.70) | HITL |
| 9 | sinon | MANUAL |

Règles d'opérations sensibles (règle 4) — deux familles :

- *par le texte* (regex) : changement de coordonnées bancaires, procuration/mandat,
  difficulté de paiement, décès/succession, fraude suspectée, menace juridique,
  contestation explicite, hors périmètre client (presse/RH), expéditeur `noreply` ;
- *par l'état calculé* (insensible à la formulation) : IBAN / carte / NIR transmis
  en clair, corps sans contenu exploitable renvoyant à une pièce jointe.

Garde-fou de sortie (règle 5) — le brouillon lui-même est inspecté avant envoi :
engagement commercial (code promo, contrat annulé), lien externe, discours
méta-IA, confirmation de remboursement. **Mesuré sur le dataset : une
instruction cachée dans la signature d'un e-mail a franchi à la fois la règle
anti-injection du prompt du drafter et le LLM-as-a-judge (qui a noté le
brouillon 1.0). Seule une vérification déterministe de la sortie l'arrête.**

Trois principes derrière ces règles : on ne répond jamais à ce qu'on n'a pas su
classer (`autre`) ; répondre à un phishing confirme au fraudeur que l'adresse
est active (`spam`) ; et on ne fait confiance ni à l'entrée ni à la sortie du
modèle. Le champ `decision_reason` trace la règle appliquée — premier étage de
la piste d'audit.

### Étape 6 — Validation humaine (HITL)

Tout e-mail dont l'action est HITL ou MANUAL entre dans une file d'attente
SQLite (`hitl_queue.db`) avec l'e-mail brut *et* masqué, le brouillon, la
classification, la raison d'escalade et la trace des agents. L'agent traite la
file depuis l'écran Streamlit : il voit ce que le LLM a vu (version masquée) à
côté de l'original, puis **valide**, **corrige** ou **rejette** le brouillon.

Chaque décision est journalisée en append-only — qui, quoi, quand, et le texte
final s'il a été édité. Une reprise de dossier ajoute une ligne au lieu
d'écraser la précédente. Avec `decision_reason` (la règle automatique qui a
déclenché l'escalade), cela forme la piste d'audit complète : pourquoi la
machine a escaladé, et ce que l'humain en a fait.

Le garde-fou de sortie s'applique aussi au texte corrigé par l'humain :
l'écran alerte si la version éditée contient un lien ou un engagement
commercial.

### Étape 7 — Observabilité

Chaque e-mail écrit une ligne dans `metrics/metrics.csv` (table de runs
branchable Power BI) : horodatage, catégorie, verdict, décision et sa raison,
PII masquées, tokens et **coût estimé**, latence, versions de prompts, colonne
`human_decision` (réservée à l'UI HITL Phase 3).

### Réponse JSON (extrait)

```json
{
  "classification": {"categorie": "facturation", "priorite": "normale", "confiance": 0.92},
  "draft_reply": "Bonjour [CLIENT_NAME], ...",
  "critic": {"approved": true, "score": 0.85, "verdict": "AUTO_SEND",
             "scores": {"pertinence": 4, "ton": 5, "conformite": 4, "factualite": 4}},
  "pii": {"entities": {"IBAN": 1, "TEL": 1, "NOM": 2}, "engine": "regex"},
  "pii_reinjection": {"[CLIENT_NAME]": "Marie Dupont"},
  "action": "AUTO", "requires_human": false, "decision_reason": "seuils",
  "tokens_in": 1840, "tokens_out": 420, "cost_usd_estimate": 0.001408,
  "duplicate": false, "total_duration_ms": 4231,
  "agent_trace": [{"agent": "guardrail", "duration_ms": 2, "success": true}, "..."]
}
```

---

## 2. Lancer le POC — étapes techniques

### Prérequis

- **Python 3.11+** (testé en 3.13) — `py -3.13 --version`
- Un accès **Azure OpenAI** : endpoint + clé + un déploiement chat (`gpt-4.1-mini`)
- Commandes ci-dessous : **Windows / PowerShell**, depuis le dossier du projet

### Étape 1 — Installation

```powershell
cd "D:\Dossier-principal\Poc RAG\Uipath LLM poc email\IntelliMail_Backend"
py -3.13 -m venv .venv ; .venv\Scripts\Activate.ps1 ; $env:PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 ; python -m pip install --upgrade pip ; python -m pip install -r requirements.txt
```

> Si `Activate.ps1` est bloqué : `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

### Étape 2 — Configuration

```powershell
copy .env.example .env
```

Renseigner dans `.env` : `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, les
noms de déploiements. Les seuils, la table de règles HITL, les prix tokens et
le RAG sont préconfigurés avec des valeurs par défaut raisonnables.
**Ne jamais commiter le `.env`.**

### Étape 3 — Ingérer le corpus RAG (une fois)

```powershell
python ingest_corpus.py
```

Lit `corpus/*.md` (17 documents), les découpe en ~80 chunks et les indexe dans
ChromaDB (`chroma_db/`). Idempotent — relancer après toute modification du
corpus. Sans cette étape le pipeline fonctionne, mais sans contexte documentaire.

### Étape 4 — Test rapide (hors serveur)

```powershell
python test_smoke.py
```

Passe un e-mail de bout en bout et affiche classification, PII masquées,
verdict du judge, brouillon et trace des agents.

### Étape 5 — Lancer l'API

```powershell
python main.py
# ou : uvicorn main:app --reload
```

API sur `http://127.0.0.1:8000` — Swagger : `/docs` — santé : `/health`
(expose versions de prompts et catégories à HITL forcé).

### Étape 6 — Appeler le triage

```powershell
curl -X POST http://127.0.0.1:8000/v1/triage ^
  -H "Content-Type: application/json" ^
  -d "{\"email_from\":\"marie.dupont@example.com\",\"email_subject\":\"Erreur facture\",\"email_body\":\"Bonjour, ma facture de juillet est incorrecte. Marie Dupont\",\"message_id\":\"MSG-001\"}"
```

Cas à tester : corps `".."` → HITL direct sans LLM ; e-mail de réclamation →
HITL forcé même à confiance 0.99 ; même `message_id` deux fois → `duplicate: true`.

### Étape 7 — Écran de validation humaine

La file se remplit par les appels à `/v1/triage`. Pour la peupler avec des cas
réalistes (démo, recette), depuis un **second terminal**, l'API tournant dans
le premier :

```powershell
python seed_queue.py          # 15 e-mails variés, un par famille de règle
python seed_queue.py --all    # les 60 du dataset
```

> `benchmark.py` n'alimente pas la file : il appelle le workflow directement,
> sans passer par l'API. C'est voulu (mesure sans réseau), mais cela veut dire
> qu'un run de benchmark laisse l'écran HITL vide.

Puis, dans un **troisième terminal** :

```powershell
python -m streamlit run app_hitl.py
```

> **Postes Windows avec contrôle d'application (WDAC / Smart App Control)**
> Si `streamlit run` échoue avec « Une stratégie de contrôle d'application a
> bloqué ce fichier », c'est le lanceur `streamlit.exe` généré par pip qui est
> refusé — non signé. Passer par le module (`python -m streamlit`) résout le
> problème : seul `python.exe`, déjà autorisé, s'exécute. Le blocage revient
> après chaque `pip install`, qui régénère le `.exe` avec un nouveau hash.
> Même contournement au besoin : `python -m uvicorn main:app`.

S'ouvre sur `http://localhost:8501`. L'API n'a pas besoin de tourner : l'écran
lit directement la base alimentée par `/v1/triage`. Trois onglets :

- **File d'attente** — les escalades, e-mail brut/masqué côte à côte, brouillon
  éditable, raison d'escalade justifiée, trace des agents, actions
  valider / corriger / rejeter
- **Réglages** — les trois seuils de confiance et la table de règles
  (catégories et priorités à escalade forcée, activation des garde-fous),
  modifiables **à chaud** : l'API les relit au prochain e-mail, sans
  redémarrage. Toute modification est horodatée et signée.
- **Audit** — le journal des décisions humaines, la répartition des motifs
  d'escalade, et l'export CSV pour Power BI

Renseignez votre identifiant dans la barre latérale : il est journalisé avec
chaque décision.

### Optionnel — LangGraph Studio (visualisation du graphe)

```powershell
langgraph dev
```

Serveur sur le port 2024, Studio :
`https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`.
Studio (2024) et FastAPI (8000) sont deux serveurs distincts → deux terminaux.

> ⚠️ Si `langgraph dev` plante avec `ImportError: cannot import name 'feature_flags'` :
> versions LangGraph incohérentes dans le venv. Correctif :
> `python -m pip install -r requirements.txt` (versions épinglées) ou `.\corriger_langgraph.bat`.

---

## 3. Structure du projet

```
IntelliMail_Backend/
├── main.py                  FastAPI : /v1/triage, décision finale, idempotence
├── graph.py                 LangGraph : guardrail → classifier → researcher → drafter ⇄ judge
├── rules.py                 Table de règles déterministes d'escalade (regex, sans LLM)
├── hitl_api.py              Endpoints REST de la file (Copilot Studio / UiPath)
├── app_hitl.py              UI Streamlit : validation humaine des escalades
├── store.py                 File d'attente HITL + journal d'audit (SQLite)
├── runtime_config.py        Seuils et règles modifiables à chaud depuis l'UI
├── benchmark.py             Rejoue le dataset et mesure les faux AUTO_SEND
├── guardrails.py            Masquage PII + [CLIENT_NAME] (regex / Presidio)
├── rag.py                   Accès ChromaDB (requête fail-safe)
├── ingest_corpus.py         Ingestion corpus/*.md → ChromaDB
├── llm.py                   Client Azure OpenAI + comptage tokens
├── prompts.py               Loader de templates versionnés (templates/)
├── schemas.py               Modèles Pydantic (requête / réponse / JudgeVerdict)
├── config.py                Réglages (.env) : seuils, règles HITL, prix, RAG
├── metrics.py               Table de runs CSV (metrics/metrics.csv → Power BI)
├── corpus/                  17 documents FAQ / procédures (base RAG)
├── dataset/                 Vérité terrain : 50 e-mails étiquetés + 10 adverses
├── templates/               Prompts versionnés (classifier v1.2, drafter, judge)
└── test_smoke.py            Test bout en bout hors FastAPI
```

Détails : **ARCHITECTURE.md** (relations entre fichiers), **UPGRADE.md**
(historique sécurité), `dataset/README.md` (conventions d'étiquetage),
`demo/copilot_studio_agent.md` (agent Teams de validation),
`demo/tournage_hitl.md` (captation vidéo de la démo).

### API de la file HITL

| Endpoint | Consommateur | Rôle |
|---|---|---|
| `GET /v1/hitl/queue` | Agent / UI | E-mails en attente, avec le motif d'escalade en clair |
| `GET /v1/hitl/case/{id}` | Agent / UI | Détail + brouillon (PII masquée par défaut) |
| `POST /v1/hitl/decision` | Agent / UI | Valider, corriger, rejeter — garde-fou de sortie réappliqué |
| `GET /v1/hitl/approved` | Robot | Brouillons approuvés à envoyer + carte de réinjection PII |
| `POST /v1/hitl/sent` | Robot | Confirmation d'envoi, idempotente |
| `GET /v1/kb/search` | Agent | Recherche dans les procédures internes |
| `GET /v1/rules` | Agent | Règles d'escalade en vigueur |

Le schéma OpenAPI (`/openapi.json`) est directement importable comme connecteur
personnalisé Power Platform.

## 4. Roadmap

- **Fait** : pipeline 5 agents, guardrail PII + nom, règles d'escalade
  déterministes (entrée et sortie), entrée dégénérée, RAG ChromaDB, coût par
  e-mail, idempotence, datasets étiquetés + adverses, benchmark mesuré,
  UI HITL avec journal d'audit et réglages à chaud.
- **Reste** : intégration UiPath bout en bout (timeout, retry, réinjection de
  `[CLIENT_NAME]`, test Outlook → triage → HITL → envoi), puis Azure Key Vault,
  déploiement Bicep et dashboard Power BI.

### Résultats mesurés (60 e-mails, dont 10 adverses)

| Métrique | Valeur |
|---|---|
| Faux AUTO_SEND | 0 % |
| Sans la table de règles (contrefactuel) | 94,7 % |
| Brouillons approuvés par le LLM-as-a-judge | 98,3 % |
| Précision de classification | ~83 % |
| Coût par e-mail | 0,00125 $ |
| Latence moyenne | 6,5 s |
| Taux d'escalade | 63 % |

La lecture importante n'est pas le 0 % mais l'écart avec le contrefactuel : le
LLM-as-a-judge a approuvé des réponses à un phishing, à un jailbreak et à une
tentative d'injection. **Il évalue la qualité rédactionnelle du brouillon, pas
l'opportunité de l'envoyer.** Ce sont les règles déterministes qui arrêtent ces
cas, y compris une injection qui avait franchi la consigne anti-injection du
prompt système et obtenu 1,0 du judge.

Réserve méthodologique : le dataset est synthétique et écrit par l'auteur du
système. Ces chiffres démontrent que le pipeline traite correctement les cas
anticipés, pas qu'il résiste à des attaques non imaginées.
