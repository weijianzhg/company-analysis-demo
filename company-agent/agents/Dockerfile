# -------------------------------------------------------------------
# Bedrock AgentCore Runtime requires linux/arm64 containers.
# This image uses uv for fast, reproducible dependency installation.
# -------------------------------------------------------------------

FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Install dependencies first (layer caching via uv.lock)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy agent source code
COPY . .

ENV AGENT_HOST=0.0.0.0 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# AgentCore Runtime expects the application on port 8080
EXPOSE 8080

# Run exactly the dependencies installed above; AgentCore captures runtime logs.
CMD ["uv", "run", "--no-sync", "python", "main.py"]
