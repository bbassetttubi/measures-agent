"""
Widget tool abstractions inspired by Google ADK's tool patterns.

Each widget is modeled as a function tool with clear metadata so the LLM
can decide when and how to invoke it. The toolset consolidates execution,
observability, and deduplication helpers for the base agent.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from ..widget_helper import WidgetHelper


class WidgetToolset:
    """Manages widget tool declarations and execution."""

    def __init__(self, helper: Optional[WidgetHelper] = None):
        self.helper = helper or WidgetHelper()
        self._tool_declarations = [
            {
                "name": "return_workout_widget",
                "description": (
                    "Return an interactive workout plan widget with exercise videos. "
                    "Use this to provide users with a goal-aligned fitness plan."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "goal": {
                            "type": "STRING",
                            "description": "Primary workout goal (e.g., 'Hypertrophy', 'Cardio', 'Cholesterol')."
                        }
                    },
                    "required": ["goal"]
                }
            },
            {
                "name": "return_supplement_widget",
                "description": (
                    "Return a supplement recommendation widget with buying options. "
                    "Use when advising on micronutrients or supportive products."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "supplement_names": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                            "description": "List of supplement names (e.g., ['Vitamin D3', 'Omega-3'])."
                        }
                    },
                    "required": ["supplement_names"]
                }
            },
            {
                "name": "return_meal_plan_widget",
                "description": (
                    "Return a meal plan widget with watch/order links. "
                    "Use when giving actionable nutrition guidance."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "plan_type": {
                            "type": "STRING",
                            "description": "Plan keyword (e.g., 'cholesterol', 'energy', 'muscle')."
                        }
                    },
                    "required": ["plan_type"]
                }
            }
        ]

        self._handlers = {
            "return_workout_widget": self._execute_workout_widget,
            "return_supplement_widget": self._execute_supplement_widget,
            "return_meal_plan_widget": self._execute_meal_plan_widget,
        }

    def get_tool_declarations(self) -> Dict[str, list]:
        """Return ADK-style function declarations for these tools."""
        return {"function_declarations": self._tool_declarations}

    def is_widget_tool(self, tool_name: str) -> bool:
        return tool_name in self._handlers

    def get_signature(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Stable signature for deduplication and observability."""
        try:
            serialized = json.dumps(args, sort_keys=True)
        except (TypeError, ValueError):
            serialized = repr(args)
        return f"{tool_name}:{serialized}"

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the widget tool and return payload plus diagnostics.

        Returns dict with keys:
            - widget: widget payload or None
            - duration_ms: execution time
            - args: normalized args used
        """
        handler = self._handlers.get(tool_name)
        if not handler:
            return {"widget": None, "duration_ms": 0, "args": args}

        start = time.time()
        widget_payload = handler(args)
        duration_ms = int((time.time() - start) * 1000)
        return {
            "widget": widget_payload,
            "duration_ms": duration_ms,
            "args": args,
        }

    # --- Individual widget executors -------------------------------------------------

    def _execute_workout_widget(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        goal = (args.get("goal") or "").strip()
        return self.helper.get_workout_widget(goal)

    def _execute_supplement_widget(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        names = args.get("supplement_names") or []
        return self.helper.get_supplement_widget(names)

    def _execute_meal_plan_widget(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        plan_type = (args.get("plan_type") or "").strip()
        return self.helper.get_meal_plan_widget(plan_type)


