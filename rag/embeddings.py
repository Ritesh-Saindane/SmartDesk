# rag/embeddings.py
# Provides the shared HuggingFace embedding model instance.
# Runs all-MiniLM-L6-v2 locally via sentence-transformers (the HF Inference API
# endpoint needs paid credits). Same model, same 384-dim vectors.

from langchain_huggingface import HuggingFaceEmbeddings

_embedding_model: HuggingFaceEmbeddings | None = None

def get_embedding_model() -> HuggingFaceEmbeddings:
    """Return the singleton local HuggingFace embedding model."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embedding_model
