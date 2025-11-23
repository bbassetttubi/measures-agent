class AgentRegistry:
    AGENTS = {
        "Physician": "Medical analysis, biomarker interpretation, reviewing blood work, identifying health risks.",
        "Fitness Coach": "Workout plans, exercise routines, activity analysis, heart rate zones.",
        "Nutritionist": "Dietary planning, food journal analysis, macronutrient advice, meal plans.",
        "Sleep Doctor": "Sleep hygiene, sleep stage analysis, improving sleep quality.",
        "Mindfulness Coach": "Stress reduction, meditation, mental wellness.",
        "User Persona": "Represents the user's preferences, goals, and profile data.",
        "Critic": "Final synthesis, safety check, formatting the response for the user."
    }

    @classmethod
    def get_registry_prompt(cls) -> str:
        prompt = "You are part of a collaborative mesh. Here are your peers and their capabilities:\n"
        for name, desc in cls.AGENTS.items():
            prompt += f"- **{name}**: {desc}\n"
        return prompt
