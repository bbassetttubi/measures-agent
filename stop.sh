#!/bin/bash

# Stop script for Agentic Mesh Health Assistant

echo "============================================================"
echo "🛑 Stopping Agentic Mesh Health Assistant..."
echo "============================================================"
echo ""

# Check if PID file exists
if [ ! -f ".web_app.pid" ]; then
    echo "⚠️  No PID file found. Server may not be running."
    echo "Checking for running processes..."
    
    # Try to find and kill any running web_app.py processes
    PIDS=$(ps aux | grep "[w]eb_app.py" | awk '{print $2}')
    
    if [ -z "$PIDS" ]; then
        echo "✅ No running processes found."
        exit 0
    else
        echo "Found running processes: $PIDS"
        echo "Killing processes..."
        kill $PIDS
        sleep 1
        echo "✅ Processes stopped."
        exit 0
    fi
fi

# Read PID from file
PID=$(cat .web_app.pid)

# Check if process is running
if ps -p $PID > /dev/null 2>&1; then
    echo "Stopping web server (PID: $PID)..."
    kill $PID
    
    # Wait for process to stop
    sleep 2
    
    # Force kill if still running
    if ps -p $PID > /dev/null 2>&1; then
        echo "Force stopping..."
        kill -9 $PID
    fi
    
    echo "✅ Web server stopped successfully"
else
    echo "⚠️  Process $PID not found (may have already stopped)"
fi

# Clean up PID file
rm -f .web_app.pid

echo ""
echo "============================================================"
echo "✅ Shutdown complete"
echo "============================================================"
