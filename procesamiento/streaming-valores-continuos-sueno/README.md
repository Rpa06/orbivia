# Datos de sueño en streaming (`sleep_stream`)

Recibe los datos biométricos de cada astronauta mientras duerme, los agrega de forma incremental en Redis y, al terminar la sesión, genera un vector resumen por astronauta que se guarda en PostgreSQL.

Diseño, garantías, vector y resultados medidos: [docs/sleep_stream_design.md](../../docs/sleep_stream_design.md).

Los datos de ejemplo y de las pruebas son sintéticos. Las anomalías que detecta son estadísticas, no diagnósticos.

## Puesta en marcha

Con el despliegue normal de Orbivia (`docker compose up -d --build`) quedan activos:

- `worker-stream`: consume el stream de Redis y procesa los datos.
- `api`: expone los endpoints `/sleep/...` en <http://localhost:8000/docs>.

## Uso por la API

Iniciar una sesión:

```bash
curl -X POST localhost:8000/sleep/sessions -H 'content-type: application/json' -d '{"astronaut_id":"ASTRO_001","sleep_session_id":"SLEEP_2026_001","start_timestamp":1794672000,"sample_period_s":1}'
```

Enviar un registro (o una lista de registros):

```bash
curl -X POST localhost:8000/sleep/records -H 'content-type: application/json' -d '{"astronaut_id":"ASTRO_001","sleep_session_id":"SLEEP_2026_001","timestamp":1794672060,"metrics":{"heart_rate":58,"heart_rate_variability":72,"spo2":98,"respiratory_rate":14,"skin_temperature":33.8,"movement":0.12}}'
```

Consultar el estado, finalizar y recuperar el resultado:

```bash
curl localhost:8000/sleep/sessions/ASTRO_001/SLEEP_2026_001
```

```bash
curl -X POST localhost:8000/sleep/sessions/ASTRO_001/SLEEP_2026_001/end -H 'content-type: application/json' -d '{"end_timestamp":1794700800}'
```

```bash
curl localhost:8000/sleep/sessions/ASTRO_001/SLEEP_2026_001/summary
```

| Método y ruta | Qué hace | Respuestas |
|---|---|---|
| `POST /sleep/sessions` | Inicia una sesión | 201; 409 si existe con otro inicio; 422 si está mal formada |
| `POST /sleep/records` | Encola uno o varios registros | 202; 422 si alguno está mal formado (no se encola ninguno) |
| `GET /sleep/sessions/{astro}/{sesión}` | Estado del procesamiento | 200; 404 |
| `POST /sleep/sessions/{astro}/{sesión}/end` | Finaliza la sesión | 202; 404 |
| `GET /sleep/sessions/{astro}/{sesión}/summary` | Vector y resumen | 200; 409 si aún no está; 404 |
| `GET /sleep/sessions/{astro}/{sesión}/measurements` | Mediciones para el planificador | 200; 409; 404 |
| `GET /sleep/astronauts/{astro}/sessions` | Historial de sesiones | 200 |

La API solo valida y encola. Un sensor también puede escribir directamente en el stream `orbivia:sleep:ingest` con el campo `data` y el mismo JSON.

Estados de una sesión: `active` → `finalizing` (fin recibido) → `sealed` (resumen calculado) → `completed` (guardado en PostgreSQL y disponible).

Cada resumen completado publica un aviso en el stream `orbivia:sleep:summaries`.

## Configuración

Variables de entorno opcionales, en `.env` (ver `.env.example`). Las usan `worker-stream` y `api`.

