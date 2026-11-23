# Multi-stage production Dockerfile for OntoAgent
FROM python:3.12-slim

# Install system runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency definition and install Python dependencies
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Copy application source code and configuration assets
COPY src/ ./src/
COPY ontology/ ./ontology/
COPY policies/ ./policies/
COPY mcp_server/ ./mcp_server/
COPY scripts/ ./scripts/
COPY docs/ ./docs/

# Set production environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    GRADIO_SERVER_NAME="0.0.0.0" \
    GRADIO_SERVER_PORT="7860"

# Expose ports: Gradio Console (7860) and REST API (8000)
EXPOSE 7860 8000

# Default entrypoint runs the Gradio Operations Console
CMD ["python", "-m", "ontoagent.ui.app", "--host", "0.0.0.0", "--port", "7860"]
