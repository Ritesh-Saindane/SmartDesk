import os
import json
import time
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage, RemoveMessage
from langchain_core.tools import tool
from llm_factory import get_llm
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from state import GraphState, Artifact, ArtifactType

# ── RAW_CONTEXT scalability ────────────────────────────────────────────────────
# Large file contents are intentionally omitted from the artifact payload to
# avoid exceeding LLM context limits while preserving planning ability.
# The Orchestrator uses metadata["payload_inlined"] as the authoritative signal.
MAX_INLINE_CONTEXT_TOKENS = 5000

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token (computed once at ingestion)."""
    return len(text) // 4

load_dotenv()
MODEL_NAME = "openai/gpt-oss-120b"
MAX_AGENT_STEPS = 5

# =========================================================
# TOOLS
# =========================================================

@tool
def read_file(path: str) -> str:
    """Read contents of a file from disk."""
    print(f"  [Tool] read_file({path})")
    try:
        if not os.path.exists(path):
            return f"Error: File does not exist -> {path}"
        if not os.path.isfile(path):
            return f"Error: Path is not a file -> {path}"
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return f"File is empty -> {path}"

        # ── Token-limit guard ──────────────────────────────────────────────────
        # If the file is too large to inline, return a structured error instead
        # of the full content. This prevents the large text from entering
        # workspace_messages and causing 413 / context-overflow errors.
        # The workspace_finalizer detects this prefix and creates a proper
        # RAW_CONTEXT artifact with the path stored in metadata.
        token_count = _estimate_tokens(content)
        if token_count > MAX_INLINE_CONTEXT_TOKENS:
            abs_path = os.path.abspath(path)
            print(f"  [Tool] read_file: file too large ({token_count} tokens) — returning error.")
            return (
                f"FILE_TOO_LARGE::{abs_path}::{token_count}\n"
                f"The file '{os.path.basename(path)}' is too large to read inline "
                f"({token_count} estimated tokens, limit is {MAX_INLINE_CONTEXT_TOKENS}). "
                f"To summarize or query this file, please upload it using the chat upload button."
            )

        return content
    except Exception as e:
        return f"Error reading file: {str(e)}"


@tool
def search_file(name: str) -> str:
    """Search for files matching a name query."""
    print(f"  [Tool] search_file({name})")
    try:
        matches = []
        ignore_dirs = {".venv", "__pycache__", ".git", "chroma_db"}
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            for file in files:
                if name.lower() in file.lower():
                    full_path = os.path.join(root, file)
                    matches.append(full_path)
                    if len(matches) >= 50:
                        return "\n".join(matches) + "\n...and more (limited to 50 results). Please be more specific."
        if not matches:
            return f"No files found matching '{name}'"
        return "\n".join(matches)
    except Exception as e:
        return f"Error searching file: {str(e)}"

@tool
def create_folder(path: str) -> str:
    """Create a new directory at the given path."""
    print(f"  [Tool] create_folder({path})")
    try:
        os.makedirs(path, exist_ok=True)
        return f"Folder created successfully at: {path}"
    except Exception as e:
        return f"Error creating folder: {str(e)}"

@tool
def write_file(path: str, text: str) -> str:
    """Write text content to a file at the given path."""
    print(f"  [Tool] write_file({path})")
    try:
        parent_dir = os.path.dirname(path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return f"Written successfully to {path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"

workspace_tools = [read_file, search_file, create_folder, write_file]
workspace_llm = get_llm(model_name=MODEL_NAME, temperature=0).bind_tools(workspace_tools)
workspace_tool_node = ToolNode(workspace_tools, messages_key="workspace_messages")

# =========================================================
# AGENT LOGIC
# =========================================================

def workspace_agent(state: GraphState) -> dict:
    task = state["current_task"]
    print(f"\n--- [WorkspaceAgent] Executing {task.id} ---")

    context = {
        aid: state["artifacts"][aid].payload
        for aid in task.context_artifacts
        if aid in state["artifacts"]
    }

    sys_prompt = f"""You are WorkspaceAgent. You handle file system operations.
Task: {task.instruction}
Expected Output: {task.expected_output}
Context: {json.dumps(context)}

Use the available tools to complete the task. You may call multiple tools if needed.

IMPORTANT: If a tool returns a message starting with FILE_TOO_LARGE::, the file is too
large to read inline. Do NOT attempt any other tool calls. Simply respond with a short
confirmation that the file was too large and stop — the system will handle it.

