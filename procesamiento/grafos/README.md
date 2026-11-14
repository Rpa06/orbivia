# Grafo social de la tripulación

Servicio de ORBIVIA que estima cuánto tiempo de ocio pasan juntos los astronautas a partir de sus posiciones. Cada día de misión produce:

- una matriz de interacción y un grafo ponderado,
- indicadores de integración social por astronauta (`IsolationAnalyzer`),
- propuestas de actividades conjuntas voluntarias (`CollaborationRecommender`).

**Es un indicador estimativo, no un diagnóstico.** La proximidad física no prueba amistad ni bienestar. El diseño y sus justificaciones están en [docs/social_graph_design.md](../../docs/social_graph_design.md).

## Acceso a los resultados

- **En esta demo** el grafo y los indicadores son accesibles para cualquiera con acceso a la base de datos o a la carpeta de salida. No hay control de acceso.
- **En el producto final** solo deben ser accesibles desde la base de mando en Tierra, por personal autorizado. La tripulación solo ve el texto neutro de las propuestas aceptadas (`crew_text`), nunca el grafo ni los motivos.
- El grafo no se usa para asignar tareas operativas ni para juzgar compatibilidad entre personas.

## Ejecutar

### Demo en un paso

Borra el histórico, compila, levanta la pila, simula 30 días del escenario `drift` y muestra los resultados (unos 2 minutos):

```bash
bash procesamiento/grafos/demo.sh
```

Admite escenario y número de días: `bash procesamiento/grafos/demo.sh cliques 15`. Fija `SG_SIM_SCENARIO` y `SG_SIM_SPEEDUP=86400` en tu `.env`.

### Paso a paso

Desde la raíz del repositorio, con `.env` creado a partir de `.env.example`:

```bash
docker compose up -d --build
```

```bash
docker compose logs -f social-graph
```

Por defecto arranca en modo simulación. Con `SG_SIM_SPEEDUP=3600` un día de misión dura unos 30 segundos reales, y la simulación se detiene a los 60 días.

Los resultados aparecen en dos sitios:

- **Carpeta `volumenes/social-graph/`**: `latest.json` y `latest.png` (último día cerrado) y `day_NNNN.json` / `day_NNNN.png` por día.
- **PostgreSQL**, esquema `social_graph`: tabla `daily_result` (un documento JSON por día) y tabla `checkpoint` (estado del día en curso).

Ver los últimos días y el estado de cada astronauta:

```bash
docker compose exec db psql -U orbivia -d orbivia -c "SELECT day, jsonb_object_agg(a.key, a.value->>'status') AS estados FROM social_graph.daily_result, jsonb_each(result->'isolation'->'astronauts') a GROUP BY day ORDER BY day DESC LIMIT 5"
```

Ver las propuestas del último día:

```bash
docker compose exec db psql -U orbivia -d orbivia -c "SELECT p->>'crew_text' AS tripulacion, p->>'justification' AS tierra FROM social_graph.daily_result, jsonb_array_elements(result->'recommendations'->'proposals') p ORDER BY day DESC LIMIT 2"
```

## Reinicios

El servicio guarda su estado cada 30 segundos y al detenerse. Tras un `docker compose restart social-graph`, o una caída, retoma desde el último estado guardado sin perder ni contar dos veces.

## Empezar de cero

El estado guardado sobrevive a los reinicios, también al cambiar de escenario. Para cambiar de escenario o de tripulación hay que borrar el histórico:

```bash
docker compose stop social-graph
```

```bash
docker compose exec db psql -U orbivia -d orbivia -c "DROP SCHEMA IF EXISTS social_graph CASCADE"
```

```bash
docker compose up -d social-graph
```

Las imágenes y JSON antiguos siguen en `volumenes/social-graph/`; se pueden borrar a mano.

## Configurar

Todas las variables son opcionales y se definen en `.env`. Tiempos en segundos, distancias en metros.

### Fuente de datos

