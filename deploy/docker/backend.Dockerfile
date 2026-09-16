ARG PYTHON_IMAGE=python@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d
FROM ${PYTHON_IMAGE} AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv==0.11.28
WORKDIR /build/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM ${PYTHON_IMAGE} AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libpq5 postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 xray \
    && useradd --uid 10001 --gid 10001 --home-dir /app --create-home --shell /usr/sbin/nologin xray
WORKDIR /app
COPY --from=builder /build/backend/.venv /app/backend/.venv
COPY backend/ /app/backend/
COPY installer/ /app/installer/
COPY deploy/scripts/container-entrypoint.sh /usr/local/bin/xray-entrypoint
COPY deploy/scripts/run-outbox.sh /usr/local/bin/xray-outbox
RUN chmod 0555 /usr/local/bin/xray-entrypoint /usr/local/bin/xray-outbox \
    && chown -R 10001:10001 /app
ENV PATH=/app/backend/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["curl", "--fail", "--silent", "http://127.0.0.1:8000/health/live"]
ENTRYPOINT ["/usr/local/bin/xray-entrypoint"]
CMD ["gunicorn", "--chdir", "/app/backend", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "config.wsgi:application"]
