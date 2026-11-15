# Catálogo de tareas por entorno: metodología

Catálogo de 160 tareas de cuatro entornos de misión (ISS, superficie lunar, superficie marciana y servicio de satélites) con sus requisitos físicos y cognitivos. Lo usa el planificador de [crew_planner_design.md](crew_planner_design.md) sin cambiar su lógica: al elegir un entorno solo cambian las tareas que recibe.

- Datos: `sistema-de-recomendacion/planificador/catalog/`.
- Tabla comparativa e informe de calibración, generados: [task_requirements_table.md](task_requirements_table.md).
- Código: `crew_planner/catalog.py` (carga, validación, selección y traducción) y `crew_planner/catalog_report.py`.

## 1. Qué hay en el repositorio y cómo encaja

Antes de este trabajo no existía ningún catálogo de entornos. El planificador ya tenía:

- un modelo de tarea (`model.Task`) con requisitos sobre **parámetros medidos** del astronauta: sueño, fallos en el PVT, cansancio declarado, fuerza de agarre, SpO2, frecuencia cardíaca y horas trabajadas;
- restricciones duras (cualificaciones, requisitos críticos, disponibilidad, descanso) separadas de los costes blandos;
- un optimizador CP-SAT y un grafo social de solo lectura.

Los vectores de exigencia de este catálogo (15 puntuaciones de 0 a 1) **no se miden en nadie**. Para no cambiar el modelo de estado del astronauta, se eligió la adaptación más pequeña: una tabla configurable traduce las exigencias a requisitos sobre las mediciones que ya existen (sección 5).

Cambios en el núcleo del planificador, los mínimos:

| Cambio | Para qué |
|---|---|
| `Task.only_for` | Tareas que hace cada astronauta, como el ejercicio diario |
| `Task.interdependence` | Escalar el peso de la compatibilidad social según cuánto depende el equipo de sí mismo |
| Clave `meta` en la entrada | Información de contexto (entorno, tareas robóticas); el optimizador no la usa |

## 2. Estructura de una tarea

Un JSON por entorno en `catalog/tasks/`. Campos principales:

| Campo | Contenido |
|---|---|
| `task_id`, `name`, `description`, `environment`, `category` | Identificación. Los identificadores son los del enunciado y no cambian |
| `type`, `min_crew`, `max_crew` | Individual (1–1) o colectiva (desde 2, con tamaño variable si la actividad lo permite) |
| `importance` | 1–5, configurable |
| `duration_minutes` + `duration_metadata` | Duración y su tipo de evidencia |
| `frequency` | `daily`, `weekly` (con `weekday`), `periodic` (con `every_days`), `event_based`, `contingency` o `mission_specific` |
| `execution_mode`, `crew_role` | `human`, `robotic` o `remote_controlled`; papel de la tripulación: `performer`, `operator` o `none` |
| `per_astronaut` | La tarea la hace cada astronauta (ejercicio) |
| `safety_critical`, `requires_eva`, `resources` | Seguridad, EVA y recursos compartidos (esclusa, brazo, rover) |
| `technical_requirements` | Cualificaciones obligatorias (restricción dura), competencias recomendables, experiencia específica y formación |
| `constraints` | Restricciones duras documentadas, restricciones médicas y descanso mínimo (vacíos si no hay fuente) |
| `requirements` | Vector físico (7) y cognitivo (8), de 0 a 1 |
| `team_requirements` | Solo en colectivas: coordinación, comunicación, interdependencia y liderazgo |
| `requirements_metadata` | Perfil, tipo de evidencia, confianza, justificación, ajustes, fuentes y estado de validación |
| `source_type`, `nasa_reference` | `real`, `planned` o `conceptual`, y las referencias del registro |

Ficheros comunes:

- `references.json`: cada fuente con su título, organismo, año, identificador, URL, tipo de evidencia y qué respalda.
- `qualifications.json`: vocabulario de cualificaciones.
- `profiles.json`: rúbrica de perfiles.
- `environments.json`: tripulación de ejemplo, jornada, plan de la misión y eventos.

## 3. Fuentes y tipos de evidencia

**Qué respaldan las fuentes.** Las referencias respaldan que la actividad existe (ISS, Apolo, Hubble), que está prevista (Artemis) o que figura en una arquitectura de referencia (Marte). También respaldan algunas restricciones cualitativas:

- protocolos de prerrespiración antes de una EVA desde la ISS (OCHMO, DCS);
- control del polvo de regolito (OCHMO, informe de Gaier sobre Apolo);
- EVA siempre en pareja.

**Qué no respaldan.** Ninguna publica puntuaciones de exigencia por tarea. Por eso **todas las puntuaciones son `theoretical`** y un test lo comprueba. La única duración derivada de una fuente es la del ejercicio de la ISS: unas dos horas diarias, según la CSA.

