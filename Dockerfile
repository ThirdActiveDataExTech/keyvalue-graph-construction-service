# Global ARG for use in FROM statements
ARG VARIANT=cpu

# Production base images
FROM python:3.11-slim AS base-cpu

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS base-cu124-raw

# Install Python on CUDA image
FROM base-cu124-raw AS base-cu124
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3-pip && \
    ln -sf /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# CUDA library 환경변수 추가
ENV LD_LIBRARY_PATH=/usr/local/cuda-12.4/compat:${LD_LIBRARY_PATH}

# Builder stage - uses VARIANT-specific base
FROM base-${VARIANT} AS builder-base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY uv.lock pyproject.toml ./

ARG VARIANT
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$VARIANT" = "cu124" ]; then \
        uv sync --frozen --no-install-project --link-mode=copy --extra $VARIANT; \
    else \
        uv sync --frozen --no-install-project --link-mode=copy; \
    fi

# Final production stage
FROM base-${VARIANT} AS production

# Setting home directory and user name
ENV APP_HOME=/home/wisenut/app \
    GROUP_NAME=wisenut \
    APP_USER=wisenut

# Create a non-root user and group
RUN groupadd -r $GROUP_NAME && useradd -r -g $GROUP_NAME -d $APP_HOME $APP_USER

# Set the working directory
WORKDIR $APP_HOME
RUN chown -R $APP_USER:$GROUP_NAME $APP_HOME

# Set environment variables
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Seoul \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Switch to the non-root user
USER $APP_USER

# Copy virtual environment from builder
COPY --from=builder-base --chown=$APP_USER:$GROUP_NAME $VIRTUAL_ENV $VIRTUAL_ENV

# Copy files in order of change frequency (least to most)
# Static files change rarely
COPY --chown=$APP_USER:$GROUP_NAME ./static ./static/

# Model files (if any) - these are large but rarely change
# COPY --chown=$APP_USER:$GROUP_NAME ./model ./model/

# Config files
COPY --chown=$APP_USER:$GROUP_NAME pyproject.toml .env ./

# Application code changes most frequently
COPY --chown=$APP_USER:$GROUP_NAME ./app ./app/

# Generate version info file
RUN python app/version.py

# Expose the port
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
