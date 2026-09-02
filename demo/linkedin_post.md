# Post LinkedIn — IntelliMail POC

> Format optimal LinkedIn : 1300-1900 caractères, première ligne accrocheuse, retours à la ligne fréquents pour la lisibilité mobile.
> Choisis la version qui te parle le plus, ou mixe-les.

---

## VERSION 1 — Hook "résultat"

🤖 J'ai construit un agent IA qui traite mes emails clients tout seul.

78% d'auto-traitement. 12 secondes par mail. 0,03€ de tokens.
Voici comment ça marche en 5 lignes 👇

──────────

📥 Un email arrive dans Outlook.
🏷️ Un Classifier (gpt-4.1-mini) détermine catégorie + priorité + score de confiance.
✍️ Un Drafter rédige une réponse contextualisée.
🛡️ Un Critic relit le brouillon — qualité, ton, hallucinations.
🤖 UiPath exécute : déplace l'email, crée le brouillon Outlook, log le tout.

──────────

🎯 Le vrai sujet n'était pas "classer des emails" — c'est :

→ Comment faire cohabiter un RPA déterministe (UiPath) et un cerveau probabiliste (LangGraph) ?
→ Comment garder un human-in-the-loop conforme BFSI sur les cas ambigus ?
→ Comment garantir 0 hallucination quand on engage la responsabilité de l'entreprise ?

──────────

⚙️ Stack :
• UiPath Studio 26 (RPA)
• Python 3.12 + FastAPI + LangGraph (multi-agent)
• Azure OpenAI Foundry (gpt-4.1-mini)
• ChromaDB (RAG — Phase 3)
• Streamlit (HITL UI — Phase 3)

──────────

📚 Toute l'archi est ici : [lien GitHub]
Phase 1 (RPA) : DONE ✅
Phase 2 (Agentic backend) : DONE ✅
Phase 3 (RAG + HITL) : en cours

Si tu bosses sur l'intégration RPA + IA agentic, je suis preneur d'échanges techniques.

#RPA #UiPath #AgenticAI #LangGraph #AzureOpenAI #BFSI #IA

---

## VERSION 2 — Hook "problème"

"Les agents IA ne tiendront jamais en production parce qu'ils hallucinent."

J'ai entendu ça 50 fois. Alors j'ai construit le contre-exemple.

──────────

🎯 Un POC de triage d'emails clients pour banque/assurance.
Avec 4 garde-fous explicites :

1️⃣ Un Classifier qui produit un **score de confiance**.
2️⃣ Un Critic qui audite chaque brouillon (ton, conformité, hallucinations).
3️⃣ Trois seuils de décision : >85% = AUTO, 70-85% = humain valide, <70% = manuel.
4️⃣ Un trail d'audit complet de chaque décision IA.

──────────

🏗️ Archi hybride :
• **UiPath** garde le contrôle déterministe (Outlook, Excel, audit).
• **LangGraph** porte l'intelligence (4 agents : Classifier, Researcher, Drafter, Critic).
• L'un sans l'autre = soit rigide soit imprévisible.
• Les deux = production-ready.

──────────

📊 Résultats sur 50 emails synthétiques :
✅ 78% d'auto-traitement
🧑 22% d'escalade HITL contrôlée
⏱️ 12s de latence moyenne
💰 0,03€ par mail

──────────

🛠️ Stack : UiPath + Python 3.12 + FastAPI + LangGraph + Azure OpenAI Foundry + ChromaDB + Streamlit.

Repo public : [lien GitHub]

Curieux d'échanger avec ceux qui poussent ce genre d'archi en production — DM ouverts.

#AgenticAI #RPA #UiPath #LangGraph #AzureOpenAI #ResponsibleAI

---

## VERSION 3 — Hook "démo"

▶️ 90 secondes de démo. Mon agent IA en action.

Email reçu :
"Bonjour, ma facture de juillet est de 320€ au lieu de 280€. Je veux un remboursement."

Ce qui se passe en arrière-plan :

🏷️ Classifier (1.0s)  →  facturation · haute · 0.93
🔍 Researcher (instant) →  [Phase 3 : recherche RAG dans la base FAQ]
✍️ Drafter (1.8s)     →  brouillon de réponse personnalisée
🛡️ Critic (1.4s)      →  ✓ ton approprié, pas d'hallucination

→ Action automatique : déplacement vers IntelliMail/Facturation + brouillon créé dans Outlook.

──────────

Ce que l'agent NE fait PAS tout seul :
❌ Inventer un montant ou une date
❌ Promettre un délai non étayé
❌ Traiter un cas à confiance < 70%

C'est ce qui le rend déployable en banque.

──────────

🏗️ Hybride RPA + Agentic :
• UiPath (déterministe) parle à Outlook
• LangGraph orchestre 4 agents IA
• Azure OpenAI Foundry alimente le cerveau

Open source : [lien GitHub]
Phase 1+2 livrées · Phase 3 (RAG + HITL UI) en cours.

#RPA #UiPath #AgenticAI #LangGraph #AzureOpenAI #PortfolioProject
