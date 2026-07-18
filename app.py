import os
import shutil
import uuid
from langchain_core.messages import HumanMessage
import streamlit as st
import threading
from main import build_graph, GraphState, get_all_existing_threads
from memory import retrieve_memories, store_memories

st.set_page_config(page_title="SmartDesk AI", page_icon="🤖", layout="wide")

if "chat_id" not in st.session_state:
    st.session_state.chat_id = uuid.uuid4().hex[:6]
if "chat_rag_enabled" not in st.session_state:
    st.session_state.chat_rag_enabled = False
if "uploaded_documents" not in st.session_state:
    st.session_state.uploaded_documents = []

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
            chat_id = st.session_state.chat_id
            chat_uploads_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "chat_uploads", f"chat_{chat_id}"
            )
            os.makedirs(chat_uploads_dir, exist_ok=True)
            save_path = os.path.join(chat_uploads_dir, uploaded.name)

            with st.spinner(f"Indexing {uploaded.name}…"):
                try:
                    with open(save_path, "wb") as f:
                        shutil.copyfileobj(uploaded, f)

                    from rag.indexer import index_chat_file
                    num_chunks = index_chat_file(save_path, chat_id)

                    st.session_state.chat_rag_enabled = True
                    if uploaded.name not in st.session_state.uploaded_documents:
                        st.session_state.uploaded_documents.append(uploaded.name)

                    st.success(
                        f"✅ **{uploaded.name}** indexed!\n\n"
                        f"**{num_chunks}** chunks stored for this chat."
                    )
                except EnvironmentError as e:
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
    st.subheader("🕒 Previous Chats")
    
    try:
        threads = get_all_existing_threads()
        if not threads:
            st.info("No previous chats found.")
        else:
            for t in threads:
                # Disable the button if it's the current chat
                is_current = (t == st.session_state.chat_id)
                btn_label = f"💬 Chat: {t}" + (" (Current)" if is_current else "")
                
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
    except Exception as e:
        st.error(f"Could not load threads: {e}")


# ── Main Chat Interface ───────────────────────────────────────────────────────
st.title("SmartDesk: Multi-Agent AI Assistant 🤖")
st.markdown(
    "A hierarchical AI system with **Workspace**, **Knowledge** (RAG), "
    "and **Productivity** agents."
)

if "messages" not in st.session_state:
    st.session_state.messages = []

# Render previous chat turns
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


