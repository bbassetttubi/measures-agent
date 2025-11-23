import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool
from typing import List, Dict, Any, Optional
from .models import AgentContext
from .registry import AgentRegistry
from .mcp_client import SimpleMCPClient
import os
from dotenv import load_dotenv
import time

load_dotenv()
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))

class Agent:
    def __init__(self, name: str, role: str, system_instruction: str, mcp_client: SimpleMCPClient):
        self.name = name
        self.role = role
        self.base_instruction = system_instruction
        self.mcp_client = mcp_client
        
        # Configure the model
        self.model_name = "gemini-2.5-flash" # SOTA model
        
    def _build_system_prompt(self, context: AgentContext) -> str:
        registry_prompt = AgentRegistry.get_registry_prompt()
        
        context_str = f"""
        CURRENT CONTEXT:
        - User Intent: {context.user_intent}
        - Accumulated Findings: {context.accumulated_findings}
        - Pending Tasks: {context.pending_tasks}
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

    def run(self, context: AgentContext) -> List[str]:
        """
        Runs the agent. Returns a list of agent names to execute next (for parallel execution) or ['STOP'] if finished (Critic).
        """
        agent_start = time.time()
        print(f"\n--- Agent Active: {self.name} ---")
        
        # 1. Setup Tools
        mcp_tools = self.mcp_client.get_tools_definitions()
        handoff_tool = self._get_handoff_tool()
        all_tools = mcp_tools + [handoff_tool]
        
        # 2. Setup Model
        model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=self._build_system_prompt(context),
            tools=all_tools
        )
        
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
        response_stream = chat.send_message("Proceed with your task based on the context.", stream=True)
        
        # Collect streamed response and chunks
        full_text = ""
        has_text = False
        chunks = []
        print(f"  💬 ", end="", flush=True)
        
        for chunk in response_stream:
            chunks.append(chunk)
            # Check if this chunk has text (not a function call)
            try:
                if chunk.text:
                    has_text = True
                    print(chunk.text, end="", flush=True)
                    full_text += chunk.text
            except ValueError:
                # This chunk is a function call, not text - skip streaming for it
                pass
        
        if has_text:
            print()  # New line after streaming
        else:
            print("(function call)")  # Indicate it was a function call
        
        llm_time = time.time() - llm_start
        print(f"  ⏱️  LLM Response: {llm_time:.2f}s")
        
        # The last chunk contains the complete response with all parts
        final_response = chunks[-1] if chunks else None
        
        if not final_response:
            return ["Critic"]  # Fallback
        
        # 5. Handle Tool Calls Loop
        # Gemini SDK handles the loop if we use automatic function calling, but we want to intercept 'transfer_handoff'.
        # So we will do a manual loop or check the parts.
        
        # OPTIMIZATION: Collect all MCP tool calls for parallel execution
        mcp_tool_calls = []
        
        for part in final_response.parts:
            if fn := part.function_call:
                tool_name = fn.name
                args = dict(fn.args)
                
                print(f"  > Tool Call: {tool_name}({args})")
                
                if tool_name == "transfer_handoff":
                    target = args["target_agent"]
                    reason = args["reason"]
                    if "new_finding" in args and args["new_finding"]:
                        context.add_finding(f"[{self.name}]: {args['new_finding']}")
                    
                    # Parse target agents (can be comma-separated for parallel execution)
                    target_agents = [agent.strip() for agent in target.split(",")]
                    
                    if len(target_agents) > 1:
                        context.add_message("model", f"Handing off to {', '.join(target_agents)} (parallel): {reason}", sender=self.name)
                        print(f"  🔀 Parallel Handoff to: {', '.join(target_agents)}")
                    else:
                        context.add_message("model", f"Handing off to {target}: {reason}", sender=self.name)
                    
                    agent_total = time.time() - agent_start
                    print(f"  ⏱️  Total Agent Time: {agent_total:.2f}s")
                    return target_agents
                else:
                    # Collect MCP tool call for parallel execution
                    mcp_tool_calls.append((tool_name, args))
        
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
                
                # Execute tools sequentially (MCP client has internal async handling)
                # Note: Batching multiple tool results to send back together for efficiency
                batch_start = time.time()
                tool_results = []
                
                if len(mcp_tool_calls) > 1:
                    print(f"  📊 Executing {len(mcp_tool_calls)} tools in batch...")
                
                for tool_name, args in mcp_tool_calls:
                    try:
                        plain_args = to_plain_python(args)
                        tool_start = time.time()
                        result = self.mcp_client.execute_tool(tool_name, plain_args)
                        tool_time = time.time() - tool_start
                        
                        tool_results.append({
                            'name': tool_name,
                            'result': result,
                            'time': tool_time,
                            'error': None
                        })
                        
                        if result:
                            print(f"  > {tool_name}: {result[:100]}...")
                        else:
                            print(f"  > {tool_name}: None")
                            
                    except Exception as e:
                        print(f"  > {tool_name} Error: {e}")
                        tool_results.append({
                            'name': tool_name,
                            'result': None,
                            'time': 0,
                            'error': str(e)
                        })
                
                batch_time = time.time() - batch_start
                
                # Prepare response parts for all tool results
                response_parts = []
                for tool_result in tool_results:
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
                
                if len(mcp_tool_calls) > 1:
                    print(f"  ⏱️  Batch Tool Execution: {batch_time:.2f}s ({len(mcp_tool_calls)} tools)")
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
                return ["Critic"]
                    
        # If text response (already streamed above)
        if full_text:
            context.add_message("model", full_text, sender=self.name)
            agent_total = time.time() - agent_start
            print(f"  ⏱️  Total Agent Time: {agent_total:.2f}s")
            if self.name == "Critic":
                return ["STOP"]
            # If a normal agent just talks without handing off, we might default to Critic or ask it to handoff.
            # For now, let's assume it means it's done or needs user input.
            # But in a mesh, it SHOULD handoff.
            # We'll force a handoff to Critic if it didn't specify.
            return ["Critic"]

    def _process_response(self, response, context, chat):
        """Helper to handle the response loop recursively with parallel tool execution."""
        # Collect all tool calls
        mcp_tool_calls = []
        
        for part in response.parts:
            if fn := part.function_call:
                tool_name = fn.name
                args = dict(fn.args)
                print(f"  > Tool Call: {tool_name}({args})")
                
                if tool_name == "transfer_handoff":
                    target = args["target_agent"]
                    reason = args["reason"]
                    if "new_finding" in args and args["new_finding"]:
                        context.add_finding(f"[{self.name}]: {args['new_finding']}")
                    
                    # Parse target agents (can be comma-separated for parallel execution)
                    target_agents = [agent.strip() for agent in target.split(",")]
                    
                    if len(target_agents) > 1:
                        context.add_message("model", f"Handing off to {', '.join(target_agents)} (parallel): {reason}", sender=self.name)
                        print(f"  🔀 Parallel Handoff to: {', '.join(target_agents)}")
                    else:
                        context.add_message("model", f"Handing off to {target}: {reason}", sender=self.name)
                    
                    return target_agents
                else:
                    # Collect MCP tool calls for parallel execution
                    mcp_tool_calls.append((tool_name, args))
        
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
            
            # Execute tools sequentially (MCP client manages async internally)
            # Batching results to send back together for efficiency
            tool_results = []
            
            if len(mcp_tool_calls) > 1:
                print(f"  📊 Executing {len(mcp_tool_calls)} tools in batch...")
            
            for tool_name, args in mcp_tool_calls:
                try:
                    plain_args = to_plain_python(args)
                    result = self.mcp_client.execute_tool(tool_name, plain_args)
                    tool_results.append({'name': tool_name, 'result': result, 'error': None})
                    
                    if result:
                        print(f"  > {tool_name}: {result[:100]}...")
                    else:
                        print(f"  > {tool_name}: None")
                except Exception as e:
                    print(f"  > {tool_name} Error: {e}")
                    tool_results.append({'name': tool_name, 'result': None, 'error': str(e)})
            
            # Prepare response parts for all tool results
            response_parts = []
            for tool_result in tool_results:
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
        
        if response.text:
            print(f"  > Response: {response.text[:100]}...")
            context.add_message("model", response.text, sender=self.name)
            if self.name == "Critic":
                return ["STOP"]
            return ["Critic"]
