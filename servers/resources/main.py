from mcp.server.fastmcp import FastMCP
from typing import List, Optional
import data_loader
import logging

# Suppress verbose MCP logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger('mcp').setLevel(logging.WARNING)

# Initialize FastMCP server
mcp = FastMCP("resources")

@mcp.tool()
def get_biomarker_ranges(biomarker_name: str) -> str:
    """
    Retrieves reference ranges for a specific biomarker.
    
    Args:
        biomarker_name: Name of the biomarker (e.g. "Vitamin D").
    """
    data = data_loader.get_biomarker_ranges(biomarker_name)
    if not data:
        return f"No reference ranges found for {biomarker_name}."
    return str(data)

@mcp.tool()
def get_workout_plan(goal: str) -> str:
    """
    Retrieves workout plans based on a goal or difficulty.
    
    Args:
        goal: Goal (e.g. "Hypertrophy") or difficulty ("Beginner").
    """
    data = data_loader.get_workout_plan(goal)
    if not data:
        return f"No workout plans found matching '{goal}'."
    return str(data)

@mcp.tool()
def get_supplement_info(name: str) -> str:
    """
    Retrieves information about a supplement.
    
    Args:
        name: Name of the supplement.
    """
    data = data_loader.get_supplement_info(name)
    if not data:
        return f"No information found for supplement '{name}'."
    return str(data)

@mcp.tool()
def search_knowledge_base(query: str) -> str:
    """
    Searches the knowledge base (Articles, Videos) using semantic search.
    
    Args:
        query: The search query (e.g. "benefits of sleep", "how to improve iron").
    """
    data = data_loader.search_knowledge_base(query)
    if not data:
        return f"No relevant articles or videos found for '{query}'."
    return str(data)

if __name__ == "__main__":
    mcp.run()
