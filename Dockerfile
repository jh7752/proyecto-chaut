FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY src ./src
COPY vendor ./vendor
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .
RUN if [ -f vendor/coinsenda/package-lock.json ]; then npm ci --prefix vendor/coinsenda --omit=dev; else npm install --prefix vendor/coinsenda --omit=dev; fi

EXPOSE 8000
CMD ["uvicorn", "chaut_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
