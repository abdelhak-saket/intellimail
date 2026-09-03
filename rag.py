"""RAG — accès au corpus ChromaDB pour le researcher.

Ingestion : python ingest_corpus.py   (lit corpus/*.md, découpe par sections)
Requête   : rag.query(texte) -> top-k snippets "[source] texte"

Embeddings :
- défaut : fonction intégrée ChromaDB (all-MiniLM-L6-v2, locale, gratuite)
- si EMBEDDING_DEPLOYMENT est défini dans .env : Azure OpenAI embeddings
  (même moteur à l'ingestion et à la requête — ne pas mélanger).

Fail-safe : query() ne lève jamais — toute erreur retourne [].
"""
from pathlib import Path
from typing import List, Optional

from config import settings

CORPUS_DIR = Path(__file__).parent / "corpus"
CHROMA_PATH = Path(__file__).parent / settings.CHROMA_DIR
COLLECTION_NAME = "intellimail_corpus"

_collection = None


class _AzureEmbeddingFunction:
    """Embedding via un deployment Azure OpenAI (réutilise le client llm.py)."""

    def __init__(self, deployment: str):
        self.deployment = deployment

    def __call__(self, input) -> List[List[float]]:  # protocole Chroma
        from llm import get_client
        resp = get_client().embeddings.create(model=self.deployment,
                                              input=list(input))
        return [d.embedding for d in resp.data]

    def name(self) -> str:  # requis par les versions récentes de Chroma
        return f"azure-openai-{self.deployment}"


def _embedding_kwargs() -> dict:
    if settings.EMBEDDING_DEPLOYMENT:
        return {"embedding_function":
                _AzureEmbeddingFunction(settings.EMBEDDING_DEPLOYMENT)}
    return {}  # défaut ChromaDB


def get_collection(create: bool = False):
    """Collection ChromaDB persistante (singleton). Lève si absente et create=False."""
    global _collection
    if _collection is not None:
        return _collection
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    if create:
        _collection = client.get_or_create_collection(
            COLLECTION_NAME, **_embedding_kwargs())
    else:
        _collection = client.get_collection(COLLECTION_NAME, **_embedding_kwargs())
    return _collection


# ─── Repli sans ChromaDB : recherche par mots-clés ──────────────────────
# ChromaDB et son modèle d'embedding local dépassent le gigaoctet de mémoire
# de Streamlit Community Cloud. Plutôt que de priver la démo publique de tout
# contexte documentaire, on retombe sur une recherche lexicale sur corpus/*.md :
# moins fine qu'une recherche vectorielle, mais suffisante pour montrer que le
# rédacteur s'appuie sur des procédures internes, et sans aucune dépendance.
_MOTS_VIDES = {
    "avec", "dans", "pour", "vous", "nous", "votre", "notre", "mais", "donc",
    "cette", "cette", "elle", "être", "avoir", "faire", "plus", "tout", "tous",
    "bien", "sans", "sous", "leur", "leurs", "quel", "quelle", "cela", "very",
    "bonjour", "cordialement", "madame", "monsieur", "merci", "email", "mail",
}
_chunks_cache: Optional[List[tuple]] = None


def _charger_chunks() -> List[tuple]:
    """(source, section, texte) pour chaque section '## ' du corpus."""
    global _chunks_cache
    if _chunks_cache is not None:
        return _chunks_cache
    import re
    out = []
    if CORPUS_DIR.is_dir():
        for f in sorted(CORPUS_DIR.glob("*.md")):
            parties = re.split(r"^## +", f.read_text(encoding="utf-8"), flags=re.M)
            for p in parties:
                p = p.strip()
                if len(p) > 40:
                    out.append((f.stem, p.splitlines()[0].lstrip("# ").strip(), p))
    _chunks_cache = out
    return out


def _mots(texte: str) -> set:
    import re
    return {m for m in re.findall(r"[a-zà-öø-ÿ]{5,}", (texte or "").lower())
            if m not in _MOTS_VIDES}


def query_mots_cles(text: str, top_k: int) -> List[str]:
    """Recherche lexicale : score = mots significatifs partagés, pondérés par
    leur rareté dans le corpus (approximation d'un IDF)."""
    chunks = _charger_chunks()
    if not chunks:
        return []
    mots_requete = _mots(text)
    if not mots_requete:
        return []
    # Fréquence documentaire de chaque mot, pour ne pas privilégier les
    # sections qui répètent des termes ubiquitaires ("client", "demande").
    freq: dict = {}
    mots_par_chunk = []
    for _, _, corps in chunks:
        m = _mots(corps)
        mots_par_chunk.append(m)
        for w in m:
            freq[w] = freq.get(w, 0) + 1
    n = len(chunks)
    scores = []
    for i, (src, section, corps) in enumerate(chunks):
        communs = mots_requete & mots_par_chunk[i]
        if not communs:
            continue
        score = sum(1.0 / (1 + freq.get(w, 1) / n) for w in communs)
        scores.append((score, src, section, corps))
    scores.sort(key=lambda t: -t[0])
    return [f"[{src}] {corps.strip()}" for _, src, section, corps in scores[:top_k]]


def query(text: str, top_k: Optional[int] = None) -> List[str]:
    """Top-k snippets pour le drafter. Jamais d'exception (fail-safe).

    ChromaDB si disponible et ingéré, sinon repli lexical sur le corpus.
    """
    if not text or not text.strip():
        return []
    k = top_k or settings.RAG_TOP_K
    try:
        col = get_collection()
        res = col.query(query_texts=[text], n_results=k)
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        out = []
        for d, m in zip(docs, metas):
            src = (m or {}).get("source", "corpus")
            out.append(f"[{src}] {d.strip()}")
        if out:
            return out
    except Exception:
        pass
    try:
        return query_mots_cles(text, k)
    except Exception:
        return []
