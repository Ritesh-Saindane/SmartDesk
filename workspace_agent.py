import os
import json
import time
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from state import GraphState, Artifact

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
workspace_llm = ChatGroq(model=MODEL_NAME, temperature=0).bind_tools(workspace_tools)
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

Use the available tools to complete the task. You may call multiple tools if needed."""

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
    last_msg = state["workspace_messages"][-1]

    if isinstance(last_msg, ToolMessage):
        payload = last_msg.content
        tool_name = last_msg.name
    else:
        payload = last_msg.content
        tool_name = "direct_response"

    task = state["current_task"]
    new_art_counter = state["artifact_counter"] + 1
    artifact_id = f"art_{new_art_counter}"

    artifact = Artifact(
        id=artifact_id,
        type="workspace_output",
        title=f"Output of {tool_name}",
        description=f"Produced by WorkspaceAgent for {task.id}",
        payload=payload,
    )

    task.status = "completed"
    print(f"  [WorkspaceAgent] Created artifact {artifact_id}.")

    return {
        "artifacts": {artifact_id: artifact},
        "completed_tasks": [task],
        "current_task": None,
        "artifact_counter": new_art_counter,
        "agent_steps": 0,
        "logs": [f"WorkspaceAgent completed {task.id} -> {artifact_id}"],
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
