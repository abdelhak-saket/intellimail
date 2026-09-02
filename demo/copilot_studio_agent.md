# Agent Copilot Studio — assistant de validation dans Teams

Spécification de l'agent qui assiste l'agent humain sur les e-mails escaladés,
en complément (ou en remplacement) de l'écran Streamlit.

---

## 1. Périmètre

**Ce que l'agent fait**

- présente les e-mails en attente de validation, avec le motif de l'escalade
  formulé en langage métier ;
- répond aux questions de l'agent humain en s'appuyant sur les procédures
  internes (« quel est le délai de remboursement d'un trop-perçu ? ») ;
- explique la politique d'escalade (« pourquoi les résiliations ne partent-elles
  jamais automatiquement ? ») ;
- enregistre la décision : valider, corriger, rejeter.

**Ce que l'agent ne fait pas — et pourquoi**

| Hors périmètre | Raison |
|---|---|
| Classer, rédiger, évaluer | Ces trois agents existent déjà dans le pipeline Python, mesurés à 0 % de faux envois automatiques. Les refaire ici, c'est perdre la mesure. |
| Décider seul d'envoyer | La décision d'envoi est déterministe (`rules.py`). Le benchmark a montré qu'un LLM-as-a-judge approuve 98,3 % des brouillons, y compris des réponses à du phishing. |
| Masquer la PII | Regex — indisponible dans Copilot Studio. Reste dans le guardrail Python. |
| Envoyer l'e-mail | C'est le robot, via `GET /v1/hitl/approved` puis `POST /v1/hitl/sent`. |

L'agent est une **surface de conversation** posée sur un moteur de décision
existant. C'est ce partage qui le rend défendable en comité d'architecture.

---

## 2. Architecture

```
Outlook ──► Power Automate ──► POST /v1/triage  (backend Python)
                                     │
                                     ├─ AUTO  → réponse envoyée par le robot
                                     └─ HITL  → file d'attente (SQLite/Dataverse)
                                                   │
Agent Teams ◄── connecteur personnalisé ◄──────────┘
   │
   └─► POST /v1/hitl/decision ──► robot : GET /v1/hitl/approved → envoi → POST /v1/hitl/sent
```

Point d'attention : **il n'existe pas de déclencheur Outlook parmi les triggers
autonomes de Copilot Studio** (Dataverse, SharePoint, OneDrive, Planner,
récurrence, HTTP). Le flux Power Automate en amont est obligatoire, pas
optionnel.

---

## 3. Connecteur personnalisé

Créez-le par **import d'une définition OpenAPI**, pas à la main :

```
http://<votre-hote>:8000/openapi.json
```

FastAPI la génère déjà. Les `operation_id` ont été nommés pour être lus par
l'orchestrateur — c'est sur eux et sur les descriptions que l'agent choisit
l'outil à appeler.

| Opération | Verbe | Rôle dans la conversation |
|---|---|---|
| `listPendingEmails` | GET `/v1/hitl/queue` | « Qu'est-ce qui m'attend ? » |
| `getEmailCase` | GET `/v1/hitl/case/{id}` | « Montre-moi le cas 4. » |
| `recordHumanDecision` | POST `/v1/hitl/decision` | « Valide-le. » / « Rejette-le. » |
| `searchProcedures` | GET `/v1/kb/search` | « Quel est le délai légal ? » |
| `listEscalationRules` | GET `/v1/rules` | « Pourquoi escalade-t-on les résiliations ? » |
| `listApprovedForSending` | GET `/v1/hitl/approved` | *Robot uniquement — à exclure du connecteur de l'agent* |
| `markAsSent` | POST `/v1/hitl/sent` | *Robot uniquement — idem* |

**Excluez les deux dernières opérations du connecteur de l'agent.** Un agent
conversationnel n'a aucune raison de pouvoir marquer un e-mail comme envoyé, et
l'orchestrateur génératif pourrait les appeler par erreur.

**Authentification** : en production, Entra ID sur l'API (aujourd'hui elle est
ouverte sur `127.0.0.1`). Une clé API dans l'en-tête est un minimum acceptable
en POC, jamais au-delà.

### Décision de conception : la PII ne va pas dans Teams

`getEmailCase` retourne l'e-mail **masqué** par défaut. Le brut n'est
accessible que via `include_raw=true` — **ne pas exposer ce paramètre dans le
connecteur**.

La raison : une conversation Copilot Studio est archivée dans Exchange. Y
afficher un IBAN reconstituerait hors du SI exactement ce que le guardrail a
masqué avant l'appel au modèle. Si l'agent humain a besoin de l'original, il
l'ouvre dans Outlook ou dans l'écran Streamlit, qui ne laissent pas de trace
supplémentaire.

