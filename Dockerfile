# Module 9c: one image = React dashboard + decision API.
#   docker build -t credit-console .
#   docker run -p 8000:8000 credit-console          -> http://localhost:8000
# Needs api/bundle/ first:  python -m api.export

# 1. Build the dashboard (runs natively on the build machine; the output is plain HTML/JS)
FROM --platform=$BUILDPLATFORM node:22-alpine AS web
WORKDIR /web
COPY dashboard/package*.json ./
RUN npm ci || npm install
COPY dashboard/ ./
RUN npm run build

# 2. The API: only the modules the scorer needs, no training stack, no raw data
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt
COPY pipeline/__init__.py pipeline/config.py pipeline/
COPY models/__init__.py models/features.py models/reason_codes.py models/
COPY stress/__init__.py stress/glm.py stress/
COPY streaming/__init__.py streaming/scorer.py streaming/
COPY api/__init__.py api/main.py api/service.py api/
COPY api/bundle/ api/bundle/
COPY --from=web /web/dist dashboard/dist

RUN useradd --create-home app && chown -R app /app
USER app
ENV PYTHONUNBUFFERED=1 WEB_CONCURRENCY=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers $WEB_CONCURRENCY"]
