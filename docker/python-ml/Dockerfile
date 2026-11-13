FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/python-core/requirements.txt ./requirements-core.txt
COPY docker/python-ml/requirements.txt ./requirements-ml.txt
RUN pip install --no-cache-dir -r requirements-core.txt -r requirements-ml.txt

COPY docker/workers ./workers