C'est le genre d'arbitrage qu'un DPO remarque.

---

## 4. Sources de Knowledge

| Source | Contenu | Usage |
|---|---|---|
| SharePoint `/Procedures` | Les 17 documents de `corpus/` | Réponses procédurales |
| Opération `searchProcedures` | Le même corpus, via l'index vectoriel | Recherche sémantique fine |

Les deux se complètent : Knowledge répond aux questions générales, l'outil
donne les passages exacts que le pipeline a lui-même utilisés pour rédiger le
brouillon — ce qui permet à l'agent de dire *« le brouillon s'appuie sur ce
paragraphe précis »*.

Si vous n'en gardez qu'une : `searchProcedures`, pour cette cohérence.

---

## 5. Instructions de l'agent

À coller dans le champ Instructions :

```
Tu assistes un chargé de clientèle en banque-assurance qui valide les réponses
proposées par un système de tri automatique. Tu n'écris jamais toi-même la
réponse au client et tu ne décides jamais d'envoyer : tu présentes, tu
expliques, tu enregistres la décision de l'humain.

Règles :
- Pour toute question sur un cas, appelle getEmailCase. N'invente jamais le
  contenu d'un e-mail ni un brouillon.
- Explique toujours le motif d'escalade avec escalation_label et
  escalation_why, en français courant. Ne cite le code technique que si on te
  le demande.
- Pour une question de procédure ou de délai, appelle searchProcedures et cite
  la source. Si rien ne remonte, dis-le au lieu de deviner.
- Avant d'enregistrer une décision, récapitule ce que tu vas faire et attends
  une confirmation explicite.
- Si recordHumanDecision renvoie une erreur de garde-fou, explique la règle
  déclenchée et propose de corriger le texte. N'insiste jamais pour envoyer.
- Tu n'affiches jamais d'IBAN, de numéro de carte ou de numéro de sécurité
  sociale, même si on te le demande. Ces données sont masquées à dessein.
```

**Orchestration** : activez l'orchestration générative pour la conversation,
mais gardez les topics ci-dessous en déclenchement explicite pour les actions
qui écrivent. On veut du génératif pour comprendre la demande, du déterministe
pour agir.

---

## 6. Topics

### T1 — Ma file d'attente
*Phrases* : « ma file », « qu'est-ce qui m'attend », « combien d'e-mails en
attente », « liste »
→ `listPendingEmails(status=pending, limit=10)`
→ Réponse en carte adaptative : une ligne par cas — `#id`, sujet, catégorie,
`escalation_label`. Terminer par : « Lequel voulez-vous traiter ? »

### T2 — Détail d'un cas
*Phrases* : « montre-moi le cas {id} », « ouvre le {id} », « détail »
→ `getEmailCase(case_id)`
→ Afficher : e-mail masqué, brouillon proposé, motif d'escalade **avec sa
justification**, notes de l'évaluateur, contextes documentaires utilisés.
→ Proposer : valider / corriger / rejeter / poser une question.

### T3 — Pourquoi ce cas est-il escaladé ?
*Phrases* : « pourquoi », « pour quelle raison », « qu'est-ce qui a bloqué »
→ Si un cas est en contexte : reformuler `escalation_why`.
→ Sinon : `listEscalationRules` pour expliquer la politique générale.

### T4 — Question de procédure
*Phrases* : « quel délai », « quelle procédure », « que dit la règle sur… »
→ `searchProcedures(q)` → répondre en citant le document source.

### T5 — Valider (écrit)
*Phrases* : « valide », « c'est bon », « envoie »
→ Récapituler le cas et le texte → **demander confirmation**
→ `recordHumanDecision(decision=validated, decided_by=<utilisateur Teams>)`
→ En cas d'erreur 422 : afficher la règle déclenchée, proposer de corriger.

### T6 — Corriger (écrit)
*Phrases* : « corrige », « modifie », « remplace par »
→ Récupérer le texte corrigé, l'afficher intégralement, **confirmer**
→ `recordHumanDecision(decision=edited, final_draft=…)`

