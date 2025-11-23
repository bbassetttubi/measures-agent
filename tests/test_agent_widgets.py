import os
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from types import SimpleNamespace

from agent_system.base_agent import Agent  # noqa: E402
from agent_system.models import AgentContext  # noqa: E402


class DummyMCPClient:
    def get_tools_definitions(self):
        return []

    def execute_tool(self, name, args):
        raise NotImplementedError("Not used in widget tests")


def _build_sample_biomarkers():
    return [
        {"name": "LDL (Low-Density Lipoprotein)", "value": "167", "units": "mg/dL"},
        {"name": "Apolipoprotein B (ApoB)", "value": "132", "units": "mg/dL"},
        {"name": "Triglycerides", "value": "171", "units": "mg/dL"},
        {"name": "Vitamin D", "value": "26", "units": "ng/mL"},
        {"name": "Lipase", "value": "79", "units": "U/L"},
    ]


def test_process_biomarker_flags_and_auto_widgets():
    ctx = AgentContext(user_intent="health")
    agent = Agent(
        name="Critic",
        role="QA",
        system_instruction="You are critic.",
        mcp_client=DummyMCPClient(),
        enable_widget_tools=True,
        allowed_mcp_tools=[],
    )

    biomarkers = _build_sample_biomarkers()
    agent._process_biomarker_flags(ctx, biomarkers)

    assert ctx.get_flag("high_cardio_risk")
    assert ctx.get_flag("vitd_low")
    assert ctx.get_flag("needs_meal_widget")
    assert ctx.get_flag("needs_workout_widget")
    assert ctx.get_flag("needs_supp_widget")

    agent._auto_widgets_from_flags(ctx)

    widget_types = {widget["type"] for widget in agent.widgets}
    assert "Meal plan: watch & order" in widget_types
    assert "Workout plan" in widget_types
    assert any("Supplement" in w for w in widget_types)

