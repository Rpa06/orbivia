FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# ffmpeg decodifica audio y vídeo por tuberías (stdin/stdout), sin ficheros temporales
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Modelos de transcripción y texto (procesamiento/texto). Se instalan para poder activar
# ENABLE_NLP, pero por defecto no se cargan. INSTALL_NLP=false los omite de la imagen.
ARG INSTALL_NLP=true
RUN if [ "$INSTALL_NLP" = "true" ]; then pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    "torch==2.7.1+cpu"; fi

COPY docker/python-ml/requirements.txt ./requirements-ml.txt
COPY docker/python-ml/requirements-nlp.txt ./requirements-nlp.txt
RUN pip install --no-cache-dir -r requirements-ml.txt \
    && if [ "$INSTALL_NLP" = "true" ]; then pip install --no-cache-dir -r requirements-nlp.txt; fi

COPY docker/workers/worker.py ./workers/worker.py
COPY workers ./workers
COPY procesamiento/texto/ ./texto/
COPY procesamiento/video/ ./video/
