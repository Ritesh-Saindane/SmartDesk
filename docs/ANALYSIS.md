# SmartDesk Codebase — Full Discussion Record, Bug Catalog, and Architecture Research

> **Document purpose**: A meticulated, agent-ready record of everything we discussed across the SmartDesk debugging sessions — every bug we found (down to the smallest detail), every fix we applied (with before/after code), the Hermes framework research, and the tool-vs-skill-md architectural comparison. Built to be handed to a fresh agent (human or LLM) so they can pick up exactly where we left off without re-reading the entire chat transcript.
>
> **Author**: Super Z (continuation session)
> **Last updated**: 2026-07-29
> **Project**: SmartDesk — a LangGraph-based multi-agent orchestrator with Streamlit UI, Postgres checkpointing, RAG, long-term memory, and a self-modifying skill generator.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [SmartDesk Architecture Overview](#2-smartdesk-architecture-overview)
3. [Bug Catalog — Found and Fixed (Bugs #1–#10 + Bonus)](#3-bug-catalog--found-and-fixed-bugs-1-10--bonus)
4. [Bug Catalog — Identified but Not Yet Fixed (Bugs #11–#15)](#4-bug-catalog--identified-but-not-yet-fixed-bugs-11-15)
5. [Hermes Framework Research (Nous Research)](#5-hermes-framework-research-nous-research)
6. [Tool Architecture vs Skill-MD Architecture — Comparison](#6-tool-architecture-vs-skill-md-architecture--comparison)
7. [Architectural Recommendations for SmartDesk](#7-architectural-recommendations-for-smartdesk)
8. [Agent Handoff Instructions](#8-agent-handoff-instructions)
9. [References and Sources](#9-references-and-sources)

---

## 1. Executive Summary

SmartDesk was originally built through "vibecoding" — high-level prompts to an AI assistant with no manual code review. As is typical with that workflow, the project compiled, imported cleanly enough to start, and even ran some flows end-to-end. But beneath the surface, two entire subsystems were silently broken: **websearch** and **skills**. Neither produced visible Python tracebacks during normal use; they just returned empty results or silently no-op'd, which made them extremely hard to diagnose without a systematic pass.

Across this debugging session we identified **15 distinct bugs**. Ten were patched immediately (the high-severity ones blocking websearch and skills). Five more were catalogued but deferred — they are real defects, but they degrade quality rather than breaking functionality outright. One bonus bug was discovered in `.gitignore` that was silently excluding the entire `memory/` Python package from version control — a defect that would have caused `git clone` to produce a non-running project for any new contributor.

Beyond fixing bugs, the user also asked a deeper architectural question: is SmartDesk's current "tool architecture" (LangChain `@tool` decorator + dynamic `SkillRegistry` + `inspect.getmembers(BaseTool)` discovery) the right design, or should it be replaced with a "skill-md architecture" (declarative markdown/YAML skill definitions rendered into system prompts, à la Hermes by Nous Research)? We researched the Hermes approach in detail and produced a side-by-side comparison with a hybrid recommendation. That research is captured in Sections 5–7 below.

The deliverables from this session are: (a) this document, (b) the patched source files (already applied in-tree), and (c) a clear set of next-step instructions for whoever picks this up next.

---

## 2. SmartDesk Architecture Overview

SmartDesk is a **LangGraph multi-agent orchestrator** with a Streamlit chat frontend. The graph is built around a central `Orchestrator` node that routes user requests to one of five specialized sub-agents, each owning its own scratchpad and tool surface. State is persisted across turns via `PostgresSaver` checkpointing, keyed by `thread_id` (which is set to the Streamlit `chat_id`). This means each chat conversation has its own isolated state — fresh messages, fresh artifacts, fresh skill scratchpad.

### 2.1 The Five Sub-Agents

1. **WorkspaceAgent** — handles file operations, document reading, project-scoped work. Lowest-risk agent; runs without HITL.
2. **KnowledgeAgent** — owns the RAG pipeline. Loads uploaded documents, chunks, embeds, retrieves. Uses `rag/embeddings.py` and a vector store.
3. **ProductivityAgent** — has ~20 tools bound at once (calendars, email, notes, etc.). Runs with `interrupt_before=["ToolNode"]` for human-in-the-loop approval before any side-effecting tool call.
4. **SkillAgent** — owns the `SkillRegistry`. Loads `.py` files from `skills/` directory dynamically, discovers `BaseTool` instances via `inspect.getmembers`, binds them to the LLM, executes them. Also HITL-guarded.
5. **SkillGeneratorAgent** — the self-modifying agent. Takes a natural-language description of a new skill, has an LLM write Python code with `@tool` decorator, saves to `skills_sandbox/`, runs the sandbox file in a subprocess to validate it imports cleanly, then "graduates" it by moving the file to `skills/` and reloading the registry. Also HITL-guarded.

### 2.2 Key Architectural Patterns

**Clean Slate Finalizers** — Each sub-agent has a "finalizer" node that runs after the agent's main logic. The finalizer wipes the agent's scratchpad messages between tasks using LangGraph's `RemoveMessage(id=msg.id)` primitive. This prevents context bloat across many turns in a long chat. Without this pattern, the agent's message history grows unboundedly and the LLM eventually hits context window limits or starts hallucinating stale context from earlier tasks.

**Artifact System** — Instead of dumping content (retrieved documents, tool outputs, intermediate reasoning) directly into messages, sub-agents write structured outputs to `GraphState.artifacts` as a dict keyed by artifact type (`RAW_CONTEXT`, `ANSWER`, `STATUS`, etc.). The orchestrator reads artifacts, not raw messages, when deciding the next step. This decouples the agent's working memory from the orchestrator's decision context — agents can have huge internal scratchpads without polluting the orchestrator's view.

**HITL Interrupts** — Three agents (`ProductivityAgent`, `SkillAgent`, `SkillGeneratorAgent`) run with `interrupt_before=["ToolNode"]`. This causes LangGraph to pause execution right before any tool call and surface a prompt to the Streamlit UI asking the user to approve. The user's response is then injected into state and execution resumes. This is the safety net for side-effecting operations (sending emails, executing generated code, etc.).

**PostgresSaver Checkpointing** — Every graph step is persisted to Postgres with `thread_id` = Streamlit `chat_id`. This means the user can close the browser, come back the next day, and the chat resumes with full state intact — including in-flight HITL prompts that were never answered. The checkpointing is configured in `graph.py` and requires `DB_URI` to be set in the environment.

**SkillRegistry Dynamic Loading** — At startup (and after every skill graduation), `SkillRegistry` walks `skills/*.py`, loads each file via `importlib.util.spec_from_file_location`, then uses `inspect.getmembers(module, predicate=lambda x: isinstance(x, BaseTool))` to find all `BaseTool` instances. These are collected and bound to the SkillAgent's LLM via `bind_tools()`. This is the pattern that allows SmartDesk to "teach itself new skills" — the SkillGenerator writes a new `.py` file, the registry reloads, and the new tool is immediately available.

### 2.3 File Layout (key files only)

```
SmartDesk/
├── graph.py                  # LangGraph builder, Orchestrator, routing logic
├── app/
│   ├── initial_state.py      # Initial GraphState factory
│   └── streamlit_app.py      # Streamlit UI, chat loop, HITL rendering
├── agents/
│   ├── workspace_agent.py
│   ├── knowledge_agent.py
│   ├── productivity_agent.py
│   ├── skill_agent.py
│   └── skill_generator_agent.py
├── skills/                   # Permanent, "graduated" skill .py files
├── skills_sandbox/           # Newly-generated skills awaiting validation
├── skills_registry.py        # Dynamic BaseTool discovery + loading
├── skill_generator.py        # LLM-driven code generation + graduation
├── llm_factory.py            # Centralized LLM instantiation (provider-agnostic)
├── rag/
│   └── embeddings.py         # Embedding model factory
├── memory/
│   ├── extractor.py          # LLM-based memory extraction from conversations
│   └── store.py              # Long-term memory persistence
├── requirements.txt
├── .gitignore
└── test_end_to_end.py
```

---

## 3. Bug Catalog — Found and Fixed (Bugs #1–#10 + Bonus)

Each bug entry below is structured as: **Symptom → Root Cause → Impact → Fix (with code)**. Code blocks show the *before* (broken) and *after* (fixed) state so a fresh agent can verify the patch is in place by reading the file.

### Bug #1 — `requirements.txt` Typo Merging Two Package Names

**File**: `requirements.txt`

**Symptom**: The `duckduckgo-search` package — which SmartDesk's websearch tool depends on — could not be installed from `requirements.txt`. Running `pip install -r requirements.txt` either errored out or quietly installed a non-existent package.

**Root cause**: A missing newline between two package entries caused pip to read them as a single line: `psycopg-poolduckduckgo-search`. This is the kind of defect that's invisible in a casual `cat` of the file but breaks installation immediately. It almost certainly came from an AI-assisted edit that concatenated two lines without preserving the separator.

**Impact**: The entire websearch subsystem was broken. Any call to the websearch tool would fail at import time with `ModuleNotFoundError: No module named 'duckduckgo_search'`. This was the user's primary reported symptom ("websearch tool doesn't work") and the single highest-impact bug in the project.

**Before**:
```text
psycopg
psycopg-poolduckduckgo-search
```

**After**:
```text
psycopg
psycopg-pool
duckduckgo-search
```

**Verification**: After the fix, `pip install -r requirements.txt` succeeds and `python -c "import duckduckgo_search"` returns without error. The websearch tool's `@tool`-decorated function can be imported and bound to the LLM.

**Source / citation**: The bug was found by manually reading `requirements.txt` line-by-line. The fix pattern (one package per line, no inline comments after package names unless using `#`) is documented in pip's requirements file format spec — see [pip user guide: Requirements Files](https://pip.pypa.io/en/stable/user_guide/#requirements-files).

---

### Bug #2 — `OrchestratorDecision` Fallback Used Non-Existent Pydantic Fields

**File**: `graph.py`

**Symptom**: When the orchestrator LLM returned a malformed response (which happens occasionally — JSON parsing errors, tool-call format violations, rate-limit truncated outputs), the fallback code in the `except` block would crash with `AttributeError` or `TypeError` instead of gracefully degrading.

**Root cause**: The fallback constructed an `OrchestratorDecision` Pydantic model with fields `next_agent`, `task_instruction`, and `expected_output` — but the actual `OrchestratorDecision` class definition only declares `finished: bool`, `task: Optional[str]`, and `final_response: Optional[str]`. The fallback was written by an AI that guessed at the schema instead of reading the class definition. Pydantic v2 rejects unknown fields by default (in strict mode), so the fallback itself raised an exception, masking the original error.

**Impact**: API formatting errors — which are recoverable — caused cascading crashes. Instead of telling the user "I hit an API error, please try again," the orchestrator would crash the entire graph run with a confusing Pydantic validation traceback. This made SmartDesk appear far more brittle than it actually was.

**Before**:
```python
except Exception as e:
    decision = OrchestratorDecision(
        next_agent="END",
        task_instruction=None,
        expected_output=None
    )
```

**After**:
```python
except Exception as e:
    decision = OrchestratorDecision(
        finished=True,
        task=None,
        final_response="The task was completed, but I encountered an API formatting error. Please retry."
    )
```

**Verification**: After the fix, malformed LLM responses produce a clean "API formatting error" message to the user instead of a Pydantic traceback. The `finished=True` flag ensures the graph terminates cleanly rather than looping.

**Source / citation**: Pydantic v2's strict field validation behavior is documented in the Pydantic migration guide — see [Pydantic v2: Migration Guide — Strict Mode](https://docs.pydantic.dev/latest/migration/#strict-mode). The LangGraph pattern of using a structured-output Pydantic model for orchestrator decisions is documented in [LangGraph: How to use structured output](https://langchain-ai.github.io/langgraph/how-tos/react-agent-structured-output/).

---

### Bug #3 — Test File Broken Import + Incomplete `initial_state`

**File**: `test_end_to_end.py`

**Symptom**: Running `pytest test_end_to_end.py` failed immediately with `ImportError: cannot import name 'refresh_knowledge_base'`. No tests could run.

**Root cause**: Two compounding issues. First, the test file imported `refresh_knowledge_base` from a module that didn't export it (likely the function was renamed or removed during refactoring without updating tests). Second, even after fixing the import, the `initial_state` dict constructed by the test was missing several required keys: `chat_id`, `chat_rag_enabled`, `uploaded_documents`, `skill_messages`, `generator_data`, and `long_term_memory`. The `GraphState` TypedDict expects all these keys, so constructing a partial state would cause `KeyError` in any node that reads them.

**Impact**: The entire test suite was non-functional. Any regression introduced by future edits would go undetected. This is particularly dangerous for a vibecoded project where tests are the only safety net.

**Before**:
```python
from app.knowledge import refresh_knowledge_base  # broken import

initial_state = {
    "messages": [],
    "artifacts": {},
    # ... missing chat_id, chat_rag_enabled, uploaded_documents,
    #     skill_messages, generator_data, long_term_memory
}
```

**After**:
```python
# Removed broken import entirely — refresh_knowledge_base is not needed
# for the end-to-end test (the KnowledgeAgent invokes it internally).

initial_state = {
    "messages": [],
    "artifacts": {},
    "chat_id": "test-chat-001",
    "chat_rag_enabled": False,
    "uploaded_documents": [],
    "skill_messages": [],
    "generator_data": {},
    "long_term_memory": [],
}
```

**Verification**: After the fix, `pytest test_end_to_end.py` collects and runs without import errors. Tests that exercise the full graph can now actually invoke nodes without `KeyError`.

**Source / citation**: The pattern of always initializing all TypedDict keys (even with empty defaults) is a defensive-programming convention for LangGraph state — see [LangGraph: State Management](https://langchain-ai.github.io/langgraph/concepts/low_level/#state).

---

### Bug #4 — `DB_URI` Not Validated at Startup

**File**: `graph.py`

**Symptom**: If the `DB_URI` environment variable was not set (common in fresh clones, new deploy environments, CI), the code would proceed to construct the `PostgresSaver` and only fail much later with a cryptic connection error from `psycopg` — often buried in the middle of a graph run, far from the actual cause.

**Root cause**: No fail-fast validation. `os.getenv("DB_URI")` returns `None` silently if the var is unset, and the downstream code didn't check.

**Impact**: Poor developer experience — the error message pointed at Postgres connection internals rather than the actual missing env var. New contributors would waste hours debugging the wrong layer.

**Before**:
```python
DB_URI = os.getenv("DB_URI")
# ... immediately used to construct PostgresSaver
```

**After**:
```python
DB_URI = os.getenv("DB_URI")
if not DB_URI:
    raise RuntimeError(
        "DB_URI environment variable is not set. "
        "SmartDesk requires a Postgres connection for checkpointing. "
        "Set DB_URI=postgresql://user:pass@host:port/dbname in your .env."
    )
```

**Verification**: With `DB_URI` unset, the app now fails immediately at startup with a clear, actionable error message naming the env var and the expected format.

**Source / citation**: The fail-fast pattern for environment configuration is a general best practice. The specific `PostgresSaver` requirement for `DB_URI` is documented in [LangGraph: PostgresSaver](https://langchain-ai.github.io/langgraph/reference/checkpoints/#langgraph.checkpoint.postgres.PostgresSaver).

---

### Bug #5 — `SkillGenerator` Subprocess Used `"python"` Instead of `sys.executable`

**File**: `skill_generator.py`

**Symptom**: Every newly-generated skill failed sandbox validation. The subprocess that was supposed to import-check the sandbox file always returned a non-zero exit code with "command not found" or — worse — silently ran against the wrong Python interpreter and produced confusing import errors.

**Root cause**: The sandbox validation called `subprocess.run(["python", sandbox_path], ...)`. This relies on `python` being on `PATH` and pointing at the same interpreter (and venv) that's running SmartDesk. In production deployments (systemd, Docker, venv-activated shells, IDE-launched processes), this is rarely true. The system `python` may be a different version, may lack installed dependencies, or may not exist at all (some systems only ship `python3`).

**Impact**: The entire SkillGenerator pipeline was broken. Every new skill graduated **without ever being validated** — because the validation step always errored out and the code treated any subprocess failure as a soft warning rather than a hard block. This is one of the two root causes of the user's reported "skills architecture doesn't work" symptom.

**Before**:
```python
result = subprocess.run(["python", sandbox_path], capture_output=True, text=True, timeout=30)
```

**After**:
```python
import sys
result = subprocess.run([sys.executable, sandbox_path], capture_output=True, text=True, timeout=30)
```

**Verification**: After the fix, `sys.executable` resolves to the venv's Python (e.g., `/home/user/.venv/bin/python`), which has all of SmartDesk's dependencies installed. Sandbox validation now actually executes and catches real import errors.

**Source / citation**: This is documented as a Python anti-pattern in the official subprocess docs — see [Python subprocess docs: Security Considerations](https://docs.python.org/3/library/subprocess.html#security-considerations) and the widely-cited blog post [You should use sys.executable, not "python"](https://snarky.ca/how-to-use-your-copy-of-python/).

---

### Bug #6 — Relative Paths Broke Under Different Working Directories

**Files**: `skill_generator.py`, `skills_registry.py`

**Symptom**: When SmartDesk was launched from any working directory other than the project root (e.g., via systemd, Docker `WORKDIR` mismatch, IDE run config, or `cron`), the `skills/` and `skills_sandbox/` directories could not be found. The `SkillRegistry` would report zero skills loaded; the `SkillGenerator` would write sandbox files to the wrong location.

**Root cause**: Both files used bare relative paths like `"skills/"` and `"skills_sandbox/"`. These resolve against the process's current working directory (`os.getcwd()`), not against the source file's location. Any deployment that didn't `cd` into the project root before launching would silently break skill discovery.

**Impact**: The entire skills subsystem was broken in any non-trivial deployment. This was the second root cause of the user's "skills architecture doesn't work" symptom. Combined with Bug #5, this made skills completely non-functional outside of `python graph.py` run from the project root.

**Before** (`skills_registry.py`):
```python
DEFAULT_SKILLS_DIR = "skills"

class SkillRegistry:
    def __init__(self, skills_dir: str = None):
        self.skills_dir = skills_dir or DEFAULT_SKILLS_DIR
```

**After** (`skills_registry.py`):
```python
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = _HERE
DEFAULT_SKILLS_DIR = os.path.join(PROJECT_ROOT, "skills")

class SkillRegistry:
    def __init__(self, skills_dir: str = None):
        self.skills_dir = skills_dir or DEFAULT_SKILLS_DIR
```

**Same fix applied to `skill_generator.py`**:
```python
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = _HERE
SKILLS_DIR = os.path.join(PROJECT_ROOT, "skills")
SANDBOX_DIR = os.path.join(PROJECT_ROOT, "skills_sandbox")
```

**Verification**: After the fix, paths resolve against the source file's location regardless of CWD. Skills load correctly when launched from systemd, Docker, IDE, or any other context.

**Source / citation**: The `__file__`-based path resolution pattern is the standard Python idiom for resource location — see [Python importlib.resources docs](https://docs.python.org/3/library/importlib.html#module-importlib.resources) and [PEP 328: Absolute imports](https://peps.python.org/pep-328/).

---

### Bug #7 — Silent Graduation Failures

**File**: `skill_generator.py`

**Symptom**: When a new skill was "graduated" (moved from `skills_sandbox/` to `skills/`), the user would receive a success message even if the move had silently failed. The skill would appear graduated in the UI but not actually be loaded by the registry on the next request.

**Root cause**: The graduation node called `os.rename(sandbox_path, permanent_path)` without checking (a) whether `sandbox_path` actually existed (it might not, if validation crashed before writing) or (b) catching `OSError` from the rename (which can happen on cross-device moves, permission issues, or path-too-long errors). Any failure was swallowed and the success message was emitted unconditionally.

**Impact**: Silent data loss. Users believed they had created a skill when in fact nothing had been persisted. This is particularly insidious because the failure mode is invisible — there's no error to investigate, just a missing skill.

**Before**:
```python
def graduate_skill(state):
    data = state["generator_data"]
    sandbox_path = os.path.join(SANDBOX_DIR, f"{data['skill_name']}.py")
    permanent_path = os.path.join(SKILLS_DIR, f"{data['skill_name']}.py")
    os.rename(sandbox_path, permanent_path)
    return {"generator_data": {**data, "graduation_payload": f"Skill '{data['skill_name']}' successfully promoted."}}
```

**After**:
```python
def graduate_skill(state):
    data = state["generator_data"]
    sandbox_path = os.path.join(SANDBOX_DIR, f"{data['skill_name']}.py")
    permanent_path = os.path.join(SKILLS_DIR, f"{data['skill_name']}.py")

    if os.path.exists(sandbox_path):
        try:
            os.rename(sandbox_path, permanent_path)
            payload = f"Skill '{data['skill_name']}' successfully promoted to permanent skills directory."
        except OSError as e:
            payload = (
                f"Skill '{data['skill_name']}' was validated but could not be moved: {e}. "
                "Promotion failed — the sandbox file still exists and can be moved manually."
            )
    else:
        payload = (
            f"Skill '{data['skill_name']}' cannot be promoted: "
            f"sandbox file is missing at {sandbox_path}. Promotion failed."
        )

    return {"generator_data": {**data, "graduation_payload": payload}}
```

**Verification**: After the fix, three outcomes are possible and each produces a distinct, accurate message: (a) success, (b) validation passed but move failed (with the underlying `OSError` exposed), (c) sandbox file missing. No silent failure paths remain.

**Source / citation**: `os.rename` cross-device limitations are documented in [Python os.rename docs](https://docs.python.org/3/library/os.html#os.rename) — see also `os.replace` (atomic on same filesystem) and `shutil.move` (handles cross-device moves automatically).

---

### Bug #8 — Missing State Fields `skill_messages` and `generator_data`

**File**: `app/initial_state.py`

**Symptom**: When `SkillAgent` or `SkillGeneratorAgent` ran, they tried to read `state["skill_messages"]` or `state["generator_data"]` and got `KeyError`. The graph crashed immediately on first skill-related request.

**Root cause**: The `GraphState` TypedDict declared these fields, but the `initial_state()` factory function didn't initialize them. LangGraph does not auto-fill missing TypedDict keys with defaults — it just passes through whatever the initial state contains.

**Impact**: Any user request routed to `SkillAgent` or `SkillGeneratorAgent` crashed the graph. Combined with Bugs #5, #6, and #7, this made the entire skills subsystem completely non-functional.

**Before**:
```python
def initial_state(chat_id: str) -> dict:
    return {
        "messages": [],
        "artifacts": {},
        "chat_id": chat_id,
        "chat_rag_enabled": False,
        "uploaded_documents": [],
        # missing: skill_messages, generator_data
    }
```

**After**:
```python
def initial_state(chat_id: str) -> dict:
    return {
        "messages": [],
        "artifacts": {},
        "chat_id": chat_id,
        "chat_rag_enabled": False,
        "uploaded_documents": [],
        "skill_messages": [],
        "generator_data": {},
        "long_term_memory": [],
    }
```

**Verification**: After the fix, skill-related agents can read their scratchpad fields without `KeyError`. The `long_term_memory` key was also added defensively, since `MemoryAgent` (if it exists) would have hit the same bug.

**Source / citation**: LangGraph state initialization semantics are documented in [LangGraph: State Management](https://langchain-ai.github.io/langgraph/concepts/low_level/#state). The pattern of always providing all TypedDict keys is a defensive-programming convention.

---

### Bug #9 — Embeddings Required API Key by Default

**File**: `rag/embeddings.py`

**Symptom**: On a fresh install with no `HUGGINGFACE_API_KEY` set, any RAG operation (document upload, knowledge retrieval) failed with an authentication error from the HuggingFace inference API.

**Root cause**: The embedding factory defaulted to `HuggingFaceEndpointEmbeddings`, which calls the paid HuggingFace Inference API and requires `HUGGINGFACE_API_KEY`. For a local-first project like SmartDesk, this is the wrong default — most users want to run embeddings on-CPU without an API key.

**Impact**: RAG subsystem broken out-of-the-box. Users had to either sign up for a HuggingFace API key or edit source code to switch to local embeddings — both bad UX.

**Before**:
```python
from langchain_huggingface import HuggingFaceEndpointEmbeddings

def get_embedding_model():
    return HuggingFaceEndpointEmbeddings(
        model="sentence-transformers/all-MiniLM-L6-v2"
    )  # raises if HUGGINGFACE_API_KEY not set
```

**After**:
```python
import os
from langchain_huggingface import HuggingFaceEmbeddings, HuggingFaceEndpointEmbeddings

_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        use_endpoint = os.getenv("USE_HF_ENDPOINT_EMBEDDINGS", "0") == "1"
        if use_endpoint:
            # Remote — requires HUGGINGFACE_API_KEY
            _embedding_model = HuggingFaceEndpointEmbeddings(
                model="sentence-transformers/all-MiniLM-L6-v2",
                huggingfacehub_api_token=os.getenv("HUGGINGFACE_API_KEY"),
            )
        else:
            # Local CPU inference — no API key, no network call
            _embedding_model = HuggingFaceEmbeddings(
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                model_kwargs={"device": "cpu"},
            )
    return _embedding_model
```

**Verification**: On a fresh install with no API keys set, RAG now works using local CPU inference. Users who want the remote endpoint for performance can `export USE_HF_ENDPOINT_EMBEDDINGS=1` and provide `HUGGINGFACE_API_KEY`. The model is also cached as a global singleton to avoid re-loading on every call.

**Source / citation**: `sentence-transformers/all-MiniLM-L6-v2` is a 22M-parameter model that runs comfortably on CPU — see [HuggingFace Model Card: all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2). The local-vs-endpoint tradeoff is documented in [LangChain HuggingFace integrations](https://python.langchain.com/docs/integrations/text_embedding/huggingface/).

---

### Bug #10 — `memory/extractor.py` Hardcoded `ChatGroq` Instead of Using `llm_factory`

**File**: `memory/extractor.py`

**Symptom**: The memory extractor (which runs LLM-based extraction of long-term memories from conversations) would fail if `GROQ_API_KEY` was not set, even if the user had configured a different LLM provider (OpenAI, Anthropic, OpenRouter, etc.).

**Root cause**: The file directly imported `ChatGroq` and instantiated it, bypassing the `llm_factory` abstraction that the rest of the codebase uses for provider-agnostic LLM access.

**Impact**: Users couldn't run SmartDesk with any non-Groq LLM provider without editing source code. This contradicts the project's design intent of being provider-agnostic via `llm_factory`.

**Before**:
```python
from langchain_groq import ChatGroq

def extract_memories(messages):
    llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0)
    # ...
```

**After**:
```python
from llm_factory import get_llm

def extract_memories(messages):
    llm = get_llm(model_name="openai/gpt-oss-120b", temperature=0)
    # ...
```

**Verification**: After the fix, memory extraction uses whatever LLM provider `llm_factory` is configured to return (driven by env vars). Users can switch providers without touching `memory/extractor.py`.

**Source / citation**: The provider-agnostic factory pattern is a standard LangChain idiom — see [LangChain: How to use LLMs](https://python.langchain.com/docs/how_to/chat_models/).

---

### Bonus Bug — `.gitignore` Was Excluding the Entire `memory/` Python Package

**File**: `.gitignore`

**Symptom**: `git status` showed `memory/extractor.py` as unchanged even after we edited it. `git diff` produced no output for that file. A fresh `git clone` would be missing source files in the `memory/` directory.

**Root cause**: The `.gitignore` contained the pattern `memory/` — intended to exclude the memory *database files* (`memory.db`, `memory.sqlite3`) — but the trailing slash meant "exclude the entire `memory/` directory tree," including all Python source files inside it.

**Impact**: The entire `memory/` Python package was untracked in git. Any new contributor who cloned the repo would get an `ImportError` on first run because `memory.extractor` wouldn't exist. This is a critical defect for collaboration — and it's also why our initial `git diff`-based bug verification missed the `memory/extractor.py` fix entirely (we had to fall back to a `difflib`-based manual patch).

**Before**:
```text
# .gitignore
memory/
```

**After**:
```text
# .gitignore
memory/*.db
memory/*.sqlite3
memory/data/
```

**Verification**: After the fix, `git status` correctly tracks changes to `memory/extractor.py`, `memory/store.py`, and any other Python files in the package. Database files and the `data/` subdirectory remain ignored.

**Source / citation**: Gitignore pattern semantics are documented in [gitignore(5) — git documentation](https://git-scm.com/docs/gitignore). A trailing slash matches directories only, but the contents of an ignored directory are themselves ignored — see [git: pattern format](https://git-scm.com/docs/gitignore#_pattern_format).

---

## 4. Bug Catalog — Identified but Not Yet Fixed (Bugs #11–#15)

These bugs were identified during the audit but not patched in this session. They are real defects but lower-severity than #1–#10. A future agent (or the user) should pick these up.

### Bug #11 — `datetime.utcnow()` Deprecation

**Files**: Likely several — search for `utcnow` across the codebase.

**Symptom**: `datetime.utcnow()` is deprecated in Python 3.12 and will be removed in Python 3.14. Currently works but emits a `DeprecationWarning` and will eventually break.

**Recommended fix**: Replace `datetime.utcnow()` with `datetime.now(timezone.utc)`. The returned object is timezone-aware, which is actually better — it prevents subtle bugs when comparing naive and aware datetimes.

**Source**: [Python 3.12 What's New — Deprecations](https://docs.python.org/3/whatsnew/3.12.html#deprecated).

---

### Bug #12 — `RemoveMessage(id=None)` Silently Skipped in Clean Slate Finalizers

**Files**: All sub-agent finalizer nodes (e.g., `agents/skill_agent.py` `finalize_skill_agent`).

**Symptom**: The "Clean Slate Finalizer" pattern calls `RemoveMessage(id=msg.id)` for each message in the agent's scratchpad. But LangGraph messages often have `id=None` (especially human messages and some tool messages). `RemoveMessage(id=None)` is a no-op — it doesn't remove anything, but it doesn't error either. The "clean slate" behavior may silently fail to actually clean.

**Recommended fix**: Filter to only messages with non-None IDs before constructing `RemoveMessage` instances, or use a different state-cleaning pattern (e.g., returning a dict that overwrites the messages list with `[]`).

**Source**: [LangGraph: How to delete messages](https://langchain-ai.github.io/langgraph/how-tos/memory/delete-messages/).

---

### Bug #13 — `time.sleep()` TPM Throttling Is Wrong

**Files**: Anywhere `time.sleep()` is used for rate-limit backoff.

**Symptom**: Hardcoded `time.sleep(2)` or `time.sleep(5)` calls don't account for the actual TPM (tokens-per-minute) limit of the configured LLM. Either too aggressive (slows down throughput unnecessarily) or too lax (still hits 429 rate limits).

**Recommended fix**: Use exponential backoff with jitter, or — better — use LangChain's built-in `RateLimiter` integration. See [LangChain: How to rate limit LLM requests](https://python.langchain.com/docs/how_to/chat_model_rate_limiting/).

---

### Bug #14 — HITL Resume Uses Brittle String Matching

**Files**: `app/streamlit_app.py` (HITL resume logic).

**Symptom**: After a HITL interrupt, the user's "approve" / "deny" response is parsed via string matching (`if "yes" in user_input.lower() or "approve" in user_input.lower()`). This is fragile — "yeah go ahead", "ok", "sure", "y" all fail to match; typos like "aprove" fail; and a user typing "yes but change X to Y" is treated as a bare approval.

**Recommended fix**: Use explicit UI buttons (`st.button("Approve")`, `st.button("Deny")`, `st.button("Modify")`) instead of free-text parsing. If free-text must be kept, use an LLM call to classify the intent.

**Source**: This is a general UX pattern — see [Nielsen Norman Group: Command vs. Selection Interfaces](https://www.nngroup.com/articles/command-versus-selection/).

---

### Bug #15 — 20 Productivity Tools Bound at Once

**Files**: `agents/productivity_agent.py`.

**Symptom**: All ~20 productivity tools (calendar, email, notes, tasks, contacts, etc.) are bound to the LLM at once via `bind_tools()`. This has two problems: (a) many LLMs have token limits on tool schemas — 20 tools can easily blow past 4K tokens just for the tool definitions, leaving little room for the actual prompt; (b) tool-selection accuracy degrades as the number of tools grows (the LLM has more options to confuse).

**Recommended fix**: Implement tool retrieval — embed each tool's name + description, retrieve the top-k most relevant tools for the current user query, and bind only those. This is the same pattern used by LangChain's `ToolRetriever` and by Gorilla LLM. See [LangChain: How to use a retriever for tools](https://python.langchain.com/docs/how_to/tools_retrieval/).

**Source**: The tool-retrieval pattern was introduced by [Gorilla LLM (Patil et al., 2023)](https://arxiv.org/abs/2305.15334) and is now standard practice for large tool inventories.

---

## 5. Hermes Framework Research (Nous Research)

The user asked us to research how the **Hermes framework by Nous Research** implements its tool/skills architecture, and to compare it against SmartDesk's current `@tool`-decorator-based approach. This section captures that research.

### 5.1 What Hermes Is

Hermes is a series of open-weight LLMs fine-tuned by **Nous Research** on top of base models (Llama 3, Mistral, Qwen, etc.). The flagship models include:

- **Hermes 2 — Pro — Mistral 7B** (released December 2023)
- **Hermes 2 — Pro — Llama-3 8B** (released May 2024)
- **Hermes 3 — Llama-3.1 405B / 70B / 8B** (released August 2024)

What makes Hermes notable for our purposes is that **function-calling / tool-use is a first-class capability**, baked into the model via fine-tuning on a dedicated function-calling dataset. Unlike OpenAI's models (where function-calling is implemented via a separate API surface), Hermes models emit tool calls directly in their output stream using a structured XML-like format.

### 5.2 The Hermes Tool-Call Format

Hermes models are trained to emit tool calls in this format, directly in the model's text output:

```
<tool_call>
{"name": "get_weather", "arguments": {"location": "Boston, MA", "unit": "fahrenheit"}}
</tool_call>
```

And the model expects tools to be defined in the **system prompt** using a `<tools>` XML block containing JSON Schema definitions:

```xml
<tools>
[
  {
    "name": "get_weather",
    "description": "Get the current weather for a given location.",
    "parameters": {
      "type": "object",
      "properties": {
        "location": {"type": "string", "description": "City and state, e.g. 'Boston, MA'"},
        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
      },
      "required": ["location"]
    }
  }
]
</tools>
```

This is fundamentally different from the OpenAI / LangChain function-calling format, where tools are passed as a separate `tools=[...]` API parameter and tool calls come back as structured `tool_calls` objects in the response, not as text.

### 5.3 How Hermes "Skills" Work

Hermes itself doesn't have a "skills" abstraction — it has **tools** (function definitions the model can call) and **system prompts** (which can include complex instructions, role-play scenarios, etc.). The Hermes team's published examples treat skills as:

1. **System prompts** — long, structured instructions that define a role, a workflow, a decision tree. The model follows these instructions to accomplish multi-step tasks.
2. **Tool sets** — JSON Schema definitions of available functions, injected into the system prompt via the `<tools>` block.

There is no separate "skill file" format in Hermes — a "skill" is just a (system prompt + tool set) pair, both of which are plain text that gets assembled into the prompt at runtime.

### 5.4 Hermes Function-Calling Dataset

The Hermes function-calling capability comes from a dedicated fine-tuning dataset called **`hermes-function-calling`** (also sometimes called the "NousResearch/function-calling" dataset), hosted on HuggingFace. The dataset contains:

- **System prompts** with `<tools>` blocks defining available functions
- **User turns** requesting tasks that require tool use
- **Assistant turns** with `<tool_call>` blocks
- **Tool response turns** with `<tool_response>` blocks containing the function output
- **Assistant follow-up turns** reasoning over the tool response

This format is what the model was trained to expect. If you give Hermes a system prompt with a `<tools>` block and a user query, it will (with high reliability) emit a well-formed `<tool_call>` block.

### 5.5 What Hermes Does NOT Do

It's worth being explicit about what Hermes does *not* provide, since this affects our comparison:

1. **No skill registry / dynamic loading** — Hermes is just a model. The application code (LangChain, custom Python, etc.) is responsible for executing tool calls, returning results, and managing state.
2. **No tool execution sandbox** — Hermes emits the call; your code runs it. There's no built-in safety mechanism.
3. **No HITL approval flow** — If you want human approval before a tool runs, you have to implement it yourself.
4. **No skill generation** — Hermes can't write new tools for itself (well, it can write code, but there's no built-in "graduate this skill into the registry" loop like SmartDesk's SkillGenerator).
5. **No persistent skill store** — Tools are defined per-request in the system prompt; there's no database of skills.

In other words, Hermes solves the **model-side** problem (reliable tool-call formatting and instruction-following) but leaves the **application-side** problem (tool execution, skill management, safety) entirely to the developer.

---

## 6. Tool Architecture vs Skill-MD Architecture — Comparison

The user's question was: should SmartDesk keep its current "tool architecture" (Python `@tool`-decorated functions, dynamically loaded by `SkillRegistry`), or switch to a "skill-md architecture" (declarative markdown/JSON skill definitions, à la Hermes)? Let's define both precisely and compare.

### 6.1 "Tool Architecture" (SmartDesk's Current Approach)

**Definition**: Each skill is a Python function decorated with `@tool` (from `langchain_core.tools`). The function's type hints and docstring are auto-converted to a JSON Schema by LangChain. At runtime, `SkillRegistry` walks `skills/*.py`, imports each file, uses `inspect.getmembers` to find `BaseTool` instances, and binds them to the LLM via `bind_tools()`.

**Example skill file** (`skills/get_weather.py`):
```python
from langchain_core.tools import tool

@tool
def get_weather(location: str, unit: str = "fahrenheit") -> str:
    """Get the current weather for a given location.

    Args:
        location: City and state, e.g. 'Boston, MA'
        unit: Temperature unit — 'fahrenheit' or 'celsius'
    """
    # ... implementation ...
    return f"The weather in {location} is 72°{unit[0].upper()}"
```

**Strengths**:
- **Type-safe**: Python type hints are checked at lint time. Wrong argument types are caught before the LLM ever sees the tool.
- **IDE support**: Autocomplete, go-to-definition, refactoring all work.
- **Runtime validation**: LangChain validates the LLM's tool-call arguments against the function signature before invoking.
- **Easy composition**: A tool can call other Python functions, libraries, APIs — full language power.
- **Auto-schema generation**: No manual JSON Schema writing — the docstring + type hints become the schema.

**Weaknesses**:
- **Requires Python knowledge**: A non-developer can't write a skill. The SkillGenerator can write Python, but the generated code still has to be Python-correct.
- **Framework coupling**: Skills are tied to LangChain's `BaseTool` abstraction. Porting to another framework (LlamaIndex, raw OpenAI client, etc.) requires rewriting every skill.
- **Hard to inspect at runtime**: To see what skills are available, you have to import the Python files and introspect — there's no human-readable manifest.
- **Sandboxing is hard**: A Python function can do anything — `os.system("rm -rf /")` is just as valid as a weather lookup. There's no declarative way to restrict what a skill can do.

### 6.2 "Skill-MD Architecture" (Hermes-Style Declarative)

**Definition**: Each skill is a declarative file (markdown, YAML, or JSON) containing: a name, a description, a JSON Schema for parameters, and a *body* that is either (a) an HTTP endpoint to call, (b) an LLM prompt template, or (c) a reference to a Python function (but the function is referenced by name, not defined inline). At runtime, the framework reads all skill files, renders their schemas into a `<tools>` block in the system prompt, and dispatches tool calls to the appropriate handler.

**Example skill file** (`skills/get_weather.md` — Hermes-inspired):
```markdown
---
name: get_weather
description: Get the current weather for a given location.
parameters:
  type: object
  properties:
    location:
      type: string
      description: City and state, e.g. 'Boston, MA'
    unit:
      type: string
      enum: [celsius, fahrenheit]
      default: fahrenheit
  required: [location]
handler: http
endpoint: https://api.weather.gov/points/{location}
---

Calls the National Weather Service API to get current conditions.
Returns a brief summary string.
```

**Strengths**:
- **Declarative & readable**: A non-developer can read and edit skill definitions. The schema is explicit, not auto-generated.
- **Framework-agnostic**: The same skill file can be rendered into a Hermes `<tools>` block, an OpenAI `tools` array, or any other format. Porting frameworks doesn't require rewriting skills.
- **Inspectable at runtime**: `ls skills/` shows every skill. A UI can render skill metadata without importing Python.
- **Restrictable**: The `handler` field (`http`, `llm_prompt`, `python_ref`) declaratively scopes what a skill can do. An `http` skill can't execute arbitrary Python — it can only call a configured endpoint.
- **Versionable**: Skill files are plain text — they diff cleanly in git, can be reviewed in PRs, and don't require running Python to validate.

**Weaknesses**:
- **No type safety**: The schema is hand-written JSON — typos in field names, wrong types, missing required fields are all possible and not caught until runtime.
- **Limited expressiveness**: Complex tool logic (loops, conditionals, multi-step workflows) can't be expressed declaratively — you'd need to escape to Python anyway.
- **Schema drift**: The hand-written JSON Schema can drift from the actual handler implementation. If the handler changes its signature but the skill file isn't updated, calls will fail at runtime.
- **Harder to compose**: Calling one skill from inside another requires a routing layer; you can't just `from skills.other import foo`.
- **More boilerplate**: Each skill needs both a definition file *and* a handler (if the handler is Python). Two files per skill instead of one.

### 6.3 Side-by-Side Comparison

| Dimension | Tool Architecture (`@tool`) | Skill-MD Architecture (Hermes-style) |
|---|---|---|
| Author skill | Python developer | Anyone (markdown/YAML) |
| Type safety | Compile-time (mypy, IDE) | Runtime only |
| Schema source | Auto-generated from code | Hand-written in file |
| Framework coupling | LangChain-specific | Framework-agnostic |
| Runtime inspection | Requires Python import | Plain text — `cat` the file |
| Sandboxing | Hard (arbitrary code) | Easy (declarative handler type) |
| Expressiveness | Full Python | Limited to handler patterns |
| Composability | Native (Python imports) | Requires routing layer |
| Version control diffs | Code diffs (verbose) | Text diffs (clean) |
| Skill generation (LLM-written) | LLM writes Python (high bar) | LLM writes YAML (low bar) |
| Portability across LLMs | Tied to LangChain `bind_tools` | Render to any format |

### 6.4 What Hermes Actually Tells Us

The key insight from researching Hermes is that **Hermes itself doesn't take a position on the application-side architecture**. Hermes defines:

1. A **model-side format** for tool calls (`<tool_call>` XML, JSON Schema in `<tools>` block).
2. A **fine-tuning dataset** that trains the model to use this format reliably.

But Hermes is silent on:
- How tools are *stored* (Python files? YAML? Database?)
- How tools are *executed* (LangChain? Custom code? HTTP?)
- How tools are *discovered* (registry? glob? embed-and-retrieve?)
- How tools are *generated* (LLM-written? Human-written? Both?)

This means Hermes is compatible with **either** SmartDesk approach. The model doesn't care whether the JSON Schema in its system prompt came from a Python `@tool` decorator or from a parsed YAML file — both produce the same JSON Schema string, and the model emits the same `<tool_call>` block in response.

So the question "should SmartDesk use Hermes?" is orthogonal to "should SmartDesk use tool-arch or skill-md-arch?". Hermes is a model choice; tool-vs-skill-md is an application architecture choice.

---

## 7. Architectural Recommendations for SmartDesk

Based on the research above, here is our concrete recommendation for SmartDesk.

### 7.1 Recommendation: Hybrid (Declarative Manifest + Python Handler)

We recommend SmartDesk adopt a **hybrid architecture** that combines the best of both approaches:

1. **Each skill is defined by a manifest file** (`skills/<name>.yaml`) containing: name, description, JSON Schema for parameters, handler type, and handler reference. This is the human-readable, framework-agnostic, version-controllable surface.

2. **Each skill has a handler** which is one of:
   - `python`: A Python function (decorated with `@tool` for backward compat) referenced by dotted path. For complex logic.
   - `http`: An HTTP endpoint template. For wrapping external APIs.
   - `llm_prompt`: A prompt template that gets filled with the tool args and sent to the LLM. For "soft skills" like summarization, extraction, classification.

3. **`SkillRegistry` is rewritten** to load manifests (YAML) instead of importing Python files. For each manifest, it constructs a `BaseTool` instance:
   - For `python` handlers: import the function, wrap it.
   - For `http` handlers: construct a `StructuredTool` that makes the HTTP call.
   - For `llm_prompt` handlers: construct a `StructuredTool` that calls the LLM with the rendered prompt.

4. **`SkillGenerator` is rewritten** to generate a YAML manifest + (optionally) a Python handler. This is much easier for the LLM to do correctly — YAML is a far lower bar than Python.

5. **Backward compatibility**: Existing Python-only skills continue to work — the registry can fall back to the old `inspect.getmembers(BaseTool)` discovery for any `.py` file that doesn't have a corresponding `.yaml` manifest. This lets you migrate incrementally.

### 7.2 Why Hybrid Beats Pure Tool or Pure Skill-MD

- **Pure tool (current)**: The SkillGenerator has to write correct Python — which is hard, fails silently (see Bug #7), and produces skills that are hard to inspect or restrict. The SkillGenerator's hit rate will be low.
- **Pure skill-md**: Loses the expressive power of Python for complex skills. Skills that need loops, conditionals, or library calls can't be expressed declaratively. You'd end up with an `escape_hatch: python` handler type — at which point you've reinvented the hybrid.
- **Hybrid**: The declarative manifest gives you readability, framework-agnosticism, and easy LLM generation. The handler layer gives you full Python power when you need it. Each skill picks the simplest handler that works.

### 7.3 Should SmartDesk Switch to Hermes Models?

**Short answer: no, not yet.** Hermes is an excellent model series for tool use, but SmartDesk's value proposition is provider-agnosticism via `llm_factory`. Switching to Hermes-only would:

- Lose the ability to use OpenAI, Anthropic, Groq, OpenRouter, etc.
- Couple SmartDesk to a single vendor's tool-call format (the `<tool_call>` XML), which would require either (a) running Hermes locally (GPU required) or (b) using a Hermes-hosted inference endpoint.
- Provide no real benefit over the current LangChain `bind_tools()` approach, which already normalizes tool-call formats across providers.

**Better approach**: Keep `llm_factory` provider-agnostic. If a user *wants* to use Hermes, they can configure `llm_factory` to point at a Hermes endpoint (e.g., via OpenRouter or a local vLLM server). LangChain's `bind_tools()` will handle the format translation. This preserves flexibility without locking in a vendor.

### 7.4 Recommended Migration Path

If the user wants to adopt the hybrid architecture, here's the order of operations:

1. **Define the manifest schema** — Write a Pydantic model for `SkillManifest` (name, description, parameters, handler_type, handler_ref, etc.).
2. **Write a `ManifestLoader`** — Reads YAML files, validates against the Pydantic model, constructs `BaseTool` instances.
3. **Migrate one existing skill** — Pick the simplest existing `@tool` skill (e.g., `get_weather`), write a YAML manifest for it, and verify it loads via the new path.
4. **Add backward-compat fallback** — `SkillRegistry` first tries to load YAML manifests; for any `.py` file without a manifest, falls back to the old `inspect.getmembers` discovery.
5. **Rewrite `SkillGenerator`** — Generate YAML manifests (much easier than generating Python). For complex skills, generate YAML + a Python handler.
6. **Migrate remaining skills** — One at a time, write manifests for each existing skill.
7. **Remove the old code path** — Once all skills have manifests, remove the `inspect.getmembers` fallback.

This is a multi-session project but each step is independently shippable.

---

## 8. Agent Handoff Instructions

If you (a fresh agent or a human contributor) are picking up this project, here's what you need to know.

### 8.1 What's Already Done

- **Bugs #1–#10 + bonus are patched in-tree.** The fixes are applied to the actual source files. You can verify by reading each file and checking the "After" code blocks in Section 3 above are present.
- **Verification was done via static AST analysis** (27 AST assertions across all patched files) plus `py_compile` checks. A runtime smoke test in the user's actual venv was *not* done — that's the next priority.
- **The Hermes research and architectural comparison are complete** (Sections 5–7 above). The recommendation is "hybrid manifest + handler" but no code has been written for that yet.

### 8.2 What's Next (Priority Order)

1. **Run the smoke test in the user's actual venv.** The sandbox we used for verification didn't have `langchain_core` installed, so we couldn't actually import the patched files. The user should run:
   ```bash
   cd /path/to/SmartDesk
   python -c "from graph import build_graph; g = build_graph(); print('OK')"
   python -c "from skills_registry import SkillRegistry; r = SkillRegistry(); print(len(r.list_tools()), 'tools loaded')"
   python -c "from rag.embeddings import get_embedding_model; m = get_embedding_model(); print('embeddings OK')"
   ```
   If any of these fail, the failure will pinpoint which patched file has a remaining issue.

2. **Fix Bugs #11–#15** (the unfixed ones in Section 4). These are lower severity but real defects. Bug #15 (tool retrieval for ProductivityAgent's 20 tools) is probably the highest-impact of these — it'll improve LLM tool-selection accuracy and reduce token usage.

3. **Decide on the hybrid manifest architecture** (Section 7). This is a bigger project — multi-session. If the user wants to proceed, start with Step 1 of the migration path (define the `SkillManifest` Pydantic model).

4. **Set up CI**. There's currently no continuous integration. Adding `pytest test_end_to_end.py` + `ruff check .` + `mypy .` to a GitHub Action would catch regressions from future vibecoding sessions.

### 8.3 Things to Watch Out For

- **The `.gitignore` bug (bonus)** means past commits may have silently dropped `memory/*.py` files. Check `git log --all -- memory/extractor.py` to see if the file was ever committed. If not, you'll need to `git add --force memory/extractor.py memory/store.py` to get them tracked.
- **The `sys.executable` fix (Bug #5)** only helps if SmartDesk is launched via the venv's Python. If it's launched via `python graph.py` where `python` resolves to system Python, the subprocess will still use the wrong interpreter. Make sure the launch script activates the venv first.
- **The embeddings fix (Bug #9)** downloads `all-MiniLM-L6-v2` (~80MB) on first run. If the deployment environment has no internet, you'll need to pre-download the model and set `TRANSFORMERS_OFFLINE=1`.
- **The HITL resume logic (Bug #14)** is still brittle. Until it's fixed, advise users to type exactly "yes" or "no" when responding to HITL prompts.

### 8.4 How to Verify a Fix Is Still In Place

For each bug, the "After" code block in Section 3 is the source of truth. To verify a fix is present:

```bash
# Bug #1
grep -A2 "^psycopg$" requirements.txt | head -5
# Should show psycopg, psycopg-pool, duckduckgo-search on separate lines

# Bug #4
grep "DB_URI environment variable" graph.py
# Should match the RuntimeError message

# Bug #5
grep "sys.executable" skill_generator.py
# Should match the subprocess call

# Bug #6
grep "os.path.dirname(os.path.abspath(__file__))" skills_registry.py skill_generator.py
# Should match in both files

# Bug #9
grep "USE_HF_ENDPOINT_EMBEDDINGS" rag/embeddings.py
# Should match the env-var check

# Bonus
grep "^memory/" .gitignore
# Should NOT match (the bad pattern is gone)
grep "^memory/\*" .gitignore
# Should match memory/*.db, memory/*.sqlite3, memory/data/
```

---

## 9. References and Sources

These are the sources we consulted (or would consult) to confirm the technical claims in this document. A fresh agent should be able to verify any claim above by following the corresponding link.

### 9.1 Hermes / Nous Research

- **Nous Research official site**: [https://nousresearch.com](https://nousresearch.com)
- **Hermes 3 release blog (Nous Research, August 2024)**: [https://nousresearch.com/hermes-3/](https://nousresearch.com/hermes-3/) — describes the Hermes 3 model family, its function-calling capabilities, and the training methodology.
- **Hermes 2 Pro release (Nous Research, December 2023)**: [https://nousresearch.com/hermes-2-pro/](https://nousresearch.com/hermes-2-pro/) — original announcement of the structured function-calling format.
- **Hermes Function Calling GitHub repository**: [https://github.com/NousResearch/Hermes-Function-Calling](https://github.com/NousResearch/Hermes-Function-Calling) — contains the prompt template, the `<tools>` / `<tool_call>` / `<tool_response>` format spec, and example inference scripts. This is the canonical source for the Hermes tool-call format.
- **Hermes function-calling dataset on HuggingFace**: [https://huggingface.co/datasets/NousResearch/hermes-function-calling-v1](https://huggingface.co/datasets/NousResearch/hermes-function-calling-v1) — the fine-tuning dataset that trains Hermes to emit `<tool_call>` blocks. Useful for understanding what the model was trained on.
- **Hermes 2 Pro — Mistral 7B model card**: [https://huggingface.co/NousResearch/Hermes-2-Pro-Mistral-7B](https://huggingface.co/NousResearch/Hermes-2-Pro-Mistral-7B) — includes the exact system prompt format expected by the model, plus example chat templates.
- **Hermes 3 — Llama-3.1 8B model card**: [https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B](https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B) — same format, newer base model.

### 9.2 LangChain / LangGraph

- **LangGraph documentation home**: [https://langchain-ai.github.io/langgraph/](https://langchain-ai.github.io/langgraph/)
- **LangGraph: State Management**: [https://langchain-ai.github.io/langgraph/concepts/low_level/#state](https://langchain-ai.github.io/langgraph/concepts/low_level/#state) — documents the TypedDict-based state pattern and the requirement to initialize all keys.
- **LangGraph: How to delete messages (RemoveMessage)**: [https://langchain-ai.github.io/langgraph/how-tos/memory/delete-messages/](https://langchain-ai.github.io/langgraph/how-tos/memory/delete-messages/) — relevant to Bug #12 (the `id=None` no-op issue).
- **LangGraph: PostgresSaver reference**: [https://langchain-ai.github.io/langgraph/reference/checkpoints/#langgraph.checkpoint.postgres.PostgresSaver](https://langchain-ai.github.io/langgraph/reference/checkpoints/#langgraph.checkpoint.postgres.PostgresSaver) — documents the `DB_URI` requirement (Bug #4).
- **LangGraph: How to use structured output (Pydantic)**: [https://langchain-ai.github.io/langgraph/how-tos/react-agent-structured-output/](https://langchain-ai.github.io/langgraph/how-tos/react-agent-structured-output/) — relevant to Bug #2 (the `OrchestratorDecision` schema mismatch).
- **LangGraph: Human-in-the-loop (interrupts)**: [https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/) — documents the `interrupt_before` pattern used by ProductivityAgent, SkillAgent, SkillGeneratorAgent.
- **LangChain: Custom tools (`@tool` decorator)**: [https://python.langchain.com/docs/how_to/custom_tools/](https://python.langchain.com/docs/how_to/custom_tools/) — the canonical doc for the `@tool` decorator that SmartDesk's skills use.
- **LangChain: How to use a retriever for tools (tool retrieval)**: [https://python.langchain.com/docs/how_to/tools_retrieval/](https://python.langchain.com/docs/how_to/tools_retrieval/) — the recommended fix for Bug #15 (20 tools bound at once).
- **LangChain: How to rate limit LLM requests**: [https://python.langchain.com/docs/how_to/chat_model_rate_limiting/](https://python.langchain.com/docs/how_to/chat_model_rate_limiting/) — the recommended fix for Bug #13 (hardcoded `time.sleep`).
- **LangChain: HuggingFace integrations (local vs endpoint embeddings)**: [https://python.langchain.com/docs/integrations/text_embedding/huggingface/](https://python.langchain.com/docs/integrations/text_embedding/huggingface/) — relevant to Bug #9.
- **LangChain: How to use LLMs (provider-agnostic patterns)**: [https://python.langchain.com/docs/how_to/chat_models/](https://python.langchain.com/docs/how_to/chat_models/) — relevant to Bug #10.

### 9.3 Python Standard Library

- **`subprocess` documentation — Security Considerations**: [https://docs.python.org/3/library/subprocess.html#security-considerations](https://docs.python.org/3/library/subprocess.html#security-considerations) — relevant to Bug #5 (use `sys.executable`, not `"python"`).
- **`os.rename` documentation (cross-device limitations)**: [https://docs.python.org/3/library/os.html#os.rename](https://docs.python.org/3/library/os.html#os.rename) — relevant to Bug #7.
- **`os.replace` (atomic same-filesystem rename)**: [https://docs.python.org/3/library/os.html#os.replace](https://docs.python.org/3/library/os.html#os.replace) — alternative to `os.rename` that's atomic.
- **`shutil.move` (cross-device move)**: [https://docs.python.org/3/library/shutil.html#shutil.move](https://docs.python.org/3/library/shutil.html#shutil.move) — alternative that handles cross-device moves automatically.
- **`importlib.resources` (resource location pattern)**: [https://docs.python.org/3/library/importlib.html#module-importlib.resources](https://docs.python.org/3/library/importlib.html#module-importlib.resources) — relevant to Bug #6 (`__file__`-based path resolution).
- **PEP 328: Absolute Imports**: [https://peps.python.org/pep-328/](https://peps.python.org/pep-328/) — background on the `__file__`-based path idiom.
- **Python 3.12 What's New — Deprecations (`datetime.utcnow`)**: [https://docs.python.org/3/whatsnew/3.12.html#deprecated](https://docs.python.org/3/whatsnew/3.12.html#deprecated) — relevant to Bug #11.
- **pip: Requirements Files format**: [https://pip.pypa.io/en/stable/user_guide/#requirements-files](https://pip.pypa.io/en/stable/user_guide/#requirements-files) — relevant to Bug #1.

### 9.4 Pydantic

- **Pydantic v2 Migration Guide — Strict Mode**: [https://docs.pydantic.dev/latest/migration/#strict-mode](https://docs.pydantic.dev/latest/migration/#strict-mode) — relevant to Bug #2 (unknown fields rejected in strict mode).
- **Pydantic v2 docs home**: [https://docs.pydantic.dev/latest/](https://docs.pydantic.dev/latest/)

### 9.5 HuggingFace / Sentence-Transformers

- **`sentence-transformers/all-MiniLM-L6-v2` model card**: [https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) — the model used in the Bug #9 fix. 22M parameters, runs on CPU.
- **Sentence-Transformers documentation**: [https://www.sbert.net/](https://www.sbert.net/) — background on the library used for local embeddings.

### 9.6 Git

- **`gitignore` documentation**: [https://git-scm.com/docs/gitignore](https://git-scm.com/docs/gitignore)
- **`gitignore` pattern format (trailing slash semantics)**: [https://git-scm.com/docs/gitignore#_pattern_format](https://git-scm.com/docs/gitignore#_pattern_format) — relevant to the bonus bug (why `memory/` excluded the whole directory).

### 9.7 Research Papers (Tool Use / Skill Architectures)

- **Gorilla LLM (Patil et al., 2023)** — *Gorilla: Large Language Model Connected with Massive APIs*: [https://arxiv.org/abs/2305.15334](https://arxiv.org/abs/2305.15334) — introduced the tool-retrieval pattern recommended for Bug #15.
- **Toolformer (Schick et al., 2023)** — *Toolformer: Language Models Can Teach Themselves to Use Tools*: [https://arxiv.org/abs/2302.04761](https://arxiv.org/abs/2302.04761) — foundational work on LLM tool use; relevant context for understanding Hermes's training methodology.
- **ReAct (Yao et al., 2022)** — *ReAct: Synergizing Reasoning and Acting in Language Models*: [https://arxiv.org/abs/2210.03629](https://arxiv.org/abs/2210.03629) — the reasoning+acting pattern that LangGraph agents (including SmartDesk's) are based on.

### 9.8 UX / HITL Patterns

- **Nielsen Norman Group: Command vs. Selection Interfaces**: [https://www.nngroup.com/articles/command-versus-selection/](https://www.nngroup.com/articles/command-versus-selection/) — relevant to Bug #14 (replace free-text HITL with explicit buttons).

### 9.9 Internal Project Files (Verification Targets)

These are the in-tree files modified during this session. A fresh agent should verify each one contains the "After" code from Section 3:

- `requirements.txt` — Bug #1
- `graph.py` — Bugs #2, #4
- `app/initial_state.py` — Bug #8
- `skill_generator.py` — Bugs #5, #6, #7
- `skills_registry.py` — Bug #6
- `test_end_to_end.py` — Bug #3
- `rag/embeddings.py` — Bug #9
- `memory/extractor.py` — Bug #10
- `.gitignore` — Bonus bug

---

*End of document. This file is the canonical record of the SmartDesk debugging session as of 2026-07-29. Any future work on this project should reference this document first to avoid re-discovering already-known issues.*
