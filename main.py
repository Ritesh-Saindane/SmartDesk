import json
import time
import sys
from typing import List, Literal, Optional
import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langgraph.checkpoint.postgres import PostgresSaver

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from langchain_core.messages import AIMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph

from state import GraphState, Task, ArtifactType
from workspace_agent import build_workspace_subgraph
from knowledge_agent import build_knowledge_subgraph
from productivity_agent import build_productivity_subgraph

load_dotenv()
MODEL_NAME = "openai/gpt-oss-120b"

# =========================================================
# PYDANTIC MODELS (Orchestrator specific)
# =========================================================

class OrchestratorTask(BaseModel):
    agent: Literal["WorkspaceAgent", "KnowledgeAgent", "ProductivityAgent"]
    instruction: str
    context_artifacts: List[str] = Field(default_factory=list)
    expected_output: str

class OrchestratorDecision(BaseModel):
    finished: bool = Field(..., description="True if the user query is fully resolved.")
    task: Optional[OrchestratorTask] = Field(
        None, description="The single next task to assign."
    )
    final_response: Optional[str] = Field(
        None, description="Final message to user when finished."
    )

orchestrator_llm = ChatGroq(model=MODEL_NAME, temperature=0).with_structured_output(
    OrchestratorDecision
)

# =========================================================
# ORCHESTRATOR
# =========================================================

def orchestrator(state: GraphState) -> dict:
    print("\n--- [Orchestrator] Deciding next step ---")

    # print(f" State messages : {state['messages']}")

    time.sleep(3)

    completed = [
        {"id": t.id, "agent": t.agent, "status": t.status, "instruction": t.instruction}
        for t in state.get("completed_tasks", [])
    ]

    # ── Build artifact summaries for the Orchestrator prompt ───────────────────
    # RAW_CONTEXT payloads are intentionally omitted for large documents to
    # avoid exceeding LLM context limits while preserving planning ability.
    # Use metadata["payload_inlined"] as the authoritative signal — never
    # check `if artifact.payload:` directly to decide what to include.
    # For all other artifact types (SUMMARY, ANSWER, STATUS, etc.), always
    # include the payload so the Orchestrator can reason over the result.
    artifact_summaries = []
    for a in state.get("artifacts", {}).values():
        summary = {
            "id": a.id,
            "type": a.type,
            "title": a.title,
            "description": a.description,
            "metadata": a.metadata,
        }
        if a.type == ArtifactType.RAW_CONTEXT:
            # Only inline if the metadata flag explicitly says so.
            if a.metadata.get("payload_inlined") == True:
                summary["payload"] = a.payload
            # else: payload intentionally omitted — Orchestrator uses metadata instead
        else:
            # SUMMARY, ANSWER, STATUS, etc. always expose their payload.
            summary["payload"] = a.payload
        artifact_summaries.append(summary)

    chat_history_str = ""
    for m in state.get("messages", []):
        role = "User" if m.type == "human" else "Assistant"
        chat_history_str += f"{role}: {m.content}\n"

    prompt = f"""You are the Orchestrator of a hierarchical multi-agent AI system.
You must assign ONE task at a time to the most appropriate agent.

Conversation History:
{chat_history_str}
User Query: {state["user_query"]}

Current Chat Uploads:
{json.dumps(state.get("uploaded_documents", []), indent=2)}

Completed Tasks (with instructions):
{json.dumps(completed, indent=2)}

Available Artifacts:
{json.dumps(artifact_summaries, indent=2)}

Strict Rules:
1. Assign exactly ONE next task to WorkspaceAgent, KnowledgeAgent, or ProductivityAgent.
2. Look at the completed task instructions carefully. If all tasks required to fulfill the user query are completed, set finished=True NOW.
3. Do NOT repeat a task type that is already completed.
4. Only assign tasks that are directly necessary to answer the user query.
4a. ONE FILE PER TASK (CRITICAL for WorkspaceAgent reads):
   Each WorkspaceAgent task must read AT MOST ONE file. If the user asks to
   read or summarize multiple files (e.g. "read a.txt and b.txt"), you MUST
   create a separate task for each file. Reading multiple files in one task
   causes content loss because only one artifact is created per task.
   Example — user says "read summary.txt and mumbai.txt":
     task_1: WorkspaceAgent → read summary.txt
     task_2: WorkspaceAgent → read mumbai.txt
     task_3 (if needed): Orchestrator uses both artifacts to respond.
5. Do NOT set finished=True if there are pending actions requested in the user query that have not been performed yet.
6. When setting finished=True, you MUST write a final_response answering the user's query using the content/payload of the completed task artifacts.
7. When you read a file, print its content in final response which you will get in payload.
8. VERY IMP : AGENT DEMARCATION (CRITICAL):
   - WorkspaceAgent: Use ONLY for local file system operations (read, write, search files/folders) when the user specifies a path or wants to modify local files. Do NOT use this for answering questions about uploaded documents.
   - KnowledgeAgent: If chat_rag_enabled == True ({state.get('chat_rag_enabled', False)}) and the user asks a question that may require information from the uploaded documents, route the task HERE. 
   - ProductivityAgent: Use ONLY for external APIs: Emails, Google Calendar, Tasks, Google Docs, Drive, Telegram, Contacts. If the user asks to "draft an email" or "send an email", route it HERE, never to WorkspaceAgent.
9. When instructing the ProductivityAgent to upload a file to Google Drive, you MUST provide the literal local file_path (e.g. './folder/file.txt'). Do not just provide the text content.
10. Decide between WorkspaceAgent and KnowledgeAgent carefully.
- Use WorkspaceAgent when the user explicitly asks to operate on a local file system file (e.g. read README.md, delete notes.txt, create report.pdf).
- Use KnowledgeAgent when the user asks questions about the contents of their current chat uploads. The KnowledgeAgent has access to semantic search (RAG) over the documents uploaded in this chat.

Examples:
- "What do my notes say about LangGraph?"
- "Explain normalization from my DBMS notes."
- "Have I written anything about vector databases?"
- "Summarize my AI research papers."
- "What does my resume mention about machine learning?"

When in doubt, prefer the KnowledgeAgent for semantic document questions rather than WorkspaceAgent.

11. LARGE DOCUMENT HANDLING:
If a raw_context artifact has metadata.payload_inlined=False, the file content was too
large to read inline. In this case:

  a) If the user's intent requires reasoning over the document (summarize, Q&A, extract, etc.):
     Set finished=True immediately. Write a final_response telling the user:
       "The file '[filename]' is too large to read directly (estimated [token_count] tokens).
        To summarize or query it, please upload it using the 📎 upload button in this chat."
     Do NOT route to KnowledgeAgent. The file is a local file and is NOT in the chat
     knowledge base, so KnowledgeAgent cannot access it.

  b) If the user's intent does NOT require reading the content (e.g. "upload to Drive"):
     Continue the workflow normally. Use metadata["path"] to pass the file path to
     ProductivityAgent or another appropriate agent.

12. ANTI-LOOP RULES (CRITICAL):

Rule 12a — Never re-read a file already captured as a raw_context artifact.
  If a raw_context artifact already exists for a filename/path, DO NOT assign
  WorkspaceAgent to read that file again. The read is done. Use artifact metadata.

Rule 12b — If more than 2 tasks completed without resolving the user query,
  set finished=True with the best available explanation rather than looping.
"""

    decision: OrchestratorDecision = orchestrator_llm.invoke(
        [SystemMessage(content=prompt)]
    )

    if decision.finished or decision.task is None:
        final_msg = decision.final_response or "All tasks completed successfully."
        print("  [Orchestrator] All done. Final response ready.")
        return {"final_response": final_msg , "messages": [AIMessage(content=final_msg)]}

    new_task_counter = state["task_counter"] + 1
    new_task = Task(
        id=f"task_{new_task_counter}",
        agent=decision.task.agent,
        instruction=decision.task.instruction,
        context_artifacts=decision.task.context_artifacts,
        expected_output=decision.task.expected_output,
        status="pending",
    )
    print(f"  [Orchestrator] Assigned {new_task.id} -> {new_task.agent}")
    return {
        "current_task": new_task,
        "task_counter": new_task_counter,
        "agent_steps": 0,
        "logs": [f"Orchestrator -> {new_task.agent}: {new_task.id}"],
    }

