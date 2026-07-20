import os

# Disable all telemetry (ChromaDB, PostHog, Mem0) before any imports happen!
# This stops background analytics threads from spawning, which are what block
# the server from shutting down cleanly when you press Ctrl+C.
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"
os.environ["MEM0_TELEMETRY"] = "False"
os.environ["POSTHOG_DISABLED"] = "True"

import uuid
import streamlit as st

from app.application import handle_query, upload_document, ChatResult

st.set_page_config(page_title="SmartDesk AI", page_icon="🤖", layout="wide")

st.markdown("""
<style>
/* Modern typography and polished UI elements */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* Polished buttons with hover effects */
.stButton>button {
    border-radius: 8px;
    transition: all 0.2s ease-in-out;
    border: 1px solid rgba(150, 150, 150, 0.2);
}
.stButton>button:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    border-color: rgba(150, 150, 150, 0.4);
}

/* Refined dividers */
hr {
    margin-top: 1.5rem;
    margin-bottom: 1.5rem;
    opacity: 0.5;
}
</style>
""", unsafe_allow_html=True)

if "chat_id" not in st.session_state:
    st.session_state.chat_id = uuid.uuid4().hex[:6]
if "chat_rag_enabled" not in st.session_state:
    st.session_state.chat_rag_enabled = False
if "uploaded_documents" not in st.session_state:
    st.session_state.uploaded_documents = []
if "messages" not in st.session_state:
    st.session_state.messages = []

# ── Sidebar: Knowledge Base Upload ────────────────────────────────────────────
with st.sidebar:
    st.title("📚 Current Chat Uploads")
    st.caption("Upload documents to search them with RAG in this session.")

    uploaded = st.file_uploader(
        "Choose a document",
        type=["pdf", "txt", "md", "docx"],
        help="Supported formats: PDF, TXT, Markdown, DOCX",
    )

    if uploaded:
        if st.button("⬆️ Upload & Index", use_container_width=True):
            with st.spinner(f"Indexing {uploaded.name}…"):
                try:
                    num_chunks = upload_document(uploaded, uploaded.name, chat_id=st.session_state.chat_id)
                    st.session_state.chat_rag_enabled = True
                    if uploaded.name not in st.session_state.uploaded_documents:
                        st.session_state.uploaded_documents.append(uploaded.name)

                    st.success(
                        f"✅ **{uploaded.name}** indexed!\n\n"
                        f"**{num_chunks}** chunks stored for this chat."
                    )
                except ValueError as e:
                    st.error(f"Configuration error: {str(e)}")
                except Exception as e:
                    st.error(f"Failed to index: {str(e)}")

    st.divider()

    if st.session_state.uploaded_documents:
        st.subheader("📄 Uploaded in this chat")
        for doc in st.session_state.uploaded_documents:
            st.markdown(f"- {doc}")
    else:
        st.info("No documents uploaded yet.")
        
    st.divider()
    st.subheader("⚙️ Settings")
    if "auto_approve" not in st.session_state:
        st.session_state.auto_approve = False
    st.session_state.auto_approve = st.toggle("⚡ Auto-Approve Tools (Bypass HITL)", value=st.session_state.auto_approve)

    st.divider()
    
    if st.button("➕ Start New Chat", use_container_width=True, type="primary"):
        st.session_state.chat_id = uuid.uuid4().hex[:6]
        st.session_state.messages = []
        st.session_state.uploaded_documents = []
        st.session_state.chat_rag_enabled = False
        st.rerun()

    st.subheader("🕒 Previous Chats")
    
    try:
        from graph import get_all_existing_threads, build_graph, delete_thread
        threads = get_all_existing_threads()
        if not threads:
            st.info("No previous chats found.")
        else:
            for t in threads:
                # Disable the button if it's the current chat
                is_current = (t == st.session_state.chat_id)
                btn_label = f"💬 {t}" + (" (Current)" if is_current else "")
                
                col1, col2 = st.columns([5, 1])
                with col1:
                    if st.button(btn_label, key=f"btn_{t}", use_container_width=True, disabled=is_current):
                        st.session_state.chat_id = t
                        graph = build_graph()
                        checkpoint_state = graph.get_state({"configurable": {"thread_id": t}})
                        
                        if checkpoint_state and hasattr(checkpoint_state, 'values') and checkpoint_state.values:
                            st.session_state.messages = []
                            for m in checkpoint_state.values.get("messages", []):
                                role = "user" if m.type == "human" else "assistant"
                                st.session_state.messages.append({"role": role, "content": m.content})
                            
                            st.session_state.uploaded_documents = checkpoint_state.values.get("uploaded_documents", [])
                            st.session_state.chat_rag_enabled = checkpoint_state.values.get("chat_rag_enabled", False)
                        
                        st.rerun()
                with col2:
                    if st.button("🗑️", key=f"del_{t}", help="Delete chat history"):
                        delete_thread(t)
                        if is_current:
                            st.session_state.messages = []
                            st.session_state.uploaded_documents = []
                            st.session_state.chat_rag_enabled = False
                        st.rerun()
    except Exception as e:
        st.error(f"Could not load threads: {e}")

