import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

LOG_PATH = Path("logs/feedback.log")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def record_feedback(event: str, payload: Dict[str, Any]):
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event": event,
        "payload": payload,
    }
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

