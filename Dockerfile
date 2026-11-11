# The base image is pinned by digest; Dependabot (M2) will propose updates.
FROM python:3.15-slim-bookworm@sha256:96599df822d0e1c6bb700014a05c7f3c8cabc6e0f7ff3c4f9f69cee033b4b5d9 AS build
RUN pip install --no-cache-dir uv==0.11.32
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.15-slim-bookworm@sha256:96599df822d0e1c6bb700014a05c7f3c8cabc6e0f7ff3c4f9f69cee033b4b5d9
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PTB_TIMEDELTA=1 \
    DATA_DIR=/data
COPY --from=build /app/.venv /app/.venv
RUN mkdir -p /data && chown 10001:10001 /data
USER 10001:10001
WORKDIR /data
VOLUME /data
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s \
    CMD ["python", "-m", "canvas_tracker", "healthcheck"]
ENTRYPOINT ["python", "-m", "canvas_tracker"]