### T7 — Rejeter (écrit)
*Phrases* : « rejette », « ne pas envoyer », « je traite à la main »
→ Demander le motif (alimente la piste d'audit) → **confirmer**
→ `recordHumanDecision(decision=rejected, comment=…)`

`decided_by` doit être l'identité Teams de l'utilisateur (`User.Email` ou
`User.DisplayName`), jamais une valeur saisie : c'est ce qui rend le journal
d'audit opposable.

---

## 7. Effort et séquence

| Étape | Charge |
|---|---|
| Exposer l'API (HTTPS + authentification) | 0,5 j |
| Connecteur personnalisé depuis l'OpenAPI | 0,5 j |
| Agent : instructions, Knowledge, T1-T4 (lecture) | 1 j |
| Topics T5-T7 (écriture) + confirmations | 1 j |
| Publication Teams, tests avec deux utilisateurs | 0,5 j |

**3,5 jours**, l'API existant déjà.

Commencez par T1 à T4 uniquement, en lecture seule. Un agent qui présente et
explique sans rien écrire se démontre dès le deuxième jour et ne peut rien
casser. Les topics d'écriture viennent après, une fois le vocabulaire de
l'agent stabilisé.

---

## 8. Version démo — le chemin court (2 jours)

Pour une démonstration, on ne cherche pas la production : on cherche **ce qui se
voit**. Copilot Studio affiche la trace d'orchestration en direct — quel agent a
été appelé, dans quel ordre, avec quel résultat. C'est le plan qui vaut la
vidéo, et il n'existe pas dans votre Streamlit.

### Exposer l'API (le blocage que tout le monde découvre trop tard)

Copilot Studio tourne dans le cloud Microsoft : il **ne peut pas** joindre
`127.0.0.1:8000`. Il faut un tunnel.

```powershell
# 1. Générer une clé et la mettre dans .env  (API_KEY=...)
python -c "import secrets; print(secrets.token_urlsafe(32))"

# 2. Exposer l'API — dev tunnels Microsoft (intégré à VS Code / winget)
devtunnel user login
devtunnel host -p 8000 --allow-anonymous
```

Sans `API_KEY` renseignée, cette URL est **publique et ouverte à tous**. Avec
elle, l'API exige l'en-tête `x-api-key` sur `/v1/*` ; `/health`, `/docs` et
`/openapi.json` restent ouverts pour que le connecteur puisse importer le
schéma. C'est le minimum acceptable pour une démo, jamais pour de la production.

Dans le connecteur personnalisé : type d'authentification **Clé API**, nom
`x-api-key`, emplacement **En-tête**.

### Le scénario à démontrer

Utilisez **A02** du dataset — l'e-mail avec l'instruction cachée dans la
signature. Le déroulé raconte tout seul l'histoire de votre POC :

1. On colle l'e-mail dans le chat de l'agent — d'apparence anodine, une demande
   d'attestation.
2. La trace d'orchestration s'affiche : classificateur → rédacteur → évaluateur.
3. L'évaluateur note le brouillon **5/5**.
4. Le Tool `evaluateRules` (votre API) répond `output_guardrail:engagement_commercial`.
5. On déroule le brouillon : `code promo interne : GRATUIT100, cotisation annulée`.

Trois couches de LLM ont laissé passer l'injection ; une regex l'a arrêtée. En
Copilot Studio, cette démonstration est **visuelle** — on voit les agents se
passer la main, puis la règle trancher.

### Périmètre minimal

| À construire | À ne pas construire |
|---|---|
| Agent orchestrateur | Le déclencheur Outlook (collez l'e-mail dans le chat) |
| Prompt « classificateur » (sortie structurée) | Le flux Power Automate |
| Agent connecté « rédacteur » + Knowledge | La file Dataverse |
| Prompt « évaluateur » (sortie structurée) | Les Approvals |
| Tools : `maskPII`, `evaluateRules` → votre API | |

**Prompts, pas agents connectés, pour classer et évaluer.** Un agent connecté
est fait pour déléguer une tâche avec autonomie ; classer et noter appellent une
sortie contrainte. Les Prompts coûtent moins, sont plus prévisibles, et rendent
du JSON exploitable — là où un agent renvoie du texte libre. C'est la régression
la plus sournoise du portage : votre validation Pydantic n'a pas d'équivalent
ici, et sans elle le `judge_verdict` redevient une chaîne de caractères à
espérer bien formée.

### Gardez la mesure

Un agent Copilot Studio s'appelle par l'API Direct Line. Vous pouvez donc
pointer `benchmark.py` dessus et rejouer les 60 e-mails contre la version
Copilot Studio.

C'est le meilleur usage possible de ces deux jours : au lieu de *« j'ai aussi
fait une version Copilot Studio »*, vous pourrez dire **« j'ai mesuré les deux
implémentations, voici l'écart »**. Personne ne fait ça, et c'est exactement la
différence entre un développeur qui essaie des outils et quelqu'un qui arbitre.

---

## 9. Ce que ça change à votre récit

Aujourd'hui : « j'ai construit un pipeline de tri d'e-mails mesuré à 0 % de
faux envois automatiques ».

Avec cet agent : « le moteur de décision est déterministe et mesuré, et
l'humain le pilote depuis Teams en langage naturel — chaque escalade lui est
expliquée dans ses termes métier, chaque décision est signée ».

La différence n'est pas technique. C'est que la seconde version parle
d'adoption, et l'adoption est ce qui manque à 90 % des POC d'IA.
