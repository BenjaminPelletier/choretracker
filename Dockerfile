FROM python:3.13-slim

ENV UV_PROJECT_ENVIRONMENT=/app/.venv

# Install uv
RUN pip install --no-cache-dir uv

# Install build tools required for some Python packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project metadata
COPY pyproject.toml uv.lock ./

# Install dependencies without installing the project itself
RUN uv sync --frozen --no-install-project \
    && apt-get purge -y --auto-remove build-essential zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY choretracker ./choretracker

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "choretracker.app:app", "--host", "0.0.0.0", "--port", "8000"]
