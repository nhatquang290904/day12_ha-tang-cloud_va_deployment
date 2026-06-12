# ============================================================
# Production Dockerfile — Multi-stage, < 200 MB, non-root
# ============================================================

# Stage 1: Builder — cài dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Stage 2: Runtime — image cuối cùng, nhỏ gọn
FROM python:3.11-slim AS runtime

# Non-root user cho bảo mật
RUN groupadd -r agent && useradd -r -g agent -d /app agent

WORKDIR /app

# Copy packages vào system Python path (không phụ thuộc user)
COPY --from=builder /install /usr/local

# Copy application code
COPY app/ ./app/
COPY utils/ ./utils/

RUN chown -R agent:agent /app

USER agent

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check — platform dùng để detect container unhealthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
