import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Any


class FeedbackAnalytics:
    """
    Lightweight reader that aggregates feedback events from logs/feedback.log
    so agents can tailor their behavior based on historical user interactions.
    """

    def __init__(self, log_path: str = "logs/feedback.log"):
        self.log_path = Path(log_path)
        self._last_mtime = None
        self._summary: Dict[str, Any] = {
            "plan_confirmed": 0,
            "plan_declined": 0,
            "partial_requests": {},
            "scope_preferences": {},
            "total_events": 0,
        }
        self.refresh(force=True)

    def refresh(self, force: bool = False):
        if not self.log_path.exists():
            if force:
                self._summary = {
                    "plan_confirmed": 0,
                    "plan_declined": 0,
                    "partial_requests": {},
                    "scope_preferences": {},
                    "total_events": 0,
                }
            return

        mtime = self.log_path.stat().st_mtime
        if not force and self._last_mtime == mtime:
            return

        plan_confirmed = 0
        plan_declined = 0
        partial_counter = Counter()
        scope_counter = Counter()
        total = 0

        with self.log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload") or {}
                evt = event.get("event")
                total += 1
                if evt == "plan_confirmed":
                    plan_confirmed += 1
                elif evt == "plan_declined":
                    plan_declined += 1
                elif evt == "partial_plan":
                    partial_counter[payload.get("offer", "unknown")] += 1
                elif evt == "plan_scope":
                    for domain in payload.get("scope") or []:
                        scope_counter[domain] += 1
                elif evt == "plan_scope_expanded":
                    for domain in payload.get("added") or []:
                        scope_counter[domain] += 1

        self._summary = {
            "plan_confirmed": plan_confirmed,
            "plan_declined": plan_declined,
            "partial_requests": dict(partial_counter),
            "scope_preferences": dict(scope_counter),
            "total_events": total,
        }
        self._last_mtime = mtime

    def get_summary(self) -> Dict[str, Any]:
        return self._summary.copy()

