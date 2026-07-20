import os
import json
import time
import requests
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, ToolMessage, RemoveMessage
from langchain_core.tools import tool
from llm_factory import get_llm
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from state import GraphState, Artifact, ArtifactType

load_dotenv()
MODEL_NAME = "openai/gpt-oss-120b"
MAX_AGENT_STEPS = 5

# =========================================================
# TOOLS
# =========================================================

@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to the specified recipient using Gmail SMTP if credentials exist, else mock it."""
    import smtplib
    from datetime import datetime
    from email.message import EmailMessage
    print(f"  [Tool] send_email(to={to})")
    sender_email = os.getenv("GMAIL_ADDRESS", "smartdeskgenai@gmail.com")
    app_password = os.getenv("GMAIL_APP_PASSWORD")

    if app_password:
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = sender_email
            msg["To"] = to
            msg.set_content(body)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender_email, app_password)
                server.send_message(msg)
            return f"Email successfully sent to {to} via SMTP."
        except Exception as e:
            return f"Error sending email via SMTP: {str(e)}"
    else:
        try:
            outbox_file = "email_outbox.json"
            emails = []
            if os.path.exists(outbox_file):
                with open(outbox_file, "r") as f:
                    emails = json.load(f)
            emails.append({
                "to": to,
                "subject": subject,
                "body": body,
                "timestamp": datetime.now().isoformat(),
            })
            with open(outbox_file, "w") as f:
                json.dump(emails, f, indent=4)
            return f"Email mock-queued to {to}. (Set GMAIL_APP_PASSWORD in .env for real sending)"
        except Exception as e:
            return f"Error mock-sending email: {str(e)}"

def get_google_credentials():
    import os.path
    import json
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.exceptions import RefreshError

    SCOPES = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/tasks",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/gmail.readonly"
    ]
    creds = None
    if os.path.exists("token.json"):
        try:
            with open("token.json", "r") as f:
                token_data = json.load(f)
            token_scopes = token_data.get("scopes", [])
            if not all(s in token_scopes for s in SCOPES):
                print("  [Auth] Scopes updated. Forcing re-authentication.")
                os.remove("token.json")
                creds = None
            else:
                creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        except Exception:
            pass

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                return None
        elif os.path.exists("credentials.json"):
            if os.environ.get("HEADLESS_TEST") == "1":
                return None
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
            with open("token.json", "w") as token:
                token.write(creds.to_json())
        else:
            return None
    return creds

def get_google_service(name, version):
    try:
        from googleapiclient.discovery import build
        creds = get_google_credentials()
        if creds:
            return build(name, version, credentials=creds)
    except ImportError:
        pass
    return None

@tool
def calendar_today() -> str:
    """Get today's calendar events."""
    print("  [Tool] calendar_today()")
    try:
        service = get_google_service("calendar", "v3")
        if service:
            import datetime as dt
            now = dt.datetime.utcnow().isoformat() + "Z"
            end_of_day = (dt.datetime.utcnow() + dt.timedelta(days=1)).isoformat() + "Z"
            events_result = service.events().list(
                calendarId="primary", timeMin=now, timeMax=end_of_day,
                singleEvents=True, orderBy="startTime"
            ).execute()
            events = events_result.get("items", [])
            if not events:
                return "No upcoming events found for today (Google Calendar)."
            today_events = []
            for e in events:
                start = e["start"].get("dateTime", e["start"].get("date"))
                today_events.append(f"{start} - {e['summary']} - {e['description']}")
            return " | ".join(today_events)

        calendar_file = "calendar.json"
        if not os.path.exists(calendar_file):
            return "No events scheduled for today (Mock)."
        with open(calendar_file, "r") as f:
            events = json.load(f)
        today_events = [f"{e['date']} - {e['title']}" for e in events]
        if not today_events:
            return "No events scheduled for today (Mock)."
        return " | ".join(today_events)
    except Exception as e:
        return f"Error reading calendar: {str(e)}"

@tool
def create_event(title: str, date: str) -> str:
    """Create a calendar event with a title and date."""
    print(f"  [Tool] create_event({title}, {date})")
    try:
        service = get_google_service("calendar", "v3")
        if service:
            if "T" in date:
                time_dict = {"dateTime": date}
            else:
                time_dict = {"date": date}
            event = {"summary": title, "start": time_dict, "end": time_dict}
            event_result = service.events().insert(calendarId="primary", body=event).execute()
            return f"Event '{title}' scheduled on {date} (Google Calendar ID: {event_result.get('id')})"

        calendar_file = "calendar.json"
        events = []
        if os.path.exists(calendar_file):
            with open(calendar_file, "r") as f:
                events = json.load(f)
        events.append({"title": title, "date": date})
        with open(calendar_file, "w") as f:
            json.dump(events, f, indent=4)
        return f"Event '{title}' mock-scheduled on {date}. (Need token.json for real Calendar)"
    except Exception as e:
        return f"Error creating event: {str(e)}"

