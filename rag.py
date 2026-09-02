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


def query(text: str, top_k: Optional[int] = None) -> List[str]:
    """Top-k snippets pour le drafter. Jamais d'exception (fail-safe)."""
    if not text or not text.strip():
        return []
    try:
        col = get_collection()
        res = col.query(query_texts=[text],
                        n_results=top_k or settings.RAG_TOP_K)
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        out = []
        for d, m in zip(docs, metas):
            src = (m or {}).get("source", "corpus")
            out.append(f"[{src}] {d.strip()}")
        return out
    except Exception:
        return []