| Variable | Por defecto | Qué hace |
|---|---|---|
| `SG_SOURCE` | `simulation` | `simulation` o `redis` |
| `SG_STREAM` | `orbivia:positions` | Stream de Redis del que se lee |
| `SG_CREW` | `A1,A2,A3,A4,A5,A6` | Identificadores de la tripulación |
| `SG_CHECKPOINT_EVERY_S` | `30` | Cada cuánto se guarda el estado (tiempo real) |

Con `SG_SOURCE=redis`, cada entrada del stream lleva un campo `data` con este JSON:

```json
{"t": 86400.0, "positions": {"A1": [1.2, 0.4, 2.0], "A2": [3.1, 0.4, 2.0], "A3": null}}
```

`t` son segundos de tiempo de misión; `null` o la ausencia de un astronauta significa que no hay dato.

### Simulación

| Variable | Por defecto | Qué hace |
|---|---|---|
| `SG_SIM_SCENARIO` | `homogeneous` | Escenario (ver lista abajo) |
| `SG_SIM_SAMPLE_PERIOD_S` | `10` | Frecuencia de muestreo de posiciones |
| `SG_SIM_SPEEDUP` | `3600` | Segundos simulados por segundo real |
| `SG_SIM_DAYS` | `60` | Días a simular antes de quedar en pausa; `0` = sin límite |
| `SG_SIM_SEED` | `42` | Semilla; misma semilla, mismos datos |

`SG_SIM_SAMPLE_PERIOD_S` debe ser menor o igual que `SG_MAX_GAP_S`. Si no, todo cuenta como hueco de datos y no se observa nada; el servicio avisa en el log.

Escenarios: `homogeneous`, `low_integration`, `cliques`, `drift`, `unequal_leisure`, `shifted_schedules`, `schedule_change`, `simultaneous`, `sensor_loss`, `crew_wide_drop`. Para la demo, `drift` es el más ilustrativo: un astronauta se aísla progresivamente entre los días 10 y 25.

### Horarios

En simulación los define el escenario. Con Redis:

| Variable | Por defecto | Qué hace |
|---|---|---|
| `SG_SCHEDULE_JSON` | — | Horarios en JSON (ver formato) |
| `SG_SCHEDULE_FILE` | — | Ruta a un fichero con ese JSON |
| `SG_SCHEDULE_JITTER_S` | `0` | Variación diaria aleatoria de cada bloque |
| `SG_SCHEDULE_SEED` | `42` | Semilla de esa variación |

```json
{"A1": {"sleep": [["22:00", "06:00"]], "work": [["08:00", "16:00"]]}}
```

Quien no aparezca usa sueño 22:00–06:00 y trabajo 08:00–16:00. El ocio es lo que queda.

### Modelo

| Variable | Por defecto | Qué hace |
|---|---|---|
| `SG_D_IN_M` / `SG_D_OUT_M` | `2.0` / `2.5` | Distancia para empezar / dejar de contar interacción |
| `SG_MIN_DWELL_S` | `60` | Permanencia mínima para que un encuentro cuente |
| `SG_MAX_GAP_S` | `60` | Hueco máximo entre muestras que se tolera |
| `SG_DAY_CUTOFF` | `04:00` | Hora de misión en que se corta el día |
| `SG_NORMALIZATION` | `overlap` | `overlap` (por ocio simultáneo) o `leisure` (por ocio individual) |
| `SG_WEIGHT_FN` / `SG_KAPPA` | `exp` / `0.3` | Función de peso: `exp`, `linear`, `tanh`, `log1p`, `hill`, `sqrt` |
| `SG_MIN_LEISURE_S` / `SG_MIN_OVERLAP_S` | `1800` / `1800` | Mínimos para que algo sea evaluable |
| `SG_MIN_COVERAGE` | `0.5` | Cobertura mínima de datos |

### Aislamiento, grafo y recomendaciones