def orchestrator_route(state: GraphState) -> str:
    if state.get("final_response"):
        return END
    task = state.get("current_task")
    if task is None:
        return END
    return task.agent

# =========================================================
# BUILD GRAPH
# =========================================================
import atexit

DB_URI = os.getenv("DB_URI")

checkpointer_cm = PostgresSaver.from_conn_string(DB_URI)
checkpointer = checkpointer_cm.__enter__()
checkpointer.setup()

def cleanup_checkpointer():
    print("Closing PostgresSaver connection pool...")
    checkpointer_cm.__exit__(None, None, None)

atexit.register(cleanup_checkpointer)

def get_all_existing_threads():
    all_threads = set()
    for checkpoint in checkpointer.list(None):
        all_threads.add(checkpoint.config["configurable"]["thread_id"])
    return list(all_threads)

def build_graph():
    builder = StateGraph(GraphState)

    # ── Nodes ────────────────────────────────────────────
    builder.add_node("Orchestrator", orchestrator)

    # Register subgraphs instead of flat nodes
    builder.add_node("WorkspaceAgent", build_workspace_subgraph())
    builder.add_node("KnowledgeAgent", build_knowledge_subgraph())
    builder.add_node("ProductivityAgent", build_productivity_subgraph())

    # ── Entry ─────────────────────────────────────────────
    builder.add_edge(START, "Orchestrator")

    # ── Orchestrator routes to one agent (or END) ─────────
    builder.add_conditional_edges("Orchestrator", orchestrator_route)

    # ── Subgraph Returns ───────────────────────────────────
    builder.add_edge("WorkspaceAgent", "Orchestrator")
    builder.add_edge("KnowledgeAgent", "Orchestrator")
    builder.add_edge("ProductivityAgent", "Orchestrator")

    return builder.compile(checkpointer=checkpointer)

# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    graph = build_graph()

    initial_state: GraphState = {
        "chat_id": "cli_test_chat",
        "chat_rag_enabled": False,
        "uploaded_documents": [],
        "user_query": "",
        "messages": [],
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
    }
    
    print("=========================================================")
    print("  MULTI-AGENT LANGGRAPH — EXPLICIT NODES & TOOL LOOPS")
    print("=========================================================")

    final_state = graph.invoke(initial_state, config={
        "recursion_limit": 35,
        "configurable": {"thread_id": "cli_test_chat"}
    })

    print("\n=========================================================")
    print("  GRAPH FINISHED")
    print(f"  Final Response  : {final_state.get('final_response')}")
    print(f"  Tasks Completed : {len(final_state.get('completed_tasks', []))}")
    print(f"  Artifacts       : {len(final_state.get('artifacts', {}))}")
    print("=========================================================")
