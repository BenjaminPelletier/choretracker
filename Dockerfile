FROM python:3.13-slim

ENV UV_PROJECT_ENVIRONMENT=/app/.venv

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy project metadata
COPY pyproject.toml uv.lock ./

# Install dependencies without installing the project itself
RUN uv sync --frozen --no-install-project

# Copy application code
COPY choretracker ./choretracker

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "choretracker.app:app", "--host", "0.0.0.0", "--port", "8000"]
