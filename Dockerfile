FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD python -c "import os; port=os.environ.get('PORT','8501'); os.execvp('streamlit',['streamlit','run','dashboard/app.py','--server.port='+port,'--server.address=0.0.0.0','--server.headless=true'])"
