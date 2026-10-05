# syntax=docker/dockerfile:1
# ---- frontend build -------------------------------------------------------
FROM --platform=$BUILDPLATFORM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --include=dev --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- runtime ----------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/searxng_control ./searxng_control
COPY --from=ui /ui/dist ./static
ENV STATIC_DIR=/app/static DATA_DIR=/data HOST=0.0.0.0 PORT=8890
EXPOSE 8890
VOLUME ["/data"]
LABEL org.opencontainers.image.title="searxng-control" \
      org.opencontainers.image.description="Monitoring and control panel for a self-hosted SearXNG instance" \
      org.opencontainers.image.source="https://github.com/ghreprimand/searxng-control" \
      org.opencontainers.image.licenses="MIT"
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request;h=os.environ['HOST'];h='127.0.0.1' if h in ('0.0.0.0','::') else h;urllib.request.urlopen(f\"http://{h}:{os.environ['PORT']}/healthz\",timeout=4)"
CMD ["python", "-m", "searxng_control.main"]
