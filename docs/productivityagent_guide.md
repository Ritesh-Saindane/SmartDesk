# SmartDesk: Productivity Agent Guide

## Overview
The **Productivity Agent** is the external communication and scheduling arm of the SmartDesk multi-agent system. While the Workspace Agent handles local files and the Knowledge Agent handles research, the Productivity Agent seamlessly integrates with Google Workspace APIs (Calendar, Tasks, Docs, Drive), Telegram, and SMTP to broadcast information and manage your life.

## Architecture
Like all SmartDesk agents, the Productivity Agent is an autonomous node within our **LangGraph** StateGraph architecture, powered by the **Groq API**. 
1. **Orchestrator Delegation:** The Orchestrator intercepts the user query. If the query involves emails, calendars, tasks, messaging, Google Docs, or Google Drive, it assigns a `Task` to the `ProductivityAgent`.
2. **Tool Execution Loop:** The Productivity Agent receives the instructions and context artifacts. It can invoke one or multiple tools in a loop.
3. **Resilient Fallback (Mock Mode):** To ensure the agent never crashes when credentials are missing, expired, or lack proper OAuth scopes, every single connector is wrapped in a `try/except` block. If the API fails, the agent automatically falls back to reading/writing local JSON files (e.g., `calendar.json`, `tasks.json`, `telegram_outbox.json`).

## Connectors & Tools

### 1. Google Calendar
- **`calendar_today()`**: Fetches today's events.
- **`create_event(title, date)`**: Schedules a new event (RFC3339 or YYYY-MM-DD).
- **`reschedule_event(event_id, new_date)`**: Updates an existing event's time.
- **`delete_event(event_id)`**: Removes an event from the calendar.

### 2. Google Tasks
- **`create_task(title, due_date)`**: Adds a task to the default task list.
- **`list_tasks()`**: Retrieves all pending tasks.

### 3. Google Docs & Drive
- **`create_doc(title, text)`**: Creates a new Google Doc and optionally populates it.
- **`read_doc(doc_id)`**: Extracts all paragraph text from a Google Doc.
- **`append_to_doc(doc_id, text)`**: Appends content to the end of a Doc.
- **`upload_to_drive(file_path, mime_type)`**: Uploads a local file to Drive.
- **`search_drive(query)`**: Uses Drive search syntax (e.g., `name contains 'Report'`) to find file IDs.
- **`share_drive_file(file_id, email, role)`**: Grants reader, commenter, or writer permissions.

### 4. Communications
- **`send_email(to, subject, body)`**: Connects via SMTP (`GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` in `.env`).
- **`send_telegram_message(text)`**: Posts to a Telegram chat (`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` in `.env`).
- **`lookup_contact(name)`**: Searches `contacts.json` for email addresses to avoid manual typing.

## How to Test

### Setup
Ensure your `.venv` is activated and packages are installed:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Authentication
If you wish to test the live Google APIs, ensure `credentials.json` is present. Delete `token.json` if you previously authenticated without Docs/Tasks scopes, and let the browser prompt you for permissions again. To test the mock fallback logic safely without triggering a browser popup, set the environment variable:
```bash
export HEADLESS_TEST=1
```

### Running the End-to-End Suite
We have built a robust testing suite in `test_productivity.py`. This script doesn't just test individual python functions; it tests the **LangGraph Orchestrator's ability to autonomously route** complex prompts to the Productivity Agent. 
Run it via:
```bash
python test_productivity.py
```

### Example Prompts for Manual Testing (via `main.py`)
To test manually, modify the `user_query` string in the `initial_state` block of `main.py`. 
* **Individual Test:** "Create a Google Doc called 'Meeting Notes' and add a reminder to my Calendar for tomorrow."
* **Mixed Workflow Test (Workspace + Productivity):** "Read the file 'Project_plan.md' from my local workspace, create a Google Doc with its contents, and send a Telegram message saying the upload is complete."
* **Contact Book Test:** "Email Sarah to let her know the tasks for today have been listed, and send me a copy of my pending Google tasks."
