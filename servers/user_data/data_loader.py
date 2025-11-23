import json
import os
from typing import List, Dict, Any, Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

def load_json(filename: str) -> Any:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path, 'r') as f:
        return json.load(f)

def get_biomarkers(names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    all_biomarkers = load_json("biomarkers.json")
    if not names:
        return all_biomarkers
    
    # Case-insensitive partial match
    results = []
    for b in all_biomarkers:
        for name in names:
            if name.lower() in b['name'].lower():
                results.append(b)
                break
    return results

def get_activity_log(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    log = load_json("activity.json")
    # Simple string comparison for ISO dates works
    return [entry for entry in log if start_date <= entry['date'] <= end_date]

def get_food_journal(date: str) -> Optional[Dict[str, Any]]:
    log = load_json("food_journal.json")
    for entry in log:
        if entry['date'] == date:
            return entry
    return None

def get_sleep_data(date: str) -> Optional[Dict[str, Any]]:
    log = load_json("sleep.json")
    for entry in log:
        if entry['date'] == date:
            return entry
    return None

def get_user_profile() -> Optional[Dict[str, Any]]:
    return load_json("profile.json")
