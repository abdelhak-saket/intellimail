"""Alimente la file HITL en postant des e-mails du dataset sur l'API.

Pourquoi ce script
------------------
`benchmark.py` appelle le workflow LangGraph directement (mesure pure, sans
réseau) : il ne passe donc jamais par `/v1/triage` et ne remplit pas la file
d'attente. Pour avoir un écran Streamlit peuplé — démo, recette, capture
d'écran — il faut de vrais appels HTTP. C'est ce que fait ce script.

Usage :
    python seed_queue.py                 # 15 e-mails variés (défaut)
    python seed_queue.py --all           # les 60 du dataset
    python seed_queue.py --only E01 A02  # cas précis
    python seed_queue.py --url http://127.0.0.1:8000

Prérequis : l'API doit tourner (python main.py) dans un autre terminal.
"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

DATASET_DIR = Path(__file__).parent / "dataset"

# Sélection par défaut : un panaché qui déclenche chaque famille de règle,
# pour que l'écran HITL montre la diversité des motifs d'escalade.
ECHANTILLON = ["E01", "E07", "E12", "E19", "E22", "E32", "E33", "E40",
               "E44", "E48", "E17", "E25", "A02", "A05", "A09"]


def load_dataset() -> list:
    rows = []
    for name in ("emails_labeled.jsonl", "emails_adversarial.jsonl"):
        f = DATASET_DIR / name
        if f.exists():
            rows += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()
                     if l.strip()]
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description="Alimente la file HITL via l'API")
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--all", action="store_true", help="les 60 e-mails")
    p.add_argument("--only", nargs="*", help="ids précis (E01 A02...)")
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--reset", action="store_true",
                   help="vide la file et le journal avant d'envoyer "
                        "(pratique pour refaire une prise de démo)")
    p.add_argument("--parallel", type=int, default=1, metavar="N",
                   help="N envois simultanés : accélère le remplissage pour "
                        "une captation vidéo (4 = ~4x plus rapide)")
    p.add_argument("--delay", type=float, default=0.0, metavar="S",
                   help="pause entre deux envois, pour cadencer la démo")
    p.add_argument("--fresh-ids", action="store_true",
                   help="identifiants uniques sans vider la file : permet de "
                        "rejouer un cas pour obtenir une nouvelle génération "
                        "(utile sur les cas adverses, dont le résultat varie)")
    args = p.parse_args()

    if args.reset:
        # L'API garde la base ouverte : on vide les tables plutôt que de
        # supprimer le fichier, qui resterait verrouillé sous Windows.
        import store
        store.init()
        with store._conn() as con:
            con.execute("DELETE FROM decisions")
            con.execute("DELETE FROM queue")
            con.execute("DELETE FROM sqlite_sequence WHERE name IN "
                        "('queue','decisions')")
        print("File et journal vidés — les compteurs repartent de zéro.\n")

    rows = load_dataset()
    if args.only:
        wanted = set(args.only)
    elif args.all:
        wanted = {r["id"] for r in rows}
    else:
        wanted = set(ECHANTILLON)
    items = [r for r in rows if r["id"] in wanted]
    if not items:
        print("Aucun e-mail sélectionné.")
        return 1

    try:
        httpx.get(f"{args.url}/health", timeout=5.0).raise_for_status()
    except Exception as e:
        print(f"API injoignable sur {args.url} : {e}\n"
              f"Lancez d'abord « python main.py » dans un autre terminal.")
        return 1

    # Le cache d'idempotence de l'API mémorise les message_id pendant 1 h et
    # renvoie la réponse en cache sans re-remplir la file. Après un --reset on
    # suffixe donc les identifiants, sinon la deuxième prise resterait vide.
    suffixe = f"-{int(time.time())}" if (args.reset or args.fresh_ids) else ""

    def payload_for(item: dict) -> dict:
        return {
            "email_from":    item["email_from"],
            "email_subject": item["email_subject"],
            "email_body":    item["email_body"],
            "job_id":        f"SEED-{item['id']}{suffixe}",
            "message_id":    f"<seed-{item['id']}{suffixe}@intellimail.local>",
        }

    compteurs: dict = {}
    lock = threading.Lock()
    total = len(items)
    done = 0

    def envoyer(item: dict, client: httpx.Client) -> None:
        nonlocal done
        try:
            r = client.post(f"{args.url}/v1/triage", json=payload_for(item))
            r.raise_for_status()
            d = r.json()
            ligne = (f"{item['id']:4} {d['classification']['categorie']:<20} "
                     f"{d['action']:<6} ({d['decision_reason']})"
                     f"{'  → file HITL' if d['requires_human'] else ''}")
            with lock:
                compteurs[d["action"]] = compteurs.get(d["action"], 0) + 1
        except Exception as e:
            ligne = f"{item['id']:4} ÉCHEC : {type(e).__name__}: {e}"
        with lock:
            done += 1
            print(f"  [{done:02}/{total}] {ligne}")

    print(f"Envoi de {total} e-mail(s) vers {args.url}/v1/triage"
          + (f" · {args.parallel} en parallèle" if args.parallel > 1 else "")
          + "\n")
    t0 = time.perf_counter()
    with httpx.Client(timeout=args.timeout) as client:
        if args.parallel > 1:
            with ThreadPoolExecutor(max_workers=args.parallel) as pool:
                list(pool.map(lambda it: envoyer(it, client), items))
        else:
            for item in items:
                envoyer(item, client)
                if args.delay:
                    time.sleep(args.delay)

    print(f"\nRécapitulatif : {compteurs} en {time.perf_counter() - t0:.0f} s")
    en_file = sum(v for k, v in compteurs.items() if k in ("HITL", "MANUAL"))
    print(f"{en_file} e-mail(s) en attente de validation.\n"
          f"Ouvrez l'écran : streamlit run app_hitl.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
