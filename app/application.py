import os
import shutil
import threading
from typing import Generator, Any
from pydantic import BaseModel

from memory import retrieve_memories, store_memories
from rag.indexer import index_chat_file, index_file, KNOWLEDGE_BASE_DIR, SUPPORTED_EXTENSIONS
from graph import build_graph
from app.initial_state import create_initial_state

# Build the graph ONCE globally and reuse it
graph = build_graph()

class ChatResult(BaseModel):
    response: str

def upload_document(file_obj, filename: str, chat_id: str = None) -> int:
    """
    Saves and indexes a document.
    If chat_id is provided, it indexes it for that specific chat.
    If chat_id is None, it indexes it globally into the knowledge_base.
    Returns the number of chunks indexed.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{ext}'")

    if chat_id:
        # Chat-specific upload
        save_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chat_uploads", f"chat_{chat_id}")
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, filename)
        
        with open(save_path, "wb") as f:
            shutil.copyfileobj(file_obj, f)
            
        return index_chat_file(save_path, chat_id)
    else:
        # Global upload
        os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
        save_path = os.path.join(KNOWLEDGE_BASE_DIR, filename)
        
        with open(save_path, "wb") as out_file:
            shutil.copyfileobj(file_obj, out_file)
            
        try:
            return index_file(save_path)
        except Exception as e:
            if os.path.exists(save_path):
                os.remove(save_path)
            raise e

def handle_query(
    *,
    user_id: str,
    chat_id: str,
    user_query: str = None,
    uploaded_documents: list[str] = None,
    chat_rag_enabled: bool = False,
    resume_action: str = None,
    auto_approve: bool = False
) -> Generator[dict, None, None]:
    """
    The main backend entry point.
    Handles memory retrieval, state initialization, streaming graph execution, 
    and asynchronous memory storage.
    
    Yields event dictionaries for the frontend to render, ending with a 'final' event containing ChatResult.
    """
    
    config = {
        "recursion_limit": 35,
        "configurable": {"thread_id": chat_id}
    }
    
    if resume_action:
        if resume_action == "reject":
            state = graph.get_state(config)
            msgs = state.values.get("productivity_messages", [])
            last_msg = msgs[-1] if msgs else None
            if last_msg and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                from langchain_core.messages import ToolMessage
                reject_msgs = [ToolMessage(content="User REJECTED this action.", tool_call_id=tc["id"], name=tc["name"]) for tc in last_msg.tool_calls]
                graph.update_state(config, {"productivity_messages": reject_msgs}, as_node="ProductivityToolNode")
        stream_generator = graph.stream(None, config=config, stream_mode="values")
    else:
        try:
            memories = retrieve_memories(user_id=user_id, query=user_query, limit=5)
        except Exception as e:
            memories = []
            yield {"type": "error", "message": f"Memory retrieval failed: {e}"}
            
        initial_state = create_initial_state(
            chat_id=chat_id,
            chat_rag_enabled=chat_rag_enabled,
            uploaded_documents=uploaded_documents or [],
            user_query=user_query,
            memories=memories
        )
        stream_generator = graph.stream(initial_state, config=config, stream_mode="values")
    
    # State tracking variables for diffing stream chunks
    MSG_KEYS = [
        ("workspace_messages", "WorkspaceAgent"),
        ("knowledge_messages", "KnowledgeAgent"),
        ("productivity_messages", "ProductivityAgent"),
    ]
    prev_task_id = None
    prev_final = False
    prev_msg_counts = {k: 0 for k, _ in MSG_KEYS}
    prev_artifact_ids: set = set()
    
    final_state = None
    
    try:
        for state in stream_generator:
            final_state = state
            
            # Orchestrator: new task assigned
            task = state.get("current_task")
            if task and task.id != prev_task_id:
                yield {"type": "task_start", "agent": task.agent, "instruction": task.instruction[:150]}
                prev_task_id = task.id
                
            # Orchestrator: finished
            if state.get("final_response") and not prev_final:
                yield {"type": "orchestrator_done"}
                prev_final = True
                
            # Agent messages: detect new tool calls & results
            for key, agent_name in MSG_KEYS:
                msgs = state.get(key, [])
                new_count = len(msgs)
                old_count = prev_msg_counts[key]
                
                if new_count > old_count:
                    for msg in msgs[old_count:]:
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            tools = [tc["name"] for tc in msg.tool_calls]
                            yield {"type": "tool_call", "agent": agent_name, "tools": tools}
                        elif hasattr(msg, "name"):
                            yield {"type": "tool_result", "name": msg.name}
                    prev_msg_counts[key] = new_count
                    
            # New artifacts created by finalizers
            arts = state.get("artifacts", {})
            new_arts = set(arts.keys()) - prev_artifact_ids
            for art_id in sorted(new_arts):
                yield {"type": "artifact", "id": art_id, "title": arts[art_id].title}
            if new_arts:
                prev_artifact_ids = set(arts.keys())
                
        current_state = graph.get_state(config)
        if current_state.next:
            if auto_approve:
                yield {"type": "auto_resume"}
                return
            msgs = current_state.values.get("productivity_messages", [])
            last_msg = msgs[-1] if msgs else None
            pending_tools = [tc["name"] for tc in last_msg.tool_calls] if (last_msg and hasattr(last_msg, "tool_calls")) else []
            yield {"type": "interrupted", "pending_tools": pending_tools}
            return
                
    except Exception as e:
        import traceback
        traceback.print_exc()
        yield {"type": "error", "message": f"Error during execution: {str(e)}"}
        return
        
    if final_state:
        response_text = final_state.get("final_response", "Task completed without a final response.")
        
        # Background Memory Storage
        # Convert full chat history to dicts for the new memory extractor
        mem_messages = []
        for m in final_state.get("messages", []):
            role = "user" if m.type == "human" else "assistant"
            mem_messages.append({"role": role, "content": m.content})
            
        threading.Thread(
            target=store_memories, 
            args=(mem_messages, user_id),
            daemon=True
        ).start()
        
        # Additional data for the expandable panel
        completed_tasks = [{"agent": t.agent, "instruction": t.instruction} for t in final_state.get("completed_tasks", [])]
        artifacts = [{"id": a_id, "title": a.title, "type": a.type.value, "description": a.description} for a_id, a in final_state.get("artifacts", {}).items()]
        
        yield {
            "type": "final",
            "result": ChatResult(response=response_text),
            "completed_tasks": completed_tasks,
            "artifacts": artifacts
        }
    else:
        yield {"type": "error", "message": "An error occurred. Please try again."}
