FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/python-core/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY sistema-de-recomendacion/api ./api
COPY docker/workers ./workers
COPY procesamiento/streaming-valores-continuos-sueno/sleep_stream ./sleep_stream

