FROM python:3.13-slim

ARG CHORETRACKER_VERSION
ENV CHORETRACKER_VERSION=$CHORETRACKER_VERSION
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies required to build packages from source
# Remove Docker's default apt cleanup hook which fails on some architectures
RUN rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        zlib1g-dev \
        libjpeg-dev \
        libpng-dev \
        libfreetype6-dev \
        libtiff-dev \
        libwebp-dev \
        libopenjp2-7-dev \
        liblcms2-dev \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv after required build tools are available
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy project metadata
COPY pyproject.toml uv.lock ./

# Install dependencies without installing the project itself
RUN uv sync --frozen --no-install-project \
    && rm -rf /var/lib/apt/lists/*

# Copy application code and migration files
# Copy each directory explicitly so Docker preserves their names
COPY choretracker/ ./choretracker
COPY alembic.ini ./alembic.ini
COPY migrations/ ./migrations

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "choretracker.app:app", "--host", "0.0.0.0", "--port", "8000"]
