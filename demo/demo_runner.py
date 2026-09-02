"""Demo runner — sortie console esthétique, idéal pour screencast.

Usage : python demo/demo_runner.py
Prérequis : .env complet avec credentials Azure OpenAI.
"""
import sys
import time
from pathlib import Path

# Permet de lancer le script depuis demo/ ou depuis le dossier parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph import WORKFLOW


# ─── Style console ──────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
CYAN  = "\033[36m"
GOLD  = "\033[33m"
GREEN = "\033[32m"
ROSE  = "\033[35m"
RED   = "\033[31m"
GREY  = "\033[90m"


def banner(txt: str, color: str = CYAN):
    line = "═" * 72
    print(f"\n{color}{line}{RESET}")
    print(f"{color}{BOLD}  {txt}{RESET}")
    print(f"{color}{line}{RESET}\n")


def field(label: str, value, color: str = CYAN, width: int = 16):
    print(f"  {GREY}{label:<{width}}{RESET}{color}{value}{RESET}")


SAMPLES = [
    {
        "name": "Réclamation facturation",
        "color": GOLD,
        "input": {
            "email_from":    "marie.dupont@example.com",
            "email_subject": "Erreur sur ma facture de juillet",
            "email_body": (
                "Bonjour,\n\n"
                "Je vous contacte car ma facture du mois de juillet est incorrecte. "
                "Le montant prélevé est de 320 EUR alors que mon contrat prévoit 280 EUR.\n\n"
                "Je souhaite un remboursement du trop-perçu dans les meilleurs délais.\n\n"
                "Cordialement,\nMarie Dupont"
            ),
            "drafter_retries": 0,
            "trace": [],
        },
    },
    {
        "name": "Demande d'information",
        "color": CYAN,
        "input": {
            "email_from":    "jean.martin@example.com",
            "email_subject": "Question sur mon contrat",
            "email_body": (
                "Bonjour,\n\n"
                "Pourriez-vous m'indiquer si je peux modifier mon contrat en cours d'année "
                "ou si je dois attendre l'échéance ?\n\nMerci d'avance.\nJean"
            ),
            "drafter_retries": 0,
            "trace": [],
        },
    },
]


def run_one(sample: dict):
    banner(sample["name"], color=sample["color"])

    print(f"{BOLD}📥 EMAIL ENTRANT{RESET}")
    print(f"{DIM}De      :{RESET} {sample['input']['email_from']}")
    print(f"{DIM}Sujet   :{RESET} {sample['input']['email_subject']}")
    print(f"{DIM}Corps   :{RESET}")
    for line in sample["input"]["email_body"].strip().split("\n"):
        print(f"          {line}")

    print(f"\n{BOLD}🤖 PIPELINE AGENTIC{RESET}\n")

    t0 = time.perf_counter()
    result = WORKFLOW.invoke(sample["input"])
    total_ms = int((time.perf_counter() - t0) * 1000)

    # Trace par agent
    for entry in result.get("trace", []):
        ok = entry["success"]
        color = GREEN if ok else RED
        check = "✓" if ok else "✗"
        agent = entry["agent"]
        ms    = entry["duration_ms"]
        note  = entry.get("note") or ""
        print(f"  {color}{check}{RESET} {BOLD}{agent:<12}{RESET}{GREY}{ms:>5} ms{RESET}  {DIM}{note}{RESET}")

    print()
    field("Catégorie",       result.get("categorie", "?"),     GOLD)
    field("Priorité",        result.get("priorite", "?"),       GOLD)
    field("Confiance",       f"{result.get('confiance', 0):.2f}", GOLD)
    field("Résumé",          result.get("resume", "")[:80] + "...", DIM)
    field("Critic approuvé", result.get("critic_approved", False),
          GREEN if result.get("critic_approved") else RED)
    field("Critic score",    f"{result.get('critic_score', 0):.2f}", GREEN)

    print(f"\n{BOLD}✍️  BROUILLON RÉDIGÉ{RESET}")
    print(f"{GREY}{'─' * 72}{RESET}")
    draft = result.get("draft", "(aucun brouillon)")
    for line in draft.split("\n"):
        print(f"  {line}")
    print(f"{GREY}{'─' * 72}{RESET}")

    print(f"\n{CYAN}⏱  Total : {total_ms} ms{RESET}\n")


def main():
    banner("IntelliMail Triage Agent — Demo", color=ROSE)
    print(f"{DIM}Phase 2 : Multi-agent LangGraph + Azure OpenAI Foundry{RESET}\n"
          f"{DIM}Agents : Classifier → Researcher → Drafter ⇄ Critic{RESET}\n")
    time.sleep(1.5)  # respiration

    for sample in SAMPLES:
        run_one(sample)
        time.sleep(0.8)

    banner("Demo terminée — Phase 2 validée", color=GREEN)


if __name__ == "__main__":
    main()
