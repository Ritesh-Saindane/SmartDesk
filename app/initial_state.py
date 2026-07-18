from langchain_core.messages import HumanMessage
from state import GraphState

def create_initial_state(
    chat_id: str,
    chat_rag_enabled: bool,
    uploaded_documents: list[str],
    user_query: str,
    memories: list
) -> GraphState:
    """
    Builds the initial GraphState dict for a new user query.
    """
    return {
        "chat_id": chat_id,
        "chat_rag_enabled": chat_rag_enabled,
        "uploaded_documents": uploaded_documents,
        "user_query": user_query,
        "messages": [HumanMessage(content=user_query)],
        "workspace_messages": [],
        "knowledge_messages": [],
        "productivity_messages": [],
        "current_task": None,
        "completed_tasks": [],
        "artifacts": {},
        "logs": [],
        "final_response": None,
        "task_counter": 0,
        "artifact_counter": 0,
        "agent_steps": 0,
        "long_term_memory": memories,
    }
