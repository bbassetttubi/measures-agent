from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import threading

class Message(BaseModel):
    role: str
    content: str
    sender: Optional[str] = None

class AgentContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    user_intent: str = Field(description="The original high-level goal of the user.")
    accumulated_findings: List[str] = Field(default_factory=list, description="Key facts and data points discovered so far.")
    pending_tasks: List[str] = Field(default_factory=list, description="Tasks that still need to be completed.")
    history: List[Message] = Field(default_factory=list, description="The conversation history.")
    hop_count: int = Field(default=0, description="Counter to prevent infinite loops.")
    data_version: int = Field(default=0, description="Version number for user data. Increments when data changes.")
    pending_widgets: List[dict] = Field(default_factory=list, description="Widgets to be returned to user.")
    flags: Dict[str, bool] = Field(default_factory=dict, description="State flags shared across agents.")
    tool_cache: Dict[str, Any] = Field(default_factory=dict, description="Cached tool responses keyed by tool+args.")
    trace: List[str] = Field(default_factory=list, description="Ordered trace of agent/tool activity.")
    
    def __init__(self, **data):
        super().__init__(**data)
        self._lock = threading.Lock()
    
    def add_message(self, role: str, content: str, sender: str = None):
        with self._lock:
            self.history.append(Message(role=role, content=content, sender=sender))

    def add_finding(self, finding: str):
        with self._lock:
            self.accumulated_findings.append(finding)
    
    def set_flag(self, key: str, value: bool = True):
        with self._lock:
            self.flags[key] = value
    
    def get_flag(self, key: str, default: bool = False) -> bool:
        with self._lock:
            return self.flags.get(key, default)
    
    def cache_tool_result(self, tool_name: str, args: Dict[str, Any], result: Any):
        key = self._tool_cache_key(tool_name, args)
        with self._lock:
            self.tool_cache[key] = result
    
    def get_cached_tool_result(self, tool_name: str, args: Dict[str, Any]):
        key = self._tool_cache_key(tool_name, args)
        with self._lock:
            return self.tool_cache.get(key)
    
    def add_trace(self, entry: str):
        with self._lock:
            self.trace.append(entry)
    
    def _tool_cache_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        from json import dumps
        return f"{tool_name}:{dumps(args, sort_keys=True)}"
    
    def increment_data_version(self):
        """Increment data version when user data is updated. This invalidates cached responses."""
        with self._lock:
            self.data_version += 1
            print(f"  🔄 Data version incremented to {self.data_version} - cache will be invalidated")
            self.tool_cache.clear()
