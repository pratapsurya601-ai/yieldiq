FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY backend/requirements_backend.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements_backend.txt

COPY . .

EXPOSE ${PORT:-8000}

CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
