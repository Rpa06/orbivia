# Planificador diario de tareas

Módulo de ORBIVIA que propone el reparto diario de tareas individuales y colectivas de la tripulación. Tiene en cuenta:

- el estado de cada astronauta,
- los requisitos y la importancia de cada tarea,
- las cualificaciones,
- el historial reciente,
- la equidad de carga,
- y los límites semanales de NASA-STD-3001 que fija el proyecto.

No usa el grafo social, ni directa ni indirectamente.

**Es una herramienta de apoyo: propone, no decide.** Toda planificación la valida una persona. El modelo matemático y las decisiones de diseño están en [docs/crew_planner_design.md](../../docs/crew_planner_design.md).

## Principios

- **Seguridad antes que nada.** Cualificaciones, requisitos críticos, disponibilidad, descanso, horas máximas, tareas exigentes por día y recursos compartidos son restricciones duras: no tienen peso y nunca se relajan.
- **Verificación independiente.** Todo plan pasa por un verificador que no depende del optimizador antes de devolverse.
- **No se inventan datos.** Un parámetro sin medición, caducado o sin línea base es *desconocido*:
  - si es crítico para la tarea, el astronauta no es elegible;
  - si no lo es, se penaliza como incertidumbre.
  - La confianza de una medición solo se usa si la da la fuente.
- **No se infieren emociones ni se usa el grafo social.** No entran en el estado el ánimo, la personalidad, las puntuaciones de voz o texto ni el grafo social.
- **Objetivos por etapas.** Primero la cobertura de tareas aplazables y después el coste operativo (estado, repetición, incertidumbre y equidad).
- **Explicable y reproducible.** Cada asignación lleva su desglose y sus alternativas. El mismo dato con la misma configuración da siempre el mismo plan.

## Acceso a los resultados

- La **justificación** (`justification`) es para personal autorizado.
- La tripulación solo debe ver `crew_text`: tarea, personas y horario, sin métricas ni motivos.
- En Orbivia integrado, el acceso lo controla la API por rol (ver README principal).

## Ejecutar

### En Docker

Desde la raíz del repositorio. El servicio tiene el perfil `planner` y no arranca con `docker compose up`.

```bash
docker compose --profile planner build planner
```

Escenario de demostración:

```bash
docker compose run --rm --no-deps planner python -m crew_planner.simulation --scenario high_fatigue
```

Siete días seguidos, guardando en `volumenes/planner/` un plan JSON y dos informes visuales por día (`plan_NNNN.html` para Tierra y `plan_NNNN_tripulacion.html`):

```bash
docker compose run --rm --no-deps planner python -m crew_planner.simulation --days 7 --out /data
```

Planificar una entrada propia:

```bash
docker compose run --rm --no-deps planner python -m crew_planner examples/day_nominal.json
```

Tests:

```bash
docker compose run --rm --no-deps planner python -m pytest
```

### En local

Con Python 3.12 o superior y las dependencias de `docker/planner/requirements.txt`, desde esta carpeta:

```bash
python -m pytest
```

```bash
PYTHONPATH=.:../../procesamiento/grafos python -m crew_planner examples/day_nominal.json --out plan.json
```

### Informe visual

`--html plan.html` genera, además del JSON, un informe que se abre con doble clic en el navegador, sin conexión y en modo claro u oscuro. Contiene:

- el cronograma por astronauta, con las franjas no disponibles;
- la carga frente a la carga objetivo;
- el coste por término;
- una ficha por tarea con su justificación, alternativas y descartes.

`--html-crew horario.html` genera la versión para la tripulación: solo el horario y el texto neutro de cada tarea. Lo demás no se oculta, simplemente no se escribe en el fichero.

```bash
docker compose run --rm --no-deps planner python -m crew_planner examples/day_nominal.json --html /data/plan.html --html-crew /data/horario.html
```

Códigos de salida:

| Código | Significado |
|---|---|
| `0` | Plan generado |
| `2` | Sin solución factible, o el optimizador agotó el tiempo |
| `1` | Entrada inválida |

## Tres planes para elegir

Por defecto el planificador propone **tres planes completos del día**, entre los que eligen la tripulación y el control de misión:

| Opción | Enfoque |
|---|---|
| A · Equilibrado | Los pesos de la configuración |
| B · Mejor adecuación | Que cada tarea la haga quien mejor encaja hoy con sus requisitos, aunque el reparto sea menos parejo |
| C · Reparto y rotación | Repartir la carga según la capacidad de cada uno y rotar las actividades repetidas |

- **Los tres son seguros:** cumplen las mismas restricciones duras y pasan el verificador independiente. Solo cambia el peso de los objetivos blandos.
- **Siempre son distintos:** cada plan difiere de los anteriores en al menos `min_difference` asignaciones (2 por defecto). Si no es posible, se exige menos; si no hay ninguna alternativa, se proponen menos planes y se dice por qué.
- **Comparación para Tierra:** una tabla con métricas que no dependen de los pesos (adecuación, incertidumbre, reparto de la carga, rotación). Cada plan lista sus ventajas y en qué asignaciones cambia respecto a la opción A.
- **Versión de la tripulación:** solo ve los tres horarios con el nombre de cada plan.

