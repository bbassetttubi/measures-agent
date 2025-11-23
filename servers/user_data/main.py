from mcp.server.fastmcp import FastMCP
from typing import List, Optional
import data_loader
import logging

# Suppress verbose MCP logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger('mcp').setLevel(logging.WARNING)

# Initialize FastMCP server
mcp = FastMCP("user_data")

@mcp.tool()
def get_biomarkers(names: Optional[List[str]] = None) -> str:
    """
    Retrieves biomarker data from the user's records.
    
    Args:
        names: Optional list of biomarker names to filter by (e.g. ["HbA1c", "Vitamin D"]). 
               If None, returns all biomarkers.
    """
    data = data_loader.get_biomarkers(names)
    if not data:
        return "No biomarkers found matching the criteria."
    return str(data)

@mcp.tool()
def get_activity_log(start_date: str, end_date: str) -> str:
    """
    Retrieves activity logs (steps, workouts) for a date range.
    
    Args:
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
    """
    data = data_loader.get_activity_log(start_date, end_date)
    if not data:
        return f"No activity data found between {start_date} and {end_date}."
    return str(data)

@mcp.tool()
def get_food_journal(date: str) -> str:
    """
    Retrieves the food journal for a specific date.
    
    Args:
        date: Date in YYYY-MM-DD format.
    """
    data = data_loader.get_food_journal(date)
    if not data:
        return f"No food journal entry found for {date}."
    return str(data)

@mcp.tool()
def get_sleep_data(date: str) -> str:
    """
    Retrieves sleep data for a specific date.
    
    Args:
        date: Date in YYYY-MM-DD format.
    """
    data = data_loader.get_sleep_data(date)
    if not data:
        return f"No sleep data found for {date}."
    return str(data)

@mcp.tool()
def get_user_profile() -> str:
    """
    Retrieves the user's general profile (age, height, weight, goals).
    """
    data = data_loader.get_user_profile()
    if not data:
        return "No user profile found."
    return str(data)

if __name__ == "__main__":
    mcp.run()