| Variable | Por defecto | Qué hace |
|---|---|---|
| `SG_BASELINE_WARMUP_DAYS` / `SG_BASELINE_WINDOW_DAYS` / `SG_BASELINE_LAG_DAYS` | `7` / `21` / `5` | Línea base individual |
| `SG_ALERT_Z` / `SG_ALERT_K` / `SG_ALERT_M` | `-2.5` / `3` / `5` | Desviación sostenida: `K` de `M` días por debajo de `Z` |
| `SG_CREW_RATIO_MIN` | `0.5` | Fracción de la mediana de la tripulación por debajo de la cual se señala |
| `SG_EDGE_MIN_W` / `SG_SMOOTH_DAYS` / `SG_MIN_MODULARITY` | `0.1` / `7` / `0.2` | Estructura de la red |
| `SG_LAYOUT` | `spring` | `spring` o `circular` |
| `SG_REC_MAX_PER_DAY` / `SG_REC_MAX_PER_PERSON_WEEK` | `2` / `2` | Topes de propuestas |
| `SG_REC_MIN_WINDOW_S` / `SG_REC_MAX_LEISURE_FRACTION` | `2700` / `0.33` | Duración de la actividad y parte del ocio que puede ocupar |
| `SG_REC_GROUP_SIZES` | `2,3` | Tamaños de grupo admitidos |

`SG_OUTPUT_DIR` y `SG_HEARTBEAT_FILE` los fija `docker-compose.yml`.

## Cómo leer los resultados

**Por pareja** hay cuatro casos, y solo los dos primeros dicen algo sobre la relación:

| Estado | Significado |
|---|---|
| `interaction` | Evaluable y con interacción |
| `zero` | Evaluable y sin interacción |
| `no_data` | No hay datos de la pareja |
| `not_evaluable` | Ocio, solape o cobertura insuficientes |

En la matriz `weights`, las parejas `no_data` y `not_evaluable` valen 0: hay que leer siempre la máscara `evaluable` o la matriz `status`. La falta de datos nunca se interpreta como aislamiento.

**Por astronauta**, el estado de integración:

| Estado | Significado |
|---|---|
| `normal` | Sin señales |
| `follow_up` | Una señal activa: seguimiento |
| `review` | Dos señales o aislamiento estructural: revisión por el equipo en Tierra |
| `warming_up` | Aún no hay línea base (12 días) |
| `no_data` / `not_evaluable` | No se emite juicio |

**En la imagen**, el grosor de la arista es proporcional al peso. La distancia entre nodos no significa nada.

## Tests

En el contenedor, con Python 3.12:

```bash
docker compose run --rm --no-deps social-graph python -m pytest
```

En local, con las dependencias de `docker/social-graph/requirements.txt` instaladas:

```bash
cd procesamiento/grafos && python -m pytest
```

Tardan unos 45 segundos, casi todo en las simulaciones de 32 días.

## Estructura

| Archivo | Contenido |
|---|---|
| `social_graph/intervals.py`, `schedule.py` | Intervalos, días de misión, horarios y ocio |
| `social_graph/validation.py` | Validación de posiciones y distancias |
| `social_graph/tracker.py` | Detector con histéresis y acumulador diario |
| `social_graph/weights.py`, `daily.py` | Normalización, peso y matriz diaria con máscara |
| `social_graph/isolation.py` | `IsolationAnalyzer` |
| `social_graph/recommender.py` | `CollaborationRecommender` |
| `social_graph/graph.py` | Grafo, layout, JSON e imagen |
| `social_graph/simulator.py` | Simulador y escenarios |
| `social_graph/sources.py`, `store.py` | Fuentes de datos y persistencia |
| `social_graph/service.py`, `config.py`, `__main__.py` | Servicio, configuración y arranque |

## Limitaciones

- Proximidad no equivale a interacción: dos personas a 2 m sin hablarse cuentan igual.
- Los horarios son los planificados; si no se siguen, el ocio real es otro.
- Los umbrales no están calibrados con datos reales.
- Las propuestas no se pueden aceptar ni descartar todavía: todas quedan como `proposed`.
- No hay panel de Tierra; los resultados están en ficheros y en la base de datos.
