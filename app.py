import streamlit as st
import json
import time
from main import build_graph, GraphState

st.set_page_config(page_title="SmartDesk AI", page_icon="🤖", layout="wide")

st.title("SmartDesk: Multi-Agent AI Assistant 🤖")
st.markdown("A hierarchical AI system with Workspace, Knowledge, and Productivity agents.")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("How can I help you today?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("Thinking... 🤔")
        
        try:
            graph = build_graph()
            initial_state = {
                "user_query": prompt,
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
            
            with st.spinner("Processing through Orchestrator..."):
                final_state = graph.invoke(initial_state, config={"recursion_limit": 35})
                
            response_text = final_state.get('final_response', "Task completed without a final response.")
            
            # Show completed tasks and artifacts in an expander
            with st.expander("View Agent Execution Details"):
                st.subheader("Tasks Completed")
                for task in final_state.get('completed_tasks', []):
                    st.write(f"✅ **{task.agent}**: {task.instruction}")
                    
                artifacts = final_state.get('artifacts', {})
                if artifacts:
                    st.subheader("Generated Artifacts")
                    for a_id, artifact in artifacts.items():
                        st.markdown(f"**{artifact.title}** ({artifact.type})")
                        st.caption(artifact.description)
            
            message_placeholder.markdown(response_text)
            st.session_state.messages.append({"role": "assistant", "content": response_text})
            
        except Exception as e:
            error_msg = f"An error occurred: {str(e)}"
            message_placeholder.error(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
