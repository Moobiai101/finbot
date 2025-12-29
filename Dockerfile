# Use official Python 3.12 runtime (required for pandas-ta)
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Set work directory
WORKDIR /app

# Install system dependencies (gcc needed for some python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code
COPY . .

# Expose port (Railway overrides PORT env var)
EXPOSE $PORT

# Run the application (shell form to expand $PORT)
CMD uvicorn finbot.main:app --host 0.0.0.0 --port $PORT
