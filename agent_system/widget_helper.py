"""
Widget Helper - Loads widget data from resource files for agent responses.
"""

import json
import os
from datetime import datetime
from pathlib import Path

class WidgetHelper:
    """Helper class to load and format widget data for agent responses."""
    
    def __init__(self):
        self.data_dir = Path(__file__).parent.parent / "servers" / "resources" / "data"
        self._cache = {}
    
    def _load_json(self, file_path: Path):
        """Load JSON with simple mtime-based caching."""
        try:
            mtime = file_path.stat().st_mtime
        except FileNotFoundError:
            return None
        
        cache_entry = self._cache.get(file_path)
        if cache_entry and cache_entry["mtime"] == mtime:
            return cache_entry["data"]
        
        with open(file_path) as f:
            data = json.load(f)
        
        self._cache[file_path] = {"mtime": mtime, "data": data}
        return data
    
    def get_workout_widget(self, goal: str) -> dict:
        """
        Get workout widget data.
        
        Args:
            goal: Workout goal (e.g., "Hypertrophy", "Cardio", "Cholesterol")
            
        Returns:
            Widget data dictionary
        """
        workouts_file = self.data_dir / "workouts.json"
        
        workouts = self._load_json(workouts_file)
        if not workouts:
            return None
        
        # Find matching workout
        for workout in workouts:
            if goal.lower() in workout.get('name', '').lower() or goal.lower() in workout.get('difficulty', '').lower():
                return {
                    "type": "Workout plan",
                    "data": {
                        "planId": workout.get("id"),
                        "title": workout.get("name"),
                        "level": workout.get("difficulty"),
                        "duration": workout.get("duration"),
                        "description": workout.get("description"),
                        "videos": workout.get("videos", [])
                    }
                }
        
        return None
    
    def get_supplement_widget(self, supplement_names: list) -> dict:
        """
        Get supplement widget data.
        
        Args:
            supplement_names: List of supplement names
            
        Returns:
            Widget data dictionary
        """
        supplements_file = self.data_dir / "supplements.json"
        
        supplements = self._load_json(supplements_file)
        if not supplements:
            return None
        
        # Filter supplements based on requested names
        selected_supplements = []
        for name in supplement_names:
            for supp in supplements:
                if name.lower() in supp.get('name', '').lower():
                    selected_supplements.append({
                        "id": supp.get("id", supp['name'].lower().replace(" ", "-")),
                        "name": supp['name'],
                        "tagline": supp.get('tagline', ", ".join(supp.get('benefits', [])[:2])),
                        "buyUrl": supp.get('buyUrl', 'https://www.thorne.com')
                    })
                    break
        
        if not selected_supplements:
            return None
        
        return {
            "type": "Supplements — Thorne",
            "data": {
                "title": "Supplement Recommendations",
                "note": "Consult your physician before starting any supplements. These are general recommendations based on your health data.",
                "items": selected_supplements
            }
        }
    
    def get_meal_plan_widget(self, plan_type: str) -> dict:
        """
        Get meal plan widget data.
        
        Args:
            plan_type: Type of meal plan (e.g., "cholesterol", "energy", "muscle")
            
        Returns:
            Widget data dictionary
        """
        meals_file = self.data_dir / "meals.json"
        
        meal_plans = self._load_json(meals_file)
        if not meal_plans:
            return None
        
        # Find matching meal plan
        selected_plan = None
        for plan in meal_plans:
            if plan_type.lower() in plan.get('name', '').lower() or plan_type.lower() in plan.get('id', '').lower():
                selected_plan = plan
                break
        
        if not selected_plan and meal_plans:
            selected_plan = meal_plans[0]
        
        if not selected_plan:
            return None
        
        # Get current date for label
        today = datetime.now().strftime("%a, %b %d, %Y")
        
        return {
            "type": "Meal plan: watch & order",
            "data": {
                "title": selected_plan['name'],
                "dateLabel": today,
                "meals": selected_plan['meals']
            }
        }

