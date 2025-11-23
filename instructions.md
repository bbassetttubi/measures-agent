# Agentic System Build Instructions

## Project Overview
Build a state-of-the-art (SOTA) agentic system for personal health and wellness coaching using the **Google Gen AI SDK** and **Model Context Protocol (MCP)**. The system employs a decentralized **"Agentic Mesh"** architecture where specialized agents collaborate peer-to-peer (A2A) to solve complex user requests.

## Architecture: Agentic Mesh
The system moves beyond simple "Router-Solver" patterns to a collaborative mesh. Agents are not just tools; they are autonomous entities that can delegate work to peers, maintaining a shared context.

### 1. Core Components
*   **Guardrail**: The entry point for user input. Responsible for safety checks, PII redaction, and input validation.
*   **Triage Agent (formerly Planner)**: The initial intent classifier. Instead of a rigid router, it acts as a "dispatcher" that identifies the *primary* domain and hands off control. It does *not* micro-manage the entire flow.
*   **Specialized Agents (The Mesh)**: Domain-specific agents that execute tasks and collaborate.
    *   **Physician Agent**: Medical/biomarker analysis.
    *   **Fitness Coach**: Workout plans and activity.
    *   **Mindfulness Coach**: Mental health.
    *   **Sleep Doctor**: Sleep analysis.
    *   **Nutrition Agent**: Diet and food.
    *   **User Persona Agent**: Represents the user's preferences and holistic profile.
*   **Critic and Synthesizer**: The final "sink" node. It receives the collective output from the mesh, critiques it for consistency/safety, and formats the final response.
*   **Shared Context / Memory**: A structured state object passed between agents (not just chat history).

### 2. Data Layer (MCP Servers)
The system integrates with **Model Context Protocol (MCP) Servers** to access external data.
*   **Personal Knowledge Graph (User Data)**:
    *   **(A) Biomarker Data**: Blood work, lab results, genetics.
    *   **(B) Activity / Fitness Data**: Workouts, steps, heart rate.
    *   **(C) Food Journal Data**: Daily intake, macros, meal logs.
    *   **(D) Sleep Data**: Sleep stages, duration, quality.
    *   **(E) User Profile Data**: Age, height, weight, sex, goals.
*   **Resources Data (Reference)**:
    *   **(F) Biomarker Ranges Data**: Reference ranges, optimal levels.
    *   **(G) Workout Plans Data**: Exercises, routines, progressions.
    *   **(H) Approved Supplements Data**: Dosage, interactions, benefits.
    *   **(I) Book / Article / Research Data**: Scientific literature, guides.
    *   **(J) Videos**: Instructional content, educational clips.
    *   **(K) Food Plan Data**: Recipes, meal plans, dietary guidelines.

## Technology Stack & SOTA Patterns
*   **Language**: Python
*   **Framework**: **Google Gen AI SDK**.
*   **Protocol**: **Model Context Protocol (MCP)**.
*   **Storage**: **Vector Database** (e.g., LanceDB) for semantic retrieval.

### Key SOTA Patterns to Implement
1.  **Dynamic Handoff Collaboration (A2A Protocol)**:
    *   Agents use **dynamic peer-to-peer handoffs** rather than hardcoded paths or a central router.
    *   **Universal Transfer Tool**: Agents utilize a single `transfer_handoff(target_agent, reason, context_update)` tool.
    *   **Context-Aware Routing**: The LLM decides the *next best agent* at runtime based on the `AgentContext` and a **Dynamic Registry** of peer capabilities.
2.  **Structured Context Transfer**:
    *   Do not just pass the conversation history. Pass a **Structured Context Object** (e.g., a Pydantic model) containing:
        *   `user_intent`: The original goal.
        *   `accumulated_findings`: Key data discovered so far (e.g., "High Cholesterol confirmed").
        *   `pending_tasks`: What still needs to be done.
    *   Use the SDK's context/state management features to ensure this object is available to the next agent.
3.  **Agents as Tools (MCP)**:
    *   Treat MCP servers as first-class tools. Agents should "discover" capabilities via MCP.
    *   Use **Intent-Based Routing** in the Triage Agent to select the best starting point.
4.  **Observability & Tracing**:
    *   Implement deep tracing for every agent handoff and tool call.
    *   Log the "reasoning chain" across the mesh to debug infinite loops or bad handoffs.

## Implementation Steps

### Phase 1: Infrastructure & MCP
1.  **Project Setup**: Initialize with `google-generativeai`.
2.  **MCP Integration**: Implement an MCP Client that connects to the data servers. Ensure tools are typed and validated.

### Phase 2: The Mesh Network
1.  **Define the Context Schema**: Create a Pydantic model for `AgentContext` that holds the state of the investigation.
2.  **Implement Agents**:
    *   Each agent must have a system prompt defining its **Role**, **Capabilities**, and **Handoff Criteria**.
    *   *Crucial*: Give agents a **Universal Handoff Tool** and inject a **Dynamic Registry** of peer capabilities into their system prompt so they can make intelligent routing decisions.
3.  **Implement Handoff Logic**:
    *   Ensure the `handoff` function updates the `AgentContext` before transferring control.

### Phase 3: Entry & Exit
1.  **Triage Agent**: Implements the initial routing logic based on user intent.
2.  **Critic Agent**: The final destination. It must look at the `accumulated_findings` in the context and generate a cohesive answer.

### Phase 4: Orchestration Loop
1.  **Main Loop**:
    *   `User Input` -> `Guardrail` -> `Triage` -> `[Agent Mesh]` -> `Critic` -> `Output`.
2.  **Loop Detection**: Implement a counter in the `AgentContext` to prevent infinite handoff cycles (e.g., max 10 turns).

## Example Workflow (SOTA Mesh)
1.  **User**: "I'm feeling tired and my recent blood work shows low iron."
2.  **Triage**: Identifies "Medical" intent. Hands off to **Physician Agent**.
3.  **Physician Agent**:
    *   *Action*: Calls MCP tool `get_biomarkers`. Confirms low iron.
    *   *Reasoning*: "Low iron requires dietary changes and sleep check."
    *   *Update Context*: Adds `finding: low_iron`, `recommendation: increase_iron_intake`.
    *   *Handoff*: Decides `Nutritionist` is needed. Calls `transfer_handoff(target="Nutritionist", reason="Needs iron-rich diet plan", context=...)`.
4.  **Nutrition Agent**:
    *   *Action*: Reads context. Generates iron-rich meal plan.
    *   *Update Context*: Adds `plan: iron_rich_meals`.
    *   *Handoff*: Calls `transfer_handoff(target="Sleep Doctor", reason="User reported tiredness", context=...)`.
5.  **Sleep Doctor**:
    *   *Action*: Checks sleep data. Suggests rest.
    *   *Handoff*: Calls `transfer_handoff(target="Critic", reason="All tasks complete", context=...)`.
6.  **Critic**: Synthesizes all findings into one empathetic response.

## Notes for the Agent
*   **Type Safety**: Use Pydantic for all tool inputs/outputs and context objects.
*   **Fail Fast**: If an agent cannot help, it should hand off to the Critic with a "cannot assist" message, not loop endlessly.
