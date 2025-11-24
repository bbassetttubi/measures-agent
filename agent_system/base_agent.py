import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool
from typing import List, Dict, Any, Optional
from .models import AgentContext
from .registry import AgentRegistry
from .mcp_client import SimpleMCPClient
from .tools.widget_tools import WidgetToolset
import os
import sys
from dotenv import load_dotenv
import time
import hashlib
import json
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))

# Model Instance Cache - shared across all agents
# Caches model instances to avoid recreating them with identical configurations
_model_cache = {}
_model_cache_lock = __import__('threading').Lock()

OFFER_TARGET_MAP = {
    "comprehensive_plan": ["Nutritionist", "Fitness Coach", "Sleep Doctor", "Mindfulness Coach"],
    "nutrition_plan": ["Nutritionist"],
    "fitness_plan": ["Fitness Coach"],
    "sleep_plan": ["Sleep Doctor"],
    "mindfulness_plan": ["Mindfulness Coach"],
}

class Agent:
    def __init__(
        self,
        name: str,
        role: str,
        system_instruction: str,
        mcp_client: SimpleMCPClient,
        enable_widget_tools: bool = False,
        allowed_mcp_tools: Optional[List[str]] = None,
        default_next_agents: Optional[List[str]] = None,
        enable_handoff: bool = True,
        allow_emergency_stop: bool = False,
    ):
        self.name = name
        self.role = role
        self.base_instruction = system_instruction
        self.mcp_client = mcp_client
        self.enable_widget_tools = enable_widget_tools
        self.widget_toolset = WidgetToolset() if enable_widget_tools else None
        self.widgets = []  # Store widgets to be returned with response
        self._current_widget_calls = set()
        self._summary_prompted = False
        self.cacheable_tools = {"get_biomarker_ranges"}
        self.allowed_mcp_tools = set(allowed_mcp_tools) if allowed_mcp_tools else None
        self.default_next_agents = default_next_agents
        self.enable_handoff = enable_handoff
        self.allow_emergency_stop = allow_emergency_stop
        
        # Configure the model
        self.model_name = "gemini-2.5-flash" # SOTA model

    def _should_stream_to_client(self) -> bool:
        """Only certain agents (Guardrail, Critic) should surface text directly to the UI."""
        return self.name in {"Guardrail", "Critic"}

    def _write_text_chunk(self, text: str, newline: bool = False, prefix: bool = True):
        """Stream text either to SSE (sys.stdout) or only to server logs (sys.__stdout__)."""
        target = sys.stdout if self._should_stream_to_client() else sys.__stdout__
        if prefix:
            target.write("  💬 ")
        target.write(text)
        if newline:
            target.write("\n")
        target.flush()
        
    def _build_system_prompt(self, context: AgentContext) -> str:
        registry_prompt = AgentRegistry.get_registry_prompt()
        
        state = context.state
        context_str = f"""
        CURRENT CONTEXT:
        - User Intent (raw): {context.user_intent}
        - Conversation Intent: {state.intent}
        - Conversation Focus: {state.focus}
        - Conversation Stage: {state.stage}
        - Pending Offer: {state.pending_offer if state.pending_offer else "None"}
        - Offer Targets: {state.offer_targets if state.offer_targets else "None"}
        - Accumulated Findings: {context.accumulated_findings}
        - Pending Tasks: {context.pending_tasks}
        - System Flags: {context.flags}
        """
        
        return f"""
        You are the **{self.name}**.
        Role: {self.role}
        
        {self.base_instruction}
        
        {registry_prompt}
        
        {context_str}
        
        INSTRUCTIONS:
        1. Analyze the context and history.
        2. Use your tools to gather information or perform tasks.
        3. If you need another agent's expertise, use `transfer_handoff`.
        4. If you have completed your part, handoff to the next logical agent or the 'Critic' if finished.
        5. Always update the context with new findings before handing off.
        """

    def _filter_mcp_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.allowed_mcp_tools:
            return tools
        filtered = []
        for group in tools:
            decls = [
                decl for decl in group.get("function_declarations", [])
                if decl["name"] in self.allowed_mcp_tools
            ]
            if decls:
                filtered.append({"function_declarations": decls})
        return filtered

    def _get_widget_tools(self):
        """Get widget tool declarations for this agent."""
        if not self.widget_toolset:
            return {"function_declarations": []}
        return self.widget_toolset.get_tool_declarations()
    
    def _get_handoff_tool(self):
        return {
            "function_declarations": [
                {
                    "name": "transfer_handoff",
                    "description": "Transfers control to one or more agents. For concurrent execution, specify multiple target agents as a comma-separated string (e.g., 'Physician,Nutritionist,Fitness Coach'). All specified agents will execute in parallel.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "target_agent": {"type": "STRING", "description": "Name(s) of the agent(s) to transfer to. For multiple agents, use comma-separated values: 'Agent1,Agent2,Agent3'"},
                            "reason": {"type": "STRING", "description": "Reason for the transfer."},
                            "new_finding": {"type": "STRING", "description": "Optional finding to add to context."}
                        },
                        "required": ["target_agent", "reason"]
                    }
                }
            ]
        }

    def _get_emergency_stop_tool(self):
        return {
            "function_declarations": [
                {
                    "name": "trigger_emergency_stop",
                    "description": "Immediately stop the conversation and instruct the user to contact emergency services.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "reason": {
                                "type": "STRING",
                                "description": "Short description of the emergency condition or policy violation."
                            }
                        },
                        "required": ["reason"]
                    }
                }
            ]
        }

    def _normalize_tool_args(self, obj):
        """
        Recursively convert protobuf/map/repeated structures into plain Python types
        so they can be serialized or compared reliably.
        """
        if isinstance(obj, dict):
            return {k: self._normalize_tool_args(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [self._normalize_tool_args(v) for v in obj]
        if hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes)):
            try:
                return [self._normalize_tool_args(v) for v in list(obj)]
            except TypeError:
                pass
        return obj

    def _handle_widget_tool(self, tool_name: str, args: Dict[str, Any], context: AgentContext) -> bool:
        """
        Execute native widget tools and deduplicate repeated calls.
        
        Returns:
            bool: True if the tool_name was handled as a widget tool.
        """
        if not self.widget_toolset:
            return False
        if not (tool_name.startswith("return_") and "_widget" in tool_name):
            return False
        
        normalized_args = self._normalize_tool_args(args)
        
        if not self.widget_toolset.is_widget_tool(tool_name):
            return False
        
        call_signature = self.widget_toolset.get_signature(tool_name, normalized_args)
        if call_signature in self._current_widget_calls:
            print(f"  > Skipping duplicate widget call: {tool_name}({normalized_args})")
            context.add_trace(f"{self.name}: skipped duplicate widget {tool_name}")
            return True
        self._current_widget_calls.add(call_signature)
        
        execution = self.widget_toolset.execute(tool_name, normalized_args)
        widget_data = execution.get("widget")
        duration_ms = execution.get("duration_ms", 0)
        
        if widget_data:
            self.widgets.append(widget_data)
            print(f"  ✅ Widget added: {widget_data['type']} ({duration_ms}ms)")
            context.add_trace(f"{self.name}: added widget {widget_data['type']}")
        else:
            print(f"  ⚠️ Widget data unavailable for {tool_name}({normalized_args})")
            context.add_trace(f"{self.name}: widget data unavailable for {tool_name}")
        return True

    def _extract_text_from_parts(self, response) -> str:
        """Safely collect all text parts from a model response."""
        text_chunks = []
        for part in getattr(response, "parts", []):
            try:
                part_text = getattr(part, "text", None)
                if part_text:
                    text_chunks.append(part_text)
            except ValueError:
                # Raised when the part represents a function call rather than text
                continue
        return "".join(text_chunks).strip()

    def _get_model_cache_key(self, system_prompt: str, tools: list) -> str:
        """Generate cache key for model configuration."""
        # For simplicity, use agent name as cache key since system prompts are per-agent
        # and tools are the same for all instances of an agent
        return f"{self.name}:{self.model_name}"
    
    def _get_cached_model(self, system_prompt: str, tools: list):
        """Get or create a cached model instance."""
        cache_key = self._get_model_cache_key(system_prompt, tools)
        
        with _model_cache_lock:
            if cache_key in _model_cache:
                return _model_cache[cache_key], True  # Cache hit
            
            # Create new model and cache it
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_prompt,
                tools=tools
            )
            _model_cache[cache_key] = model
            return model, False  # Cache miss
    
    def run(self, context: AgentContext) -> List[str]:
        """
        Runs the agent. Returns a list of agent names to execute next (for parallel execution) or ['STOP'] if finished (Critic).
        """
        agent_start = time.time()
        print(f"\n--- Agent Active: {self.name} ---")
        context.add_trace(f"{self.name}: started run (hop {context.hop_count})")
        
        # 1. Setup Tools (MCP + Widget + Handoff)
        mcp_tools = self._filter_mcp_tools(self.mcp_client.get_tools_definitions())
        widget_tools = self._get_widget_tools()
        all_tools = list(mcp_tools)
        if widget_tools["function_declarations"]:
            all_tools.append(widget_tools)
        if self.enable_handoff:
            all_tools.append(self._get_handoff_tool())
        if self.allow_emergency_stop:
            all_tools.append(self._get_emergency_stop_tool())
        
        # Clear per-run widget tracking
        self.widgets = []
        self._current_widget_calls = set()
        self._summary_prompted = False
        
        # 2. Setup Model with caching
        system_prompt = self._build_system_prompt(context)
        model, cache_hit = self._get_cached_model(system_prompt, all_tools)
        
        if not cache_hit:
            print(f"  🔧 Model instance created and cached")
        
        # 3. Chat Session (Stateless for the agent, but we inject history)
        # We need to convert our Message model to Gemini history format
        gemini_history = []
        for msg in context.history:
            role = "user" if msg.role == "user" else "model"
            # Simple mapping. In a real system, we'd handle tool outputs in history more carefully.
            gemini_history.append({"role": role, "parts": [msg.content]})
            
        chat = model.start_chat(history=gemini_history)
        
        # 4. Send Request with streaming
        llm_start = time.time()
        response_stream = None
        full_text = ""
        has_text = False
        chunks = []
        streamed_text = False
        
        try:
            response_stream = chat.send_message("Proceed with your task based on the context.", stream=True)
            for chunk in response_stream:
                chunks.append(chunk)
                # Check if this chunk has text (not a function call)
                try:
                    if chunk.text:
                        has_text = True
                        streamed_text = True
                        self._write_text_chunk(chunk.text)
                        full_text += chunk.text
                except ValueError:
                    # This chunk is a function call, not text - skip streaming for it
                    pass
        except Exception as stream_error:
            print(f"\n  ❌ Streaming error detected: {stream_error}. Retrying without streaming...")
            try:
                chat.rewind()
            except Exception:
                pass
            fallback_response = chat.send_message("Proceed with your task based on the context.")
            chunks = [fallback_response]
            full_text = self._extract_text_from_parts(fallback_response)
            if full_text:
                has_text = True
                streamed_text = True
                self._write_text_chunk(full_text, newline=True)
        else:
            if streamed_text:
                self._write_text_chunk("", newline=True, prefix=False)
        finally:
            if not streamed_text and not has_text:
                self._write_text_chunk("(function call)", newline=True)
        
        llm_time = time.time() - llm_start
        print(f"  ⏱️  LLM Response: {llm_time:.2f}s")
        
        # The last chunk contains the complete response with all parts
        final_response = chunks[-1] if chunks else None
        
        if not final_response:
            return self._get_completion_targets()  # Fallback
        
        # 5. Handle Tool Calls Loop
        # Gemini SDK handles the loop if we use automatic function calling, but we want to intercept 'transfer_handoff'.
        # So we will do a manual loop or check the parts.
        
        # OPTIMIZATION: Collect all MCP tool calls for parallel execution
        mcp_tool_calls = []
        for part in final_response.parts:
            if fn := part.function_call:
                tool_name = fn.name
                args = self._normalize_tool_args(dict(fn.args))
                
                print(f"  > Tool Call: {tool_name}({args})")
                context.add_trace(f"{self.name}: tool_call {tool_name} ({args})")
                
                if self._handle_widget_tool(tool_name, args, context):
                    continue  # Already processed as a native widget tool
                
                if tool_name == "transfer_handoff":
                    # Guardrail should only use STOP handoffs; ignore others so orchestrator can decide.
                    if self.name == "Guardrail":
                        target_arg = args.get("target_agent", "").strip()
                        if target_arg.upper() != "STOP":
                            print(f"  ⚠️  Guardrail attempted to route to '{target_arg}', ignoring (orchestrator handles routing).")
                            context.add_trace(f"Guardrail transfer to '{target_arg}' ignored; state machine will route.")
                            continue
                    if full_text:
                        self._finalize_text_response(full_text, context, allow_widgets=False)
                        full_text = ""
                    target = args["target_agent"]
                    reason = args["reason"]
                    if "new_finding" in args and args["new_finding"]:
                        finding = args["new_finding"]
                        print(f"  🔎 New finding from {self.name}: {finding}")
                        context.add_finding(f"[{self.name}]: {finding}")
                        if "OFFER:" in finding:
                            offer_value = finding.split("OFFER:")[-1].strip()
                            self._register_offer(context, offer_value)
                    
                    # Parse target agents (can be comma-separated for parallel execution)
                    target_agents = [agent.strip() for agent in target.split(",")]
                    
                    if len(target_agents) > 1:
                        context.add_message("model", f"Handing off to {', '.join(target_agents)} (parallel): {reason}", sender=self.name)
                        print(f"  🔀 Parallel Handoff to: {', '.join(target_agents)}")
                    else:
                        context.add_message("model", f"Handing off to {target}: {reason}", sender=self.name)
                    context.add_trace(f"{self.name}: handoff -> {target_agents}")
                    
                    # Store widgets in context before handoff
                    if self.widgets:
                        context.pending_widgets.extend(self.widgets)
                    
                    agent_total = time.time() - agent_start
                    print(f"  ⏱️  Total Agent Time: {agent_total:.2f}s")
                    return target_agents
                elif tool_name == "trigger_emergency_stop" and self.allow_emergency_stop:
                    reason = args.get("reason", "Emergency condition detected.")
                    if full_text:
                        self._finalize_text_response(full_text, context, allow_widgets=False)
                        full_text = ""
                    print(f"  🛑 Emergency stop triggered: {reason}")
                    context.add_trace(f"{self.name}: emergency stop -> {reason}")
                    context.add_message("model", f"Emergency stop triggered: {reason}", sender=self.name)
                    agent_total = time.time() - agent_start
                    print(f"  ⏱️  Total Agent Time: {agent_total:.2f}s")
                    return ["STOP"]
                else:
                    entry = {"name": tool_name, "args": args}
                    if tool_name in self.cacheable_tools:
                        cached = context.get_cached_tool_result(tool_name, args)
                        if cached is not None:
                            entry["cached_result"] = cached
                    mcp_tool_calls.append(entry)
        
        # If we have text AND tool calls, log the text now (without widgets) before executing tools
        if mcp_tool_calls and full_text:
            self._finalize_text_response(full_text, context, allow_widgets=False)
            full_text = ""

        # Execute all MCP tools in parallel if we have multiple
        if mcp_tool_calls:
            try:
                # Helper function to convert protobuf types
                def to_plain_python(obj):
                    """Recursively convert protobuf types to plain Python."""
                    if isinstance(obj, dict):
                        return {k: to_plain_python(v) for k, v in obj.items()}
                    elif isinstance(obj, (list, tuple)):
                        return [to_plain_python(item) for item in obj]
                    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
                        return [to_plain_python(item) for item in obj]
                    else:
                        return obj
                
                batch_start = time.time()
                tool_results_ordered = []
                pending_entries = []
                cached_results = {}
                for idx, entry in enumerate(mcp_tool_calls):
                    entry["idx"] = idx
                    if "cached_result" in entry:
                        cached_results[idx] = entry["cached_result"]
                        context.add_trace(f"{self.name}: cache hit {entry['name']}")
                        print(f"  💾 Context cache HIT: {entry['name']}")
                    else:
                        pending_entries.append(entry)
                
                executed_results = {}
                if pending_entries:
                    max_workers = min(len(pending_entries), 4)
                    if len(pending_entries) > 1:
                        print(f"  📊 Executing {len(pending_entries)} tools in batch...")
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        future_map = {
                            executor.submit(self._run_tool_call, entry["name"], to_plain_python(entry["args"])): entry
                            for entry in pending_entries
                        }
                        for future in as_completed(future_map):
                            entry = future_map[future]
                            tool_name = entry["name"]
                            idx = entry["idx"]
                            try:
                                result, duration = future.result()
                                executed_results[idx] = {
                                    'name': tool_name,
                                    'result': result,
                                    'error': None,
                                    'time': duration
                                }
                                if tool_name in self.cacheable_tools and result is not None:
                                    context.cache_tool_result(tool_name, entry["args"], result)
                                context.add_trace(f"{self.name}: executed tool {tool_name} ({duration:.2f}s)")
                                if result:
                                    preview = result if (tool_name.startswith('return_') and 'widget' in tool_name.lower()) else result[:100]
                                    print(f"  > {tool_name}: {preview}...")
                                else:
                                    print(f"  > {tool_name}: None")
                                if self.name == "Physician" and tool_name == "get_biomarkers":
                                    context.set_flag("biomarkers_ready", True)
                                    self._process_biomarker_flags(context, result)
                            except Exception as e:
                                print(f"  > {tool_name} Error: {e}")
                                executed_results[idx] = {
                                    'name': tool_name,
                                    'result': None,
                                    'error': str(e),
                                    'time': 0
                                }
                batch_time = time.time() - batch_start if pending_entries else 0
                
                for entry in mcp_tool_calls:
                    idx = entry["idx"]
                    if idx in cached_results:
                        tool_results_ordered.append({
                            'name': entry["name"],
                            'result': cached_results[idx],
                            'error': None,
                            'time': 0,
                            'cached': True
                        })
                        if self.name == "Physician" and entry["name"] == "get_biomarkers":
                            context.set_flag("biomarkers_ready", True)
                            self._process_biomarker_flags(context, cached_results[idx])
                    else:
                        exec_info = executed_results.get(idx, {'name': entry["name"], 'result': None, 'error': 'Unknown error', 'time': 0})
                        exec_info['cached'] = False
                        tool_results_ordered.append(exec_info)
                
                # Prepare response parts for all tool results
                response_parts = []
                for tool_result in tool_results_ordered:
                    if tool_result['error']:
                        response_parts.append(
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=tool_result['name'],
                                    response={"error": tool_result['error']}
                                )
                            )
                        )
                    else:
                        response_parts.append(
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=tool_result['name'],
                                    response={"result": tool_result['result']}
                                )
                            )
                        )
                
                if pending_entries:
                    if len(pending_entries) > 1:
                        print(f"  ⏱️  Batch Tool Execution: {batch_time:.2f}s ({len(pending_entries)} tools)")
                    else:
                        print(f"  ⏱️  Tool Execution: {batch_time:.2f}s")
                
                # Send all tool responses back to the model at once
                tool_response = chat.send_message(
                    genai.protos.Content(parts=response_parts)
                )
                
                # Process the response to the tool outputs
                return self._process_response(tool_response, context, chat)
                    
            except Exception as e:
                print(f"  > Tool Execution Error: {e}")
                import traceback
                traceback.print_exc()
                # Return error to allow agent to continue
                agent_total = time.time() - agent_start
                print(f"  ⏱️  Total Agent Time: {agent_total:.2f}s")
                return self._get_completion_targets()
                    
        # If text response (already streamed above)
        if full_text:
            self._finalize_text_response(full_text, context, allow_widgets=True)
            agent_total = time.time() - agent_start
            print(f"  ⏱️  Total Agent Time: {agent_total:.2f}s")
            return self._get_completion_targets()

        if self.name == "Physician" and not self._summary_prompted:
            self._summary_prompted = True
            print("  ⚠️  Physician response lacked narrative; requesting summary.")
            try:
                summary_response = chat.send_message(
                    "Provide a concise, user-facing summary of the key biomarker findings, "
                    "then explicitly hand off to Nutritionist and Fitness Coach with justification."
                )
            except Exception as summary_error:
                print(f"  ❌ Summary request failed: {summary_error}. Proceeding with default handoff.")
                return ["Critic"]
            return self._process_response(summary_response, context, chat)
        
        default_handoff = self._get_completion_targets()
        if self.name == "Physician":
            # Ensure cardiovascular cases still reach specialists even if the Physician
            # returned only widgets. Default to Nutritionist + Fitness Coach so the user
            # receives actionable follow-ups.
            default_handoff = ["Nutritionist", "Fitness Coach"]
            context.add_message(
                "model",
                "Routing to Nutritionist and Fitness Coach for lifestyle interventions.",
                sender=self.name,
            )

        if self.widgets:
            context.pending_widgets.extend(self.widgets)
            self.widgets = []

        agent_total = time.time() - agent_start
        print(f"  ⚠️  No explicit response provided. Defaulting to {', '.join(default_handoff)}.")
        print(f"  ⏱️  Total Agent Time: {agent_total:.2f}s")
        return default_handoff

    def _process_response(self, response, context, chat):
        """Helper to handle the response loop recursively with parallel tool execution."""
        # Collect all tool calls
        mcp_tool_calls = []
        
        for part in response.parts:
            if fn := part.function_call:
                tool_name = fn.name
                args = self._normalize_tool_args(dict(fn.args))
                print(f"  > Tool Call: {tool_name}({args})")
                
                if self._handle_widget_tool(tool_name, args, context):
                    continue  # Already processed as a native widget tool
                
                if tool_name == "transfer_handoff":
                    target = args["target_agent"]
                    reason = args["reason"]
                    if "new_finding" in args and args["new_finding"]:
                        finding = args["new_finding"]
                        print(f"  🔎 New finding from {self.name}: {finding}")
                        context.add_finding(f"[{self.name}]: {finding}")
                        if "OFFER:" in finding:
                            offer_value = finding.split("OFFER:")[-1].strip()
                            self._register_offer(context, offer_value)
                    
                    # Parse target agents (can be comma-separated for parallel execution)
                    target_agents = [agent.strip() for agent in target.split(",")]
                    
                    if len(target_agents) > 1:
                        context.add_message("model", f"Handing off to {', '.join(target_agents)} (parallel): {reason}", sender=self.name)
                        print(f"  🔀 Parallel Handoff to: {', '.join(target_agents)}")
                    else:
                        context.add_message("model", f"Handing off to {target}: {reason}", sender=self.name)
                    context.add_trace(f"{self.name}: handoff -> {target_agents}")
                    
                    # Store widgets in context before handoff
                    if self.widgets:
                        context.pending_widgets.extend(self.widgets)
                    
                    return target_agents
                else:
                    # Collect MCP tool calls for parallel execution
                    entry = {"name": tool_name, "args": args}
                    if tool_name in self.cacheable_tools:
                        cached = context.get_cached_tool_result(tool_name, args)
                        if cached is not None:
                            entry["cached_result"] = cached
                    
                    # Set flags for downstream widget selection based on tool calls
                    if tool_name == "get_workout_plan":
                        context.set_flag("needs_workout_widget", True)
                    elif tool_name == "get_food_journal" or tool_name == "get_meal_plan":
                        context.set_flag("needs_meal_widget", True)
                    elif tool_name == "get_supplement_info":
                        context.set_flag("needs_supp_widget", True)
                        
                    mcp_tool_calls.append(entry)
        
        # Execute MCP tools in parallel if we have any
        if mcp_tool_calls:
            def to_plain_python(obj):
                """Recursively convert protobuf types to plain Python."""
                if isinstance(obj, dict):
                    return {k: to_plain_python(v) for k, v in obj.items()}
                elif isinstance(obj, (list, tuple)):
                    return [to_plain_python(item) for item in obj]
                elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
                    return [to_plain_python(item) for item in obj]
                else:
                    return obj
            
            tool_results_ordered = []
            pending_entries = []
            cached_results = {}
            for idx, entry in enumerate(mcp_tool_calls):
                entry["idx"] = idx
                if "cached_result" in entry:
                    cached_results[idx] = entry["cached_result"]
                    context.add_trace(f"{self.name}: cache hit {entry['name']}")
                    print(f"  💾 Context cache HIT: {entry['name']}")
                else:
                    pending_entries.append(entry)
            
                executed_results = {}
                if pending_entries:
                    max_workers = min(len(pending_entries), 4)
                    if len(pending_entries) > 1:
                        print(f"  📊 Executing {len(pending_entries)} tools in batch...")
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        future_map = {
                            executor.submit(self._run_tool_call, entry["name"], to_plain_python(entry["args"])): entry
                            for entry in pending_entries
                        }
                        for future in as_completed(future_map):
                            entry = future_map[future]
                            tool_name = entry["name"]
                            idx = entry["idx"]
                            try:
                                result, duration = future.result()
                                executed_results[idx] = {
                                    'name': tool_name,
                                    'result': result,
                                    'error': None,
                                    'time': duration
                                }
                                if tool_name in self.cacheable_tools and result is not None:
                                    context.cache_tool_result(tool_name, entry["args"], result)
                                context.add_trace(f"{self.name}: executed tool {tool_name} ({duration:.2f}s)")
                                if result:
                                    preview = result if (tool_name.startswith('return_') and 'widget' in tool_name.lower()) else result[:100]
                                    print(f"  > {tool_name}: {preview}...")
                                else:
                                    print(f"  > {tool_name}: None")
                                if self.name == "Physician" and tool_name == "get_biomarkers":
                                    context.set_flag("biomarkers_ready", True)
                                    self._process_biomarker_flags(context, result)
                            except Exception as e:
                                print(f"  > {tool_name} Error: {e}")
                                executed_results[idx] = {
                                    'name': tool_name,
                                    'result': None,
                                    'error': str(e),
                                    'time': 0
                                }
            
            for entry in mcp_tool_calls:
                idx = entry["idx"]
                if idx in cached_results:
                    tool_results_ordered.append({
                        'name': entry["name"],
                        'result': cached_results[idx],
                        'error': None,
                        'time': 0,
                        'cached': True
                    })
                    if self.name == "Physician" and entry["name"] == "get_biomarkers":
                        context.set_flag("biomarkers_ready", True)
                        self._process_biomarker_flags(context, cached_results[idx])
                else:
                    exec_info = executed_results.get(idx, {'name': entry["name"], 'result': None, 'error': 'Unknown error', 'time': 0})
                    exec_info['cached'] = False
                    tool_results_ordered.append(exec_info)
            
            # Prepare response parts for all tool results
            response_parts = []
            for tool_result in tool_results_ordered:
                if tool_result['error']:
                    response_parts.append(
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=tool_result['name'],
                                response={"error": tool_result['error']}
                            )
                        )
                    )
                else:
                    response_parts.append(
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=tool_result['name'],
                                response={"result": tool_result['result']}
                            )
                        )
                    )
            
            # Send all responses back
            tool_response = chat.send_message(genai.protos.Content(parts=response_parts))
            return self._process_response(tool_response, context, chat)
        
        text_content = self._extract_text_from_parts(response)
        if text_content:
            # Stream the full response text to frontend/stdout for SSE
            self._write_text_chunk(text_content, newline=True)
            context.add_message("model", text_content, sender=self.name)
            if self.widgets:
                context.pending_widgets.extend(self.widgets)
                self.widgets = []
            return self._get_completion_targets()

        if self.name == "Physician" and not self._summary_prompted:
            self._summary_prompted = True
            print("  ⚠️  Physician response lacked narrative; requesting summary.")
            summary_response = chat.send_message(
                "Provide a concise, user-facing summary of the key biomarker findings, "
                "then explicitly hand off to Nutritionist and Fitness Coach with justification."
            )
            return self._process_response(summary_response, context, chat)

        # If we reach here, no further instructions were provided; default to next agents
        default_handoff = self._get_completion_targets()
        if self.name == "Physician":
            default_handoff = ["Nutritionist", "Fitness Coach"]
            context.add_message(
                "model",
                "Routing to Nutritionist and Fitness Coach for lifestyle interventions.",
                sender=self.name,
            )
        if self.widgets:
            context.pending_widgets.extend(self.widgets)
            self.widgets = []
        print(f"  ⚠️  No textual response from model. Defaulting to {', '.join(default_handoff)}.")
        context.add_trace(f"{self.name}: default -> {default_handoff}")
        return default_handoff

    def _get_completion_targets(self) -> List[str]:
        if self.default_next_agents is not None:
            return self.default_next_agents
        if self.name == "Critic":
            return ["STOP"]
        return ["Critic"]

    def _run_tool_call(self, tool_name: str, plain_args: Any):
        tool_start = time.time()
        result = self.mcp_client.execute_tool(tool_name, plain_args)
        return result, time.time() - tool_start

    def _safe_float(self, value: Any) -> Optional[float]:
        try:
            if isinstance(value, str):
                value = value.replace('%', '').strip()
            return float(value)
        except (ValueError, TypeError):
            return None

    def _process_biomarker_flags(self, context: AgentContext, biomarker_data: Any):
        try:
            if isinstance(biomarker_data, str):
                try:
                    data = json.loads(biomarker_data)
                except json.JSONDecodeError:
                    data = ast.literal_eval(biomarker_data)
            else:
                data = biomarker_data
        except Exception:
            return
        if not isinstance(data, list):
            return
        ldl = trig = apo = ratio = vitd = lipase = None
        for marker in data:
            name = marker.get("name", "").lower()
            value = marker.get("value")
            num = self._safe_float(value)
            if "ldl" in name and "low-density" in name:
                ldl = num
                context.flags["ldl_value"] = num
            elif "triglyceride" in name:
                trig = num
                context.flags["trig_value"] = num
            elif "apolipoprotein b" in name:
                apo = num
                context.flags["apo_value"] = num
            elif "cholesterol / hdl" in name:
                ratio = num
                context.flags["chol_ratio"] = num
            elif "vitamin d" in name:
                vitd = num
                context.flags["vitd_value"] = num
            elif "lipase" in name:
                lipase = num
                context.flags["lipase_value"] = num
        high_cardio = any([
            ldl is not None and ldl >= 130,
            apo is not None and apo >= 100,
            ratio is not None and ratio >= 5,
            trig is not None and trig >= 150
        ])
        if high_cardio:
            context.set_flag("high_cardio_risk", True)
            context.set_flag("needs_meal_widget", True)
            context.set_flag("needs_workout_widget", True)
        if vitd is not None and vitd < 40:
            context.set_flag("vitd_low", True)
            context.set_flag("needs_supp_widget", True)
        if lipase is not None and lipase > 60:
            context.set_flag("lipase_high", True)

    def _register_offer(self, context: AgentContext, offer_type: str):
        if not offer_type:
            return
        targets = OFFER_TARGET_MAP.get(offer_type) or ["Physician"]
        context.state.set_offer(offer_type, targets)
        target_str = ", ".join(targets) if targets else "unspecified specialists"
        print(f"  📌 Pending offer '{offer_type}' registered for {target_str}.")

    def _update_pending_offer(self, context: AgentContext, allow_widgets: bool):
        offer_type = context.state.pending_offer
        if offer_type and context.state.stage == "awaiting_confirmation":
            print(f"  📌 Pending Offer active: {offer_type} (awaiting user confirmation).")

    def _finalize_text_response(self, text: str, context: AgentContext, allow_widgets: bool):
        if not text:
            return
        widgets_allowed = allow_widgets
        if self.name == "Critic":
            self._update_pending_offer(context, allow_widgets)
            if widgets_allowed:
                pending_offer = context.state.pending_offer
                awaiting_confirmation = context.state.stage == "awaiting_confirmation"
                plan_delivery = context.state.stage == "plan_delivery"
                if pending_offer and awaiting_confirmation:
                    print(f"  ⏳ Widgets deferred; pending offer '{pending_offer}' not confirmed yet.")
                    widgets_allowed = False
                else:
                    self._auto_widgets_from_flags(context)
                    if plan_delivery and pending_offer:
                        print(f"  ✅ Offer '{pending_offer}' fulfilled; delivering plan output.")
                        context.state.mark_plan_delivered()
        context.add_message("model", text, sender=self.name)
        if widgets_allowed and self.widgets:
            context.pending_widgets.extend(self.widgets)
            self.widgets = []
        elif not widgets_allowed:
            # Discard any speculative widgets captured before the final response
            self.widgets = []

    def _auto_widgets_from_flags(self, context: AgentContext):
        if not self.widget_toolset:
            return
        
        # Debug: print active flags
        print(f"  🔍 Widget flag check: needs_meal={context.get_flag('needs_meal_widget')}, needs_workout={context.get_flag('needs_workout_widget')}, needs_supp={context.get_flag('needs_supp_widget')}")
        
        desired = []
        if context.get_flag("needs_meal_widget"):
            desired.append(("needs_meal_widget", "return_meal_plan_widget", {"plan_type": "cholesterol"}))
        if context.get_flag("needs_workout_widget"):
            goal = "Cardio"
            desired.append(("needs_workout_widget", "return_workout_widget", {"goal": goal}))
        if context.get_flag("needs_supp_widget"):
            desired.append(("needs_supp_widget", "return_supplement_widget", {"supplement_names": ["Vitamin D3"]}))
        
        print(f"  🎯 Auto-widget selection: {len(desired)} widgets to add.")
        
        for flag_name, tool_name, args in desired:
            self._handle_widget_tool(tool_name, args, context)
            context.flags.pop(flag_name, None)
