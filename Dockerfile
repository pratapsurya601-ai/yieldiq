FROM python:3.12-slim

WORKDIR /app

# Cache bust: v2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Unset any stale STREAMLIT env vars from previous builds
ENV STREAMLIT_SERVER_PORT=""
ENV STREAMLIT_SERVER_ADDRESS=""
ENV STREAMLIT_SERVER_HEADLESS=""

# Use Python to read Railway's PORT and start Streamlit
CMD python3 -c "import os;p=os.environ.get('PORT','8501');os.environ['STREAMLIT_SERVER_PORT']=p;os.environ['STREAMLIT_SERVER_ADDRESS']='0.0.0.0';os.environ['STREAMLIT_SERVER_HEADLESS']='true';os.execvp('streamlit',['streamlit','run','dashboard/app.py'])"
