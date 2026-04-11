FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create a startup script that handles PORT properly
RUN echo '#!/bin/bash\nstreamlit run dashboard/app.py --server.port=${PORT:-8501} --server.address=0.0.0.0 --server.headless=true' > /app/start.sh && chmod +x /app/start.sh

CMD ["/bin/bash", "/app/start.sh"]
