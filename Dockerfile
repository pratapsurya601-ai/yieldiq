FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway injects PORT as env var. Streamlit reads STREAMLIT_SERVER_PORT.
# This script bridges the two.
RUN printf '#!/bin/bash\nexport STREAMLIT_SERVER_PORT="${PORT:-8501}"\nexport STREAMLIT_SERVER_ADDRESS="0.0.0.0"\nexport STREAMLIT_SERVER_HEADLESS="true"\nexec streamlit run dashboard/app.py\n' > /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"]
