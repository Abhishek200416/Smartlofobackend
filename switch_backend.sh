#!/bin/bash

# SmartLOFO Backend Switcher
# This script helps you switch between MongoDB and SQLite backends

echo "╔════════════════════════════════════════╗"
echo "║   SmartLOFO Backend Switcher          ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo "Available backends:"
echo "  1) MongoDB Backend (server.py) - Default"
echo "  2) SQLite Backend (server.py)"
echo "  3) Run both backends (MongoDB:8001, SQLite:8002)"
echo "  4) Show backend status"
echo "  5) Exit"
echo ""
read -p "Choose an option (1-5): " choice

case $choice in
    1)
        echo ""
        echo "→ Switching to MongoDB Backend..."
        sudo supervisorctl stop backend
        cd /app/backend
        sudo supervisorctl start backend
        echo "✓ MongoDB backend is running on port 8001"
        echo "  Database: MongoDB"
        echo "  API: http://localhost:8001/api/"
        ;;
    2)
        echo ""
        echo "→ Switching to SQLite Backend..."
        sudo supervisorctl stop backend
        cd /app/backend
        # Kill any existing SQLite backend
        pkill -f "uvicorn server_sqlite:app" 2>/dev/null
        # Start SQLite backend
        nohup uvicorn server_sqlite:app --host 0.0.0.0 --port 8001 --reload > /var/log/backend_sqlite.log 2>&1 &
        echo "✓ SQLite backend is running on port 8001"
        echo "  Database: SQLite (smartlofo.db)"
        echo "  API: http://localhost:8001/api/"
        echo "  Logs: /var/log/backend_sqlite.log"
        ;;
    3)
        echo ""
        echo "→ Running both backends..."
        # MongoDB on 8001 (via supervisor)
        sudo supervisorctl start backend
        # SQLite on 8002
        cd /app/backend
        pkill -f "uvicorn server_sqlite:app --host 0.0.0.0 --port 8002" 2>/dev/null
        nohup uvicorn server_sqlite:app --host 0.0.0.0 --port 8002 --reload > /var/log/backend_sqlite_8002.log 2>&1 &
        echo "✓ Both backends are running:"
        echo "  MongoDB: http://localhost:8001/api/ (via supervisor)"
        echo "  SQLite:  http://localhost:8002/api/"
        echo "  Logs: /var/log/backend_sqlite_8002.log"
        ;;
    4)
        echo ""
        echo "→ Backend Status:"
        echo ""
        echo "MongoDB Backend (supervisor):"
        sudo supervisorctl status backend
        echo ""
        echo "SQLite Backend:"
        if pgrep -f "server_sqlite:app" > /dev/null; then
            echo "  Status: RUNNING"
            ps aux | grep "server_sqlite:app" | grep -v grep | awk '{print "  PID:", $2, "Port:", "8001 or 8002"}'
        else
            echo "  Status: NOT RUNNING"
        fi
        echo ""
        echo "Testing APIs..."
        echo "MongoDB API:"
        curl -s http://localhost:8001/api/ 2>/dev/null || echo "  Not responding"
        echo ""
        echo "SQLite API (if on port 8002):"
        curl -s http://localhost:8002/api/ 2>/dev/null || echo "  Not running on port 8002"
        ;;
    5)
        echo ""
        echo "Goodbye!"
        exit 0
        ;;
    *)
        echo ""
        echo "Invalid option. Please run the script again."
        exit 1
        ;;
esac

echo ""
echo "═══════════════════════════════════════"
echo "Tip: Frontend will automatically use whichever backend is on port 8001"
echo "═══════════════════════════════════════"