@tool
def create_task(title: str, due_date: str = None) -> str:
    """Create a task in Google Tasks."""
    print(f"  [Tool] create_task({title}, {due_date})")
    try:
        service = get_google_service("tasks", "v1")
        if service:
            task = {"title": title}
            if due_date:
                task["due"] = due_date
            result = service.tasks().insert(tasklist="@default", body=task).execute()
            return f"Task '{title}' created (Google Tasks ID: {result.get('id')})"
        
        tasks_file = "tasks.json"
        tasks = []
        if os.path.exists(tasks_file):
            with open(tasks_file, "r") as f:
                tasks = json.load(f)
        tasks.append({"title": title, "due": due_date})
        with open(tasks_file, "w") as f:
            json.dump(tasks, f, indent=4)
        return f"Task '{title}' mock-created. (Need token.json for real Tasks)"
    except Exception as e:
        return f"Error creating task: {str(e)}"

@tool
def list_tasks() -> str:
    """List pending tasks from Google Tasks."""
    print("  [Tool] list_tasks()")
    try:
        service = get_google_service("tasks", "v1")
        if service:
            results = service.tasks().list(tasklist="@default", showCompleted=False).execute()
            items = results.get("items", [])
            if not items:
                return "No pending tasks found."
            return " | ".join([f"{t.get('title')} (Due: {t.get('due', 'None')})" for t in items])
        
        tasks_file = "tasks.json"
        if not os.path.exists(tasks_file):
            return "No tasks found (Mock)."
        with open(tasks_file, "r") as f:
            tasks = json.load(f)
        return " | ".join([f"{t['title']} (Due: {t.get('due', 'None')})" for t in tasks])
    except Exception as e:
        return f"Error reading tasks: {str(e)}"

@tool
def upload_to_drive(file_path: str, mime_type: str | None = None, target_mime_type: str | None = None) -> str:
    """Upload a local file to Google Drive.
    If you want to convert the file to a Google Doc, pass target_mime_type="application/vnd.google-apps.document".
    If you want to convert to Google Sheets, pass target_mime_type="application/vnd.google-apps.spreadsheet".
    """
    print(f"  [Tool] upload_to_drive({file_path})")
    try:
        if not os.path.exists(file_path):
            return f"Error: File does not exist -> {file_path}"
        service = get_google_service("drive", "v3")
        if service:
            from googleapiclient.http import MediaFileUpload
            file_name = os.path.basename(file_path)
            file_metadata = {"name": file_name}
            if target_mime_type:
                file_metadata["mimeType"] = target_mime_type
            media = MediaFileUpload(file_path, mimetype=mime_type)
            result = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
            return f"File '{file_name}' uploaded to Drive (ID: {result.get('id')})"
        return f"Mock: File '{file_path}' ready to be uploaded. (Need token.json for real Drive)"
    except Exception as e:
        return f"Error uploading to Drive: {str(e)}"

@tool
def search_drive(query: str) -> str:
    """Search for files in Google Drive."""
    print(f"  [Tool] search_drive({query})")
    try:
        service = get_google_service("drive", "v3")
        if service:
            results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
            items = results.get("files", [])
            if not items:
                return "No files found in Drive."
            return " | ".join([f"{f['name']} (ID: {f['id']})" for f in items])
        return "Mock: Searched Drive. (Need token.json for real Drive)"
    except Exception as e:
        return f"Error searching Drive: {str(e)}"

@tool
def send_telegram_message(text: str) -> str:
    """Send a message via Telegram bot."""
    print("  [Tool] send_telegram_message(...)")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {"chat_id": chat_id, "text": text}
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                return "Telegram message sent successfully."
            else:
                return f"Error sending Telegram message: {response.text}"
        except Exception as e:
            return f"Error: {str(e)}"
    try:
        outbox_file = "telegram_outbox.json"
        messages = []
        if os.path.exists(outbox_file):
            with open(outbox_file, "r") as f:
                messages = json.load(f)
        from datetime import datetime
        messages.append({"text": text, "timestamp": datetime.now().isoformat()})
        with open(outbox_file, "w") as f:
            json.dump(messages, f, indent=4)
        return "Message mock-queued to Telegram. (Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env for real sending)"
    except Exception as e:
        return f"Error mock-sending Telegram message: {str(e)}"

