FROM python:3.12-slim

WORKDIR /app

# Cache bust v3
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Clear ALL Streamlit env vars to prevent stale values
ENV STREAMLIT_SERVER_PORT=""
ENV STREAMLIT_SERVER_ADDRESS=""
ENV STREAMLIT_SERVER_HEADLESS=""

# Python reads PORT, validates it's a number, then starts Streamlit
CMD python3 -c "\
import os,sys;\
p=os.environ.get('PORT','8501');\
p=''.join(c for c in str(p) if c.isdigit()) or '8501';\
print(f'Starting on port {p}');\
os.environ['STREAMLIT_SERVER_PORT']=p;\
os.environ['STREAMLIT_SERVER_ADDRESS']='0.0.0.0';\
os.environ['STREAMLIT_SERVER_HEADLESS']='true';\
os.execvp('streamlit',['streamlit','run','dashboard/app.py'])"
