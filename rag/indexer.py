# rag/indexer.py
# Responsible for loading, chunking, embedding and storing documents.
#
# Supported formats: PDF (.pdf), plain text (.txt), Markdown (.md), Word (.docx)
# Each chunk is stored with metadata: filename, path, chunk_index.

import os
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag.chroma_client import get_vectorstore, get_chat_vectorstore

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)

KNOWLEDGE_BASE_DIR = os.path.join(_PROJECT_ROOT, "knowledge_base")

# ── Splitter (module-level to avoid re-instantiating on every call) ───────────
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=100,
    length_function=len,
)

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}


def _load_document(file_path: str) -> List[Document]:
    """Load a document from disk using the appropriate LangChain loader."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader
        loader = PyPDFLoader(file_path)

    elif ext in (".txt", ".md"):
        from langchain_community.document_loaders import TextLoader
        loader = TextLoader(file_path, encoding="utf-8")

    elif ext == ".docx":
        from langchain_community.document_loaders import Docx2txtLoader
        loader = Docx2txtLoader(file_path)

    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    return loader.load()


def index_file(file_path: str) -> int:
    """Load, chunk, embed and store a single file into ChromaDB.

    Args:
        file_path: Absolute or relative path to the document.

    Returns:
        Number of chunks indexed.

    Raises:
        ValueError: If the file type is not supported.
        Exception: If loading, embedding or storing fails.
    """
    file_path = os.path.abspath(file_path)
    filename = os.path.basename(file_path)

    # ── Load ──────────────────────────────────────────────────────────────────
    docs = _load_document(file_path)
    if not docs:
        raise ValueError(f"No content could be extracted from '{filename}'.")

    # ── Split ─────────────────────────────────────────────────────────────────
    chunks = _splitter.split_documents(docs)

    # ── Enrich metadata ───────────────────────────────────────────────────────
    for i, chunk in enumerate(chunks):
        chunk.metadata.update(
            {
                "filename": filename,
                "path": file_path,
                "chunk_index": i,
            }
        )

    # ── Embed and store ───────────────────────────────────────────────────────
    vectorstore = get_vectorstore()
    vectorstore.add_documents(chunks)

    print(f"  [Indexer] Indexed '{filename}' → {len(chunks)} chunks stored in ChromaDB.")
    return len(chunks)


def index_chat_file(file_path: str, chat_id: str) -> int:
    """Load, chunk, embed and store a single file into a chat-specific ChromaDB.

    Args:
        file_path: Absolute or relative path to the document.
        chat_id: ID of the current chat session.

    Returns:
        Number of chunks indexed.
    """
    file_path = os.path.abspath(file_path)
    filename = os.path.basename(file_path)

    # ── Load ──────────────────────────────────────────────────────────────────
    docs = _load_document(file_path)
    if not docs:
        raise ValueError(f"No content could be extracted from '{filename}'.")

    # ── Split ─────────────────────────────────────────────────────────────────
    chunks = _splitter.split_documents(docs)

    # ── Enrich metadata ───────────────────────────────────────────────────────
    for i, chunk in enumerate(chunks):
        chunk.metadata.update(
            {
                "filename": filename,
                "path": file_path,
                "chunk_index": i,
                "chat_id": chat_id,
            }
        )

    # ── Embed and store ───────────────────────────────────────────────────────
    vectorstore = get_chat_vectorstore(chat_id)
    vectorstore.add_documents(chunks)

    print(f"  [Indexer] Indexed '{filename}' for chat '{chat_id}' → {len(chunks)} chunks stored.")
    return len(chunks)


def index_knowledge_base() -> dict:
    """Index all supported files in the knowledge_base/ directory.

    Returns:
        Dict mapping filename → chunks indexed.
    """
    os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
    results = {}

    for fname in os.listdir(KNOWLEDGE_BASE_DIR):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        file_path = os.path.join(KNOWLEDGE_BASE_DIR, fname)
        try:
            n = index_file(file_path)
            results[fname] = n
        except Exception as e:
            print(f"  [Indexer] Error indexing '{fname}': {e}")
            results[fname] = 0

    return results