@tool
def create_doc(title: str, text: str = "") -> str:
    """Create a new Google Doc."""
    print(f"  [Tool] create_doc({title})")
    try:
        service = get_google_service("docs", "v1")
        if service:
            doc = service.documents().create(body={"title": title}).execute()
            doc_id = doc.get("documentId")
            if text:
                requests_list = [{"insertText": {"location": {"index": 1}, "text": text}}]
                service.documents().batchUpdate(documentId=doc_id, body={"requests": requests_list}).execute()
            return f"Google Doc '{title}' created (ID: {doc_id})"
        docs_file = "docs_mock.json"
        docs = {}
        if os.path.exists(docs_file):
            with open(docs_file, "r") as f:
                docs = json.load(f)
        doc_id = f"mock_{len(docs)+1}"
        docs[doc_id] = {"title": title, "text": text}
        with open(docs_file, "w") as f:
            json.dump(docs, f, indent=4)
        return f"Google Doc '{title}' mock-created (ID: {doc_id}). (Need token.json for real Docs)"
    except Exception as e:
        return f"Error creating doc: {str(e)}"

@tool
def read_doc(doc_id: str) -> str:
    """Read the text content of a Google Doc."""
    print(f"  [Tool] read_doc({doc_id})")
    try:
        service = get_google_service("docs", "v1")
        if service:
            doc = service.documents().get(documentId=doc_id).execute()
            content = ""
            for element in doc.get("body").get("content"):
                if "paragraph" in element:
                    for p_element in element.get("paragraph").get("elements"):
                        if "textRun" in p_element:
                            content += p_element.get("textRun").get("content")
            return content
        docs_file = "docs_mock.json"
        if os.path.exists(docs_file):
            with open(docs_file, "r") as f:
                docs = json.load(f)
            if doc_id in docs:
                return docs[doc_id].get("text", "")
        return f"Error: Mock Doc '{doc_id}' not found."
    except Exception as e:
        return f"Error reading doc: {str(e)}"

@tool
def append_to_doc(doc_id: str, text: str) -> str:
    """Append text to the end of an existing Google Doc."""
    print(f"  [Tool] append_to_doc({doc_id})")
    try:
        service = get_google_service("docs", "v1")
        if service:
            doc = service.documents().get(documentId=doc_id).execute()
            end_index = 1
            content_elements = doc.get("body", {}).get("content", [])
            if content_elements:
                last_element = content_elements[-1]
                end_index = last_element.get("endIndex", 1) - 1
            requests_list = [{"insertText": {"location": {"index": end_index}, "text": "\\n" + text}}]
            service.documents().batchUpdate(documentId=doc_id, body={"requests": requests_list}).execute()
            return f"Appended text to Google Doc (ID: {doc_id})"
        docs_file = "docs_mock.json"
        if os.path.exists(docs_file):
            with open(docs_file, "r") as f:
                docs = json.load(f)
            if doc_id in docs:
                docs[doc_id]["text"] += "\\n" + text
                with open(docs_file, "w") as f:
                    json.dump(docs, f, indent=4)
                return f"Appended text to Mock Doc (ID: {doc_id})."
        return f"Error: Mock Doc '{doc_id}' not found."
    except Exception as e:
        return f"Error appending to doc: {str(e)}"

@tool
def reschedule_event(event_id: str, new_date: str) -> str:
    """Reschedule an existing Google Calendar event."""
    print(f"  [Tool] reschedule_event({event_id}, {new_date})")
    try:
        service = get_google_service("calendar", "v3")
        if service:
            event = service.events().get(calendarId='primary', eventId=event_id).execute()
            time_dict = {"dateTime": new_date} if "T" in new_date else {"date": new_date}
            event["start"] = time_dict
            event["end"] = time_dict
            service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
            return f"Event rescheduled to {new_date}."
        return f"Mock: Event '{event_id}' rescheduled to {new_date}."
    except Exception as e:
        return f"Error rescheduling event: {str(e)}"

@tool
def delete_event(event_id: str) -> str:
    """Delete a Google Calendar event by ID."""
    print(f"  [Tool] delete_event({event_id})")
    try:
        service = get_google_service("calendar", "v3")
        if service:
            service.events().delete(calendarId='primary', eventId=event_id).execute()
            return f"Event '{event_id}' deleted."
        return f"Mock: Event '{event_id}' deleted."
    except Exception as e:
        return f"Error deleting event: {str(e)}"

