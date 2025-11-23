from .models import AgentContext
from .agents import create_agents
from .mcp_client import SimpleMCPClient
from .session_manager import SessionManager
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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
        current_agent_names = ["Guardrail"]
        
        # 6. Mesh Loop with loop detection
        agent_sequence = []  # Track which agents have been called
        
        while context.hop_count < 15:
            context.hop_count += 1
            
            # Check for STOP condition
            if "STOP" in current_agent_names:
                break
            
            # Filter out invalid agents
            valid_agents = []
            for agent_name in current_agent_names:
                if agent_name not in self.agents:
                    print(f"Error: Agent {agent_name} not found. Defaulting to Critic.")
                    valid_agents.append("Critic")
                else:
                    valid_agents.append(agent_name)
            
            current_agent_names = valid_agents
            
            # Loop Detection: Check if Triage Agent is being called repeatedly
            for agent_name in current_agent_names:
                agent_sequence.append(agent_name)
            
            if agent_sequence.count("Triage Agent") >= 3:
                print(f"⚠️  WARNING: Triage Agent called {agent_sequence.count('Triage Agent')} times. Forcing handoff to Critic to prevent loop.")
                context.add_finding("[SYSTEM]: Loop prevention activated - routing directly to Critic for final synthesis")
                current_agent_names = ["Critic"]
            
            # Execute agents in parallel or sequentially based on count
            if len(current_agent_names) == 1:
                # Single agent - execute directly
                agent = self.agents[current_agent_names[0]]
                next_agent_names = agent.run(context)
                current_agent_names = next_agent_names
            else:
                # Multiple agents - execute in parallel
                print(f"\n{'='*60}")
                print(f"⚡ PARALLEL EXECUTION: {len(current_agent_names)} agents running concurrently")
                print(f"   Agents: {', '.join(current_agent_names)}")
                print(f"{'='*60}")
                
                parallel_start = time.time()
                next_agent_names = []
                
                # Use ThreadPoolExecutor for parallel execution
                with ThreadPoolExecutor(max_workers=len(current_agent_names)) as executor:
                    # Submit all agents for parallel execution
                    future_to_agent = {
                        executor.submit(self.agents[agent_name].run, context): agent_name 
                        for agent_name in current_agent_names
                    }
                    
                    # Collect results as they complete
                    for future in as_completed(future_to_agent):
                        agent_name = future_to_agent[future]
                        try:
                            result = future.result()
                            next_agent_names.extend(result)
                        except Exception as e:
                            print(f"  ❌ Error in {agent_name}: {e}")
                            import traceback
                            traceback.print_exc()
                            next_agent_names.append("Critic")
                
                parallel_time = time.time() - parallel_start
                print(f"\n{'='*60}")
                print(f"⚡ PARALLEL BATCH COMPLETE: {parallel_time:.2f}s")
                print(f"   Next agents: {', '.join(next_agent_names)}")
                print(f"{'='*60}\n")
                
                # Deduplicate next agents (if multiple agents handoff to same agent)
                current_agent_names = list(dict.fromkeys(next_agent_names))  # Preserves order
        
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
