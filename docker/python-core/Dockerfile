FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY docker/python-core/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# API, workers y simulador
COPY sistema-de-recomendacion/api ./api
COPY docker/workers/worker.py ./workers/worker.py
COPY workers ./workers
COPY simulador ./simulador
# Módulos de procesamiento
COPY procesamiento/streaming-valores-continuos-sueno/sleep_stream ./sleep_stream
COPY procesamiento/texto/ ./texto/
COPY procesamiento/colapso/colapso ./colapso
COPY procesamiento/conductual/conductual ./conductual
COPY procesamiento/test-cerrado/checkin.py ./checkin.py
# Motor y planificador. Del grafo social solo se copia el álgebra de intervalos:
# el análisis del grafo no existe en esta imagen, así que el planificador no puede usarlo.
COPY sistema-de-recomendacion/motor/motor ./motor
COPY sistema-de-recomendacion/planificador/crew_planner ./crew_planner
COPY sistema-de-recomendacion/planificador/config ./config
COPY sistema-de-recomendacion/planificador/catalog ./catalog
COPY procesamiento/grafos/social_graph/__init__.py procesamiento/grafos/social_graph/intervals.py ./social_graph/
# Sincronización con Tierra
COPY sync-tierra/sync_tierra ./sync_tierra
