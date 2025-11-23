import os
import sys
from agent_system.orchestration import Orchestrator
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not found in environment.")
        print("Please set it via `export GOOGLE_API_KEY=...` or in a .env file.")
        return

    print("Initializing Agentic Mesh System...")
    orchestrator = Orchestrator()
    
    print("\nSystem Ready. Type 'exit' to quit.")
    print("Example: 'I'm feeling tired and my recent blood work shows low iron.'")
    
    while True:
        try:
            user_input = input("\nUser: ")
            if user_input.lower() in ["exit", "quit"]:
                break
                
            response = orchestrator.run_mesh(user_input)
            
            print(f"\nAgent: {response}")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"An error occurred: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()
