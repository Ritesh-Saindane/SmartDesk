# rag/retriever.py
# Retrieves semantically similar chunks from ChromaDB for a given query.

from typing import Any, Dict, List

from rag.chroma_client import get_vectorstore, get_chat_vectorstore

SIMILARITY_THRESHOLD = 1.5  # Relaxed threshold to filter low-quality matches (L2 distance, lower is better)

def retrieve(chat_id: str, query: str, mode: str, k: int = 5) -> List[Dict[str, Any]]:
    """Router for retrieval strategy based on selected mode.
    
    Args:
        chat_id: ID of the current chat session.
        query: Search query or filename (if mode is overview).
        mode: Retrieval mode ('overview' or 'semantic').
        k: Number of chunks to retrieve.
    """
    if mode == "overview":
        print(f"  [Retriever] Strategy: Document Overview for '{query}'")
        return retrieve_document_start(chat_id, query, k=k)
    else:
        print("  [Retriever] Strategy: Semantic Similarity Search")
        return retrieve_specific(chat_id, query, k=k)


def retrieve_document_start(chat_id: str, query: str, k: int = 5) -> List[Dict[str, Any]]:
    """Return the first k chunks from the chat collection, ordered by chunk_index.
    
    If query is not empty, it filters for the specific filename.
    """
    vectorstore = get_chat_vectorstore(chat_id)
    
    # Retrieve all documents in the collection
    data = vectorstore.get()
    
    docs = data.get("documents", [])
    metadatas = data.get("metadatas", [])
    
    if not docs or not metadatas:
        return []
        
    # Zip docs and metadata
    combined = list(zip(docs, metadatas))
    
    # Filter by filename if query is provided
    if query and query.strip():
        query_lower = query.lower().strip()
        filtered = [
            (doc, meta) for doc, meta in combined 
            if query_lower in meta.get("filename", "").lower()
        ]
        if filtered:
            combined = filtered

    # Group all retrieved chunks by filename
    from collections import defaultdict
    grouped = defaultdict(list)
    for text, meta in combined:
        filename = meta.get("filename", "Unknown")
        grouped[filename].append((text, meta))

    # Within each document, sort chunks by chunk_index and take first N chunks
    chunks_per_doc = k
    top_chunks = []
    
    for filename, items in grouped.items():
        items.sort(key=lambda x: x[1].get("chunk_index", 0))
        top_chunks.extend(items[:chunks_per_doc])
    
    print("\nRetrieved Chunks (Document Start)")
    print("---------------")
    
    output: List[Dict[str, Any]] = []
    for i, (text, meta) in enumerate(top_chunks, 1):
        filename = meta.get("filename", "Unknown")
        chunk_index = meta.get("chunk_index", -1)
        
        print(f"{i}. {filename:<12} | chunk {chunk_index} ")
        
        output.append(
            {
                "text": text,
                "filename": filename,
                "path": meta.get("path", "Unknown"),
                "chunk_index": chunk_index,
                "score": 0.0,  # No semantic score for overview
            }
        )
        
    return output


def retrieve_specific(chat_id: str, query: str, k: int = 5) -> List[Dict[str, Any]]:
    """Return the top-k most relevant chunks for a query from a chat-specific vectorstore.

    Args:
        chat_id: ID of the current chat session.
        query: Natural language search query.
        k:     Number of chunks to retrieve (default 5).

    Returns:
        List of dicts, each containing:
            - text         : chunk content
            - filename     : source document filename
            - path         : absolute path to the source document
            - chunk_index  : position of this chunk within its source document
            - score        : similarity score
    """
    vectorstore = get_chat_vectorstore(chat_id)
    
    # Retrieve more results initially to allow for filtering
    results = vectorstore.similarity_search_with_score(query, k=k * 2)

    if not results:
        return []

    # print("results of similarity_search_with_score ======> ",results)

    # Filter out low-quality matches using a similarity score threshold.
    filtered_results = []
    for doc, score in results:
        if score <= SIMILARITY_THRESHOLD:
            filtered_results.append((doc, score))
            
    # Sort by score ascending (lower L2 distance is better)
    filtered_results.sort(key=lambda x: x[1])

    # After filtering and sorting, return at most the top k chunks.
    filtered_results = filtered_results[:k]

    if not filtered_results:
        return []

    # 6. Log the retrieved filename, chunk index and similarity score to the console.
    print("\nRetrieved Chunks (Semantic)")
    print("---------------")

    output: List[Dict[str, Any]] = []
    for i, (doc, score) in enumerate(filtered_results, 1):
        filename = doc.metadata.get("filename", "Unknown")
        chunk_index = doc.metadata.get("chunk_index", -1)
        
        print(f"{i}. {filename:<12} | score {score:.2f} | chunk {chunk_index} ")

        output.append(
            {
                "text": doc.page_content,
                "filename": filename,
                "path": doc.metadata.get("path", "Unknown"),
                "chunk_index": chunk_index,
                "score": score,  # 5. Include the similarity score
            }
        )

    return output
