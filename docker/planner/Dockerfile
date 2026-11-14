FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/planner/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# El planificador reutiliza el álgebra de intervalos del grafo social (solo lectura)
COPY procesamiento/grafos/social_graph ./social_graph
COPY sistema-de-recomendacion/planificador/crew_planner ./crew_planner
COPY sistema-de-recomendacion/planificador/config ./config
COPY sistema-de-recomendacion/planificador/examples ./examples
COPY sistema-de-recomendacion/planificador/tests ./tests
COPY sistema-de-recomendacion/planificador/pytest.ini ./pytest.ini
