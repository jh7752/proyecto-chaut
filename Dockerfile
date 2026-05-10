FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
ENV CHAUT_BUILD_REV=6826252
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm ca-certificates && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY src ./src
COPY vendor ./vendor
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .
RUN if [ -f vendor/coinsenda/package-lock.json ]; then npm ci --prefix vendor/coinsenda --omit=dev; else npm install --prefix vendor/coinsenda --omit=dev; fi
RUN npx --prefix vendor/coinsenda playwright install chromium --with-deps

EXPOSE 8000
CMD ["uvicorn", "chaut_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
