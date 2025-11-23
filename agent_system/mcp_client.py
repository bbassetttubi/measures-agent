import subprocess
import json
import os
import sys
from typing import List, Dict, Any, Callable
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPClient:
    def __init__(self):
        self.tools = {}
        self.sessions = []
        self.exit_stack = None

    async def connect_to_server(self, script_path: str, server_name: str):
        """Connects to an MCP server script."""
        server_params = StdioServerParameters(
            command="python3",
            args=[script_path],
            env=os.environ.copy()
        )
        
        # We need to manage the async context properly. 
        # For simplicity in this synchronous-ish agent loop, we might need a wrapper.
        # However, google-genai is sync or async. Let's assume we can use async.
        
        # Actually, for this prototype, let's use a simpler approach:
        # We will just define the tools manually that map to the server calls if we can't easily
        # bridge the async gap in this environment.
        # BUT, we want to use the real MCP SDK.
        pass

# REVISION: The official python MCP SDK is async. 
# To keep things simple and robust for this "production-grade" prototype without complex async loops 
# in the main agent flow (if we use sync Gemini calls), we might need to run the tool calls in an event loop.

# Let's implement a helper that runs a specific tool by name against the right server.

import asyncio
import threading
import atexit
from contextlib import AsyncExitStack
import time
import hashlib

