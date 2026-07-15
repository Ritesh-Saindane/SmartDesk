import json
import time
import sys
from typing import List, Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langgraph.checkpoint.memory import MemorySaver

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from langchain_core.messages import AIMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph

from state import GraphState, Task
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
    artifact_summaries = [
        {"id": a.id, "title": a.title, "description": a.description , "payload": a.payload}
        for a in state.get("artifacts", {}).values()
    ]

    prompt = f"""You are the Orchestrator of a hierarchical multi-agent AI system.
You must assign ONE task at a time to the most appropriate agent.

User Query: {state["user_query"]}

Completed Tasks (with instructions):
{json.dumps(completed, indent=2)}

Available Artifacts:
{json.dumps(artifact_summaries, indent=2)}

Strict Rules:
1. Assign exactly ONE next task to WorkspaceAgent, KnowledgeAgent, or ProductivityAgent.
2. Look at the completed task instructions carefully. If all tasks required to fulfill the user query are completed, set finished=True NOW.
3. Do NOT repeat a task type that is already completed.
4. Only assign tasks that are directly necessary to answer the user query.
5. Do NOT set finished=True if there are pending actions requested in the user query that have not been performed yet.
6. When setting finished=True, you MUST write a final_response answering the user's query using the content/payload of the completed task artifacts.
7. When you read a file, print its content in final response which you will get in payload.
8. VERY IMP : AGENT DEMARCATION (CRITICAL):
   - WorkspaceAgent: Use ONLY for local file system operations (read, write, search files/folders) when the user specifies a path or wants to modify local files. Do NOT use this for answering questions about uploaded documents.
   - KnowledgeAgent: Use ONLY for searching the knowledge base via RAG and answering knowledge questions. If the user asks about an "uploaded document", "uploaded file", "knowledge base", or asks a question that requires searching document contents, route it HERE.
   - ProductivityAgent: Use ONLY for external APIs: Emails, Google Calendar, Tasks, Google Docs, Drive, Telegram, Contacts. If the user asks to "draft an email" or "send an email", route it HERE, never to WorkspaceAgent.
9. When instructing the ProductivityAgent to upload a file to Google Drive, you MUST provide the literal local file_path (e.g. './folder/file.txt'). Do not just provide the text content.
10. Decide between WorkspaceAgent and KnowledgeAgent carefully.
- Use WorkspaceAgent when the user explicitly asks to operate on a local file system file (e.g. read README.md, delete notes.txt, create report.pdf).
- Use KnowledgeAgent when the user asks questions about the contents of their documents (e.g. "what is in the uploaded doc?", "summarize my knowledge base"). The KnowledgeAgent has access to semantic search (RAG) over the user's uploaded documents.

Examples:
- "What do my notes say about LangGraph?"
- "Explain normalization from my DBMS notes."
- "Have I written anything about vector databases?"
- "Summarize my AI research papers."
- "What does my resume mention about machine learning?"

When in doubt, prefer the KnowledgeAgent for semantic document questions rather than WorkspaceAgent.
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

# checkpointer = MemorySaver()

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

    return builder.compile()

# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    graph = build_graph()

    initial_state: GraphState = {
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

    final_state = graph.invoke(initial_state, config={"recursion_limit": 35})

    print("\n=========================================================")
    print("  GRAPH FINISHED")
    print(f"  Final Response  : {final_state.get('final_response')}")
    print(f"  Tasks Completed : {len(final_state.get('completed_tasks', []))}")
    print(f"  Artifacts       : {len(final_state.get('artifacts', {}))}")
    print("=========================================================")
