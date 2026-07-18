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

from app.application import upload_document

@app.post("/knowledge/upload", summary="Upload and index a document")
async def upload_document_api(file: UploadFile = File(...)):
    """
    Accept a document, immediately index it into ChromaDB, and return the result.
    Supported formats: PDF, TXT, MD, DOCX
    """
    try:
        num_chunks = upload_document(file.file, file.filename)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")

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
