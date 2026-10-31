import os
from dotenv import load_dotenv
load_dotenv()

from productivity_agent import fetch_emails

if __name__ == "__main__":
    print("Fetching up to 3 emails (both read and unread)...")
    print("NOTE: If a browser window opens, please complete the Google OAuth login!")
    result = fetch_emails.invoke({"limit": 3, "unread_only": False})
    print("\n--- RESULTS ---")
    print(result)