@tool
def share_drive_file(file_id: str, email: str, role: str = "reader") -> str:
    """Share a Google Drive file with a specific email."""
    print(f"  [Tool] share_drive_file({file_id}, {email})")
    try:
        service = get_google_service("drive", "v3")
        if service:
            user_permission = {'type': 'user', 'role': role, 'emailAddress': email}
            service.permissions().create(fileId=file_id, body=user_permission, fields='id').execute()
            return f"File '{file_id}' shared with {email} as {role}."
        return f"Mock: File '{file_id}' shared with {email} as {role}."
    except Exception as e:
        return f"Error sharing file: {str(e)}"

@tool
def lookup_contact(name: str) -> str:
    """Lookup an email address for a given name from the contact book."""
    print(f"  [Tool] lookup_contact({name})")
    contacts_file = "contacts.json"
    if not os.path.exists(contacts_file):
        dummy_contacts = {
            "sarah": "sarah.smith@example.com",
            "engineering team": "eng-team@example.com",
            "manager": "boss@example.com"
        }
        with open(contacts_file, "w") as f:
            json.dump(dummy_contacts, f, indent=4)
    try:
        with open(contacts_file, "r") as f:
            contacts = json.load(f)
        name_lower = name.lower()
        for contact_name, email in contacts.items():
            if name_lower in contact_name.lower():
                return f"Contact found: {contact_name} -> {email}"
        return f"No contact found matching '{name}'."
    except Exception as e:
        return f"Error reading contact book: {str(e)}"

@tool
def create_sheet(title: str) -> str:
    """Create a new Google Sheet."""
    print(f"  [Tool] create_sheet({title})")
    try:
        service = get_google_service("sheets", "v4")
        if not service:
            return "Error: Missing Google credentials."
        spreadsheet = {"properties": {"title": title}}
        spreadsheet = service.spreadsheets().create(body=spreadsheet, fields="spreadsheetId").execute()
        return f"Sheet created successfully. ID: {spreadsheet.get('spreadsheetId')}"
    except Exception as e:
        return f"Error creating sheet: {str(e)}"

@tool
def read_sheet(spreadsheet_id: str, range_name: str) -> str:
    """Read data from a Google Sheet. Range should be like 'Sheet1!A1:D5' or just 'Sheet1'."""
    print(f"  [Tool] read_sheet({spreadsheet_id}, {range_name})")
    try:
        service = get_google_service("sheets", "v4")
        if not service:
            return "Error: Missing Google credentials."
        result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        values = result.get("values", [])
        if not values:
            return "No data found."
        return "\\n".join([", ".join([str(cell) for cell in row]) for row in values])
    except Exception as e:
        return f"Error reading sheet: {str(e)}"

@tool
def append_to_sheet(spreadsheet_id: str, range_name: str, values: list) -> str:
    """Append a row (or rows) of data to a Google Sheet. `values` should be a list of lists, e.g. [['A', 'B'], ['C', 'D']]."""
    print(f"  [Tool] append_to_sheet({spreadsheet_id}, {range_name})")
    try:
        service = get_google_service("sheets", "v4")
        if not service:
            return "Error: Missing Google credentials."
        body = {"values": values}
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
        return f"Appended {result.get('updates', {}).get('updatedCells', 0)} cells."
    except Exception as e:
        return f"Error appending to sheet: {str(e)}"

@tool
def fetch_emails(limit: int = 5, unread_only: bool = True) -> str:
    """Fetch emails from Gmail inbox using the Gmail API. Can filter by unread only."""
    print(f"  [Tool] fetch_emails(limit={limit}, unread_only={unread_only})")
    try:
        service = get_google_service("gmail", "v1")
        if not service:
            return "Error: Missing Google credentials."
        
        label_ids = ['INBOX']
        if unread_only:
            label_ids.append('UNREAD')
            
        results = service.users().messages().list(userId='me', labelIds=label_ids, maxResults=limit).execute()
        messages = results.get('messages', [])
        if not messages:
            return "No emails found matching criteria."
            
        emails_fetched = []
        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
            payload = msg_data.get('payload', {})
            headers = payload.get('headers', [])
            
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            from_ = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
            date_ = next((h['value'] for h in headers if h['name'] == 'Date'), 'Unknown Date')
            
            body = ""
            parts = payload.get('parts', [])
            if not parts and payload.get('body', {}).get('data'):
                import base64
                body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
            else:
                for part in parts:
                    if part.get('mimeType') == 'text/plain' and part.get('body', {}).get('data'):
                        import base64
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                        break
            
            snippet = body[:250].replace('\n', ' ') + "..."
            emails_fetched.append(f"From: {from_} | Date: {date_} | Subject: {subject} | Body: {snippet}")
            
        return "\n\n".join(emails_fetched)
    except Exception as e:
        return f"Error fetching emails: {str(e)}"

