import os
import json
import time
from langchain_core.messages import SystemMessage, ToolMessage, RemoveMessage
from llm_factory import get_llm
from langgraph.graph import END, START, StateGraph
from state import GraphState, Artifact, ArtifactType
from skills_registry import registry

MODEL_NAME = "openai/gpt-oss-120b"
MAX_AGENT_STEPS = 5

def skill_agent(state: GraphState) -> dict:
    task = state["current_task"]
    print(f"\n--- [SkillAgent] Executing {task.id} ---")

    context = {
        aid: state["artifacts"][aid].payload
        for aid in task.context_artifacts
        if aid in state["artifacts"]
    }

    # Refresh registry in case new skills were added
    registry.refresh()
    skills = registry.get_all_skills()

    sys_prompt = f"""You are SkillAgent. You have access to dynamically loaded skills (tools).
Task: {task.instruction}
Expected Output: {task.expected_output}
Context: {json.dumps(context)}

Use the available tools to complete the task."""

    if state["agent_steps"] == 0:
        messages = [SystemMessage(content=sys_prompt)]
    else:
        messages = [SystemMessage(content=sys_prompt)] + state.get("skill_messages", [])

    time.sleep(2)
    # Bind the current dynamic skills
    if skills:
        llm = get_llm(model_name=MODEL_NAME, temperature=0).bind_tools(skills)
    else:
        llm = get_llm(model_name=MODEL_NAME, temperature=0)

    response = llm.invoke(messages)

    if hasattr(response, "tool_calls") and response.tool_calls:
        print(f"  [SkillAgent] Tool calls: {[tc['name'] for tc in response.tool_calls]}")
    else:
        print("  [SkillAgent] Done — no more tool calls.")

    return {"skill_messages": [response], "agent_steps": state["agent_steps"] + 1}

def skill_tool_node(state: GraphState) -> dict:
    last_msg = state["skill_messages"][-1]
    responses = []
    
    registry.refresh()
    
    for tool_call in last_msg.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        skill = registry.get_skill(tool_name)
        
        if skill:
            try:
                result = skill.invoke(tool_args)
                responses.append(ToolMessage(content=str(result), name=tool_name, tool_call_id=tool_call["id"]))
            except Exception as e:
                responses.append(ToolMessage(content=f"Error executing skill {tool_name}: {str(e)}", name=tool_name, tool_call_id=tool_call["id"]))
        else:
            responses.append(ToolMessage(content=f"Error: Skill {tool_name} not found in registry.", name=tool_name, tool_call_id=tool_call["id"]))
            
    return {"skill_messages": responses}

def skill_route(state: GraphState) -> str:
    if state["agent_steps"] >= MAX_AGENT_STEPS:
        return "SkillFinalizer"
    last_msg = state["skill_messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "SkillToolNode"
    return "SkillFinalizer"

def skill_finalizer(state: GraphState) -> dict:
    print("  [SkillAgent] Finalizing task.")
    last_msg = state["skill_messages"][-1]

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
        description=f"Produced by SkillAgent for {task.id}",
        payload=payload,
    )

    task.status = "completed"
    
    remove_msgs = [RemoveMessage(id=m.id) for m in state["skill_messages"] if m.id is not None]

    return {
        "artifacts": {artifact_id: artifact},
        "completed_tasks": [task],
        "current_task": None,
        "artifact_counter": new_art_counter,
        "agent_steps": 0,
        "skill_messages": remove_msgs,
        "logs": [f"SkillAgent completed {task.id} -> {artifact_id}"],
    }

def build_skill_subgraph():
    builder = StateGraph(GraphState)
    builder.add_node("SkillAgent", skill_agent)
    builder.add_node("SkillToolNode", skill_tool_node)
    builder.add_node("SkillFinalizer", skill_finalizer)

    builder.add_edge(START, "SkillAgent")
    builder.add_conditional_edges("SkillAgent", skill_route)
    builder.add_edge("SkillToolNode", "SkillAgent")
    builder.add_edge("SkillFinalizer", END)
    
    # Interrupt before tool execution for HITL Consent Flow
    return builder.compile(interrupt_before=["SkillToolNode"])
