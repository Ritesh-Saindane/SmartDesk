import os
import sys
from dotenv import load_dotenv

# Load env vars for email
load_dotenv()

# Import the tools directly from main
from main import create_event, calendar_today, send_email

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
    
    # 3. Send the schedule via email
    print("\n3. Sending email with the schedule...")
    email_body = f"Hello,\n\nHere is your schedule for today:\n{result_fetch}\n\nBest,\nSmartDesk Productivity Agent"
    result_email = send_email.invoke({
        "to": "chaitanyashinde545@gmail.com", 
        "subject": "Your Daily Schedule (Automated Test)", 
        "body": email_body
    })
    print(f"Result: {result_email}")
    
    print("\n--- Test Complete ---")

if __name__ == "__main__":
    test_productivity()