**Fuentes que no se usan.** La SSP 50261-01 (reglas generales de planificación de la ISS) está registrada como `not_public`: no se ha podido consultar y no respalda ningún valor.

**Tipo de origen de cada tarea:**

| `source_type` | Criterio |
|---|---|
| `real` | Realizada en una misión: toda la ISS, actividades de Apolo (muestras, rover, perforación, ALSEP) y tareas del Hubble |
| `planned` | Prevista en Artemis (documentos del SDT de Artemis III, xEVA ConOps, EHP) |
| `conceptual` | Todo Marte, hábitat lunar de larga duración y operaciones de un vehículo de servicio con tripulación más allá del Hubble |

## 4. Asignación de puntuaciones

### 4.1 Rúbrica de perfiles

Cada tarea parte de uno de 23 perfiles de actividad (`profiles.json`). Ejemplos: monitorización en consola, procedimiento de laboratorio, mantenimiento preventivo, reparación crítica, logística, teleoperación robótica, EVA orbital, EVA de superficie, perforación, rover, ejercicio y simulacro de emergencia.

- El perfil fija los 15 valores y la coordinación de equipo, con su justificación y una confianza de 0,35 a 0,5.
- Así dos tareas parecidas tienen valores comparables aunque sean de entornos distintos. Por ejemplo, la recogida de muestras en la Luna y en Marte tienen el mismo vector físico (test `test_comparable_tasks_across_environments`).
- Las tareas conceptuales restan 0,05 de confianza.

**Criterios comunes de la escala:**

- 0,25 bajo, 0,5 moderado, 0,75 alto. No se usa 1,0.
- La EVA orbital es la referencia de exigencia física alta (0,85).
- La teleoperación robótica es la de concentración más alta (0,9), con esfuerzo físico mínimo.
- La monitorización tiene esfuerzo físico casi nulo y concentración moderada a alta.
- La reparación de sistemas críticos tiene concentración, decisión y resolución de problemas altas (0,75–0,8).
- La EVA de superficie tiene más movilidad y menos precisión fina que la orbital, porque se camina y se carga sobre regolito.

### 4.2 Ajustes

Una tarea solo se aparta más de 0,15 de su perfil con un **ajuste** que deja el valor del perfil, el nuevo valor y el motivo. El validador rechaza cualquier desviación sin ajuste. Ejemplos:

- Reparación de componentes en el satélite: precisión 0,9, por retirar tornillos pequeños con guantes presurizados (reparaciones de STIS y ACS en SM4).
- Biofirmas en Marte: atención al detalle 0,9, por el control de contaminación.
- Marte: +0,1 de decisión en planificación, contingencias, reparaciones y emergencias, porque el retardo de comunicaciones obliga a decidir sin ayuda en tiempo real.

### 4.3 Exigencia de la tarea frente a estado del astronauta

Los vectores describen la **tarea**, nunca a la persona.

- `fatigue_tolerance` alto significa que la tarea solo es segura con poca fatiga previa.
- `recovery_requirement` es la recuperación que la tarea exige después: desde 0,7 la tarea cuenta como exigente y se respeta un descanso tras ella.

### 4.4 Variables descriptivas

`stress_tolerance`, `communication_requirement` y `leadership_requirement` figuran en el catálogo y en la tabla, pero **no se comparan con el astronauta**: hacerlo exigiría inferir estados psicológicos.

### 4.5 Tareas robóticas y teleoperadas

- Una tarea robótica o controlada desde Tierra (`crew_role: none`) no lleva vectores humanos y no se asigna a la tripulación. En el entorno de satélites son el repostaje y la instalación de módulos (RRM y OSAM-1) y el ensamblaje de estructuras.
- Su supervisión humana es una tarea aparte (`SAT_IND_015`).
- Si la tripulación maneja el brazo (`crew_role: operator`), se modelan las exigencias del operador: concentración y precisión altas, esfuerzo físico bajo.

## 5. Correspondencia con el vector del astronauta

`config/requirement_mapping.toml` (teórico y configurable):

| Dimensión de la tarea | Parámetros del astronauta |
|---|---|
| Esfuerzo físico | Fuerza de agarre, cansancio declarado |
| Resistencia | Cansancio, horas trabajadas en 3 días, sueño |
| Movilidad | Cansancio |
| Coordinación | PVT, sueño |
| Precisión física | PVT |
| Tolerancia a la fatiga | Cansancio, horas trabajadas en 3 días |
| Concentración, decisión | PVT, sueño |
| Carga cognitiva, resolución de problemas | PVT, calidad del sueño |
| Memoria de trabajo, atención al detalle | PVT |
| Multitarea | PVT, cansancio |

**Reglas:**

