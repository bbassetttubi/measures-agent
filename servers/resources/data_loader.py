import json
import os
import lancedb
from typing import List, Dict, Any, Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LANCEDB_URI = os.path.join(DATA_DIR, "lancedb")

def load_json(filename: str) -> Any:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return {}
    with open(path, 'r') as f:
        return json.load(f)

def get_biomarker_ranges(biomarker_name: str) -> Optional[Dict[str, Any]]:
    ranges = load_json("ranges.json")
    # Case insensitive search
    for name, data in ranges.items():
        if biomarker_name.lower() in name.lower():
            return {name: data}
    return None

def get_workout_plan(goal: str) -> List[Dict[str, Any]]:
    workouts = load_json("workouts.json")
    # Filter by name or difficulty matching the goal string roughly
    results = []
    for w in workouts:
        if goal.lower() in w['name'].lower() or goal.lower() in w['difficulty'].lower():
            results.append(w)
    return results

def get_supplement_info(name: str) -> Optional[Dict[str, Any]]:
    supplements = load_json("supplements.json")
    for s in supplements:
        if name.lower() in s['name'].lower():
            return s
    return None

def search_knowledge_base(query: str) -> List[Dict[str, Any]]:
    """
    Searches the LanceDB knowledge base.
    Since we didn't generate embeddings in the generation script (to keep it simple/fast),
    we will do a full text search if possible, or just a simple scan.
    
    LanceDB's full text search requires an index which we didn't build.
    For this prototype, we will load the table and do a python-side filter.
    In a real SOTA system, we would use `tbl.search(query).limit(5).to_list()`.
    """
    try:
        db = lancedb.connect(LANCEDB_URI)
        tbl = db.open_table("knowledge_base")
        
        # Mock semantic search by simple keyword matching for this prototype
        # Real implementation would use embeddings.
        all_docs = tbl.to_pandas().to_dict('records')
        
        results = []
        keywords = query.lower().split()
        for doc in all_docs:
            score = 0
            text = (doc['title'] + " " + doc['content']).lower()
            for kw in keywords:
                if kw in text:
                    score += 1
            if score > 0:
                results.append(doc)
        
        # Sort by simple score
        results.sort(key=lambda x: sum(1 for kw in keywords if kw in (x['title'] + " " + x['content']).lower()), reverse=True)
        return results[:5]
        
    except Exception as e:
        print(f"Error searching LanceDB: {e}")
        return []
