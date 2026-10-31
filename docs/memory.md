# Long-Term Memory Integration (Mem0)

This document explains where and how the long-term memory infrastructure has been integrated into the SmartDesk application.

## 1. Graph State Update (`state.py`)
- Added `long_term_memory: list` to `GraphState`.
- This field holds memories retrieved by Mem0 before the LangGraph workflow begins. 
- No agent or node directly manipulates this list.

## 2. Memory Service (`memory/service.py`)
Implemented two primary wrappers for the Mem0 client:
- **`retrieve_long_term_memory`**: Takes the `task_instruction` as the query, performs a search in Mem0, and returns the list of memories found.
- **`store_long_term_memory`**: Takes the most recent user prompt and AI response array, and saves it to Mem0.
- All heavy processing and large payload filtering were removed as requested, leaving just the `task_instruction` as the sole query mechanism.

## 3. Application Flow Hookup (`app.py`)
Instead of adding LangGraph nodes, memory retrieval and storage were implemented as application-level concerns wrapping the main `graph.stream()` block:

### A. Pre-Execution Retrieval
Right before `initial_state` is created for the graph, `retrieve_long_term_memory` is called using the user's `prompt`.
The result is directly injected into the `initial_state` under the `long_term_memory` key.

```python
memories = retrieve_long_term_memory(
    user_id="default_user",
    task_instruction=prompt,
    limit=5
)
initial_state = {
    # ...
    "long_term_memory": memories,
}
```

### B. Post-Execution Storage
Once the graph finishes executing and the Orchestrator delivers its `final_response`, the app packages the user's prompt and the AI's response into a conversational array and sends it to `store_long_term_memory`.

```python
mem_messages = [
    {"role": "user", "content": prompt},
    {"role": "assistant", "content": response_text}
]
store_long_term_memory(mem_messages, user_id="default_user")
```

## Summary
The graph topology remains completely untouched. Agents do not contain arbitrary Retrieve/Store nodes. The orchestrator continues routing without worrying about Mem0. Mem0 integration cleanly wraps around the graph's execution lifecycle.
