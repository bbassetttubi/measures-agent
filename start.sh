#!/bin/bash

# Start script for Agentic Mesh Health Assistant

echo "============================================================"
echo "🚀 Starting Agentic Mesh Health Assistant..."
echo "============================================================"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Error: Virtual environment not found."
    echo "Please run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found."
    echo "Please create a .env file with your GOOGLE_API_KEY"
    exit 1
fi

# Check if GOOGLE_API_KEY is set
source .env
if [ -z "$GOOGLE_API_KEY" ]; then
    echo "❌ Error: GOOGLE_API_KEY not set in .env file"
    exit 1
fi

# Start the web application
echo "📱 Starting web server..."
echo ""

# Run in background and save PID
nohup venv/bin/python3 web_app.py > logs/web_app.log 2>&1 &
WEB_PID=$!
echo $WEB_PID > .web_app.pid

# Wait a moment for server to start
sleep 2

# Check if process is running
if ps -p $WEB_PID > /dev/null; then
    echo "✅ Web server started successfully (PID: $WEB_PID)"
    echo ""
    echo "============================================================"
    echo "🌐 Access the application at: http://localhost:5000"
    echo "============================================================"
    echo ""
    echo "📝 Logs: tail -f logs/web_app.log"
    echo "🛑 Stop: ./stop.sh"
    echo ""
else
    echo "❌ Failed to start web server"
    echo "Check logs/web_app.log for details"
    exit 1
fi
