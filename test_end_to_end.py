import os
import sys
from dotenv import load_dotenv

# Set HEADLESS_TEST to 1 to ensure mock fallback during automated tests
os.environ["HEADLESS_TEST"] = "1"

load_dotenv()

from main import build_graph, refresh_knowledge_base

def run_test(test_name, query):
    print(f"\n=========================================================")
    print(f"  TEST: {test_name}")
    print(f"  QUERY: {query}")
    print(f"=========================================================")
    
    graph = build_graph()
    initial_state = {
        "user_query": query,
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
    
    try:
        final_state = graph.invoke(initial_state, config={"recursion_limit": 50})
        print("\n  --- TEST COMPLETE ---")
        print(f"  Final Response  : {final_state.get('final_response')}")
        print(f"  Tasks Completed : {len(final_state.get('completed_tasks', []))}")
        for task in final_state.get('completed_tasks', []):
            print(f"  -> Agent used: {task.agent} | Task: {task.instruction}")
    except Exception as e:
        print(f"\n  --- TEST FAILED ---")
        print(f"  Error: {str(e)}")


def test_suite():
    print("--- Initializing Knowledge Base for Tests ---")
    refresh_knowledge_base.invoke({})
    
    print("\n--- Running End-to-End Test Suite ---")
    
    # 1. Workspace Agent Test
    run_test(
        "Workspace Operations",
        "Create a folder called 'TestOutput', write a file named 'hello.txt' inside it containing 'Hello World', and then read it back."
    )
    
    # 2. Knowledge Agent (RAG) Test
    run_test(
        "Knowledge RAG Search",
        "Search the knowledge base for 'DBMS' or 'Operating Systems' and summarize what you find."
    )
    
    # 3. Productivity Agent Test
    run_test(
        "Productivity Routing",
        "Check my calendar for today, then draft an email to boss@example.com saying I will be late. Do not use the workspace agent."
    )
    
    # 4. End-to-End Mixed Workflow
    run_test(
        "Mixed End-to-End Workflow",
        "Read 'hello.txt' from the 'TestOutput' folder. Use the knowledge agent to search the knowledge base for 'architecture'. Then, use the productivity agent to create a Google Doc summarizing both the file contents and the RAG search results, and send a Telegram message when done."
    )
    
if __name__ == "__main__":
    test_suite()
