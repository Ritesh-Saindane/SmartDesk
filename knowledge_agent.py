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
def rag_search(query: str) -> str:
    """Search the knowledge base for relevant information using semantic similarity.

    Use this tool whenever:
    - The user asks about a document they have uploaded.
    - The question might be answerable from user-provided files in the knowledge base.
    - You are unsure whether the knowledge base contains relevant information
      (it is better to check than to guess).

    Do NOT use this tool for general knowledge questions (e.g. 'What is Python?')
    unless the user explicitly says the answer is in their documents.
    """
    print(f"  [Tool] rag_search({query})")
    try:
        from rag.retriever import retrieve
        results = retrieve(query, k=5)
    except EnvironmentError as e:
        return f"RAG unavailable: {str(e)}"
    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"

    if not results:
        return (
            "No relevant information found in the knowledge base. "
            "The knowledge base may be empty, or try rephrasing your query."
        )

    formatted: list[str] = []
    for i, r in enumerate(results, 1):
        formatted.append(
            f"[Chunk {i}] Source: {r['filename']} (chunk #{r['chunk_index']})\n"
            f"{r['text']}"
        )

    print("rag searched documents : -----> ",formatted)
    return "\n\n---\n\n".join(formatted)

knowledge_tools = [rag_search]
knowledge_llm = ChatGroq(model=MODEL_NAME, temperature=0).bind_tools(knowledge_tools)
knowledge_tool_node = ToolNode(knowledge_tools, messages_key="knowledge_messages")

# =========================================================
# AGENT LOGIC
# =========================================================

def knowledge_agent(state: GraphState) -> dict:
    task = state["current_task"]
    print(f"\n--- [KnowledgeAgent] Executing {task.id} ---")

    context = {
        aid: state["artifacts"][aid].payload
        for aid in task.context_artifacts
        if aid in state["artifacts"]
    }

    sys_prompt = f"""You are KnowledgeAgent. You handle summarization, research, writing tasks, and document Q&A.

Task: {task.instruction}
Expected Output: {task.expected_output}
Context (artifact payloads from prior tasks): {json.dumps(context)}

You have access to the user's personal knowledge base via the `rag_search` tool.
Use `rag_search` whenever:
- The user asks about a document, file, or topic they may have uploaded.
- The question is specific enough that a personal knowledge base might contain the answer.
- You are unsure — it is always better to check the knowledge base than to guess.

If the question is clearly general knowledge (e.g., 'What is machine learning?'),
answer it directly without calling any tool.

You may call multiple tools if needed to fully complete the task."""

    if state["agent_steps"] == 0:
        messages = [SystemMessage(content=sys_prompt)]
    else:
        messages = [SystemMessage(content=sys_prompt)] + state["knowledge_messages"]

    time.sleep(2)
    response = knowledge_llm.invoke(messages)

    if response.tool_calls:
        print(f"  [KnowledgeAgent] Tool calls: {[tc['name'] for tc in response.tool_calls]}")
    else:
        print("  [KnowledgeAgent] Done — no more tool calls.")

    return {"knowledge_messages": [response], "agent_steps": state["agent_steps"] + 1}

def knowledge_route(state: GraphState) -> str:
    if state["agent_steps"] >= MAX_AGENT_STEPS:
        print("  [KnowledgeAgent] Max steps reached, forcing finalize.")
        return "KnowledgeFinalizer"
    last_msg = state["knowledge_messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "KnowledgeToolNode"
    return "KnowledgeFinalizer"

def knowledge_finalizer(state: GraphState) -> dict:
    print("  [KnowledgeAgent] Finalizing task.")
    last_msg = state["knowledge_messages"][-1]

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
        type="knowledge_output",
        title=f"Output of {tool_name}",
        description=f"Produced by KnowledgeAgent for {task.id}",
        payload=payload,
    )

    task.status = "completed"
    print(f"  [KnowledgeAgent] Created artifact {artifact_id}.")

    return {
        "artifacts": {artifact_id: artifact},
        "completed_tasks": [task],
        "current_task": None,
        "artifact_counter": new_art_counter,
        "agent_steps": 0,
        "logs": [f"KnowledgeAgent completed {task.id} -> {artifact_id}"],
    }

def build_knowledge_subgraph():
    builder = StateGraph(GraphState)
    builder.add_node("KnowledgeAgent", knowledge_agent)
    builder.add_node("KnowledgeToolNode", knowledge_tool_node)
    builder.add_node("KnowledgeFinalizer", knowledge_finalizer)

    builder.add_edge(START, "KnowledgeAgent")
    builder.add_conditional_edges("KnowledgeAgent", knowledge_route)
    builder.add_edge("KnowledgeToolNode", "KnowledgeAgent")
    builder.add_edge("KnowledgeFinalizer", END)
    
    return builder.compile()
