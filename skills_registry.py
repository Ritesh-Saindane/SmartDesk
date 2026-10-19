import os
import importlib.util
import inspect
from typing import List, Dict, Optional
from langchain_core.tools import BaseTool

class SkillRegistry:
    """
    Dynamically loads and manages LangChain tools (skills) from a specified directory.
    This supports Progressive Disclosure by allowing the system to query skill descriptions
    and selectively bind only the necessary tools to the LLM.
    """
    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = skills_dir
        self.skills: Dict[str, BaseTool] = {}
        self._ensure_directory()
        self.refresh()

    def _ensure_directory(self):
        """Ensure the skills directory exists."""
        if not os.path.exists(self.skills_dir):
            os.makedirs(self.skills_dir, exist_ok=True)
            
        init_path = os.path.join(self.skills_dir, "__init__.py")
        if not os.path.exists(init_path):
            with open(init_path, 'w') as f:
                f.write("# Dynamic skills package\n")

    def refresh(self):
        """Scans the skills directory and loads all valid BaseTool instances."""
        self.skills.clear()
        if not os.path.exists(self.skills_dir):
            return

        for filename in os.listdir(self.skills_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                module_name = filename[:-3]
                file_path = os.path.join(self.skills_dir, filename)
                
                try:
                    spec = importlib.util.spec_from_file_location(module_name, file_path)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        
                        # Extract all instances of BaseTool
                        for name, obj in inspect.getmembers(module):
                            if isinstance(obj, BaseTool):
                                # Register the tool
                                self.skills[obj.name] = obj
                except Exception as e:
                    print(f"[SkillRegistry] Failed to load skill from {filename}: {e}")

    def get_all_skills(self) -> List[BaseTool]:
        """Returns all loaded skills."""
        return list(self.skills.values())

    def get_skill(self, name: str) -> Optional[BaseTool]:
        """Retrieve a specific skill by name."""
        return self.skills.get(name)

    def get_skill_summaries(self) -> str:
        """
        Returns a formatted string of all available skills and their descriptions.
        Useful for injecting into an LLM prompt so it can reason about which skills to request.
        """
        if not self.skills:
            return "No custom skills currently available."
        
        summaries = []
        for name, tool in self.skills.items():
            summaries.append(f"- {name}: {tool.description}")
        return "\n".join(summaries)

# Instantiate a global registry for the app to use
registry = SkillRegistry()
