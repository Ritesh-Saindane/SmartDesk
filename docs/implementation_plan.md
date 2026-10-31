# Custom ChromaDB Memory System Implementation Plan

This plan details the architectural refactoring of the SmartDesk Long-Term Memory system to completely replace Mem0 with a custom ChromaDB-backed solution.

## User Review Required
> [!IMPORTANT]  
> Please review this architecture split and file setup to ensure it aligns perfectly with your requirements before I execute the changes.

## Open Questions
- You mentioned `retrieve_memories` and `store_memories` should be exposed. `app.py` currently imports and calls `retrieve_long_term_memory` and `store_long_term_memory`. I will update `app.py` to use the renamed functions to ensure the app doesn't crash. Let me know if you prefer to keep the `_long_term_` suffix!
- For embedding, I will use Chroma's built-in `SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")` to match what was previously configured for Mem0. 

## Proposed Changes

### 1. Remove Mem0
- **Uninstall/Remove References**: I will remove `mem0ai` from `requirements.txt` (if present) and delete the current `memory/config.py`.

---

### 2. Custom ChromaDB Integration

#### [NEW] [chroma_client.py](file:///C:/agentic_ai_tutorials/campusx_langraph/15_resume_project/SmartDesk/memory/chroma_client.py)
- Establish a singleton Chroma PersistentClient pointing to `./vectorstores/memory/`.
- Initializes the `SentenceTransformerEmbeddingFunction` for `"all-MiniLM-L6-v2"`.

#### [NEW] [collection.py](file:///C:/agentic_ai_tutorials/campusx_langraph/15_resume_project/SmartDesk/memory/collection.py)
- Implements `get_memory_collection(user_id: str)` which returns the `memory_<user_id>` collection, applying the embedding function.

---

### 3. Core Memory Operations

#### [NEW] [retriever.py](file:///C:/agentic_ai_tutorials/campusx_langraph/15_resume_project/SmartDesk/memory/retriever.py)
- Implements `retrieve_similar_memories(user_id, query, top_k, similarity_threshold)`.
- Performs purely semantic vector search. Returns a structured list of memory dicts (id, text, metadata, distance).

#### [MODIFY] [extractor.py](file:///C:/agentic_ai_tutorials/campusx_langraph/15_resume_project/SmartDesk/memory/extractor.py)
- Becomes the **Memory Manager LLM**.
- Redesigned Pydantic output (`MemoryOperationList` -> `MemoryOperation`).
- The prompt will receive the conversation AND retrieved similar memories, and is instructed to return explicit operations (`INSERT`, `UPDATE`, `DELETE`, `IGNORE`).

#### [NEW] [store.py](file:///C:/agentic_ai_tutorials/campusx_langraph/15_resume_project/SmartDesk/memory/store.py)
- Implements `apply_memory_operations(user_id, operations)`.
- Directly maps the LLM's `INSERT`, `UPDATE`, and `DELETE` actions to ChromaDB operations.
- Adds appropriate metadata (category, importance, created_at, updated_at).

---

### 4. Public Service API

#### [MODIFY] [service.py](file:///C:/agentic_ai_tutorials/campusx_langraph/15_resume_project/SmartDesk/memory/service.py)
- Strips out Mem0 entirely.
- Integrates the workflow for `store_memories`:
  `Retrieve Similar Memories` -> `Extractor LLM` -> `Apply Operations`.
- Exposes only `retrieve_memories` and `store_memories`.

#### [MODIFY] [__init__.py](file:///C:/agentic_ai_tutorials/campusx_langraph/15_resume_project/SmartDesk/memory/__init__.py)
- Cleans up exports to strictly expose `retrieve_memories` and `store_memories`.

---

### 5. Application Hooks

#### [MODIFY] [app.py](file:///C:/agentic_ai_tutorials/campusx_langraph/15_resume_project/SmartDesk/app.py)
- Update function imports and calls to match the new `retrieve_memories` and `store_memories` naming convention.

## Verification Plan

### Automated/Code Checks
- Syntax checking via `python -m py_compile`.
- Verifying the Pydantic schemas correctly pass through Groq's structured output.

### Manual Verification
- Testing the frontend by submitting a message with memory implications (e.g. "I love React") and ensuring the terminal logs the `INSERT` operation.
- Follow up by saying "Actually, I don't use React anymore" to verify the LLM emits a `DELETE` or `UPDATE` operation, and that Chroma successfully applies it.
