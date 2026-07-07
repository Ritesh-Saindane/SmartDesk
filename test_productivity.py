import os
import sys
from dotenv import load_dotenv

# Load env vars for email
load_dotenv()

# Import the tools directly from main
from main import create_event, calendar_today, send_email, create_task, list_tasks, upload_to_drive, search_drive

def test_productivity():
    print("--- Testing Productivity Connectors ---")
    
    # 1. Create a dummy event
    print("\n1. Creating dummy event in Google Calendar...")
    import datetime as dt
    # Schedule an event 1 hour from now to ensure it's "today"
    event_time = (dt.datetime.utcnow() + dt.timedelta(hours=1)).isoformat() + "Z"
    result_create = create_event.invoke({"title": "SmartDesk Automated Test Meeting", "date": event_time})
    print(f"Result: {result_create}")
    
    # 2. Fetch today's schedule
    print("\n2. Fetching today's calendar events...")
    result_fetch = calendar_today.invoke({})
    print(f"Result: {result_fetch}")
    
    # 3. Test Tasks
    print("\n3. Testing Google Tasks...")
    task_time = (dt.datetime.utcnow() + dt.timedelta(days=1)).isoformat() + "Z"
    result_create_task = create_task.invoke({"title": "Review SmartDesk Documentation", "due_date": task_time})
    print(f"Create Task Result: {result_create_task}")
    result_list_tasks = list_tasks.invoke({})
    print(f"List Tasks Result: {result_list_tasks}")

    # 4. Test Drive
    print("\n4. Testing Google Drive...")
    # Create a temporary file to upload
    with open("test_upload.txt", "w") as f:
        f.write("This is a test upload for Google Drive connector.")
    result_upload = upload_to_drive.invoke({"file_path": "test_upload.txt", "mime_type": "text/plain"})
    print(f"Upload Drive Result: {result_upload}")
    os.remove("test_upload.txt")
    result_search_drive = search_drive.invoke({"query": "name contains 'test_upload'"})
    print(f"Search Drive Result: {result_search_drive}")

    # 5. Send the schedule via email
    print("\n5. Sending email with the schedule...")
    email_body = f"Hello,\n\nHere is your schedule for today:\n{result_fetch}\n\nTasks:\n{result_list_tasks}\n\nDrive Activity:\n{result_upload}\n\nBest,\nSmartDesk Productivity Agent"
    result_email = send_email.invoke({
        "to": "chaitanyashinde545@gmail.com", 
        "subject": "Your Daily Schedule & Updates (Automated Test)", 
        "body": email_body
    })
    print(f"Result: {result_email}")
    
    print("\n--- Test Complete ---")

if __name__ == "__main__":
    test_productivity()

