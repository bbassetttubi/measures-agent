import os
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from agent_system.models import AgentContext  # noqa: E402


def test_tool_cache_clears_on_data_version_increment():
    ctx = AgentContext(user_intent="test")
    args = {"biomarker_name": "LDL"}
    ctx.cache_tool_result("get_biomarker_ranges", args, {"range": "0-100"})
    assert ctx.tool_cache, "tool cache should store results"

    ctx.increment_data_version()

    assert ctx.tool_cache == {}, "tool cache should clear after data version bump"

