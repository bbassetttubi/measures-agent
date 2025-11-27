from .models import AgentContext, ConversationState
from .agents import create_agents
from .mcp_client import SimpleMCPClient
from .session_manager import SessionManager
from .intelligence import IntentClassifier
from .feedback import record_feedback
from analytics.feedback_analytics import FeedbackAnalytics
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
import hashlib
import os
from pathlib import Path
import re
from typing import Optional, List, Dict


class Orchestrator:
    def __init__(self):
        self.mcp_client = SimpleMCPClient()
        self.agents = create_agents(self.mcp_client)
        self.session_manager = SessionManager(session_timeout_minutes=60)
        self.intent_classifier = IntentClassifier()
        self.feedback_analytics = FeedbackAnalytics()
        
        self._response_cache = {}
        self._response_cache_lock = threading.Lock()
        self._response_cache_ttl = 300
        
        self._data_files = [
            'servers/user_data/data/biomarkers.json',
            'servers/user_data/data/activity.json',
            'servers/user_data/data/food_journal.json',
            'servers/user_data/data/sleep.json',
            'servers/user_data/data/profile.json'
        ]
        self._last_data_check = {}
        self._init_data_tracking()
        
    def _init_data_tracking(self):
        for file_path in self._data_files:
            try:
                if os.path.exists(file_path):
                    self._last_data_check[file_path] = os.path.getmtime(file_path)
            except Exception:
                pass
    
    def _check_data_updates(self, context: AgentContext):
        data_changed = False
        for file_path in self._data_files:
            try:
                if os.path.exists(file_path):
                    current_mtime = os.path.getmtime(file_path)
                    last_mtime = self._last_data_check.get(file_path, 0)
                    if current_mtime > last_mtime:
                        data_changed = True
                        self._last_data_check[file_path] = current_mtime
            except Exception:
                pass
        if data_changed:
            context.increment_data_version()
            return True
        return False
    
    def _get_response_cache_key(self, user_input: str, session_id: str = None, data_version: int = 0) -> str:
        key_str = f"{session_id}:{data_version}:{user_input.lower().strip()}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_from_response_cache(self, cache_key: str) -> tuple:
        with self._response_cache_lock:
            if cache_key in self._response_cache:
                response, session_id, widgets, timestamp = self._response_cache[cache_key]
                age = time.time() - timestamp
                if age < self._response_cache_ttl:
                    return response, session_id, widgets, True
                else:
                    del self._response_cache[cache_key]
        return None, None, None, False
    
    def _put_in_response_cache(self, cache_key: str, response: str, session_id: str, widgets: list):
        with self._response_cache_lock:
            self._response_cache[cache_key] = (response, session_id, widgets, time.time())
            if len(self._response_cache) > 1000:
                sorted_items = sorted(self._response_cache.items(), key=lambda x: x[1][3])
                for key, _ in sorted_items[:200]:
                    del self._response_cache[key]
    
    def run_mesh(self, user_input: str, session_id: str = None) -> tuple[str, str, list]:
        total_start = time.time()
        print(f"\n>>> New Request: {user_input}")
        
        if session_id:
            context = self.session_manager.get_session(session_id)
            print(f">>> Continuing conversation (Session: {session_id[:8]}...)")
        else:
            session_id = self.session_manager.create_session(user_input)
            context = self.session_manager.get_session(session_id)
            print(f">>> New conversation (Session: {session_id[:8]}...)")
        
        self.feedback_analytics.refresh()
        context.insights["feedback_summary"] = self.feedback_analytics.get_summary()
        
        self._check_data_updates(context)
        context.trace = [f"User input: {user_input}"]
        
        if session_id:
            cache_key = self._get_response_cache_key(user_input, session_id, context.data_version)
            cached_response, cached_session_id, cached_widgets, hit = self._get_from_response_cache(cache_key)
            if hit:
                print(f"💾 RESPONSE CACHE HIT")
                return cached_response, cached_session_id, cached_widgets or [], context.trace
        
        context.pending_widgets.clear()
        
        if not context.user_intent or len(context.history) == 0:
            context.user_intent = user_input
        
        context.add_message("user", user_input)
        self._update_state_for_turn(context, user_input)
        
        context.hop_count = 0
        
        # SPECULATIVE EXECUTION: Start Conversation Planner immediately
        speculative_agents = {"Conversation Planner"}
        plan_specialist_agents = ["Nutritionist", "Fitness Coach", "Sleep Doctor", "Mindfulness Coach"]
        
        state = context.state
        if state.focus == "diagnosis" and not context.get_flag("biomarkers_ready"):
            speculative_agents.add("Physician")
        
        speculative_agents = {a for a in speculative_agents if a in self.agents}
        print(f"🚀 Speculative Execution: Guardrail + {', '.join(speculative_agents)}")
        
        active_futures: Dict[str, Future] = {}
        
        with ThreadPoolExecutor(max_workers=len(speculative_agents) + 1 + 4) as executor:
            active_futures["Guardrail"] = executor.submit(self.agents["Guardrail"].run, context)
            for agent_name in speculative_agents:
                active_futures[agent_name] = executor.submit(self.agents[agent_name].run, context)
            
            try:
                guardrail_result = active_futures["Guardrail"].result()
            except Exception as e:
                print(f"❌ Guardrail Error: {e}")
                guardrail_result = ["STOP"]
            
            if "STOP" in guardrail_result:
                print("🛑 Guardrail triggered STOP.")
                current_agent_names = ["STOP"]
            else:
                current_agent_names = ["Conversation Planner"]
            
            agent_sequence = ["Guardrail"]
            
            while context.hop_count < 15:
                context.hop_count += 1
                if "STOP" in current_agent_names:
                    break
                
                valid_agents = []
                for agent_name in current_agent_names:
                    if agent_name not in self.agents:
                        valid_agents.append("Critic")
                    else:
                        valid_agents.append(agent_name)
                current_agent_names = list(dict.fromkeys(valid_agents))
                
                for agent_name in current_agent_names:
                    agent_sequence.append(agent_name)
                
                # Loop prevention
                if agent_sequence.count("Conversation Planner") >= 3:
                    context.add_finding("[SYSTEM]: Loop prevention - routing to Critic")
                    current_agent_names = ["Critic"]
                
                next_agent_names = []

                if len(current_agent_names) == 1:
                    agent_name = current_agent_names[0]
                    if agent_name in active_futures:
                        print(f"⚡ Using speculative result for {agent_name}")
                        try:
                            result = active_futures[agent_name].result()
                            del active_futures[agent_name]
                            next_agent_names.extend(result)
                        except Exception as e:
                            print(f"❌ Error in speculative {agent_name}: {e}")
                            next_agent_names.append("Critic")
                    else:
                        next_agent_names = self.agents[agent_name].run(context)
                else:
                    print(f"\n⚡ PARALLEL EXECUTION: {len(current_agent_names)} agents: {', '.join(current_agent_names)}")
                    batch_futures = {}
                    for agent_name in current_agent_names:
                        if agent_name in active_futures:
                            print(f"⚡ Using running future for {agent_name}")
                            batch_futures[active_futures[agent_name]] = agent_name
                            del active_futures[agent_name]
                        else:
                            f = executor.submit(self.agents[agent_name].run, context)
                            batch_futures[f] = agent_name
                    
                    for future in as_completed(batch_futures):
                        agent_name = batch_futures[future]
                        try:
                            result = future.result()
                            next_agent_names.extend(result)
                        except Exception as e:
                            print(f"  ❌ Error in {agent_name}: {e}")
                            next_agent_names.append("Critic")
                
                deduped_next = list(dict.fromkeys(next_agent_names))
                
                # If user confirmed they want a plan, ensure all plan specialists are routed
                if context.get_flag("plan_request_pending"):
                    missing_agents = [agent for agent in plan_specialist_agents if agent not in deduped_next]
                    if missing_agents:
                        if "Conversation Planner" not in deduped_next:
                            deduped_next.append("Conversation Planner")
                    else:
                        context.set_flag("plan_request_pending", False)
                pending_domains = context.get_pending_plan_domains()
                if pending_domains:
                    required_agents = {
                        "nutrition": "Nutritionist",
                        "fitness": "Fitness Coach",
                        "sleep": "Sleep Doctor",
                        "mindfulness": "Mindfulness Coach",
                        "supplements": None
                    }
                    deduped_next = [agent for agent in deduped_next if agent != "Critic"]
                    for domain in pending_domains:
                        agent_name = required_agents.get(domain)
                        if agent_name and agent_name not in deduped_next:
                            deduped_next.append(agent_name)
                current_agent_names = deduped_next
        
        total_time = time.time() - total_start
        print(f"⏱️  TOTAL EXECUTION TIME: {total_time:.2f}s")
        
        self.session_manager.update_session(session_id, context)
            
        if context.history:
            last_msg = context.history[-1]
            final_response = last_msg.content
            widgets = list(context.pending_widgets)
            context.pending_widgets.clear()
            
            cache_key = self._get_response_cache_key(user_input, session_id, context.data_version)
            self._put_in_response_cache(cache_key, final_response, session_id, widgets)
            
            if widgets:
                print(f"📦 Returning {len(widgets)} widget(s) to CLIENT", flush=True)
                for w in widgets:
                    print(f"  - {w['type']}", flush=True)
            else:
                print("🚫 No widgets returned to client")
            
            return final_response, session_id, widgets, context.trace
        return "System Error: No response generated.", session_id, [], context.trace

    def _update_state_for_turn(self, context: AgentContext, user_input: str):
        state = context.state
        
        context_str = f"stage={state.stage}, focus={state.focus}"
        classification = self.intent_classifier.classify(user_input, context_str)
        
        focus = classification.get("focus") or state.focus or "diagnosis"
        intent = classification.get("intent") or focus
        confirmation_status = (classification.get("confirmation_status") or "none").lower()
        
        context.add_trace(f"LLM classification: {classification}")
        print(f"  🧠 Intent Classification: {classification}")
        record_feedback("intent_classified", classification)
        
        # Handle Confirmation Logic
        if confirmation_status in {"confirmed", "yes", "y", "accept", "accepted", "affirmed"}:
            state.set_focus("plan")
            state.set_intent("plan")
            context.set_flag("plan_request_pending", True)
            return
        elif confirmation_status in {"declined", "no", "n", "rejected"}:
            state.set_focus("diagnosis")
            state.set_intent("diagnosis")
            context.set_flag("plan_request_pending", False)
            return
        
        state.set_focus(focus)
        state.set_intent(intent)
