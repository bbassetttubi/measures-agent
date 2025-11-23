"""
Widget Manager - Loads and renders chat widgets for agent responses.

Widgets are interactive UI components that agents can include in their responses
to make recommendations more actionable (e.g., workout plans with videos, meal plans with ordering).
"""

import json
import os
from typing import Dict, Any, Optional
from pathlib import Path
from jinja2 import Template
import threading

class WidgetManager:
    """Manages loading and rendering of chat widget templates."""
    
    def __init__(self, widgets_dir: str = "chat_widget_examples"):
        self.widgets_dir = widgets_dir
        self._templates = {}  # widget_name -> widget_definition
        self._lock = threading.Lock()
        self._load_widgets()
    
    def _load_widgets(self):
        """Load all widget templates from the widgets directory."""
        widget_files = Path(self.widgets_dir).glob("*.widget")
        
        for widget_file in widget_files:
            try:
                with open(widget_file, 'r') as f:
                    widget_def = json.load(f)
                    widget_name = widget_def.get('name')
                    if widget_name:
                        self._templates[widget_name] = widget_def
                        print(f"  📦 Loaded widget: {widget_name}")
            except Exception as e:
                print(f"  ⚠️  Failed to load widget {widget_file}: {e}")
    
    def render_widget(self, widget_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Render a widget with the provided data.
        
        Args:
            widget_name: Name of the widget template to use
            data: Data to populate the widget with
            
        Returns:
            Rendered widget as JSON structure, or None if widget not found
        """
        with self._lock:
            if widget_name not in self._templates:
                print(f"  ⚠️  Widget '{widget_name}' not found")
                return None
            
            widget_def = self._templates[widget_name]
            template_str = widget_def.get('template')
            
            if not template_str:
                print(f"  ⚠️  Widget '{widget_name}' has no template")
                return None
            
            try:
                # Render the Jinja2 template with provided data
                template = Template(template_str)
                rendered_json_str = template.render(**data)
                rendered = json.loads(rendered_json_str)
                
                return {
                    "type": widget_name,
                    "version": widget_def.get('version', '1.0'),
                    "data": rendered
                }
            except Exception as e:
                print(f"  ❌ Error rendering widget '{widget_name}': {e}")
                import traceback
                traceback.print_exc()
                return None
    
    def get_available_widgets(self) -> list:
        """Get list of available widget templates."""
        return list(self._templates.keys())
    
    def get_widget_schema(self, widget_name: str) -> Optional[Dict[str, Any]]:
        """Get the JSON schema for a widget's expected data format."""
        with self._lock:
            if widget_name in self._templates:
                return self._templates[widget_name].get('jsonSchema')
        return None


# Global widget manager instance (singleton)
_widget_manager = None
_widget_manager_lock = threading.Lock()

def get_widget_manager() -> WidgetManager:
    """Get or create the global widget manager instance."""
    global _widget_manager
    with _widget_manager_lock:
        if _widget_manager is None:
            _widget_manager = WidgetManager()
        return _widget_manager