# ── Handle new user input ─────────────────────────────────────────────────────
if prompt := st.chat_input("How can I help you today?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        final_state = None

        # ── Live execution status container ───────────────────────────────────
        with st.status("⚡ SmartDesk agents are working…", expanded=True) as exec_status:

            # Emoji map for agents
            AGENT_EMOJI = {
                "WorkspaceAgent":   "🗂️",
                "KnowledgeAgent":   "🧠",
                "ProductivityAgent": "📅",
            }

            # Which state key holds messages for each agent
            MSG_KEYS = [
                ("workspace_messages",   "WorkspaceAgent"),
                ("knowledge_messages",   "KnowledgeAgent"),
                ("productivity_messages", "ProductivityAgent"),
            ]

            # Trackers for detecting what's *new* in each streamed snapshot
            prev_task_id      = None
            prev_final        = False
            prev_msg_counts   = {k: 0 for k, _ in MSG_KEYS}
            prev_artifact_ids: set = set()
            # chat_id = 3

            try:
                graph = build_graph()

                try:
                    memories = retrieve_memories(
                        user_id="default_user",
                        query=prompt,
                        limit=5
                    )
                except Exception as e:
                    memories = []
                    st.warning(f"Memory retrieval failed: {e}")

                initial_state = {
                    "chat_id": st.session_state.chat_id,
                    "chat_rag_enabled": st.session_state.chat_rag_enabled,
                    "uploaded_documents": st.session_state.uploaded_documents,
                    "user_query": prompt,
                    "messages": [HumanMessage(content=prompt)],
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
                    "long_term_memory": memories,
                }


                # stream_mode="values" → yields the FULL state snapshot after
                # every node, so we can diff what changed since the last step.
                for state in graph.stream(
                    initial_state,
                    config={
                        "recursion_limit": 35,
                        "configurable": {"thread_id": st.session_state.chat_id}
                    },
                    stream_mode="values",
                ):
                    final_state = state  # keep latest snapshot

                    # ── Orchestrator: new task assigned ───────────────────────
                    task = state.get("current_task")
                    if task and task.id != prev_task_id:
                        emoji = AGENT_EMOJI.get(task.agent, "🤖")
                        st.write(
                            f"🎯 **Orchestrator** → {emoji} **{task.agent}**"
                        )
                        st.caption(f"*{task.instruction[:150]}*")
                        prev_task_id = task.id

                    # ── Orchestrator: finished ────────────────────────────────
                    if state.get("final_response") and not prev_final:
                        st.write("✅ **Orchestrator**: All tasks complete!")
                        prev_final = True

                    # ── Agent messages: detect new tool calls & results ───────
                    for key, agent_name in MSG_KEYS:
                        msgs      = state.get(key, [])
                        new_count = len(msgs)
                        old_count = prev_msg_counts[key]

                        if new_count > old_count:
                            for msg in msgs[old_count:]:
                                emoji = AGENT_EMOJI.get(agent_name, "🤖")

                                if hasattr(msg, "tool_calls") and msg.tool_calls:
                                    # AI message requesting tool(s)
                                    tools = [tc["name"] for tc in msg.tool_calls]
                                    st.write(
                                        f"{emoji} **{agent_name}** → "
                                        f"🔧 `{'  ·  '.join(tools)}`"
                                    )

                                elif hasattr(msg, "name"):
                                    # ToolMessage — result came back
                                    st.write(f"  ↳ `{msg.name}` ✓")

                                # Plain AI message without tool calls:
                                # means the agent is done with this task —
                                # no need to clutter the log.

                            prev_msg_counts[key] = new_count

                    # ── New artifacts created by finalizers ───────────────────
                    arts     = state.get("artifacts", {})
                    new_arts = set(arts.keys()) - prev_artifact_ids
                    for art_id in sorted(new_arts):
                        art = arts[art_id]
                        st.write(f"📦 Artifact `{art_id}`: **{art.title}**")
                    if new_arts:
                        prev_artifact_ids = set(arts.keys())

                exec_status.update(
                    label="✅ Done!", state="complete", expanded=False
                )

            except Exception as e:
                exec_status.update(
                    label="❌ Error during execution", state="error", expanded=True
                )
                st.error(f"{str(e)}")
                final_state = None

        # ── Render final response below the status box ────────────────────────
        if final_state:
            response_text = final_state.get(
                "final_response", "Task completed without a final response."
            )

            # Expandable details panel
            with st.expander("🔍 Agent Execution Details"):
                col1, col2 = st.columns(2)

                with col1:
                    st.subheader("Tasks Completed")
                    for t in final_state.get("completed_tasks", []):
                        emoji = AGENT_EMOJI.get(t.agent, "🤖")
                        st.write(f"{emoji} **{t.agent}**: {t.instruction}")

                with col2:
                    artifacts = final_state.get("artifacts", {})
                    if artifacts:
                        st.subheader("Generated Artifacts")
                        for a_id, artifact in artifacts.items():
                            st.markdown(f"**`{a_id}`** — {artifact.title} _{artifact.type}_")
                            st.caption(artifact.description)

            st.markdown(response_text)
            st.session_state.messages.append(
                {"role": "assistant", "content": response_text}
            )

            # Store interaction in long term memory (asynchronously)
            try:
                mem_messages = [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": response_text}
                ]
                threading.Thread(
                    target=store_memories, 
                    args=(mem_messages, "default_user"),
                    daemon=True
                ).start()
            except Exception as e:
                st.warning(f"Memory storage failed: {e}")


        elif not final_state:
            err = "An error occurred. Please try again."
            st.error(err)
            st.session_state.messages.append({"role": "assistant", "content": err})