IMPORTANT: Do NOT hallucinate tools to return the expected output (e.g. do not try to call a tool named 'raw_context'). When you are done using the actual available tools (read_file, write_file, etc.), simply write your final response as plain text."""

    if state["agent_steps"] == 0:
        messages = [SystemMessage(content=sys_prompt)]
    else:
        messages = [SystemMessage(content=sys_prompt)] + state["workspace_messages"]

    time.sleep(2)
    response = workspace_llm.invoke(messages)

    if response.tool_calls:
        print(f"  [WorkspaceAgent] Tool calls: {[tc['name'] for tc in response.tool_calls]}")
    else:
        print("  [WorkspaceAgent] Done — no more tool calls.")

    return {"workspace_messages": [response], "agent_steps": state["agent_steps"] + 1}

def workspace_route(state: GraphState) -> str:
    if state["agent_steps"] >= MAX_AGENT_STEPS:
        print("  [WorkspaceAgent] Max steps reached, forcing finalize.")
        return "WorkspaceFinalizer"

    last_msg = state["workspace_messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "WorkspaceToolNode"
    return "WorkspaceFinalizer"

def workspace_finalizer(state: GraphState) -> dict:
    print("  [WorkspaceAgent] Finalizing task.")
    
    task = state["current_task"]
    new_art_counter = state["artifact_counter"]
    artifacts_to_add = {}

    # 1. Scan for ALL read_file ToolMessages to create RAW_CONTEXT artifacts
    for msg in state["workspace_messages"]:
        if isinstance(msg, ToolMessage) and msg.name == "read_file":
            raw_payload = msg.content
            
            new_art_counter += 1
            artifact_id = f"art_{new_art_counter}"

            if raw_payload.startswith("FILE_TOO_LARGE::"):
                # Format: FILE_TOO_LARGE::<abs_path>::<token_count>\n<human message>
                parts = raw_payload.split("::", 2)
                file_path = parts[1] if len(parts) > 1 else ""
                try:
                    token_count = int(parts[2].split("\n", 1)[0]) if len(parts) > 2 else 0
                except ValueError:
                    token_count = 0
                too_large = True
                payload = None
            else:
                token_count = _estimate_tokens(raw_payload)
                too_large = token_count > MAX_INLINE_CONTEXT_TOKENS
                
                # Recover file path from the tool call that triggered this message
                file_path = ""
                for m in state["workspace_messages"]:
                    if hasattr(m, "tool_calls") and m.tool_calls:
                        for tc in m.tool_calls:
                            if tc["id"] == msg.tool_call_id:
                                file_path = os.path.abspath(tc["args"].get("path", ""))
                                break
                    if file_path:
                        break
                payload = raw_payload if not too_large else None

            metadata = {
                "path": file_path,
                "filename": os.path.basename(file_path) if file_path else "",
                "token_count": token_count,
                "payload_inlined": not too_large,
                "too_large": too_large,
            }
            title = f"File contents: {metadata['filename']}"
            description = f"RAW_CONTEXT produced by WorkspaceAgent for {task.id}. payload_inlined={not too_large}."

            artifacts_to_add[artifact_id] = Artifact(
                id=artifact_id,
                type=ArtifactType.RAW_CONTEXT,
                title=title,
                description=description,
                metadata=metadata,
                payload=payload,
            )
            print(f"  [WorkspaceAgent] Created artifact {artifact_id} (type={ArtifactType.RAW_CONTEXT.value}).")
            if too_large:
                print(f"  [WorkspaceAgent] File too large ({token_count} tokens) — payload omitted, path stored in metadata.")

    # 2. Create a STATUS artifact for the final LLM text response ONLY IF no file was read.
    # If we already created RAW_CONTEXT artifacts for file reads, we don't need a redundant STATUS artifact.
    last_msg = state["workspace_messages"][-1]
    if not isinstance(last_msg, ToolMessage) and len(artifacts_to_add) == 0:
        new_art_counter += 1
        artifact_id = f"art_{new_art_counter}"
        artifacts_to_add[artifact_id] = Artifact(
            id=artifact_id,
            type=ArtifactType.STATUS,
            title="Output of direct_response",
            description=f"Produced by WorkspaceAgent for {task.id}",
            metadata={},
            payload=last_msg.content,
        )
        print(f"  [WorkspaceAgent] Created artifact {artifact_id} (type={ArtifactType.STATUS.value}).")

    task.status = "completed"

    # 3. Clean slate for next task — remove all messages from the current task
    remove_msgs = [RemoveMessage(id=m.id) for m in state["workspace_messages"] if m.id is not None]

    return {
        "artifacts": artifacts_to_add,
        "completed_tasks": [task],
        "current_task": None,
        "artifact_counter": new_art_counter,
        "agent_steps": 0,
        "workspace_messages": remove_msgs,
        "logs": [f"WorkspaceAgent completed {task.id} -> {len(artifacts_to_add)} artifacts"],
    }

def build_workspace_subgraph():
    builder = StateGraph(GraphState)
    builder.add_node("WorkspaceAgent", workspace_agent)
    builder.add_node("WorkspaceToolNode", workspace_tool_node)
    builder.add_node("WorkspaceFinalizer", workspace_finalizer)

    builder.add_edge(START, "WorkspaceAgent")
    builder.add_conditional_edges("WorkspaceAgent", workspace_route)
    builder.add_edge("WorkspaceToolNode", "WorkspaceAgent")
    builder.add_edge("WorkspaceFinalizer", END)
    
    return builder.compile()
