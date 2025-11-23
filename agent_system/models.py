from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import threading

class Message(BaseModel):
    role: str
    content: str
    sender: Optional[str] = None

class AgentContext(BaseModel):
    user_intent: str = Field(description="The original high-level goal of the user.")
    accumulated_findings: List[str] = Field(default_factory=list, description="Key facts and data points discovered so far.")
    pending_tasks: List[str] = Field(default_factory=list, description="Tasks that still need to be completed.")
    history: List[Message] = Field(default_factory=list, description="The conversation history.")
    hop_count: int = Field(default=0, description="Counter to prevent infinite loops.")
    data_version: int = Field(default=0, description="Version number for user data. Increments when data changes.")
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, **data):
        super().__init__(**data)
        self._lock = threading.Lock()
    
    def add_message(self, role: str, content: str, sender: str = None):
        with self._lock:
            self.history.append(Message(role=role, content=content, sender=sender))

    def add_finding(self, finding: str):
        with self._lock:
            self.accumulated_findings.append(finding)
    
    def increment_data_version(self):
        """Increment data version when user data is updated. This invalidates cached responses."""
        with self._lock:
            self.data_version += 1
            print(f"  🔄 Data version incremented to {self.data_version} - cache will be invalidated")
