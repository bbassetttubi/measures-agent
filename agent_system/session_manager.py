import uuid
from typing import Dict, Optional
from datetime import datetime, timedelta
from .models import AgentContext, Message
import threading

class SessionManager:
    """Manages conversation sessions and their histories."""
    
    def __init__(self, session_timeout_minutes: int = 60):
        self.sessions: Dict[str, AgentContext] = {}
        self.session_timestamps: Dict[str, datetime] = {}
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        self._lock = threading.Lock()
    
    def create_session(self, user_intent: str = "") -> str:
        """Create a new session and return its ID."""
        session_id = str(uuid.uuid4())
        with self._lock:
            self.sessions[session_id] = AgentContext(user_intent=user_intent)
            self.session_timestamps[session_id] = datetime.now()
        return session_id
    
    def get_session(self, session_id: str) -> Optional[AgentContext]:
        """Retrieve a session by ID, creating one if it doesn't exist."""
        with self._lock:
            # Clean up old sessions first
            self._cleanup_old_sessions()
            
            # If session doesn't exist, create it
            if session_id not in self.sessions:
                self.sessions[session_id] = AgentContext(user_intent="")
                self.session_timestamps[session_id] = datetime.now()
            
            # Update timestamp
            self.session_timestamps[session_id] = datetime.now()
            return self.sessions[session_id]
    
    def update_session(self, session_id: str, context: AgentContext):
        """Update a session's context."""
        with self._lock:
            self.sessions[session_id] = context
            self.session_timestamps[session_id] = datetime.now()
    
    def delete_session(self, session_id: str):
        """Delete a session."""
        with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
            if session_id in self.session_timestamps:
                del self.session_timestamps[session_id]
    
    def _cleanup_old_sessions(self):
        """Remove sessions that have timed out. Called from within lock - do NOT call delete_session."""
        now = datetime.now()
        expired_sessions = [
            session_id for session_id, timestamp in self.session_timestamps.items()
            if now - timestamp > self.session_timeout
        ]
        # Delete directly (we're already inside the lock - calling delete_session would deadlock)
        for session_id in expired_sessions:
            if session_id in self.sessions:
                del self.sessions[session_id]
            if session_id in self.session_timestamps:
                del self.session_timestamps[session_id]
    
    def list_sessions(self) -> Dict[str, dict]:
        """List all active sessions with metadata."""
        with self._lock:
            self._cleanup_old_sessions()
            return {
                session_id: {
                    'created': timestamp.isoformat(),
                    'message_count': len(context.history),
                    'user_intent': context.user_intent
                }
                for session_id, (timestamp, context) in 
                [(sid, (self.session_timestamps[sid], self.sessions[sid])) 
                 for sid in self.sessions.keys()]
            }

