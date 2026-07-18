import os
import sys
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

def get_llm(model_name: str, temperature: float = 0.0):
    """Returns Groq by default. Uses local LLM only if --local is passed."""
    use_local = "--local" in sys.argv
    
    if use_local:
        local_base_url = "http://127.0.0.1:8888/v1"
        print(f"\n[LLM Factory] ⚡ Connecting to Local Model Server at {local_base_url} ⚡\n")
        return ChatOpenAI(
            base_url=local_base_url, 
            api_key=os.getenv("LOCAL_API_KEY", "dummy"), 
            model="local-model",
            temperature=temperature
        )
    else:
        # Default Priority: Groq API
        return ChatGroq(model=model_name, temperature=temperature)
