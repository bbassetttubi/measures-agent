from .models import AgentContext
from .agents import create_agents
from .mcp_client import SimpleMCPClient
from .session_manager import SessionManager
import time

class Orchestrator:
    def __init__(self):
        self.mcp_client = SimpleMCPClient()
        self.agents = create_agents(self.mcp_client)
        self.session_manager = SessionManager(session_timeout_minutes=60)
        
    def run_mesh(self, user_input: str, session_id: str = None) -> tuple[str, str]:
        """
        Run the agent mesh with conversation memory.
        
        Args:
            user_input: The user's message
            session_id: Optional session ID for conversation continuity
            
        Returns:
            tuple: (response text, session_id)
        """
        total_start = time.time()
        print(f"\n>>> New Request: {user_input}")
        
        # 1. Get or create session
        if session_id:
            context = self.session_manager.get_session(session_id)
            print(f">>> Continuing conversation (Session: {session_id[:8]}...)")
            print(f">>> Previous messages: {len(context.history)}")
        else:
            session_id = self.session_manager.create_session(user_input)
            context = self.session_manager.get_session(session_id)
            print(f">>> New conversation (Session: {session_id[:8]}...)")
        
        # 2. Update user intent if this is first message or a new topic
        if not context.user_intent or len(context.history) == 0:
            context.user_intent = user_input
        
        # 3. Add new user message to history
        context.add_message("user", user_input)
        
        # 4. Reset hop count for this turn
        context.hop_count = 0
        
        # 5. Start with Guardrail
        current_agent_name = "Guardrail"
        
        # 6. Mesh Loop with loop detection
        agent_sequence = []  # Track which agents have been called
        
        while context.hop_count < 15:
            context.hop_count += 1
            
            if current_agent_name == "STOP":
                break
                
            if current_agent_name not in self.agents:
                print(f"Error: Agent {current_agent_name} not found. Defaulting to Critic.")
                current_agent_name = "Critic"
            
            # Loop Detection: Check if Triage Agent is being called repeatedly
            agent_sequence.append(current_agent_name)
            if len(agent_sequence) >= 3:
                # Check for Triage → Critic → Triage → Critic pattern
                last_three = agent_sequence[-3:]
                if current_agent_name == "Triage Agent" and agent_sequence.count("Triage Agent") >= 3:
                    print(f"⚠️  WARNING: Triage Agent called {agent_sequence.count('Triage Agent')} times. Forcing handoff to Critic to prevent loop.")
                    context.add_finding("[SYSTEM]: Loop prevention activated - routing directly to Critic for final synthesis")
                    current_agent_name = "Critic"
            
            agent = self.agents[current_agent_name]
            
            # Run Agent
            next_agent_name = agent.run(context)
            
            # Transition
            current_agent_name = next_agent_name
        
        total_time = time.time() - total_start
        print(f"\n{'='*60}")
        print(f"⏱️  TOTAL EXECUTION TIME: {total_time:.2f}s")
        print(f"{'='*60}\n")
        
        # 7. Save updated context to session
        self.session_manager.update_session(session_id, context)
            
        # 8. Return Final Response and Session ID
        # The last message from the Critic (or whoever finished) should be the response.
        if context.history:
            last_msg = context.history[-1]
            return last_msg.content, session_id
        return "System Error: No response generated.", session_id
