import requests
import json
import time
import sys

BASE_URL = "http://localhost:5000/api/chat"

def print_step(step_name):
    print(f"\n{'='*50}")
    print(f"🔵 STEP: {step_name}")
    print(f"{'='*50}")

def send_message(message, session_id=None):
    print(f"\n📤 Sending: {message}")
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    
    try:
        # Use stream=True to handle SSE, but for this test we just want the final output and session_id
        # We'll collect lines until we see 'final'
        with requests.post(BASE_URL, json=payload, stream=True) as r:
            r.raise_for_status()
            final_content = ""
            new_session_id = session_id
            
            for line in r.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data: '):
                        data = json.loads(decoded_line[6:])
                        
                        if data['type'] == 'stream':
                            # print(data['content'], end='', flush=True)
                            pass
                        elif data['type'] == 'final':
                            final_content = data['content']
                            if 'session_id' in data:
                                new_session_id = data['session_id']
                        elif data['type'] == 'session':
                            new_session_id = data['session_id']
                        elif data['type'] == 'error':
                            print(f"\n❌ Error: {data['message']}")
                            
            print(f"\n📥 Response: {final_content[:200]}... [truncated]")
            return new_session_id, final_content
            
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return session_id, ""

def run_test():
    print("🚀 Starting Multi-Turn Interaction Test")
    
    # Turn 1: Initial Diagnosis
    print_step("1. Initial Diagnosis Query")
    session_id, response = send_message("I've been feeling really tired lately and my joints hurt. Can you check my levels?")
    if not session_id:
        print("❌ Failed to get session ID. Aborting.")
        return

    time.sleep(2)

    # Turn 2: Confirmation of Comprehensive Plan
    print_step("2. Confirming the Plan")
    session_id, response = send_message("That sounds concerning. Yes, please give me a plan to fix this.", session_id)

    time.sleep(2)

    # Turn 3: Narrowing Scope (Testing Dynamic Intelligence)
    print_step("3. Narrowing Scope to Nutrition Only")
    session_id, response = send_message("Actually, I just want to focus on my diet for now. I'm too busy for exercise.", session_id)

    time.sleep(2)
    
    # Turn 4: Specific Question (Testing Context Retention)
    print_step("4. Specific Question about Nutrition")
    session_id, response = send_message("Will eating more spinach help with the fatigue?", session_id)

    print("\n✅ Test Complete.")

if __name__ == "__main__":
    run_test()

