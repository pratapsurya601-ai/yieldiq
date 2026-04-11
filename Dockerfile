FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Use STREAMLIT_SERVER_PORT env var instead of --server.port flag
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_HEADLESS=true

# Railway sets PORT env var — copy it to Streamlit's expected var
CMD bash -c "export STREAMLIT_SERVER_PORT=\${PORT:-8501} && streamlit run dashboard/app.py"
