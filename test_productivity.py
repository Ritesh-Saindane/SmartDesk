import os
import sys
from dotenv import load_dotenv

# Load env vars for email
load_dotenv()

# Import the tools directly from main
from main import (
    create_event, calendar_today, send_email, create_task, list_tasks, 
    upload_to_drive, search_drive, send_telegram_message, create_doc, 
    read_doc, append_to_doc, reschedule_event, delete_event, share_drive_file,
    lookup_contact
)

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

    # 4. Test Drive & Advanced Drive
    print("\n4. Testing Google Drive...")
    with open("test_upload.txt", "w") as f:
        f.write("This is a test upload for Google Drive connector.")
    result_upload = upload_to_drive.invoke({"file_path": "test_upload.txt", "mime_type": "text/plain"})
    print(f"Upload Drive Result: {result_upload}")
    os.remove("test_upload.txt")
    
    result_search_drive = search_drive.invoke({"query": "name contains 'test_upload'"})
    print(f"Search Drive Result: {result_search_drive}")
    
    # Using a dummy ID to test sharing (it will mock fall back)
    result_share = share_drive_file.invoke({"file_id": "dummy_id", "email": "test@example.com"})
    print(f"Share Drive Result: {result_share}")

    # 4b. Test Telegram
    print("\n4b. Testing Telegram...")
    result_telegram = send_telegram_message.invoke({"text": "Hello from SmartDesk Automated Test!"})
    print(f"Telegram Result: {result_telegram}")

    # 4c. Test Docs
    print("\n4c. Testing Google Docs...")
    result_create_doc = create_doc.invoke({"title": "Test Doc", "text": "Initial text."})
    print(f"Create Doc Result: {result_create_doc}")
    # We parse the mock ID for testing (e.g. mock_1) if not real ID, let's just append to mock_1
    result_append_doc = append_to_doc.invoke({"doc_id": "mock_1", "text": "Appended text."})
    print(f"Append Doc Result: {result_append_doc}")
    result_read_doc = read_doc.invoke({"doc_id": "mock_1"})
    print(f"Read Doc Result: {result_read_doc}")

    # 4d. Test Advanced Calendar
    print("\n4d. Testing Advanced Calendar...")
    reschedule_time = (dt.datetime.utcnow() + dt.timedelta(hours=2)).isoformat() + "Z"
    result_reschedule = reschedule_event.invoke({"event_id": "mock_event_id", "new_date": reschedule_time})
    print(f"Reschedule Result: {result_reschedule}")
    result_delete = delete_event.invoke({"event_id": "mock_event_id"})
    print(f"Delete Result: {result_delete}")

    # 4e. Test Contact Book
    print("\n4e. Testing Contact Book...")
    result_contact = lookup_contact.invoke({"name": "sarah"})
    print(f"Contact Result: {result_contact}")

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

