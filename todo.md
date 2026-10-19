# SmartDesk Todo List

## Phase 1: Foundational Enhancements
1. [ ] Implement STM and LTM (memO replacement with ChromaDB)
2. [ ] Add multiquery retrieval in RAG
3. [x] Implement Daily Briefing Feature ("fetch all emails, tasks, whatever on my plate today")
4. [x] Implement Email Reply Feature (fetch unread emails, ask what to reply, send reply)
5. [x] Implement Human-in-the-loop mechanism
6. [ ] Comprehensive end-to-end testing of Productivity Agent

## Phase 2: User Interface & Experience
1. [x] Proper UI implementation (Streamlit Premium Dark-Mode Glassmorphism)

## Phase 3: Dynamic Skills Architecture (HITL & Sandbox)
1. [x] Create `skills/` and `skills_sandbox/` directories.
2. [x] Build `skills_registry.py` to scan directories, parse python scripts, and dynamically convert them to LangChain `StructuredTool` objects.
3. [x] Update Orchestrator to support reasoning-based Skill Detection (semantically search registry).
4. [x] Implement HITL Consent Flow: Agent pauses and asks user for permission to execute an existing skill.
5. [x] Implement Skill Generator Node: An LLM node prompted as an expert engineer to write python functions + Pydantic schemas for missing capabilities.
6. [x] Implement Validation Sandbox: A node that executes the generated code in a subprocess to test for errors (and self-corrects on failure).
7. [x] Implement Graduation HITL Checkpoint: Present successful sandboxed code to the user for final approval before moving it to the permanent `skills/` directory.

## Phase 4: DevOps (Fork Exclusive)
1. [ ] CI/CD Pipelines
2. [ ] Docker Containerization

## Phase 5: Future Polish & Scaling
1. [ ] Intent Confirmation HITL: Have the Orchestrator explain its plan for a new skill and ask for user confirmation *before* spinning up the heavy SkillGeneratorAgent.
2. [ ] LLM Provider Switch: Migrate from `gpt-oss-120b` to stronger OpenRouter models for complex skill generation tasks if needed.