#!/usr/bin/env python3
"""
Multi-turn conversation test for the simplified agent system.
"""

import requests
import json
import time

BASE_URL = "http://localhost:5000"

def chat(message: str, session_id: str = None) -> tuple[str, str]:
    """Send a chat message and return (response, session_id)."""
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    
    print(f"\n{'='*60}")
    print(f"👤 USER: {message}")
    print(f"{'='*60}")
    
    response = requests.post(
        f"{BASE_URL}/api/chat",
        json=payload,
        stream=True
    )
    
    full_response = ""
    new_session_id = session_id
    widgets = []
    
    for line in response.iter_lines():
        if line:
            line = line.decode('utf-8')
            if line.startswith('data: '):
                try:
                    data = json.loads(line[6:])
                    if data['type'] == 'agent':
                        print(f"  🤖 Agent: {data['name']}")
                    elif data['type'] == 'stream':
                        pass  # Streaming text
                    elif data['type'] == 'final':
                        if isinstance(data.get('content'), dict):
                            full_response = data['content'].get('response', '')
                            new_session_id = data['content'].get('session_id', session_id)
                        else:
                            full_response = data.get('content', '')
                        if data.get('session_id'):
                            new_session_id = data['session_id']
                    elif data['type'] == 'session':
                        new_session_id = data.get('session_id', session_id)
                    elif data['type'] == 'widget':
                        widgets.append(data['widget'])
                        print(f"  📦 Widget: {data['widget']}")
                    elif data['type'] == 'done':
                        break
                except json.JSONDecodeError:
                    pass
    
    # Print response (truncated for readability)
    if full_response:
        preview = full_response[:500] + "..." if len(full_response) > 500 else full_response
        print(f"\n🤖 ASSISTANT:\n{preview}")
    
    if widgets:
        print(f"\n📦 WIDGETS: {widgets}")
    
    return full_response, new_session_id


def run_test():
    print("\n" + "="*70)
    print("🧪 MULTI-TURN CONVERSATION TEST")
    print("="*70)
    
    session_id = None
    
    # Turn 1: Ask a direct question
    print("\n\n📍 TURN 1: Direct question (should get direct answer)")
    response, session_id = chat("What are my biggest health issues?", session_id)
    time.sleep(1)
    
    # Turn 2: Follow-up question
    print("\n\n📍 TURN 2: Follow-up question")
    response, session_id = chat("Why is my cholesterol high?", session_id)
    time.sleep(1)
    
    # Turn 3: Ask for a plan
    print("\n\n📍 TURN 3: Request a plan")
    response, session_id = chat("Can you give me a plan to fix this?", session_id)
    time.sleep(1)
    
    # Turn 4: Narrow the scope
    print("\n\n📍 TURN 4: Narrow the scope")
    response, session_id = chat("Just focus on the diet part", session_id)
    time.sleep(1)
    
    print("\n\n" + "="*70)
    print("✅ TEST COMPLETE")
    print("="*70)


if __name__ == "__main__":
    run_test()

