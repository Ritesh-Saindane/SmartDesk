import os
import json
import time
import subprocess
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from llm_factory import get_llm
from langgraph.graph import END, START, StateGraph
from state import GraphState, Artifact, ArtifactType

MODEL_NAME = "openai/gpt-oss-120b"
MAX_RETRIES = 2

class GeneratedSkill(BaseModel):
    skill_name: str = Field(..., description="A snake_case name for the skill.")
    python_code: str = Field(..., description="The complete python code.")

def generator_node(state: GraphState) -> dict:
    task = state["current_task"]
    print(f"\n--- [SkillGenerator] Designing skill for: {task.id} ---")
    
    llm = get_llm(model_name=MODEL_NAME, temperature=0, max_tokens=1500).with_structured_output(GeneratedSkill)
    
    sys_prompt = f"""You are an Expert Python Engineer. 
Your task is to write a LangChain tool to fulfill this requirement: {task.instruction}

Rules:
1. Use the @tool decorator from langchain_core.tools.
2. The function must have clear type hints and a Google-style docstring.
3. Catch basic exceptions and return error strings rather than crashing.
4. MUST INCLUDE A TEST: At the bottom of the file, include an `if __name__ == '__main__':` block that calls your tool with mock inputs and prints the result. This is strictly required for the Validation Sandbox to test your code.
"""
    messages = [SystemMessage(content=sys_prompt)]
    
    attempt = 0
    success = False
    final_code = ""
    skill_name = ""
    sandbox_log = ""
    
    while attempt < MAX_RETRIES:
        print(f"  [SkillGenerator] Attempt {attempt + 1}/{MAX_RETRIES}...")
        try:
            response: GeneratedSkill = llm.invoke(messages)
            skill_name = response.skill_name.replace(".py", "")
            final_code = response.python_code
            
            # Clean up markdown formatting if the LLM hallucinated it despite structured output
            if final_code.startswith("```python"):
                final_code = final_code[9:]
            if final_code.startswith("```"):
                final_code = final_code[3:]
            if final_code.endswith("```"):
                final_code = final_code[:-3]
                
            sandbox_path = os.path.join("skills_sandbox", f"{skill_name}.py")
            with open(sandbox_path, "w") as f:
                f.write(final_code)
                
            # Run sandbox validation
            print(f"  [ValidationSandbox] Testing {skill_name}.py...")
            result = subprocess.run(
                ["python", sandbox_path], 
                capture_output=True, 
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                print("  [ValidationSandbox] SUCCESS!")
                sandbox_log = f"Success. Output:\n{result.stdout}"
                success = True
                break
            else:
                print("  [ValidationSandbox] FAILED. Sending traceback to LLM for self-correction.")
                error_msg = f"Execution failed with return code {result.returncode}.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\nFix the code."
                messages.append(HumanMessage(content=error_msg))
                attempt += 1
                time.sleep(5) # Respect TPM limits
                
        except subprocess.TimeoutExpired:
            print("  [ValidationSandbox] TIMEOUT. Sending warning to LLM.")
            messages.append(HumanMessage(content="Execution timed out after 10 seconds. Fix infinite loops or hanging network calls."))
            attempt += 1
            time.sleep(5)
        except Exception as e:
            messages.append(HumanMessage(content=f"LLM Parsing error: {str(e)}"))
            attempt += 1
            time.sleep(5)

    generator_data = {
        "success": success,
        "skill_name": skill_name,
        "sandbox_log": sandbox_log,
        "sandbox_path": os.path.join("skills_sandbox", f"{skill_name}.py")
    }
    
    return {"generator_data": generator_data}

def graduation_node(state: GraphState) -> dict:
    data = state.get("generator_data", {})
    task = state["current_task"]
    
    if not data.get("success"):
        # Max retries hit, graduation fails.
        payload = f"Failed to generate a working skill after {MAX_RETRIES} attempts. Sandbox execution crashed repeatedly."
    else:
        # Graduation Approved (reached this node because user clicked approve on the interrupt)
        sandbox_path = data["sandbox_path"]
        permanent_path = os.path.join("skills", f"{data['skill_name']}.py")
        
        # Move file from sandbox to permanent
        if os.path.exists(sandbox_path):
            os.rename(sandbox_path, permanent_path)
        payload = f"Skill '{data['skill_name']}' successfully generated, validated in sandbox, and promoted to permanent registry!"
        
    new_art_counter = state["artifact_counter"] + 1
    artifact_id = f"art_{new_art_counter}"

    artifact = Artifact(
        id=artifact_id,
        type=ArtifactType.STATUS,
        title="Skill Generation Result",
        description=f"Produced by SkillGenerator for {task.id}",
        payload=payload,
    )

    task.status = "completed"
    
    return {
        "artifacts": {artifact_id: artifact},
        "completed_tasks": [task],
        "current_task": None,
        "artifact_counter": new_art_counter,
        "generator_data": {} # clear
    }

def build_skill_generator_subgraph():
    builder = StateGraph(GraphState)
    builder.add_node("GeneratorNode", generator_node)
    builder.add_node("GraduationNode", graduation_node)

    builder.add_edge(START, "GeneratorNode")
    builder.add_edge("GeneratorNode", "GraduationNode")
    builder.add_edge("GraduationNode", END)
    
    # Interrupt before Graduation for final user approval (HITL Checkpoint)
    return builder.compile(interrupt_before=["GraduationNode"])
