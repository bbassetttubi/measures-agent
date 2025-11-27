import json
import threading
from typing import Dict, Any

import google.generativeai as genai


class IntentClassifier:
    """
    Lightweight helper that asks a fast Gemini model to interpret the user's latest
    utterance and return the conversational focus and intent in structured form.
    """

    _model = None
    _lock = threading.Lock()

    def __init__(self):
        if not IntentClassifier._model:
            with IntentClassifier._lock:
                if not IntentClassifier._model:
                    IntentClassifier._model = genai.GenerativeModel(
                        model_name="gemini-2.0-flash-thinking-exp",
                        system_instruction=(
                            "You are a conversation intent classifier for a health assistant. "
                            "Analyze the User Message given the Context. "
                            "Respond with JSON ONLY. "
                            "Fields: "
                            "1. 'focus': What is the user focused on? (diagnosis, plan, wellbeing, progress, acceleration, or other) "
                            "2. 'intent': What does the user want? (diagnosis, plan, answer, other) "
                            "3. 'confirmation_status': If user is responding to a question, are they confirming (yes), declining (no), clarifying, or none? "
                            "4. 'urgency': low, medium, high. "
                            "5. 'emotion': neutral, stressed, anxious, upbeat. "
                            "Do not add commentary."
                        ),
                    )

    def classify(self, user_text: str, context_snapshot: str = "") -> Dict[str, Any]:
        prompt = (
            "User message:\n"
            f"{user_text.strip()}\n\n"
            "Context:\n"
            f"{context_snapshot.strip() if context_snapshot else '(none)'}\n\n"
            "Respond with JSON exactly in this shape:\n"
            '{"focus":"...", "intent":"...", "confirmation_status":"...", "urgency":"...", "emotion":"...", "confidence":0.0}\n'
        )
        try:
            result = IntentClassifier._model.generate_content(prompt, generation_config={"temperature": 0.1})
            text = "".join(part.text for part in result.candidates[0].content.parts if getattr(part, "text", None))
            text = text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
        except Exception as exc:
            return {
                "focus": "diagnosis", 
                "intent": "diagnosis", 
                "confirmation_status": "none", 
                "urgency": "medium", 
                "emotion": "neutral", 
                "confidence": 0.0, 
                "error": str(exc)
            }
