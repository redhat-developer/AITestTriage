FROM --platform=linux/amd64 python:3.11-slim

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for better Docker layer caching
COPY pyproject.toml uv.lock .python-version ./

# Install dependencies only (cached unless pyproject.toml/uv.lock changes)
RUN uv sync --frozen --no-install-project

# Copy the application code
COPY . .

# Install the project itself
RUN uv sync --frozen

RUN chmod +x entrypoint.sh

# Create a non-root user and data directory
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Create data directory for conversation files
RUN mkdir -p /app/data && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app && \
    chmod -R 777 /app/data

USER appuser

# Expose the port
EXPOSE 3000

# Set environment variable to use tmp directory for data
ENV CONVERSATION_DATA_DIR=/tmp/

# Add venv to PATH so python resolves to the venv
ENV PATH="/app/.venv/bin:$PATH"

# Command to run the application
CMD ["./entrypoint.sh"]
