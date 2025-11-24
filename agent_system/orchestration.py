from .models import AgentContext
from .agents import create_agents
from .mcp_client import SimpleMCPClient
from .session_manager import SessionManager
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import os
from pathlib import Path

class Orchestrator:
    def __init__(self):
        self.mcp_client = SimpleMCPClient()
        self.agents = create_agents(self.mcp_client)
        self.session_manager = SessionManager(session_timeout_minutes=60)
        
        # Response Caching - for repeated queries
        self._response_cache = {}  # cache_key -> (response, session_id, timestamp)
        self._response_cache_lock = threading.Lock()
        self._response_cache_ttl = 300  # 5 minutes for session-based responses
        
        # Data Version Tracking - track modification times of user data files
        self._data_files = [
            'servers/user_data/data/biomarkers.json',
            'servers/user_data/data/activity.json',
            'servers/user_data/data/food_journal.json',
            'servers/user_data/data/sleep.json',
            'servers/user_data/data/profile.json'
        ]
        self._last_data_check = {}  # file_path -> last_modified_time
        self._init_data_tracking()
        
    def _init_data_tracking(self):
        """Initialize tracking of user data file modification times."""
        for file_path in self._data_files:
            try:
                if os.path.exists(file_path):
                    self._last_data_check[file_path] = os.path.getmtime(file_path)
            except Exception:
                pass  # File doesn't exist yet or can't be read
    
    def _check_data_updates(self, context: AgentContext):
        """Check if user data files have been modified and increment version if so."""
        data_changed = False
        for file_path in self._data_files:
            try:
                if os.path.exists(file_path):
                    current_mtime = os.path.getmtime(file_path)
                    last_mtime = self._last_data_check.get(file_path, 0)
                    
                    if current_mtime > last_mtime:
                        data_changed = True
                        self._last_data_check[file_path] = current_mtime
                        print(f"  📝 Data file updated: {Path(file_path).name}")
            except Exception:
                pass  # File access error, skip
        
        if data_changed:
            context.increment_data_version()
            return True
        return False
    
    def _get_response_cache_key(self, user_input: str, session_id: str = None, data_version: int = 0) -> str:
        """Generate cache key from user input, session, and data version."""
        # Include session_id and data_version to make cache session-aware and data-version aware
        # When data_version changes, cache key changes, invalidating old cached responses
        key_str = f"{session_id}:{data_version}:{user_input.lower().strip()}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_from_response_cache(self, cache_key: str) -> tuple:
        """Get response from cache if valid. Returns (response, session_id, widgets, hit) tuple."""
        with self._response_cache_lock:
            if cache_key in self._response_cache:
                response, session_id, widgets, timestamp = self._response_cache[cache_key]
                age = time.time() - timestamp
                if age < self._response_cache_ttl:
                    return response, session_id, widgets, True
                else:
                    # Expired, remove it
                    del self._response_cache[cache_key]
        return None, None, None, False
    
    def _put_in_response_cache(self, cache_key: str, response: str, session_id: str, widgets: list):
        """Store response and widgets in cache with current timestamp."""
        with self._response_cache_lock:
            self._response_cache[cache_key] = (response, session_id, widgets, time.time())
            # Cleanup old entries (keep cache size manageable)
            if len(self._response_cache) > 1000:
                # Remove oldest 20%
                sorted_items = sorted(self._response_cache.items(), key=lambda x: x[1][3])
                for key, _ in sorted_items[:200]:
                    del self._response_cache[key]
    
    def run_mesh(self, user_input: str, session_id: str = None) -> tuple[str, str, list]:
        """
        Run the agent mesh with conversation memory and response caching.
        
        Args:
            user_input: The user's message
            session_id: Optional session ID for conversation continuity
            
        Returns:
            tuple: (response text, session_id, widgets)
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
        
        # 2. Check for data updates and increment version if needed
        self._check_data_updates(context)
        context.trace = [f"User input: {user_input}"]
        
        # 3. Check response cache (only for queries with existing session)
        if session_id:
            cache_key = self._get_response_cache_key(user_input, session_id, context.data_version)
            cached_response, cached_session_id, cached_widgets, hit = self._get_from_response_cache(cache_key)
            if hit:
                cache_time = time.time() - total_start
                print(f"\n{'='*60}")
                print(f"💾 RESPONSE CACHE HIT: Returning cached response (data v{context.data_version})")
                if cached_widgets:
                    print(f"📦 Returning {len(cached_widgets)} cached widget(s)")
                print(f"⏱️  TOTAL EXECUTION TIME: {cache_time:.2f}s (instant!)")
                print(f"{'='*60}\n")
                return cached_response, cached_session_id, cached_widgets or [], context.trace
        
        # Clear any widgets left over from a previous turn
        context.pending_widgets.clear()
        if not context.state.pending_offer and context.flags:
            keys_to_clear = [k for k in context.flags if k.startswith("needs_")]
            for k in keys_to_clear:
                del context.flags[k]
        
        # 4. Update user intent if this is first message or a new topic
        if not context.user_intent or len(context.history) == 0:
            context.user_intent = user_input
        
        # 5. Add new user message to history
        is_new_session = len(context.history) == 0
        context.add_message("user", user_input)
        self._update_state_for_turn(context, user_input, is_new_session)
        
        # 6. Reset hop count for this turn
        context.hop_count = 0
        
        # 7. Run Guardrail first for safety / emergency handling
        agent_sequence = []
        guardrail_agent = self.agents["Guardrail"]
        guardrail_result = guardrail_agent.run(context)
        agent_sequence.append("Guardrail")
        
        if "STOP" in guardrail_result:
            current_agent_names = ["STOP"]
        else:
            current_agent_names = self._determine_entry_agents(context)
        
        # 8. Mesh Loop with loop detection
        
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
                deduped_next = list(dict.fromkeys(next_agent_names))  # Preserves order
                print(f"\n{'='*60}")
                print(f"⚡ PARALLEL BATCH COMPLETE: {parallel_time:.2f}s")
                print(f"   Next agents: {', '.join(deduped_next)}")
                print(f"{'='*60}\n")
                
                # Deduplicate next agents (if multiple agents handoff to same agent)
                current_agent_names = deduped_next
        
        total_time = time.time() - total_start
        print(f"\n{'='*60}")
        print(f"⏱️  TOTAL EXECUTION TIME: {total_time:.2f}s")
        print(f"{'='*60}\n")
        
        # 9. Save updated context to session
        self.session_manager.update_session(session_id, context)
            
        # 10. Return Final Response, Session ID, and Widgets
        # The last message from the Critic (or whoever finished) should be the response.
        if context.history:
            last_msg = context.history[-1]
            final_response = last_msg.content
            widgets = list(context.pending_widgets)
            context.pending_widgets.clear()
            
            # Cache the response and widgets for future identical queries (with current data version)
            cache_key = self._get_response_cache_key(user_input, session_id, context.data_version)
            self._put_in_response_cache(cache_key, final_response, session_id, widgets)
            print(f"💾 Response + widgets cached for {self._response_cache_ttl}s (data v{context.data_version})\n")
            
            # Log widgets being returned
            if widgets:
                print(f"📦 Returning {len(widgets)} widget(s)")
                for w in widgets:
                    print(f"  - {w['type']}")
            
            return final_response, session_id, widgets, context.trace
        return "System Error: No response generated.", session_id, [], context.trace

    def _infer_intent(self, user_input: str) -> str:
        normalized = user_input.lower()
        plan_markers = {
            "plan", "fix", "improve", "recommend", "action", "what can i do",
            "how do i", "give me steps", "treatment", "program"
        }
        for marker in plan_markers:
            if marker in normalized:
                return "plan"
        return "diagnosis"

    def _update_state_for_turn(self, context: AgentContext, user_input: str, is_new_session: bool):
        state = context.state
        normalized = user_input.strip().lower()
        confirmations = {
            "yes", "yes please", "sure", "please do", "let's do it",
            "do it", "absolutely", "ok", "okay", "yeah", "yep"
        }
        declines = {"no", "not now", "maybe later", "no thanks", "stop"}
        
        if state.stage == "awaiting_confirmation" and state.pending_offer:
            if normalized in confirmations:
                pending = state.pending_offer
                state.confirm_offer()
                state.set_intent("plan")
                context.add_trace(f"User confirmed offer '{pending}'")
                return
            if normalized in declines:
                context.add_trace(f"User declined offer '{state.pending_offer}'")
                state.clear_offer()
            else:
                context.add_trace("Pending offer ignored; resetting to triage.")
                state.clear_offer()
        
        intent = self._infer_intent(user_input)
        state.set_intent(intent)
        if state.stage != "plan_delivery":
            state.set_stage("triage" if is_new_session or intent in {"diagnosis", "plan"} else "triage")

    def _determine_entry_agents(self, context: AgentContext):
        state = context.state
        if state.stage == "plan_delivery" and state.confirmed_targets:
            agents = list(dict.fromkeys(state.confirmed_targets))
            context.add_trace(f"Plan delivery -> {agents}")
            print(f"  🎯 Executing confirmed plan with: {', '.join(agents)}")
            return agents
        return ["Triage Agent"]
