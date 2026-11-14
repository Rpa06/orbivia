FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    "torch==2.7.1+cpu"

COPY docker/python-ml/requirements.txt ./requirements-ml.txt
RUN pip install --no-cache-dir -r requirements-ml.txt

COPY docker/workers ./workers
COPY procesamiento/texto/ ./texto/

