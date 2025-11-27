import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool
from typing import List, Dict, Any, Optional
from .models import AgentContext
from .registry import AgentRegistry
from .mcp_client import SimpleMCPClient
from .tools.widget_tools import WidgetToolset
import os
import sys
import re
from dotenv import load_dotenv
import time
import hashlib
import json
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))

_model_cache = {}
_model_cache_lock = __import__('threading').Lock()

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
        self.widgets = []
        self._current_widget_calls = set()
        # Cache ALL tool results in context by default - all MCP tools are read-only queries
        # This avoids redundant calls when multiple agents need the same data
        # None = all tools allowed, [] = no tools allowed, ["X"] = only X allowed
        if allowed_mcp_tools is None:
            self.allowed_mcp_tools = None  # All tools
        else:
            self.allowed_mcp_tools = set(allowed_mcp_tools)  # Specific set (can be empty)
        self.default_next_agents = default_next_agents
        self.enable_handoff = enable_handoff
        self.allow_emergency_stop = allow_emergency_stop
        self.model_name = "gemini-2.5-flash"

    def _should_stream_to_client(self) -> bool:
        # Guardrail is internal safety check - never stream to client
        return self.name in {"Critic", "Conversation Planner", "Physician", "Nutritionist", "Fitness Coach", "Sleep Doctor", "Mindfulness Coach"}

    def _write_text_chunk(self, text: str, newline: bool = False, prefix: bool = True):
        is_client_stream = self._should_stream_to_client()
        target = sys.stdout if is_client_stream else sys.__stdout__
        if prefix:
            indicator = "  📤 " if is_client_stream else "  🔒 "
            target.write(indicator)
        target.write(text)
        if newline:
            target.write("\n")
        target.flush()
        
    def _build_system_prompt(self, context: AgentContext) -> str:
        registry_prompt = AgentRegistry.get_registry_prompt()
        state = context.state
        context_str = f"""
        CURRENT CONTEXT:
        - User Intent: {context.user_intent}
        - Conversation Focus: {state.focus}
        - Conversation Stage: {state.stage}
        - Accumulated Findings: {context.accumulated_findings}
        - System Flags: {context.flags}
        - Plan Domains Ready: {context.plan_domain_flags}
        """
        
        return f"""
        You are the **{self.name}**.
        Role: {self.role}
        
        {self.base_instruction}
        
        {registry_prompt}
        
        {context_str}
        
        INSTRUCTIONS:
        1. Analyze the context.
        2. Use tools to gather information.
        3. If you need another agent, use `transfer_handoff`.
        4. If finished, handoff to 'Critic'.
        """

    def _filter_mcp_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # None = all tools allowed, empty set = no tools, non-empty set = only those tools
        if self.allowed_mcp_tools is None:
            return tools
        if len(self.allowed_mcp_tools) == 0:
            return []  # Explicitly no MCP tools for this agent
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
        if not self.widget_toolset:
            return {"function_declarations": []}
        return self.widget_toolset.get_tool_declarations()
    
    def _get_handoff_tool(self):
        return {
            "function_declarations": [
                {
                    "name": "transfer_handoff",
                    "description": "Transfers control to one or more agents. For concurrent execution, specify multiple target agents as a comma-separated string.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "target_agent": {"type": "STRING", "description": "Name(s) of agent(s). Use comma-separated for parallel: 'Agent1,Agent2'"},
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
                    "description": "Immediately stop the conversation for emergency/safety.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "reason": {"type": "STRING", "description": "Short description of the emergency."}
                        },
                        "required": ["reason"]
                    }
                }
            ]
        }

    def _normalize_tool_args(self, obj):
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
        if not self.widget_toolset:
            return False
        if not (tool_name.startswith("return_") and "_widget" in tool_name):
            return False
        
        normalized_args = self._normalize_tool_args(args)
        
        if not self.widget_toolset.is_widget_tool(tool_name):
            return False
        
        call_signature = self.widget_toolset.get_signature(tool_name, normalized_args)
        if call_signature in self._current_widget_calls:
            return True
        self._current_widget_calls.add(call_signature)
        
        execution = self.widget_toolset.execute(tool_name, normalized_args)
        widget_data = execution.get("widget")
        duration_ms = execution.get("duration_ms", 0)
        
        if widget_data:
            self.widgets.append(widget_data)
            print(f"  ✅ Widget added: {widget_data['type']} ({duration_ms}ms)", flush=True)
            context.add_trace(f"{self.name}: added widget {widget_data['type']}")
        return True

    def _extract_text_from_parts(self, response) -> str:
        text_chunks = []
        for part in getattr(response, "parts", []):
            try:
                part_text = getattr(part, "text", None)
                if part_text:
                    text_chunks.append(part_text)
            except ValueError:
                continue
        return "".join(text_chunks).strip()

    def _strip_scratchpad(self, text: str):
        scratch_segments = []
        def repl(match):
            scratch_segments.append(match.group(1).strip())
            return ""
        visible_text = re.sub(r"\[\[scratch\]\](.*?)\[\[/scratch\]\]", repl, text, flags=re.DOTALL)
        return visible_text.strip(), scratch_segments

    def _get_model_cache_key(self, system_prompt: str, tools: list) -> str:
        return f"{self.name}:{self.model_name}"
    
    def _get_cached_model(self, system_prompt: str, tools: list):
        cache_key = self._get_model_cache_key(system_prompt, tools)
        with _model_cache_lock:
            if cache_key in _model_cache:
                return _model_cache[cache_key], True
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_prompt,
                tools=tools
            )
            _model_cache[cache_key] = model
            return model, False
    
    def run(self, context: AgentContext) -> List[str]:
        agent_start = time.time()
        print(f"\n--- Agent Active: {self.name} ---")
        context.add_trace(f"{self.name}: started run (hop {context.hop_count})")
        
        mcp_tools = self._filter_mcp_tools(self.mcp_client.get_tools_definitions())
        widget_tools = self._get_widget_tools()
        all_tools = list(mcp_tools)
        if widget_tools["function_declarations"]:
            all_tools.append(widget_tools)
        if self.enable_handoff:
            all_tools.append(self._get_handoff_tool())
        if self.allow_emergency_stop:
            all_tools.append(self._get_emergency_stop_tool())
        
        self.widgets = []
        self._current_widget_calls = set()
        
        system_prompt = self._build_system_prompt(context)
        model, cache_hit = self._get_cached_model(system_prompt, all_tools)
        
        if not cache_hit:
            print(f"  🔧 Model instance created and cached")
        
        gemini_history = []
        for msg in context.history:
            role = "user" if msg.role == "user" else "model"
            gemini_history.append({"role": role, "parts": [msg.content]})
            
        chat = model.start_chat(history=gemini_history)
        
        llm_start = time.time()
        full_text = ""
        has_text = False
        chunks = []
        streamed_text = False
        
        try:
            response_stream = chat.send_message("Proceed with your task based on the context.", stream=True)
            for chunk in response_stream:
                chunks.append(chunk)
                try:
                    if chunk.text:
                        has_text = True
                        streamed_text = True
                        self._write_text_chunk(chunk.text)
                        full_text += chunk.text
                except ValueError:
                    pass
        except Exception as stream_error:
            print(f"\n  ❌ Streaming error: {stream_error}. Retrying...")
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
        
        if not chunks:
            return self._get_completion_targets()
        
        # Collect function calls from ALL chunks (not just the last one)
        # With streaming, function calls can appear in any chunk
        all_function_calls = []
        for chunk in chunks:
            for part in getattr(chunk, 'parts', []):
                if hasattr(part, 'function_call') and part.function_call:
                    all_function_calls.append(part.function_call)
        
        mcp_tool_calls = []
        for fn in all_function_calls:
            tool_name = fn.name
            args = self._normalize_tool_args(dict(fn.args))
            
            print(f"  > Tool Call: {tool_name}({args})", flush=True)
            context.add_trace(f"{self.name}: tool_call {tool_name} ({args})")
            
            if self._handle_widget_tool(tool_name, args, context):
                continue
            
            if tool_name == "transfer_handoff":
                if self.name == "Guardrail":
                    target_arg = args.get("target_agent", "").strip()
                    if target_arg.upper() != "STOP":
                        print(f"  ⚠️  Guardrail attempted to route to '{target_arg}', ignoring.")
                        continue
                if full_text:
                    self._finalize_text_response(full_text, context)
                    full_text = ""
                target = args["target_agent"]
                reason = args["reason"]
                if "new_finding" in args and args["new_finding"]:
                    finding = args["new_finding"]
                    print(f"  🔎 New finding from {self.name}: {finding}")
                    context.add_finding(f"[{self.name}]: {finding}")
                
                target_agents = [agent.strip() for agent in target.split(",")]
                
                if len(target_agents) > 1:
                    context.add_message("model", f"Handing off to {', '.join(target_agents)} (parallel): {reason}", sender=self.name)
                    print(f"  🔀 Parallel Handoff to: {', '.join(target_agents)}")
                else:
                    context.add_message("model", f"Handing off to {target}: {reason}", sender=self.name)
                context.add_trace(f"{self.name}: handoff -> {target_agents}")
                if self.name == "Conversation Planner":
                    context.register_plan_request(self.name, target_agents)
                
                if self.widgets:
                    context.pending_widgets.extend(self.widgets)
                
                agent_total = time.time() - agent_start
                print(f"  ⏱️  Total Agent Time: {agent_total:.2f}s")
                return target_agents
            elif tool_name == "trigger_emergency_stop" and self.allow_emergency_stop:
                reason = args.get("reason", "Emergency condition detected.").lower()
                if full_text:
                    self._finalize_text_response(full_text, context)
                    full_text = ""
                
                # Generate user-friendly emergency message based on type
                stop_text = self._get_emergency_message(reason)
                self._write_text_chunk(stop_text, newline=True)
                print(f"  🛑 Emergency stop triggered: {reason}")
                context.add_message("model", stop_text, sender=self.name)
                return ["STOP"]
            else:
                entry = {"name": tool_name, "args": args}
                # Check context cache for ALL tools (no hardcoded whitelist)
                cached = context.get_cached_tool_result(tool_name, args)
                if cached is not None:
                    entry["cached_result"] = cached
                mcp_tool_calls.append(entry)
        
        if mcp_tool_calls and full_text:
            self._finalize_text_response(full_text, context)
            full_text = ""

        if mcp_tool_calls:
            try:
                def to_plain_python(obj):
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
                                # Cache ALL tool results in context (no hardcoded whitelist)
                                if result is not None:
                                    context.cache_tool_result(tool_name, entry["args"], result)
                                if result:
                                    preview = result[:100] if isinstance(result, str) else str(result)[:100]
                                    print(f"  > {tool_name}: {preview}...")
                                else:
                                    print(f"  > {tool_name}: None")
                                if self.name == "Physician" and tool_name == "get_biomarkers":
                                    context.set_flag("biomarkers_ready", True)
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
                    else:
                        exec_info = executed_results.get(idx, {'name': entry["name"], 'result': None, 'error': 'Unknown error', 'time': 0})
                        exec_info['cached'] = False
                        tool_results_ordered.append(exec_info)
                
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
                
                tool_response = chat.send_message(genai.protos.Content(parts=response_parts))
                return self._process_response(tool_response, context, chat)
                    
            except Exception as e:
                print(f"  > Tool Execution Error: {e}")
                return self._get_completion_targets()
                    
        if full_text:
            self._finalize_text_response(full_text, context)
            agent_total = time.time() - agent_start
            print(f"  ⏱️  Total Agent Time: {agent_total:.2f}s")
            return self._get_completion_targets()

        if self.widgets:
            context.pending_widgets.extend(self.widgets)
            self.widgets = []

        agent_total = time.time() - agent_start
        print(f"  ⏱️  Total Agent Time: {agent_total:.2f}s")
        return self._get_completion_targets()

    def _process_response(self, response, context, chat):
        mcp_tool_calls = []
        
        for part in response.parts:
            if fn := part.function_call:
                tool_name = fn.name
                args = self._normalize_tool_args(dict(fn.args))
                print(f"  > Tool Call: {tool_name}({args})", flush=True)
                
                if self._handle_widget_tool(tool_name, args, context):
                    continue
                
                if tool_name == "transfer_handoff":
                    target = args["target_agent"]
                    reason = args["reason"]
                    if "new_finding" in args and args["new_finding"]:
                        finding = args["new_finding"]
                        print(f"  🔎 New finding from {self.name}: {finding}")
                        context.add_finding(f"[{self.name}]: {finding}")
                    
                    target_agents = [agent.strip() for agent in target.split(",")]
                    
                    if len(target_agents) > 1:
                        context.add_message("model", f"Handing off to {', '.join(target_agents)} (parallel): {reason}", sender=self.name)
                        print(f"  🔀 Parallel Handoff to: {', '.join(target_agents)}")
                    else:
                        context.add_message("model", f"Handing off to {target}: {reason}", sender=self.name)
                    
                    if self.widgets:
                        context.pending_widgets.extend(self.widgets)
                    
                    return target_agents
                else:
                    entry = {"name": tool_name, "args": args}
                    # Check context cache for ALL tools (no hardcoded whitelist)
                    cached = context.get_cached_tool_result(tool_name, args)
                    if cached is not None:
                        entry["cached_result"] = cached
                    mcp_tool_calls.append(entry)
        
        if mcp_tool_calls:
            def to_plain_python(obj):
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
                            # Cache ALL tool results in context (no hardcoded whitelist)
                            if result is not None:
                                context.cache_tool_result(tool_name, entry["args"], result)
                            if result:
                                preview = result[:100] if isinstance(result, str) else str(result)[:100]
                                print(f"  > {tool_name}: {preview}...")
                            else:
                                print(f"  > {tool_name}: None")
                            if self.name == "Physician" and tool_name == "get_biomarkers":
                                context.set_flag("biomarkers_ready", True)
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
                else:
                    exec_info = executed_results.get(idx, {'name': entry["name"], 'result': None, 'error': 'Unknown error', 'time': 0})
                    exec_info['cached'] = False
                    tool_results_ordered.append(exec_info)
            
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
            
            tool_response = chat.send_message(genai.protos.Content(parts=response_parts))
            return self._process_response(tool_response, context, chat)
        
        text_content = self._extract_text_from_parts(response)
        if text_content:
            self._write_text_chunk(text_content, newline=True)
            context.add_message("model", text_content, sender=self.name)
            if self.widgets:
                context.pending_widgets.extend(self.widgets)
                self.widgets = []
            return self._get_completion_targets()

        if self.widgets:
            context.pending_widgets.extend(self.widgets)
            self.widgets = []
        return self._get_completion_targets()

    def _get_emergency_message(self, reason: str) -> str:
        """Generate a user-friendly emergency message based on the type of crisis."""
        reason_lower = reason.lower()
        
        # Mental health crisis keywords
        mental_health_keywords = ["suicid", "kill myself", "end my life", "self-harm", "hurt myself", "don't want to live"]
        is_mental_health = any(kw in reason_lower for kw in mental_health_keywords)
        
        if is_mental_health:
            return """### We're Here for You 💙

I can see you're going through something really difficult right now. Your wellbeing matters, and there are people who want to help.

**Please reach out to one of these resources:**

📞 **988 Suicide & Crisis Lifeline** — Call or text **988** (available 24/7)
💬 **Crisis Text Line** — Text **HOME** to **741741**
🌐 **International Association for Suicide Prevention** — https://www.iasp.info/resources/Crisis_Centres/

You don't have to face this alone. These trained counselors are ready to listen without judgment.

If you're in immediate danger, please call **911** or go to your nearest emergency room.

---
*This health assistant cannot provide crisis counseling, but the resources above can help right now.*"""
        else:
            # Medical emergency
            return """### ⚠️ This Sounds Like a Medical Emergency

Based on what you've described, you may need immediate medical attention.

**Please take action now:**

🚨 **Call 911** if you're experiencing:
- Chest pain or pressure
- Difficulty breathing
- Signs of stroke (face drooping, arm weakness, speech difficulty)
- Severe allergic reaction
- Loss of consciousness

🏥 **Go to the nearest Emergency Room** if you can safely get there

📞 **Contact your doctor immediately** for urgent but non-life-threatening symptoms

---
*This health assistant is not equipped to handle medical emergencies. Please seek professional medical care right away.*"""
    
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

    def _finalize_text_response(self, text: str, context: AgentContext):
        if not text:
            return
        text, scratch = self._strip_scratchpad(text)
        text = self._enforce_plan_sections(text, context)
        text = re.sub(r"\n\s*---\s*\n", "\n\n", text)
        for segment in scratch:
            context.add_trace(f"{self.name} scratch: {segment}")
        context.add_message("model", text, sender=self.name)
        self._ensure_required_widgets(context)
        if self.widgets:
            context.pending_widgets.extend(self.widgets)
            self.widgets = []

    def _enforce_plan_sections(self, text: str, context: AgentContext) -> str:
        if self.name != "Critic":
            return text
        sections = {
            "nutrition": {
                "keywords": ["Nutrition Plan", "Diet Plan"],
                "fallback": "### Nutrition Plan\nFocus on whole foods, ample soluble fiber (oats, beans, berries), lean proteins, and omega-3 rich fish at least 2x/week while limiting saturated fats and refined sugars to improve LDL, ApoB, and triglycerides."
            },
            "fitness": {
                "keywords": ["Fitness Plan", "Exercise Plan", "Workout Plan"],
                "fallback": "### Fitness Plan\nTarget 150 minutes/week of moderate cardio (brisk walking, cycling, swimming) plus 2 strength sessions covering all major muscle groups. Progress duration by 5 minutes each week as tolerated."
            },
            "sleep": {
                "keywords": ["Sleep Plan", "Sleep Optimization"],
                "fallback": "### Sleep Plan\nHold a consistent 10:30 PM bedtime / 6:30 AM wake schedule, keep the bedroom dark/cool (65-68°F), and shut down screens 60 minutes before bed to support hormone balance and recovery."
            },
            "mindfulness": {
                "keywords": ["Mindfulness Plan", "Stress Management"],
                "fallback": "### Stress Management Plan\nUse 4-7-8 breathing during stressful moments, a 2-minute midday body scan, and a 10-minute guided meditation nightly. Schedule one nature walk and one joyful hobby session weekly."
            },
        }
        lower_text = text.lower()
        for domain, cfg in sections.items():
            if context.plan_domain_flags.get(domain):
                if not any(keyword.lower() in lower_text for keyword in cfg["keywords"]):
                    text += "\n\n" + cfg["fallback"]
                    lower_text = text.lower()
        return text

    def _ensure_required_widgets(self, context: AgentContext):
        if self.name != "Critic" or not self.widget_toolset:
            return
        required = {
            "nutrition": ("return_meal_plan_widget", {"plan_type": "cholesterol"}, "Meal plan"),
            "fitness": ("return_workout_widget", {"goal": "Cardio"}, "Workout plan"),
            "supplements": ("return_supplement_widget", {"supplement_names": ["Vitamin D3"]}, "Supplements — Thorne"),
        }
        needs_supplement = context.plan_domain_flags.get("supplements") or any("vitamin d" in finding.lower() for finding in context.accumulated_findings)
        if needs_supplement:
            context.plan_domain_flags["supplements"] = True
        existing_types = {w.get("type") for w in context.pending_widgets}
        for domain, (tool_name, args, widget_type) in required.items():
            if context.plan_domain_flags.get(domain) and widget_type not in existing_types:
                self._handle_widget_tool(tool_name, args, context)
                existing_types.add(widget_type)
