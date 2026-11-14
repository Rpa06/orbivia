FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

COPY docker/social-graph/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY procesamiento/grafos/social_graph ./social_graph
COPY procesamiento/grafos/tests ./tests
COPY procesamiento/grafos/pytest.ini ./pytest.ini