El JSON de salida lleva los planes en `plans`, la comparación en `plans[i].option` y la decisión en `decision`, que queda `pending` hasta que se elija. Registrar la elección todavía no está implementado.

Los enfoques, su número y la diferencia mínima se cambian en `[alternatives]` de `config/default.toml`, o con `CP_ALTERNATIVES_COUNT` y `CP_ALTERNATIVES_MIN_DIFFERENCE`. Con `--plans 1` se obtiene un único plan, en el formato anterior.

En la simulación, `--choose B` decide qué plan se da por ejecutado cada día (por defecto, el A); el historial del día siguiente parte de ese plan.

## Entornos de misión

Hay un catálogo de 160 tareas de cuatro entornos (`catalog/`): ISS, superficie lunar, superficie marciana y servicio de satélites. Cada tarea lleva:

- un vector físico y otro cognitivo de exigencia (0-1);
- sus cualificaciones obligatorias;
- frecuencia, modo de ejecución y referencias NASA.

El optimizador es el mismo en los cuatro: al elegir un entorno solo cambian las tareas del día.

```bash
docker compose run --rm --no-deps planner python -m crew_planner.simulation --environment moon --days 7
```

Con `--event ISS_COL_006` se dispara una tarea de evento o contingencia, y con `--out /data` se guardan los planes y sus informes visuales.

**Las puntuaciones son estimaciones teóricas del modelo Orbivia, no datos de NASA.** Antes de llegar al optimizador se traducen a requisitos sobre las mediciones del astronauta con `config/requirement_mapping.toml`; en las tareas críticas, una exigencia alta se convierte en restricción dura.

- Metodología: [docs/task_catalog_methodology.md](../../docs/task_catalog_methodology.md).
- Tabla comparativa e informe de calibración: [docs/task_requirements_table.md](../../docs/task_requirements_table.md), que se regenera con `python -m crew_planner.catalog_report --out ../../docs/task_requirements_table.md`.

## Escenarios de simulación

La tripulación, las tareas y las mediciones son **sintéticas**: cada medición lleva `source = "synthetic:..."`.

| Escenario | Qué muestra |
|---|---|
| `nominal` | Día normal con seis astronautas y ocho tareas |
| `high_fatigue` | A2 no recibe tareas con umbrales críticos de sueño o fatiga, y su carga objetivo baja |
| `incomplete_data` | A3 sin datos: no es elegible donde el dato es crítico y su capacidad se toma con el valor conservador |
| `critical_task` | La EVA va a la única persona que cumple todos los umbrales, aunque la hiciera ayer |
| `unqualified` | A4, en mejor estado que nadie, nunca recibe una tarea de robótica |
| `repetition` | Rota la preparación de comidas; la revisión médica se queda con la única persona cualificada |
| `workload_imbalance` | La equidad reparte la carga de quien es la mejor opción para casi todo |
| `infeasible` | Dos EVA obligatorias imposibles: devuelve el conflicto mínimo y sugerencias, sin plan |

## Entrada

Un JSON por día; hay ejemplos completos en [examples/](examples/).

```json
{
  "day": 10,
  "as_of": 864000,
  "crew": [{
    "id": "A1",
    "qualifications": ["eva", "medical"],
    "work": [["08:00", "17:00"]],
    "sleep": [["00:00", "07:00"], ["23:00", "24:00"]],
    "unavailable": [["12:00", "13:00"]],
    "measurements": [{"parameter": "sleep_duration_h", "value": 7.4, "measured_at": 856800, "source": "watch"}],
    "baselines": [{"parameter": "pvt_lapses", "mean": 2.0, "sd": 1.0}],
    "max_work_h": 7
  }],
  "tasks": [{
    "id": "EVA_PREP", "name": "Preparación de EVA", "kind": "individual", "importance": 5,
    "duration_min": 90, "earliest": "08:00", "latest": "12:00", "intensity": 0.8, "demanding": true,
    "qualifications": ["eva"], "resources": ["airlock"], "mandatory": true,
    "requirements": [{"parameter": "sleep_duration_h", "min": 6.5, "critical": true, "weight": 2}]
  }],
  "history": [{"day": 9, "astronaut": "A1", "task_id": "EVA_PREP", "category": "EVA_PREP", "duration_min": 90}]
}
```

**Tiempos:**
- Los tiempos de misión (`as_of`, `measured_at`) van en segundos.
- Las horas del día van en `HH:MM`. Un tramo que cruza la medianoche se escribe en dos.
- La vigencia de cada dato se mide desde `as_of`, que por defecto es la medianoche del día.

**Tareas:**
- Las colectivas añaden `min_people`, `max_people` y `team_qualifications` (`{"qualification": "life_support", "mode": "at_least", "count": 1}` o `"mode": "all"`).
- `mandatory: false` significa que la tarea es aplazable.
- `category` agrupa tareas parecidas para medir la repetición.

**Requisitos:**
- `min`, `max` o ambos, en la escala del parámetro: unidades físicas si se normaliza por rango, puntuación z si se compara con la línea base.
- `critical: true` los convierte en restricción dura.

