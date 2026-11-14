FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/sleep-stream/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY procesamiento/streaming-valores-continuos-sueno/sleep_stream ./sleep_stream
COPY procesamiento/streaming-valores-continuos-sueno/tests ./tests
COPY procesamiento/streaming-valores-continuos-sueno/pytest.ini ./pytest.ini
