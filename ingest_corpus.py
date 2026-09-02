"""Ingestion du corpus documentaire dans ChromaDB.

Usage : python ingest_corpus.py
- Lit tous les corpus/*.md
- Découpe chaque fichier par sections "## " (1 section = 1 chunk)
- Réingère tout (idempotent : ids stables, upsert)

Prérequis : pip install chromadb
"""
import re
import sys

from rag import CORPUS_DIR, get_collection


def chunk_markdown(text: str) -> list:
    """Découpe par sections '## '. Retourne [(titre, contenu), ...].
    Le préambule avant la première section est un chunk 'intro'."""
    parts = re.split(r"^## +", text, flags=re.M)
    chunks = []
    intro = parts[0].strip()
    if intro:
        title = intro.splitlines()[0].lstrip("# ").strip() or "intro"
        chunks.append((title, intro))
    for part in parts[1:]:
        lines = part.strip().splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        body = "\n".join(lines).strip()
        if body:
            chunks.append((title, body))
    return chunks


def main() -> int:
    files = sorted(CORPUS_DIR.glob("*.md"))
    if not files:
        print(f"Aucun fichier dans {CORPUS_DIR} — rien à ingérer.")
        return 1

    col = get_collection(create=True)

    ids, docs, metas = [], [], []
    for f in files:
        for i, (title, body) in enumerate(chunk_markdown(f.read_text(encoding="utf-8"))):
            ids.append(f"{f.stem}-{i}")
            docs.append(body)
            metas.append({"source": f.stem, "section": title})

    col.upsert(ids=ids, documents=docs, metadatas=metas)
    print(f"Ingéré : {len(files)} fichiers → {len(ids)} chunks "
          f"dans la collection '{col.name}'.")

    # Sanity check
    from rag import query
    hits = query("contestation d'un prélèvement sur ma facture")
    print(f"Test de requête : {len(hits)} hit(s)")
    for h in hits:
        print(f"  • {h[:110]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