@tool
def reply_to_email(to: str, subject: str, body: str) -> str:
    """Send a reply to an email."""
    print(f"  [Tool] reply_to_email(to={to})")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    return send_email.invoke({"to": to, "subject": subject, "body": body})

productivity_tools = [send_email, fetch_emails, reply_to_email, calendar_today, create_event, create_task, list_tasks, upload_to_drive, search_drive, send_telegram_message, create_doc, read_doc, append_to_doc, create_sheet, read_sheet, append_to_sheet, reschedule_event, delete_event, share_drive_file, lookup_contact]
productivity_llm = get_llm(model_name=MODEL_NAME, temperature=0).bind_tools(productivity_tools)
productivity_tool_node = ToolNode(productivity_tools, messages_key="productivity_messages")

# =========================================================
# AGENT LOGIC
# =========================================================

def productivity_agent(state: GraphState) -> dict:
    task = state["current_task"]
    print(f"\n--- [ProductivityAgent] Executing {task.id} ---")

    context = {
        aid: state["artifacts"][aid].payload
        for aid in task.context_artifacts
        if aid in state["artifacts"]
    }

    sys_prompt = f"""You are ProductivityAgent. You handle emails (fetching, reading, sending, replying), calendars, scheduling, Google Tasks, Telegram messages, Google Docs, looking up contacts, and Google Drive file operations.
Task: {task.instruction}
Expected Output: {task.expected_output}
Context: {json.dumps(context)}

When asked to fetch emails, retrieve them based on the query (use unread_only=False if they ask for all emails) and present them clearly. 
When asked to reply, use the `reply_to_email` tool.
Use the available tools to complete the task. You may call multiple tools if needed."""

    if state["agent_steps"] == 0:
        messages = [SystemMessage(content=sys_prompt)]
    else:
        messages = [SystemMessage(content=sys_prompt)] + state["productivity_messages"]

    time.sleep(2)
    response = productivity_llm.invoke(messages)

    if response.tool_calls:
        print(f"  [ProductivityAgent] Tool calls: {[tc['name'] for tc in response.tool_calls]}")
    else:
        print("  [ProductivityAgent] Done — no more tool calls.")

    return {"productivity_messages": [response], "agent_steps": state["agent_steps"] + 1}

def productivity_route(state: GraphState) -> str:
    if state["agent_steps"] >= MAX_AGENT_STEPS:
        print("  [ProductivityAgent] Max steps reached, forcing finalize.")
        return "ProductivityFinalizer"
    last_msg = state["productivity_messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "ProductivityToolNode"
    return "ProductivityFinalizer"

def productivity_finalizer(state: GraphState) -> dict:
    print("  [ProductivityAgent] Finalizing task.")
    last_msg = state["productivity_messages"][-1]

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
        type=ArtifactType.STATUS,
        title=f"Output of {tool_name}",
        description=f"Produced by ProductivityAgent for {task.id}",
        payload=payload,
    )

    task.status = "completed"
    print(f"  [ProductivityAgent] Created artifact {artifact_id}.")

    remove_msgs = [RemoveMessage(id=m.id) for m in state["productivity_messages"] if m.id is not None]

    return {
        "artifacts": {artifact_id: artifact},
        "completed_tasks": [task],
        "current_task": None,
        "artifact_counter": new_art_counter,
        "agent_steps": 0,
        "productivity_messages": remove_msgs,
        "logs": [f"ProductivityAgent completed {task.id} -> {artifact_id}"],
    }

def build_productivity_subgraph():
    builder = StateGraph(GraphState)
    builder.add_node("ProductivityAgent", productivity_agent)
    builder.add_node("ProductivityToolNode", productivity_tool_node)
    builder.add_node("ProductivityFinalizer", productivity_finalizer)

    builder.add_edge(START, "ProductivityAgent")
    builder.add_conditional_edges("ProductivityAgent", productivity_route)
    builder.add_edge("ProductivityToolNode", "ProductivityAgent")
    builder.add_edge("ProductivityFinalizer", END)
    
    return builder.compile(interrupt_before=["ProductivityToolNode"])
