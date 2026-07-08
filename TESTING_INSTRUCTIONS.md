# SmartDesk: Testing Instructions 🧪

The SmartDesk project is now **100% end-to-end complete**. All agent components (Workspace, Knowledge/RAG, and Productivity) are fully implemented and wired into the Orchestrator with protective demarcations and resilient API fallbacks.

Here is how you can perform the final testing.

---

## 1. Automated End-to-End Test Suite

We have written a comprehensive python script that bypasses the need to manually click around, injecting complex, multi-step queries directly into the Orchestrator's `initial_state`.

**How to run it:**
```bash
# Ensure your virtual environment is active
source .venv/bin/activate
python test_end_to_end.py
```

**What it tests:**
1. **Workspace Agent**: Folder creation, file writing, and reading.
2. **Knowledge Agent (RAG)**: Indexing stability and embedding search retrievals.
3. **Productivity Agent**: Calendar reads and email generation (using the fallback mock system since `HEADLESS_TEST=1` is enabled in the script).
4. **Mixed Workflow**: A stress test that forces the Orchestrator to delegate tasks to all three agents sequentially.

---

## 2. Interactive Testing via UI (Streamlit)

For a real-world, interactive test, you can chat with the application directly.

**How to run it:**
```bash
streamlit run app.py
```

**Things to try:**
- **Test the RAG**: Drop a PDF or Markdown file into the `KnowledgeBase/` folder. Restart the Streamlit app. Ask: *"What does my knowledge base say about X?"*
- **Test Routing**: Ask: *"Draft an email to John saying I'm done with the project."* Expand the "View Agent Execution Details" tab in the UI. You should see it was successfully routed to the `ProductivityAgent`, not the `WorkspaceAgent`.
- **Test Workspace**: *"Write a Python script that prints hello world to a file called test.py in my workspace."*

---

## 3. Testing Live Google APIs

By default, if `credentials.json` is missing, the system uses mock JSON files (`calendar.json`, `email_outbox.json`). 

If you want to test the **LIVE** APIs:
1. Ensure your `credentials.json` is in the root directory.
2. Ensure `HEADLESS_TEST` is **not** set to `1` in your environment.
3. Run `streamlit run app.py` and trigger a calendar/docs command. A browser window will pop up asking for OAuth consent.
4. Future tests will silently authenticate using the generated `token.json` file.

Happy Testing! 🚀