# ── Main Chat Interface ───────────────────────────────────────────────────────
st.title("SmartDesk: Multi-Agent AI Assistant 🤖")
st.markdown(
    "A hierarchical AI system with **Workspace**, **Knowledge** (RAG), "
    "and **Productivity** agents."
)

# Render previous chat turns
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


# ── Handle new user input ─────────────────────────────────────────────────────
# ── Handle new user input ─────────────────────────────────────────────────────

if st.session_state.get("is_interrupted"):
    with st.chat_message("assistant"):
        st.warning("⚠️ **Approval Required for Tools**")
        st.write(f"`{', '.join(st.session_state.get('pending_tools', []))}`")
        c1, c2, _ = st.columns([1, 1, 2])
        if c1.button("✅ Approve"):
            st.session_state.resume_action = "approve"
            st.session_state.is_interrupted = False
            st.rerun()
        if c2.button("❌ Reject"):
            st.session_state.resume_action = "reject"
            st.session_state.is_interrupted = False
            st.rerun()

prompt = st.chat_input("How can I help you today?")
should_run = False

if prompt and not st.session_state.get("is_interrupted"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    should_run = True

if st.session_state.get("resume_action"):
    should_run = True

if should_run:
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)

    resume_act = st.session_state.get("resume_action")
    st.session_state.resume_action = None

    with st.chat_message("assistant"):
        # ── Live execution status container ───────────────────────────────────
        with st.status("⚡ SmartDesk agents are working…", expanded=True) as exec_status:
            
            AGENT_EMOJI = {
                "WorkspaceAgent":   "🗂️",
                "KnowledgeAgent":   "🧠",
                "ProductivityAgent": "📅",
            }
            
            final_result = None
            
            # Stream the events from handle_query
            for event in handle_query(
                user_id="default_user",
                chat_id=st.session_state.chat_id,
                user_query=prompt,
                uploaded_documents=st.session_state.uploaded_documents,
                chat_rag_enabled=st.session_state.chat_rag_enabled,
                resume_action=resume_act,
                auto_approve=st.session_state.get("auto_approve", False)
            ):
                event_type = event.get("type")
                
                if event_type == "auto_resume":
                    st.session_state.resume_action = "approve"
                    st.rerun()
                    
                elif event_type == "interrupted":
                    st.session_state.is_interrupted = True
                    st.session_state.pending_tools = event.get("pending_tools", [])
                    exec_status.update(label="⚠️ Waiting for user approval...", state="error")
                    st.rerun()

                elif event_type == "task_start":
                    emoji = AGENT_EMOJI.get(event["agent"], "🤖")
                    st.write(f"🎯 **Orchestrator** → {emoji} **{event['agent']}**")
                    st.caption(f"*{event['instruction']}*")
                
                elif event_type == "orchestrator_done":
                    st.write("✅ **Orchestrator**: All tasks complete!")
                
                elif event_type == "tool_call":
                    emoji = AGENT_EMOJI.get(event["agent"], "🤖")
                    tools_str = "  ·  ".join(event["tools"])
                    st.write(f"{emoji} **{event['agent']}** → 🔧 `{tools_str}`")
                    
                elif event_type == "tool_result":
                    st.write(f"  ↳ `{event['name']}` ✓")
                    
                elif event_type == "artifact":
                    st.write(f"📦 Artifact `{event['id']}`: **{event['title']}**")
                    
                elif event_type == "error":
                    exec_status.update(label="❌ Error during execution", state="error", expanded=True)
                    st.error(event.get("message", "Unknown error."))
                    break
                    
                elif event_type == "final":
                    final_result = event
                    exec_status.update(label="✅ Done!", state="complete", expanded=False)
        
        # ── Render final response below the status box ────────────────────────
        if final_result:
            chat_result: ChatResult = final_result["result"]
            
            with st.expander("🔍 Agent Execution Details"):
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Tasks Completed")
                    for t in final_result.get("completed_tasks", []):
                        emoji = AGENT_EMOJI.get(t["agent"], "🤖")
                        st.write(f"{emoji} **{t['agent']}**: {t['instruction']}")
                with col2:
                    artifacts = final_result.get("artifacts", [])
                    if artifacts:
                        st.subheader("Generated Artifacts")
                        for a in artifacts:
                            st.markdown(f"**`{a['id']}`** — {a['title']} _{a['type']}_")
                            st.caption(a['description'])
                            
            st.markdown(chat_result.response)
            st.session_state.messages.append({"role": "assistant", "content": chat_result.response})
