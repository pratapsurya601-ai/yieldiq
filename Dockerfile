FROM python:3.12-slim

WORKDIR /app

# Install system dependencies needed for some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all app code
COPY . .

# Railway sets PORT dynamically
ENV PORT=8501

# Run Streamlit
CMD sh -c "streamlit run dashboard/app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true"
