# rag/chroma_client.py
# Provides a factory function that returns a persistent ChromaDB vectorstore
# backed by Google Gemini embeddings.

import os

# Disable ChromaDB Telemetry to prevent PostHog warnings
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"

from langchain_chroma import Chroma
from rag.embeddings import get_embedding_model

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)

CHROMA_DB_DIR = os.path.join(_PROJECT_ROOT, "chroma_db")
COLLECTION_NAME = "rag_collection"

_vectorstore = None
_chat_vectorstores = {}

def get_vectorstore() -> Chroma:
    """Return a Chroma vectorstore connected to the shared rag_collection.
    Cached as a singleton to prevent multiple PostHog clients and SQLite reconnects.
    """
    global _vectorstore
    if _vectorstore is None:
        os.makedirs(CHROMA_DB_DIR, exist_ok=True)
        _vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=get_embedding_model(),
            persist_directory=CHROMA_DB_DIR,
        )
    return _vectorstore


def get_chat_vectorstore(chat_id: str) -> Chroma:
    """Return a Chroma vectorstore connected to a chat-specific collection.
    Cached per chat_id to prevent multiple PostHog clients.
    """
    if chat_id not in _chat_vectorstores:
        chat_chroma_dir = os.path.join(_PROJECT_ROOT, "chat_chroma", f"chat_{chat_id}")
        os.makedirs(chat_chroma_dir, exist_ok=True)
        _chat_vectorstores[chat_id] = Chroma(
            collection_name=f"chat_{chat_id}",
            embedding_function=get_embedding_model(),
            persist_directory=chat_chroma_dir,
        )
    return _chat_vectorstores[chat_id]
