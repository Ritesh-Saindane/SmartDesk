# api.py
# FastAPI server exposing the RAG upload endpoint.
#
# Run with:   uvicorn api:app --reload --port 8000
#
# Endpoints:
#   GET  /health           — health check
#   POST /knowledge/upload — save a file to knowledge_base/ and index it

import os
import shutil

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

load_dotenv()

from rag.indexer import KNOWLEDGE_BASE_DIR, SUPPORTED_EXTENSIONS, index_file

# Ensure the knowledge_base directory exists when the server starts
os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)

app = FastAPI(
    title="SmartDesk RAG API",
    description="Upload documents to the SmartDesk knowledge base for RAG retrieval.",
    version="1.0.0",
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", summary="Health check")
def health():
    return {"status": "ok", "knowledge_base_dir": KNOWLEDGE_BASE_DIR}


# ── Upload & Index ────────────────────────────────────────────────────────────

@app.post("/knowledge/upload", summary="Upload and index a document")
async def upload_document(file: UploadFile = File(...)):
    """
    Accept a document, save it to `knowledge_base/`, immediately index it
    into ChromaDB, and return the result.

    Supported formats: PDF, TXT, MD, DOCX
    """
    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            ),
        )

    save_path = os.path.join(KNOWLEDGE_BASE_DIR, file.filename)

    # ── Save to disk ──────────────────────────────────────────────────────────
    try:
        with open(save_path, "wb") as out_file:
            shutil.copyfileobj(file.file, out_file)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to save file: {str(e)}"
        )

    # ── Index into ChromaDB ───────────────────────────────────────────────────
    try:
        num_chunks = index_file(save_path)
    except Exception as e:
        # Clean up the saved file if indexing fails so state stays consistent
        if os.path.exists(save_path):
            os.remove(save_path)
        raise HTTPException(
            status_code=500, detail=f"Failed to index file: {str(e)}"
        )

    return JSONResponse(
        {
            "status": "success",
            "filename": file.filename,
            "chunks_indexed": num_chunks,
            "message": (
                f"'{file.filename}' saved to knowledge_base/ and indexed "
                f"successfully with {num_chunks} chunks."
            ),
        }
    )


# ── List indexed documents ────────────────────────────────────────────────────

@app.get("/knowledge/list", summary="List documents in the knowledge base")
def list_documents():
    """Return a list of all files currently inside knowledge_base/."""
    files = [
        f
        for f in os.listdir(KNOWLEDGE_BASE_DIR)
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
    ]
    return {"documents": files, "count": len(files)}
