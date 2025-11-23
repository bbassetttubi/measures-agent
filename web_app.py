from flask import Flask, render_template, request, Response, jsonify
from flask_cors import CORS
import json
import sys
import io
from contextlib import redirect_stdout
from agent_system.orchestration import Orchestrator
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# Initialize orchestrator
orchestrator = None

def get_orchestrator():
    global orchestrator
    if orchestrator is None:
        orchestrator = Orchestrator()
    return orchestrator

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/chat', methods=['GET', 'POST'])
def chat():
    if request.method == 'GET':
        user_message = request.args.get('message', '')
        session_id = request.args.get('session_id', None)
    else:
        data = request.json
        user_message = data.get('message', '')
        session_id = data.get('session_id', None)
    
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    
    def generate():
        """Stream agent activity and responses via Server-Sent Events"""
        import queue
        import threading
        
        output_queue = queue.Queue()
        
        def run_orchestrator():
            """Run orchestrator in separate thread and capture output"""
            try:
                # Capture stdout
                import sys
                from io import StringIO
                
                # Create custom stdout that writes to queue
                class QueueWriter:
                    def write(self, text):
                        if text.strip():
                            output_queue.put(('output', text))
                        sys.__stdout__.write(text)  # Also write to console
                    
                    def flush(self):
                        sys.__stdout__.flush()
                
                old_stdout = sys.stdout
                sys.stdout = QueueWriter()
                
                try:
                    response, new_session_id = get_orchestrator().run_mesh(user_message, session_id)
                    output_queue.put(('final', {'response': response, 'session_id': new_session_id}))
                except Exception as e:
                    output_queue.put(('error', str(e)))
                finally:
                    sys.stdout = old_stdout
                    output_queue.put(('done', None))
                    
            except Exception as e:
                output_queue.put(('error', str(e)))
                output_queue.put(('done', None))
        
        # Start orchestrator in background thread
        thread = threading.Thread(target=run_orchestrator)
        thread.start()
        
        current_agent = None
        message_buffer = ""
        
        # Stream output from queue
        while True:
            try:
                msg_type, content = output_queue.get(timeout=0.1)
                
                if msg_type == 'output':
                    # Parse output for agent activity
                    if '--- Agent Active:' in content:
                        agent_name = content.split('--- Agent Active:')[1].strip().replace('---', '').strip()
                        current_agent = agent_name
                        yield f"data: {json.dumps({'type': 'agent', 'name': agent_name})}\n\n"
                    
                    elif '💬' in content and current_agent:
                        # Streaming text
                        text = content.replace('💬', '').strip()
                        if text and text != '(function call)':
                            message_buffer += text
                            yield f"data: {json.dumps({'type': 'stream', 'content': text})}\n\n"
                
                elif msg_type == 'final':
                    # Send final response if we didn't stream it
                    response_text = content['response'] if isinstance(content, dict) else content
                    new_session_id = content['session_id'] if isinstance(content, dict) else None
                    
                    if not message_buffer or len(message_buffer) < 50:
                        yield f"data: {json.dumps({'type': 'final', 'content': response_text, 'session_id': new_session_id})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'session', 'session_id': new_session_id})}\n\n"
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break
                
                elif msg_type == 'error':
                    yield f"data: {json.dumps({'type': 'error', 'message': content})}\n\n"
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break
                
                elif msg_type == 'done':
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break
                    
            except queue.Empty:
                # Keep connection alive
                yield f": keepalive\n\n"
                continue
        
        thread.join(timeout=1)
    
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not found in environment.")
        print("Please set it in your .env file.")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("🚀 Agentic Mesh Web Interface Starting...")
    print("="*60)
    print(f"\n📱 Open your browser to: http://localhost:5000")
    print("\n💡 Press Ctrl+C to stop the server\n")
    
    app.run(debug=True, port=5000, threaded=True)
