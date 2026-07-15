# rag/retriever.py
# Retrieves semantically similar chunks from ChromaDB for a given query.

from typing import Any, Dict, List

from rag.chroma_client import get_vectorstore


def retrieve(query: str, k: int = 5) -> List[Dict[str, Any]]:
    """Return the top-k most relevant chunks for a query.

    Args:
        query: Natural language search query.
        k:     Number of chunks to retrieve (default 5).

    Returns:
        List of dicts, each containing:
            - text         : chunk content
            - filename     : source document filename
            - path         : absolute path to the source document
            - chunk_index  : position of this chunk within its source document
    """
    vectorstore = get_vectorstore()
    results = vectorstore.similarity_search(query, k=k)

    if not results:
        return []

    output: List[Dict[str, Any]] = []
    for doc in results:
        output.append(
            {
                "text": doc.page_content,
                "filename": doc.metadata.get("filename", "Unknown"),
                "path": doc.metadata.get("path", "Unknown"),
                "chunk_index": doc.metadata.get("chunk_index", -1),
            }
        )

    return output