| Variable | Por defecto | Significado |
|---|---|---|
| `SLEEP_LEVELS_S` | `60,300,900,1800` | Tamaño de las ventanas de cada nivel, en segundos |
| `SLEEP_RETAIN_S` | `900,3600,7200` | Cuánto se conserva cada nivel antes de fundirlo en el siguiente |
| `SLEEP_Z_THRESHOLD` | `4.0` | Desviaciones típicas a partir de las que un valor es anómalo |
| `SLEEP_EWMA_HALFLIFE_S` | `600` | Semivida de la referencia local de anomalías |
| `SLEEP_WARMUP_S` | `600` | Calentamiento antes de puntuar anomalías |
| `SLEEP_BASELINE_Z_THRESHOLD` | `4.0` | Umbral respecto a la línea base individual |
| `SLEEP_MAX_ANOMALIES` | `200` | Episodios guardados por sesión |
| `SLEEP_ACTIVITY_METRIC` | `movement` | Métrica usada para la actigrafía |
| `SLEEP_ACTIVITY_THRESHOLD` | `0.3` | Un minuto es activo si su media de movimiento lo supera |
| `SLEEP_DEDUP_RESOLUTION_S` | `1.0` | Dos registros en el mismo intervalo son el mismo |
| `SLEEP_MAX_SESSION_S` | `86400` | Duración máxima de una sesión |
| `SLEEP_MISSION_EPOCH_S` | `0` | Epoch Unix del segundo 0 de la misión, para el planificador |
| `SLEEP_COMPLETED_TTL_S` | `172800` | Caducidad del estado temporal tras guardar el resumen |
| `SLEEP_SUMMARY_TTL_S` | `604800` | Caducidad de la copia del resumen en Redis |
| `SLEEP_METRICS_FILE` | — | JSON con la lista de métricas, sus unidades y rangos |
| `SLEEP_PREFIX` | `orbivia:sleep` | Prefijo de las claves de Redis |
| `SLEEP_CLAIM_IDLE_MS` | `30000` | Tiempo sin confirmar tras el que otro consumidor reclama un mensaje |

Todos los valores son puntos de partida de diseño. Los rangos de las métricas describen lo que mide el sensor, no umbrales médicos.

## Pruebas

Dentro de Docker, contra el Redis y el PostgreSQL del despliegue. Usan la base 15 de Redis y un prefijo propio, y borran solo lo suyo:

```bash
docker compose run --rm worker-stream python -m pytest
```

En local, desde esta carpeta, con `redis`, `psycopg[binary]`, `fastapi`, `httpx` y `pytest` instalados y un Redis accesible (`REDIS_HOST`, `REDIS_PORT`). Sin Redis se omiten los tests que lo necesitan; sin `POSTGRES_HOST`, los de PostgreSQL.

```bash
python -m pytest
```

## Simulación, benchmark y recuperación

Noche sintética de varios astronautas, procesada por el servicio en marcha:

```bash
docker compose run --rm worker-stream python -m sleep_stream.simulate --astronauts 5 --hours 8 --period 1 --no-worker
```

Comparación medida entre guardar todo y agregar de forma incremental:

```bash
docker compose run --rm worker-stream python -m sleep_stream.benchmark --astronauts 5 --hours 8 --period 1
```

Recuperación ante un reinicio de Redis, en tres pasos. Entre el primero y el segundo se reinicia Redis:

```bash
docker compose run --rm worker-stream python -m sleep_stream.recovery_check first
```

```bash
docker compose restart broker
```

```bash
docker compose run --rm worker-stream python -m sleep_stream.recovery_check rest
```

```bash
docker compose run --rm worker-stream python -m sleep_stream.recovery_check verify
```

La simulación y la comprobación de recuperación dejan sesiones sintéticas (`ASTRO_001`…) en PostgreSQL; el benchmark borra las suyas.

## Ficheros

| Fichero | Contenido |
|---|---|
| `sleep_stream/config.py` | Configuración y catálogo de métricas |
| `sleep_stream/records.py` | Formato y validación de mensajes |
| `sleep_stream/stats.py` | Acumuladores fusionables, tendencia y referencia exponencial |
| `sleep_stream/engine.py` | Ventanas, colapso progresivo, anomalías y actigrafía |
| `sleep_stream/summary.py` | Resumen y vector de sueño |
| `sleep_stream/processor.py` | Redis: ingesta, transacciones, finalización y recuperación |
| `sleep_stream/store.py` | Almacén duradero en PostgreSQL |
| `sleep_stream/worker.py` | Servicio `worker-stream` |
| `sleep_stream/api.py` | Endpoints `/sleep` |
| `sleep_stream/integration.py` | Mediciones para el planificador y vector como lista |
| `sleep_stream/simulate.py` | Datos sintéticos y simulación |
| `sleep_stream/benchmark.py` | Benchmark A/B |
| `sleep_stream/recovery_check.py` | Comprobación de recuperación |
| `benchmarks/` | Resultados medidos |