1. Por debajo de 0,4 de exigencia, la dimensión no genera requisito.
2. Por parámetro se toma la **mayor** exigencia de las dimensiones que apuntan a él, no la suma: son evidencias correlacionadas. Concentración, coordinación y decisión miden en parte lo mismo.
3. El umbral se interpola entre niveles. Por ejemplo, el PVT admite como mucho +2,0 z con exigencia 0,4 y +0,5 z con exigencia 1,0.
4. El peso del requisito es la exigencia: una tarea con poca concentración apenas penaliza un mal PVT.
5. En una tarea crítica para la seguridad, una exigencia de 0,75 o más convierte el requisito en **duro**. Si no se cumple o el dato es desconocido, la persona no es elegible. Por ejemplo, la EVA de la ISS exige cansancio ≤ 2,9, PVT ≤ +0,9 z, sueño ≥ 6,6 h, calidad del sueño ≥ 70 % y agarre ≥ −0,9 z.
6. SpO2 y frecuencia cardíaca no se traducen automáticamente: sus umbrales son una decisión médica.

La relación no es lineal con todas las variables. Por ejemplo, la concentración no depende de la fuerza de agarre. Que la fatiga y la falta de sueño penalicen la atención y la precisión se apoya en el informe de evidencia de la HRP sobre sueño y fatiga.

## 6. Seguridad: restricciones duras, no penalizaciones

- Las cualificaciones obligatorias (`required_qualifications`) son restricciones duras del optimizador.
- **Vocabulario de cualificaciones.** Es genérico y está marcado `pending`. No se inventan nombres de certificaciones de NASA.
- **EVA.** Exige pareja (`min_crew` ≥ 2), la cualificación de EVA, ser crítica para la seguridad y un recurso exclusivo (esclusa).
- **Requisitos derivados críticos.** Funcionan como en el apartado anterior: dato desconocido o umbral incumplido significa no elegible.
- **Sin fuente, sin valor.** `medical_constraints` y `minimum_rest_requirement` quedan vacíos con la nota «pendiente de validación médica». El descanso tras tareas exigentes es el general del planificador.
- **Separación comprobada por el validador.** Un vector de exigencia solo puede contener puntuaciones: una cualificación dentro de él es un error.

## 7. Selección del día

La frecuencia **no es un calendario de NASA**: es una regla configurable.

- `daily`: todos los días.
- `weekly`: el día de la semana indicado.
- `periodic`: cada N días, con un desfase estable por tarea para que no coincidan todas.
- `mission_specific`: cuando lo programa el plan de la misión del entorno, un ciclo de días en `environments.json`. En satélites, por ejemplo, el plan alterna parejas de EVA, como en las misiones al Hubble.
- `event_based` y `contingency`: solo cuando se dispara el evento, con `--event TAREA` o desde el ciclo de eventos de ejemplo.

Una tarea programada es obligatoria si es crítica para la seguridad o tiene importancia 3 o más. Si no, es aplazable.

## 8. Validación

`validate_catalog` comprueba, y `tests/test_catalog.py` lo verifica tarea a tarea:

1. Identificadores únicos y los 160 del enunciado, sin pérdidas ni cambios.
2. Campos obligatorios presentes.
3. Coherencia entre tipo y tamaño del equipo; una EVA requiere al menos dos personas.
4. Vectores completos, numéricos y en [0, 1], sin NaN; las tareas robóticas no llevan vectores.
5. Calibración frente al perfil, con ajustes justificados.
6. Cualificaciones existentes, y suficientes personas cualificadas en la tripulación de cada entorno.
7. Frecuencias válidas; el plan y los eventos solo programan tareas de su tipo.
8. Metadatos de evidencia presentes; las tareas reales o planificadas tienen referencias; las referencias existen; nada se declara `official` sin fuente oficial.
9. Colectivas con requisitos de coordinación; satélites con modo de ejecución.
10. Puntuaciones separadas de las restricciones de seguridad.
11. Compatibilidad con el optimizador: cada tarea se traduce a `model.Task` sin errores.

**Simulación.** `python -m crew_planner.simulation --environment iss|moon|mars|satellite --days N` planifica días seguidos con una tripulación sintética. Los tests comprueban, en cada entorno, que los planes son válidos, que cada astronauta hace su ejercicio y que un astronauta con fatiga alta nunca entra en la EVA.

## 9. Limitaciones

- Las 160 × 15 puntuaciones, la tabla de correspondencia y las duraciones son estimaciones del modelo Orbivia. Hay que calibrarlas con expertos; la prioridad está en el informe de calibración de la tabla.
- Las tripulaciones, jornadas y planes de misión de `environments.json` son ejemplos.
- La correspondencia con el astronauta usa solo los parámetros que hoy se miden. Memoria de trabajo, toma de decisiones o multitarea comparten el PVT como única medida objetiva.
- Las certificaciones reales de cada programa no están modeladas: el vocabulario es genérico.
- Marte es por completo conceptual. Las referencias describen arquitecturas sin decisión de programa.
