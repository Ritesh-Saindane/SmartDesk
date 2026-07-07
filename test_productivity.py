import os
import sys
from dotenv import load_dotenv

# Set HEADLESS_TEST to 1 to ensure mock fallback during automated tests
os.environ["HEADLESS_TEST"] = "1"

load_dotenv()

from main import build_graph

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
        print(f"  Artifacts       : {len(final_state.get('artifacts', {}))}")
        for task in final_state.get('completed_tasks', []):
            print(f"  -> Agent used: {task.agent} | Task: {task.instruction}")
    except Exception as e:
        print(f"\n  --- TEST FAILED ---")
        print(f"  Error: {str(e)}")


def test_productivity():
    print("--- Robust Testing of Productivity Agent via Orchestrator ---")
    
    # 1. Calendar Individual Test
    run_test(
        "Calendar Operations",
        "Check my calendar for today. Then schedule a new meeting called 'Agent Review' for tomorrow. Finally, delete the event with ID 'mock_event_id'."
    )
    
    # 2. Tasks & Contacts Individual Test
    run_test(
        "Tasks & Contacts",
        "Lookup the email for Sarah in the contact book. Then create a Google Task called 'Review Sarahs Report' due tomorrow."
    )
    
    # 3. Google Docs & Telegram Individual Test
    run_test(
        "Docs & Telegram",
        "Create a Google Doc titled 'Automated Report', then append the text 'Test successful' to it. Finally, send a Telegram message saying the report is ready."
    )
    
    # 4. Google Drive Individual Test
    run_test(
        "Drive Sharing",
        "Search my Google Drive for a file named 'Project_plan' and share it with test@example.com as a reader."
    )
    
    # 5. Mixed Workflow Test (Workspace -> Productivity)
    # The Workspace Agent creates a file, reads it, then Productivity Agent acts on it.
    run_test(
        "Mixed Workflow: Poem to Email",
        "Write a short poem to a file called 'poem.txt' in my workspace. Read the poem.txt file. Then, use the Productivity Agent to lookup my manager's email in the contact book and send them the poem via email."
    )
    
if __name__ == "__main__":
    test_productivity()
