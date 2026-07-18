import os
from dotenv import load_dotenv

load_dotenv()

from memory import store_memories, retrieve_memories

print("Storing memory...")
messages = [
    {"role": "user", "content": "Hi, I am Ritesh and I like C++."},
    {"role": "assistant", "content": "Nice to meet you, Ritesh. I will remember you like C++."}
]
try:
    store_memories(messages, user_id="default_user")
except Exception as e:
    print(f"Exception during store: {e}")

print("\nRetrieving memory...")
try:
    memories = retrieve_memories(user_id="default_user", query="What is my name?")
    print("Retrieved:", memories)
except Exception as e:
    print(f"Exception during retrieve: {e}")
