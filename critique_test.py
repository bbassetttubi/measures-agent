import requests
import json
import time
import sys

BASE_URL = "http://127.0.0.1:5000/api/chat"

def run_turn(turn_name, message, session_id=None):
    print(f"\n=== {turn_name} ===")
    print(f"User: {message}")
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id
        
    start_time = time.time()
    response_content = ""
    
    try:
        with requests.post(BASE_URL, json=payload, stream=True) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith("data: "):
                        data = json.loads(decoded_line[6:])
                        if data['type'] == 'session':
                            session_id = data['session_id']
                        elif data['type'] == 'final':
                            response_content = data['content']
                        elif data['type'] == 'agent':
                            sys.stdout.write(f"[{data['name']}] ")
                            sys.stdout.flush()
                        elif data['type'] == 'widget':
                            print(f"\n[Widget]: {data['widget']}")
                            
    except Exception as e:
        print(f"Error: {e}")
        return session_id

    duration = time.time() - start_time
    print(f"\n\nSystem ({duration:.1f}s): {response_content[:200]}...")
    if len(response_content) > 200:
        print(f"... {len(response_content)} chars total")
    
    return session_id

def run_critique_session():
    # Turn 1: Vague complaint
    session_id = run_turn("Turn 1: Ambiguity", "I've been feeling really low energy lately.")
    time.sleep(1)
    
    # Turn 2: Data inquiry
    session_id = run_turn("Turn 2: Data Context", "Does my blood work explain why?", session_id)
    time.sleep(1)
    
    # Turn 3: Mixed Intent/Constraint
    session_id = run_turn("Turn 3: Constraint", "Okay, I want to fix it. Give me a plan, but no supplements please, I hate swallowing pills.", session_id)
    time.sleep(1)
    
    # Turn 4: Dynamic Pivot
    session_id = run_turn("Turn 4: Pivot", "Actually, wait. Just give me a meal plan for now.", session_id)

if __name__ == "__main__":
    # Ensure server is running (assuming user has it running based on context)
    run_critique_session()

