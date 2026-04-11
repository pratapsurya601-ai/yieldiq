#!/bin/bash
echo "Railway PORT=$PORT"
export STREAMLIT_SERVER_PORT="${PORT:-8501}"
export STREAMLIT_SERVER_ADDRESS="0.0.0.0"
export STREAMLIT_SERVER_HEADLESS="true"
echo "Starting Streamlit on port $STREAMLIT_SERVER_PORT"
exec streamlit run dashboard/app.py
