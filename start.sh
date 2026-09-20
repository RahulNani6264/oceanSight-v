#!/bin/bash
# OceanSight-V Startup Script
# This script starts both the backend API and frontend dev server

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "  OceanSight-V Startup"
echo "=========================================="
echo ""

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    echo "✓ Activating virtual environment"
    source .venv/Scripts/activate
fi

# Start backend in background
echo "Starting backend API server on http://127.0.0.1:8001..."
cd "$PROJECT_ROOT"
python -m uvicorn app.api:app --host 127.0.0.1 --port 8001 --reload &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID"

# Wait for backend to be ready
echo "Waiting for backend to be ready..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:8001/health > /dev/null 2>&1; then
        echo "✓ Backend is ready"
        break
    fi
    sleep 1
done

# Start frontend
echo "Starting frontend dev server on http://localhost:5173..."
cd "$PROJECT_ROOT/frontend"
npm run dev -- --host &
FRONTEND_PID=$!
echo "  Frontend PID: $FRONTEND_PID"

echo ""
echo "=========================================="
echo "  OceanSight-V is running!"
echo "=========================================="
echo "  Frontend:  http://localhost:5173"
echo "  Backend:   http://127.0.0.1:8001"
echo "  API Docs:  http://127.0.0.1:8001/docs"
echo "=========================================="
echo ""

# Wait for either process to exit
wait $BACKEND_PID $FRONTEND_PID 2>/dev/null