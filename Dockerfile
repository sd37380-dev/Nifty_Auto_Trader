# ==============================================================================
# Dockerfile for NIFTY Autonomous Trader (Render / Docker Deployments)
# ==============================================================================
FROM python:3.11-slim

# Prevent Python from writing bytecode and enable immediate output flushing
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HOST=0.0.0.0 \
    RENDER=true

WORKDIR /app

# Install minimal base packages for network healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies first for Docker caching
COPY requirements.txt pyproject.toml /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source tree
COPY . /app/
RUN pip install --no-cache-dir -e .

# Expose container port (Render maps this to $PORT dynamically)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Start the interactive dashboard server
CMD ["sh", "-c", "python -m nifty_trader.cli dashboard --host 0.0.0.0 --port ${PORT} --no-open"]
