# Post LinkedIn — Phase 2 follow-up (avec vidéo)

> Suite du post de lancement. Annonce Phase 2 livrée + vidéo demo 89s.
> Garde le même ton "build in public" et reprend les hashtags du post initial.

---

## VERSION A — Punchy (recommandée, ~1500 chars)

🚀 Phase 2 of IntelliMail Triage — shipped.

90 seconds to see the agentic backend in action ⬇️

[ATTACH VIDEO]

What you're seeing:
▸ A real customer email enters the pipeline
▸ Classifier identifies "billing complaint · high priority · 0.93 confidence"
▸ Drafter writes a contextualized response — not a template, an actual answer
▸ Critic reviews tone, conformity, hallucinations — approves or sends back for retry
▸ Full agent trace inspectable in LangGraph Studio

🛠️ Stack used here:
• Python 3.12 + FastAPI + LangGraph
• Azure OpenAI Foundry (gpt-4.1-mini)
• LangGraph Studio for live debugging
• ~5 seconds end-to-end per email

💡 The retry that surprised me:

On the first run, the Drafter suggested a refund without factual basis. The Critic caught it, sent the draft back, and the second attempt was more conservative — asking for the contract reference before promising anything.

No prompt change. No retry logic I hard-coded. Just the graph doing what graphs do when each agent has one job and the boundaries are explicit.

That's the behavior you want before this thing touches a real customer inbox in banking.

🗓️ Phase 3 next: ChromaDB-backed Researcher (actual RAG over FAQ + procedures) and a Streamlit UI for the human-in-the-loop validation queue.

Code lands on GitHub at Phase 5.

If you're shipping agentic systems into regulated industries — DMs open, I'm collecting battle scars.

#RPA #UiPath #LangGraph #AzureOpenAI #AgenticAI #BFSI #BuildInPublic #IntelligentAutomation

---

## VERSION B — Plus dense (~1900 chars)

⚡ Phase 2 of IntelliMail Triage — DONE.

The agentic backend is live. 89 seconds of demo below ⬇️

[ATTACH VIDEO]

🎯 What the multi-agent pipeline does on a single email:

1️⃣ Classifier — gpt-4.1-mini reads the body, returns category + priority + confidence score
2️⃣ Researcher — placeholder for now, becomes RAG in Phase 3
3️⃣ Drafter — composes a personalized reply using classification + retrieved context
4️⃣ Critic — audits the draft for tone, hallucinations, conformity, and either approves or triggers a retry

The conditional retry between Critic and Drafter is the part most people skip. It's also what makes the difference between a portfolio demo and something a compliance officer would actually allow into production.

🛠️ Built on:
• FastAPI + LangGraph (Python 3.12)
• Azure OpenAI Foundry (gpt-4.1-mini deployed on EU souverain)
• LangGraph Studio for visual debugging + state inspection
• Defensive coding: every agent failure is captured in state.errors, the pipeline never cascades blind

📊 Live numbers from my synthetic run:
• ~5s end-to-end per email
• Critic triggered 1 retry on first 5 emails (caught a hallucinated refund offer — exactly the failure mode this layer exists for)
• $0.04 average per email with gpt-4.1-mini

💡 What I'm learning by building in public:

The hard part isn't writing the agents. It's deciding what each one is allowed to know and decide. The Critic was tempted to rewrite drafts itself — I kept it strictly as a verdict-giver. That separation is what makes the system inspectable, and inspectability is non-negotiable in BFSI.

🗓️ Next:
• Phase 3 — ChromaDB RAG + Streamlit HITL UI
• Phase 4 — UiPath consumes /v1/triage instead of calling Azure directly
• Phase 5 — Bicep deployment + GitHub repo public

Working on agentic flows in banking/insurance? I'd value the pushback.

#RPA #UiPath #LangGraph #AzureOpenAI #AgenticAI #BFSI #BuildInPublic #IntelligentAutomation

---

## Notes d'utilisation

- **Upload la vidéo** `demo_out/IntelliMail_demo_90s.mp4` directement dans LinkedIn — pas en lien externe (perd 70% de la portée).
- **Heure de publication idéale** : mardi-jeudi, 8h-10h ou 17h-19h heure de la cible (Paris/Lyon).
- **Premier commentaire** : reposte 1-2 hashtags clés pour booster la portée :
  > "PS: full repo will land on GitHub at Phase 5. Following the build in public timeline."
- **Engagement astuce** : réponds dans les 30 premières minutes aux 3 premiers commentaires — LinkedIn boost ce signal pour décider de la diffusion.

## Petits ajustements à faire avant publication

- [ ] Remplace **"billing complaint · high priority · 0.93 confidence"** par les vraies valeurs si elles diffèrent dans ta vidéo
- [ ] Ajoute le lien vers le post initial Phase 1 en commentaire pour donner la suite
- [ ] Si tu publies un mardi matin, vérifie que LangGraph Studio est joignable côté tracing au cas où un recruteur demanderait une démo live
