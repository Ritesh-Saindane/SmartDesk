# rag/embeddings.py
# Provides the shared HuggingFace embedding model instance.

from langchain_huggingface import HuggingFaceEmbeddings

_embedding_model: HuggingFaceEmbeddings | None = None

def get_embedding_model() -> HuggingFaceEmbeddings:
    """Return the singleton HuggingFace embedding model.

    Lazily instantiated so that it only loads the model into memory
    when actually needed.
    """
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2",
            encode_kwargs={
        "normalize_embeddings": True
    }
        )
    return _embedding_model
