# rag/embeddings.py
# Provides the shared HuggingFace embedding model instance.

from langchain_huggingface import HuggingFaceEndpointEmbeddings
import os

_embedding_model: HuggingFaceEndpointEmbeddings | None = None

def get_embedding_model() -> HuggingFaceEndpointEmbeddings:
    """Return the singleton HuggingFace API embedding model."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = HuggingFaceEndpointEmbeddings(
            model="sentence-transformers/all-MiniLM-L6-v2",
            task="feature-extraction",
            huggingfacehub_api_token=os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
        )
    return _embedding_model
