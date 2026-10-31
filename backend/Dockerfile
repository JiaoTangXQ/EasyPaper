FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk libgl1 libglib2.0-0 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock .
RUN pip install --no-cache-dir uv==0.12.13 \
    && uv pip sync --system --no-cache requirements.lock
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /app/tmp /app/data /app/logs /app/reader-library \
    && chown -R app:app /app /home/app
COPY --chown=app:app . .
USER 10001:10001
EXPOSE 8000
# Caddy is the only published ingress. Keep ONE worker: in-memory queues/limits.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-keep-alive", "5"]
