# rag/chroma_client.py
# Provides a factory function that returns a persistent ChromaDB vectorstore
# backed by Google Gemini embeddings.

import os
from langchain_chroma import Chroma

from rag.embeddings import get_embedding_model

# ── Paths ─────────────────────────────────────────────────────────────────────
# Resolve paths relative to this file so they work regardless of the
# working directory the caller uses.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)

CHROMA_DB_DIR = os.path.join(_PROJECT_ROOT, "chroma_db")
COLLECTION_NAME = "rag_collection"


def get_vectorstore() -> Chroma:
    """Return a Chroma vectorstore connected to the shared rag_collection.

    A new client object is created per call (Chroma handles the underlying
    persistence), so this is safe to call from multiple modules.
    """
    os.makedirs(CHROMA_DB_DIR, exist_ok=True)

    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embedding_model(),
        persist_directory=CHROMA_DB_DIR,
    )
