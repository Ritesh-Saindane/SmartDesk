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
MAX_AGENT_STEPS = 3

# =========================================================
# TOOLS
from typing import Literal

@tool
def rag_search(chat_id: str, query: str, mode: Literal["overview", "semantic"]) -> str:
    """Search the current chat's knowledge base for relevant information or summaries.

    IMPORTANT: 
    If mode == 'overview':
      - The `query` parameter should be the specific filename of the document to overview.
      - If there's only one uploaded document, you can leave it blank or pass its name.
    If mode == 'semantic':
      - Always pass the COMPLETE natural-language user question as the `query` argument.
      - Do NOT reduce the query to generic words like "document", "pdf", or "summary".
    """
    print(f"  [Tool] rag_search(chat_id={chat_id}, query={query}, mode={mode})")
    try:
        from rag.retriever import retrieve
        results = retrieve(chat_id, query, mode, k=5)
    except EnvironmentError as e:
        return f"RAG unavailable: {str(e)}"
    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"

    if not results:
        return (
            "No relevant information found in the knowledge base. "
            "The knowledge base may be empty, or try rephrasing your query."
        )
    
    # print("rag searched documents : -----> ",results)

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

    has_tool_message = any(isinstance(m, ToolMessage) for m in state["knowledge_messages"])
    
    sys_prompt = f"""You are KnowledgeAgent. You handle summarization, research, writing tasks, and document Q&A.

Task: {task.instruction}
Expected Output: {task.expected_output}
Context (artifact payloads from prior tasks): {json.dumps(context)}
Current Chat ID: {state.get("chat_id", "unknown")}
Uploaded Documents: {json.dumps(state.get("uploaded_documents", []))}

You have access to the user's personal knowledge base via the `rag_search` tool.
The documents you search are ONLY the documents uploaded in the CURRENT CHAT.
When calling `rag_search`, you MUST pass the Current Chat ID as the `chat_id` parameter.

IMPORTANT RULES FOR RETRIEVAL & INTENT:
You must classify the user's request into one of two intents before calling `rag_search`:

1. OVERVIEW MODE: Use "overview" when the user wants to understand the uploaded document as a whole.
   - Examples: "summarize the document", "explain the document", "review the document", "what is this about", "tell me what this file contains", "give me the gist", "describe this document".
   - Rule for multiple documents: If there are multiple documents uploaded and the user requests an overview WITHOUT specifying which document, DO NOT guess. DO NOT call rag_search. Instead, ask the user a clarification question listing the available documents.
   - If only one document is uploaded, or if the user specified a document, call `rag_search` with mode="overview".
   - When calling with mode="overview", pass the specific filename as the `query` parameter (or leave it blank if only one document exists).

2. SEMANTIC MODE: Use "semantic" when the user asks about specific information contained in the uploaded document.
   - Examples: "What does it say about Mumbai?", "Explain deadlocks", "What are the interview questions?", "Where is Haji Ali discussed?"
   - When calling with mode="semantic", you MUST pass the complete natural-language user question as the `query`. Do NOT reduce it to generic words like "document" or "pdf".

STRICT TOOL EXECUTION RULES:
- If no ToolMessage exists yet, decide whether retrieval is needed.
- If a ToolMessage already exists (meaning you have already received search results):
   - NEVER call `rag_search` again. Each task should invoke `rag_search` at most once.
   - Generate the final answer from the retrieved chunks.
   - If the retrieved context is insufficient, explicitly state that instead of searching again.
- Answer ONLY using the retrieved context. Do not invent facts.

If the question is clearly general knowledge (e.g., 'What is machine learning?'),
answer it directly without calling any tool.
"""

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
        description=f"Produced by KnowledgeAgent for {task.id} ,",
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
