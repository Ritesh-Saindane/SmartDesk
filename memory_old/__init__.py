try:
    from mem0 import Memory
    import os
    import sys
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Default priority: Groq LLM + HuggingFace Embeddings
    config = {
        "llm": {
            "provider": "groq",
            "config": {
                "model": "openai/gpt-oss-120b"
            }
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "openai_base_url": "https://api-inference.huggingface.co/v1",
                "api_key": os.getenv("HUGGINGFACE_API_KEY", "hf_dummy_key")
            }
        }
    }
    
    # Override for local if --local is passed
    if "--local" in sys.argv:
        config["llm"] = {
            "provider": "openai",
            "config": {
                "model": "local-model",
                "openai_api_key": "dummy",
                "openai_api_base": "http://127.0.0.1:8888/v1"
            }
        }
        
    m = Memory.from_config(config_dict=config)

    def retrieve_memories(user_id: str, query: str, limit: int = 5):
        try:
            if not query:
                return []
            results = m.search(query, user_id=user_id, limit=limit)
            return results
        except Exception as e:
            print(f"Mem0 search error: {e}")
            return []

    def store_memories(messages: list, user_id: str):
        try:
            m.add(messages, user_id=user_id)
        except Exception as e:
            print(f"Mem0 store error: {e}")

except Exception as e:
    print(f"Failed to initialize Mem0: {e}")
    def retrieve_memories(user_id: str, query: str, limit: int = 5):
        return []
    def store_memories(messages: list, user_id: str):
        pass
