# Session Summary — RAW_CONTEXT Scalability Changes

## Goal
Make the multi-agent system handle **large local files gracefully** without blowing up the LLM context window (413 / token-limit errors).

---

## Changes That Are Live & Working

### 1. `state.py` — ArtifactType Enum
Replaced raw strings with an enum:
- RAW_CONTEXT, SUMMARY, ANSWER, ACTION_ITEMS, SEARCH_RESULTS, STATUS

---

### 2. `workspace_agent.py` — Token guard inside read_file tool (CORE FIX)
Instead of returning full file content, read_file checks token count first.
Large files return a short structured error (~30 tokens):
  FILE_TOO_LARGE::<abs_path>::<token_count>\n<human message>
This prevents large text from ever entering workspace_messages. No 413 possible.

---

### 3. `workspace_agent.py` — System prompt update
LLM is instructed: if tool returns FILE_TOO_LARGE::, stop immediately.

---

### 4. `workspace_agent.py` — workspace_finalizer — FILE_TOO_LARGE detection
Scans workspace_messages for FILE_TOO_LARGE:: ToolMessage, parses path + token count,
creates RAW_CONTEXT artifact with payload_inlined=False and path in metadata.

---

### 5. `workspace_agent.py` — workspace_route — cleaned up
Removed old token-count check. Simple 3-line router now.

---

### 6. `main.py` — Orchestrator prompt — Rules 11 and 12

Rule 11 — Large Document Handling:
  - payload_inlined=False + user wants to summarize/query ? finished=True immediately
    "File too large, please upload via chat upload button"
  - Do NOT route to KnowledgeAgent (local files not in chat KB)
  - Intent doesn't need content (e.g. upload to Drive) ? use metadata["path"]

Rule 12 — Anti-loop:
  12a: Never re-read a file that already has a RAW_CONTEXT artifact
  12b: 2+ tasks done without resolution ? finished=True with best response

---

## Things Tried but Reverted

- workspace_route token check: fires AFTER ToolMessage already in messages; 413 still possible
- workspace_agent bypass block: superseded by FILE_TOO_LARGE:: prefix approach
- workspace_messages: [] reset in finalizer returns: add_messages reducer ignores [] ? no-op
- Rule 4a (one file per task): tasks were already separate; real issue was STATUS type + Orchestrator

---

## Current Known Limitation
When one task reads one small + one large file together:
- Finalizer creates only ONE artifact (for the FILE_TOO_LARGE file)
- Small file content is in the LLM AIMessage but not captured as its own artifact
- Orchestrator final response may or may not mention both files
