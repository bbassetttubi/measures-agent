from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import threading

class Message(BaseModel):
    role: str
    content: str
    sender: Optional[str] = None

class ConversationState(BaseModel):
    stage: str = Field(default="triage")
    intent: str = Field(default="unspecified")
    focus: str = Field(default="diagnosis")

    def reset(self):
        self.stage = "triage"
        self.intent = "diagnosis"
        self.focus = "diagnosis"

    def set_stage(self, stage: str):
        self.stage = stage

    def set_intent(self, intent: str):
        self.intent = intent

    def set_focus(self, focus: str):
        self.focus = focus

class AgentContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    user_intent: str = Field(description="The original high-level goal of the user.")
    accumulated_findings: List[str] = Field(default_factory=list)
    pending_tasks: List[str] = Field(default_factory=list)
    history: List[Message] = Field(default_factory=list)
    hop_count: int = Field(default=0)
    data_version: int = Field(default=0)
    pending_widgets: List[dict] = Field(default_factory=list)
    flags: Dict[str, bool] = Field(default_factory=dict)
    insights: Dict[str, Any] = Field(default_factory=dict)
    tool_cache: Dict[str, Any] = Field(default_factory=dict)
    trace: List[str] = Field(default_factory=list)
    state: ConversationState = Field(default_factory=ConversationState)
    plan_domain_flags: Dict[str, bool] = Field(default_factory=lambda: {
        "nutrition": False,
        "fitness": False,
        "sleep": False,
        "mindfulness": False,
        "supplements": False,
    })
    required_plan_domains: List[str] = Field(default_factory=list)
    pending_plan_domains: List[str] = Field(default_factory=list)
    
    def __init__(self, **data):
        super().__init__(**data)
        self._lock = threading.Lock()
    
    def add_message(self, role: str, content: str, sender: str = None):
        with self._lock:
            self.history.append(Message(role=role, content=content, sender=sender))

    def add_finding(self, finding: str):
        with self._lock:
            self.accumulated_findings.append(finding)
            self._register_plan_completion(finding)
    
    def set_flag(self, key: str, value: bool = True):
        with self._lock:
            self.flags[key] = value
    
    def get_flag(self, key: str, default: bool = False) -> bool:
        with self._lock:
            return self.flags.get(key, default)
    
    def register_plan_request(self, requesting_agent: str, target_agents: List[str]):
        plan_agents = {"Nutritionist": "nutrition", "Fitness Coach": "fitness", "Sleep Doctor": "sleep", "Mindfulness Coach": "mindfulness"}
        domains = [plan_agents[a] for a in target_agents if a in plan_agents]
        if not domains:
            return
        with self._lock:
            self.required_plan_domains = domains
            self.pending_plan_domains = [d for d in domains if not self.plan_domain_flags.get(d, False)]
            self.flags["plan_request_active"] = True
            self.flags["plan_request_pending"] = True

    def get_pending_plan_domains(self) -> List[str]:
        with self._lock:
            return [d for d in self.pending_plan_domains if not self.plan_domain_flags.get(d, False)]

    def _register_plan_completion(self, finding: str):
        lower = finding.lower()
        mapping = {
            "nutrition": ["completed: nutrition", "nutrition plan"],
            "fitness": ["completed: fitness", "fitness plan"],
            "sleep": ["completed: sleep", "sleep plan"],
            "mindfulness": ["completed: mindfulness", "stress plan", "mindfulness plan"],
            "supplements": ["supplement plan", "vitamin plan", "completed: supplements"],
        }
        for domain, keywords in mapping.items():
            if any(keyword in lower for keyword in keywords):
                self.plan_domain_flags[domain] = True
                if domain in self.pending_plan_domains:
                    self.pending_plan_domains = [d for d in self.pending_plan_domains if d != domain]
    
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
        with self._lock:
            self.data_version += 1
            self.tool_cache.clear()
