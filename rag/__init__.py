# rag/__init__.py
# RAG package for SmartDesk — exposes the public interface.
from rag.indexer import index_file
from rag.retriever import retrieve

__all__ = ["index_file", "retrieve"]
