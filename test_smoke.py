"""Smoke test — un seul email passé au workflow, hors FastAPI.

Usage : python test_smoke.py
Prérequis : .env complet avec credentials Azure OpenAI valides.
"""
import json
import time

from graph import WORKFLOW


SAMPLE = {
    "email_from":    "marie.dupont@example.com",
    "email_subject": "Erreur sur ma facture de juillet",
    "email_body": """Bonjour,

Je vous contacte car ma facture du mois de juillet est incorrecte.
Le montant prélevé est de 320 EUR alors que mon contrat prévoit 280 EUR.
Le prélèvement a été fait sur mon compte FR76 3000 6000 0112 3456 7890 189.

Je souhaite un remboursement du trop-perçu dans les meilleurs délais.
Vous pouvez me joindre au 06 12 34 56 78.

Cordialement,
Marie Dupont""",
    "drafter_retries": 0,
    "trace": [],
}


def main():
    print("=" * 70)
    print("  Smoke test — IntelliMail Triage Backend (v0.3.0-secured)")
    print("=" * 70)
    print(f"\nEmail d'entrée :\n{SAMPLE['email_body'][:200]}...\n")

    t0 = time.perf_counter()
    result = WORKFLOW.invoke(SAMPLE)
    duration = int((time.perf_counter() - t0) * 1000)

    print(f"\n>>> Pipeline terminé en {duration} ms\n")
    print(f"Catégorie       : {result.get('categorie')}")
    print(f"Priorité        : {result.get('priorite')}")
    print(f"Confiance       : {result.get('confiance'):.2f}")
    print(f"Résumé          : {result.get('resume')}")
    print(f"PII masquées    : {result.get('pii_entities')} "
          f"(moteur {result.get('pii_engine')})")
    print(f"Judge verdict   : {result.get('judge_verdict')} "
          f"{result.get('judge_scores')}")
    print(f"Judge approved  : {result.get('critic_approved')} "
          f"(score {result.get('critic_score', 0):.2f})")
    print(f"Judge feedback  : {result.get('critic_feedback')}")
    print(f"\n--- Brouillon ---\n{result.get('draft')}\n--- Fin ---\n")

    print("Trace agents :")
    for t in result.get("trace", []):
        print(f"  • {t['agent']:11} {t['duration_ms']:5} ms  "
              f"{'OK' if t['success'] else 'KO'}  {t.get('note') or ''}")

    print("\n✅ Smoke test OK" if result.get("draft") else "\n❌ Pas de brouillon généré")


if __name__ == "__main__":
    main()