class SimpleMCPClient:
    def __init__(self):
        self.user_data_script = os.path.abspath("servers/user_data/main.py")
        self.resources_script = os.path.abspath("servers/resources/main.py")
        # Use the current python interpreter which is in the venv
        self.python_path = sys.executable
        
        # Connection pooling - maintain persistent connections
        self._connections = {}  # server_name -> (read, write, session, loop)
        self._connection_lock = threading.Lock()
        
        # Tool Result Caching - for static reference data only
        self._cache = {}  # cache_key -> (result, timestamp)
        self._cache_lock = threading.Lock()
        self._cache_ttl = 3600  # 1 hour for reference data
        
        # Define which tools return static data that can be cached
        self._cacheable_tools = {
            'get_biomarker_ranges',  # Reference ranges don't change
            'get_workout_plan',      # Workout plans are static
            'get_supplement_info',   # Supplement info is static
        }
        
        # Register cleanup
        atexit.register(self._cleanup)
    
    def _cleanup(self):
        """Clean up on exit (connections are auto-managed by context managers)."""
        # Connections are managed by async context managers and close automatically
        pass
        
    async def _call_tool_with_fresh_connection(self, script_path: str, tool_name: str, arguments: dict) -> str:
        """Call tool with a fresh connection (original behavior, more stable)."""
        async with stdio_client(
            StdioServerParameters(command=self.python_path, args=[script_path], env=os.environ.copy())
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                return result.content[0].text

    def _get_cache_key(self, tool_name: str, arguments: dict) -> str:
        """Generate a cache key from tool name and arguments."""
        # Sort arguments for consistent hashing
        args_str = json.dumps(arguments, sort_keys=True)
        key_str = f"{tool_name}:{args_str}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_from_cache(self, cache_key: str) -> tuple:
        """Get result from cache if valid. Returns (result, hit) tuple."""
        with self._cache_lock:
            if cache_key in self._cache:
                result, timestamp = self._cache[cache_key]
                age = time.time() - timestamp
                if age < self._cache_ttl:
                    return result, True
                else:
                    # Expired, remove it
                    del self._cache[cache_key]
        return None, False
    
    def _put_in_cache(self, cache_key: str, result: str):
        """Store result in cache with current timestamp."""
        with self._cache_lock:
            self._cache[cache_key] = (result, time.time())
    
    def call_tool_sync(self, server: str, tool_name: str, arguments: dict) -> str:
        """
        Synchronous wrapper for async MCP tool calls.
        Uses event loop pooling (not connection pooling - MCP connections are stateful and complex).
        Implements caching for static reference data.
        Log suppression handled in MCP server code.
        """
        # Check cache for cacheable tools
        if tool_name in self._cacheable_tools:
            cache_key = self._get_cache_key(tool_name, arguments)
            cached_result, hit = self._get_from_cache(cache_key)
            if hit:
                print(f"  💾 Cache HIT: {tool_name}")
                return cached_result
        
        script = self.user_data_script if server == "user_data" else self.resources_script
        server_name = server
        
        result = [None]
        error = [None]
        
        def run_in_thread():
            try:
                with self._connection_lock:
                    # Get or create event loop for this thread
                    # Note: We reuse loops but not connections (MCP sessions are complex to pool)
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                
                # Use fresh connection each time (stable, logging suppressed at server level)
                result[0] = loop.run_until_complete(
                    self._call_tool_with_fresh_connection(script, tool_name, arguments)
                )
            except Exception as e:
                error[0] = e
        
        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join()
        
        if error[0]:
            raise error[0]
        
        # Cache result if cacheable
        if tool_name in self._cacheable_tools:
            cache_key = self._get_cache_key(tool_name, arguments)
            self._put_in_cache(cache_key, result[0])
            print(f"  💾 Cache MISS: {tool_name} (cached for {self._cache_ttl}s)")
        
        return result[0]
    
    def call_tools_sync_parallel(self, tool_requests: list) -> list:
        """
        Execute multiple tool calls efficiently.
        Note: Due to MCP's async nature and event loop management,
        tools are executed sequentially but efficiently within a single event loop.
        
        Args:
            tool_requests: List of (server, tool_name, arguments) tuples
            
        Returns:
            List of results in same order as requests
        """
        results = []
        for server, tool_name, arguments in tool_requests:
            result = self.call_tool_sync(server, tool_name, arguments)
            results.append(result)
        return results

    def get_tools_definitions(self):
        # Hardcoded for now to match what we built, as discovering them async 
        # and converting to Gemini format dynamically is a bit heavy for this step.
        # In a full v2, we would introspect.
        
        return [
            # User Data Tools
            {
                "function_declarations": [
                    {
                        "name": "get_biomarkers",
                        "description": "Retrieves biomarker data (blood work).",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "names": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "List of biomarker names"}
                            }
                        }
                    },
                    {
                        "name": "get_activity_log",
                        "description": "Retrieves activity logs.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "start_date": {"type": "STRING"},
                                "end_date": {"type": "STRING"}
                            },
                            "required": ["start_date", "end_date"]
                        }
                    },
                    {
                        "name": "get_food_journal",
                        "description": "Retrieves food journal.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "date": {"type": "STRING"}
                            },
                            "required": ["date"]
                        }
                    },
                    {
                        "name": "get_sleep_data",
                        "description": "Retrieves sleep data.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "date": {"type": "STRING"}
                            },
                            "required": ["date"]
                        }
                    },
                    {
                        "name": "get_user_profile",
                        "description": "Retrieves user profile (age, weight, goals).",
                        "parameters": {"type": "OBJECT", "properties": {}}
                    }
                ]
            },
            # Resources Tools
            {
                "function_declarations": [
                    {
                        "name": "get_biomarker_ranges",
                        "description": "Retrieves reference ranges.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "biomarker_name": {"type": "STRING"}
                            },
                            "required": ["biomarker_name"]
                        }
                    },
                    {
                        "name": "get_workout_plan",
                        "description": "Retrieves workout plans.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "goal": {"type": "STRING"}
                            },
                            "required": ["goal"]
                        }
                    },
                    {
                        "name": "get_supplement_info",
                        "description": "Retrieves supplement info.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "name": {"type": "STRING"}
                            },
                            "required": ["name"]
                        }
                    },
                    {
                        "name": "search_knowledge_base",
                        "description": "Searches articles and videos.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "query": {"type": "STRING"}
                            },
                            "required": ["query"]
                        }
                    }
                ]
            }
        ]

    def execute_tool(self, tool_name: str, args: dict) -> str:
        # Route to correct server
        if tool_name in ["get_biomarkers", "get_activity_log", "get_food_journal", "get_sleep_data", "get_user_profile"]:
            return self.call_tool_sync("user_data", tool_name, args)
        else:
            return self.call_tool_sync("resources", tool_name, args)
