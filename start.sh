#!/bin/bash

# Start Trading Bot in background
echo "Starting Trading Bot..."
python main.py &
BOT_PID=$!

# Wait for bot to initialize
sleep 5

# Start Streamlit Dashboard
echo "Starting Dashboard on port 8501..."
streamlit run dashboard/app.py --server.port=8501 --server.address=0.0.0.0

# Cleanup
kill $BOT_PID
