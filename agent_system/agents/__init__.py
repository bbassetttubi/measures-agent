"""
Modular agent definitions for the Measures AI Health Assistant.

Each agent is defined in its own file with:
- Clear job description
- Specific data sources it evaluates
- Expected output format
- Natural conversation capabilities
"""

from .guardrail import create_guardrail_agent
from .planner import create_planner_agent
from .physician import create_physician_agent
from .nutritionist import create_nutritionist_agent
from .fitness_coach import create_fitness_coach_agent
from .sleep_doctor import create_sleep_doctor_agent
from .mindfulness_coach import create_mindfulness_coach_agent
from .user_persona import create_user_persona_agent
from .critic import create_critic_agent

def create_agents(mcp_client) -> dict:
    """Create all agents with their specialized configurations."""
    agents = {}
    
    agents["Guardrail"] = create_guardrail_agent(mcp_client)
    agents["Conversation Planner"] = create_planner_agent(mcp_client)
    agents["Physician"] = create_physician_agent(mcp_client)
    agents["Nutritionist"] = create_nutritionist_agent(mcp_client)
    agents["Fitness Coach"] = create_fitness_coach_agent(mcp_client)
    agents["Sleep Doctor"] = create_sleep_doctor_agent(mcp_client)
    agents["Mindfulness Coach"] = create_mindfulness_coach_agent(mcp_client)
    agents["User Persona"] = create_user_persona_agent(mcp_client)
    agents["Critic"] = create_critic_agent(mcp_client)
    
    return agents

__all__ = ["create_agents"]

