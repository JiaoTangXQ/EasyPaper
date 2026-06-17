FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (fonts for PDF generation, build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create directories
RUN mkdir -p /app/tmp /app/data /app/logs

EXPOSE 8000

# --proxy-headers + trusting the (internal-only) reverse proxy makes
# request.client.host the real client IP, so per-IP rate limiting works behind Caddy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