**Grafo social:** no es una entrada del planificador. Una entrada con la clave `social` se rechaza. En Orbivia el grafo social nunca se usa para repartir, agrupar ni separar a la tripulación (README principal, sección 2.D). Los pesos `gamma` y `mu`, la etapa de inclusión y el escenario `isolation` de versiones anteriores se han eliminado por ese motivo.

**Límites semanales e investigación:** `crew_planner/policy.py` traduce las horas trabajadas en los 6 días anteriores a un tope para el día (60 h semanales y como máximo dos jornadas de 10 h o más) y fija las tareas de categoría `science` a su responsable, para que nunca se reasignen.

Los campos desconocidos son un error, para que una errata no pase desapercibida.

## Salida

- `status`: `ok`, `infeasible` o `timeout`.
- `individual[]`: astronauta, horario, adecuación por requisito, datos desconocidos, repetición, desglose de coste, alternativas con su diferencia de coste, descartados con su motivo, `justification` y `crew_text`.
- `collective[]`: lo mismo por equipo, más la interacción observada del equipo, si la tarea es de baja carga y a quién se incluye.
- `global`:
  - carga por astronauta frente a su carga objetivo;
  - tareas cubiertas y pendientes, y astronautas sin asignación;
  - datos desconocidos por astronauta;
  - coste por término;
  - uso del grafo;
  - estado de cada etapa del optimizador y si el óptimo está demostrado;
  - avisos y violaciones (siempre vacías: si no, el sistema da error).
- `conflicts[]`, solo si no hay solución: las tareas y los límites en conflicto, y sugerencias que requieren una decisión humana. El sistema no aplica ninguna.

## Configurar

Todos los pesos y límites están en [config/default.toml](config/default.toml), comentados. Hay dos formas de cambiarlos sin tocar el código:

- con otro fichero, en `--config` o en `CP_CONFIG_FILE`;
- valor a valor, con `CP_<SECCIÓN>_<CLAVE>` en el `.env`.

| Variable | Por defecto | Qué hace |
|---|---|---|
| `CP_WEIGHTS_ALPHA_STATE` | `1.0` | Desviación entre estado y requisitos |
| `CP_WEIGHTS_ALPHA_REPETITION` | `0.3` | Monotonía |
| `CP_WEIGHTS_ALPHA_UNCERTAINTY` | `0.5` | Datos desconocidos o poco fiables |
| `CP_WEIGHTS_ALPHA_EQUITY` / `CP_WEIGHTS_BETA_SPREAD` | `0.5` / `0.5` | Equidad de carga |
| `CP_STAGES_MODE` | `lexicographic` | `lexicographic` (por etapas) o `weighted` (suma única) |
| `CP_LIMITS_MAX_WORK_H` | `8` | Horas de tarea por astronauta y día |
| `CP_LIMITS_MAX_DEMANDING_PER_DAY` | `2` | Tareas exigentes por día |
| `CP_LIMITS_REST_AFTER_DEMANDING_MIN` | `30` | Descanso tras una tarea exigente |
| `CP_SOLVER_TIME_LIMIT_S` | `20` | Tiempo máximo por etapa |

El catálogo de parámetros del vector de estado también está en el TOML (`[[parameters]]`). Para añadir uno nuevo basta con declararlo con su tipo, su normalización, su vigencia y su dominio.

## Estructura

| Archivo | Contenido |
|---|---|
| `crew_planner/model.py`, `history.py`, `inputs.py` | Modelo de datos, historial, entrada y validación |
| `crew_planner/config.py`, `config/default.toml` | Configuración |
| `crew_planner/state.py`, `costs.py` | Estado normalizado y costes blandos |
| `crew_planner/eligibility.py` | Restricciones duras y verificador de planes |
| `crew_planner/teams.py`, `policy.py` | Equipos candidatos; límites semanales e investigación no reasignable |
| `crew_planner/context.py`, `optimizer.py` | Preparación del problema y modelo CP-SAT |
| `crew_planner/diagnosis.py`, `explain.py`, `planner.py` | Sin solución, salida explicable y orquestación |
| `crew_planner/report.py` | Informe visual en HTML, para Tierra y para la tripulación |
| `crew_planner/catalog.py`, `catalog_report.py`, `catalog/`, `config/requirement_mapping.toml` | Catálogo de tareas por entorno, su validación, su traducción a requisitos y la tabla comparativa |
| `crew_planner/simulation.py` | Tripulación sintética y escenarios |

Del módulo del grafo social solo se reutiliza `social_graph.intervals`, el álgebra de tramos horarios, que no contiene datos sociales.

## Limitaciones

- No hay datos fisiológicos reales en el proyecto. Todo está validado con datos sintéticos, y los umbrales y pesos no están calibrados.
- El descanso entre un día y el siguiente solo se garantiza mediante el bloque de sueño.
- Los miembros de un equipo trabajan a la vez y durante toda la tarea.
- La enumeración de equipos está pensada para tripulaciones de hasta unas 10 personas.
- La elección o el rechazo de los tres planes se registra en la API de Orbivia (`operations.plan_decisions`), no en este módulo.
