# Catálogo de tareas: tabla comparativa de requisitos

Generado con `python -m crew_planner.catalog_report`; no editar a mano. Metodología en [task_catalog_methodology.md](task_catalog_methodology.md).

**Todas las puntuaciones son estimaciones teóricas del modelo Orbivia** (escala 0-1). NASA no publica puntuaciones de exigencia por tarea. Las columnas con asterisco son descriptivas: no se comparan con el estado del astronauta.

Leyenda. Físicas: Esf = physical_effort, Res = endurance, Mov = mobility, Coo = coordination, Pre = physical_precision, Fat = fatigue_tolerance, Rec = recovery_requirement. Cognitivas: Con = concentration, Car = cognitive_load, Mem = working_memory, Dec = decision_making, Det = attention_to_detail, Pro = problem_solving, Est* = stress_tolerance, Mul = multitasking.

## Resumen

| Entorno | Tareas | Individuales | Colectivas | Críticas | EVA | Sin tripulación | Real | Planificada | Conceptual |
|---|---|---|---|---|---|---|---|---|---|
| ISS | 48 | 24 | 24 | 14 | 1 | 0 | 48 | 0 | 0 |
| Luna | 41 | 19 | 22 | 24 | 15 | 0 | 7 | 20 | 14 |
| Marte | 40 | 20 | 20 | 22 | 9 | 0 | 0 | 0 | 40 |
| Satélites | 31 | 19 | 12 | 17 | 6 | 3 | 15 | 0 | 16 |

## ISS

| Tarea | Nombre | Tipo | Modo | Perfil | Esf | Res | Mov | Coo | Pre | Fat | Rec | Con | Car | Mem | Dec | Det | Pro | Est* | Mul | Conf. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ISS_IND_001 | Experimentos de biología | ind | human | lab_procedure | .20 | .25 | .20 | .55 | .65 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.45 |
| ISS_IND_002 | Experimentos de física | ind | human | lab_procedure | .20 | .25 | .20 | .55 | .65 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.45 |
| ISS_IND_003 | Experimentos de medicina espacial | ind | human | lab_procedure | .20 | .25 | .20 | .55 | .65 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.45 |
| ISS_IND_004 | Recogida de muestras biológicas | ind | human | lab_procedure | .20 | .25 | .20 | .55 | .75 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.45 |
| ISS_IND_005 | Procesamiento de muestras | ind | human | lab_procedure | .20 | .25 | .20 | .55 | .65 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.45 |
| ISS_IND_006 | Monitorización de experimentos | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.50 |
| ISS_IND_007 | Análisis de datos científicos | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.50 |
| ISS_IND_008 | Observación de la Tierra | ind | human | data_analysis | .05 | .10 | .05 | .15 | .40 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.50 |
| ISS_IND_009 | Documentación de resultados | ind | human | inventory_admin | .15 | .15 | .25 | .20 | .15 | .15 | .05 | .45 | .35 | .45 | .25 | .60 | .20 | .15 | .30 | 0.50 |
| ISS_IND_010 | Inspección de equipos | ind | human | inspection_routine | .25 | .30 | .40 | .35 | .30 | .30 | .10 | .55 | .45 | .40 | .40 | .70 | .40 | .25 | .30 | 0.45 |
| ISS_IND_011 ⚠ | Mantenimiento eléctrico | ind | human | maintenance_preventive | .40 | .40 | .45 | .60 | .60 | .40 | .25 | .60 | .55 | .50 | .45 | .70 | .55 | .35 | .35 | 0.45 |
| ISS_IND_012 | Diagnóstico de componentes | ind | human | anomaly_diagnosis | .10 | .15 | .10 | .25 | .25 | .20 | .05 | .80 | .80 | .70 | .65 | .80 | .85 | .55 | .45 | 0.45 |
| ISS_IND_013 ⚠ | Mantenimiento de sistemas de soporte vital | ind | human | maintenance_preventive | .40 | .40 | .45 | .60 | .60 | .40 | .25 | .60 | .55 | .50 | .45 | .70 | .55 | .35 | .35 | 0.45 |
| ISS_IND_014 ⚠ | Monitorización ambiental | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.50 |
| ISS_IND_015 | Inspección de sistemas de comunicaciones | ind | human | inspection_routine | .25 | .30 | .40 | .35 | .30 | .30 | .10 | .55 | .45 | .40 | .40 | .70 | .40 | .25 | .30 | 0.45 |
| ISS_IND_016 | Limpieza de módulos | ind | human | housekeeping | .35 | .30 | .45 | .30 | .15 | .30 | .15 | .25 | .15 | .15 | .15 | .35 | .10 | .10 | .20 | 0.50 |
| ISS_IND_017 | Gestión de residuos | ind | human | housekeeping | .35 | .30 | .45 | .30 | .15 | .30 | .15 | .25 | .15 | .15 | .15 | .35 | .10 | .10 | .20 | 0.50 |
| ISS_IND_018 | Control de inventario | ind | human | inventory_admin | .15 | .15 | .25 | .20 | .15 | .15 | .05 | .45 | .35 | .45 | .25 | .60 | .20 | .15 | .30 | 0.50 |
| ISS_IND_019 | Ejercicio físico | ind | human | exercise | .75 | .75 | .40 | .35 | .15 | .60 | .60 | .20 | .10 | .10 | .10 | .15 | .05 | .15 | .10 | 0.50 |
| ISS_IND_020 | Formación y entrenamiento | ind | human | training | .10 | .15 | .10 | .15 | .10 | .20 | .05 | .60 | .55 | .60 | .35 | .55 | .40 | .20 | .25 | 0.50 |
| ISS_IND_021 ⚠ | Preparación individual para EVA | ind | human | eva_preparation | .35 | .35 | .35 | .55 | .60 | .35 | .20 | .70 | .60 | .60 | .50 | .85 | .45 | .40 | .40 | 0.40 |
| ISS_IND_022 | Revisión de procedimientos | ind | human | training | .10 | .15 | .10 | .15 | .10 | .20 | .05 | .60 | .55 | .60 | .35 | .55 | .40 | .20 | .25 | 0.50 |
| ISS_IND_023 | Preparación de experimentos | ind | human | lab_procedure | .20 | .25 | .20 | .55 | .55 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.45 |
| ISS_IND_024 | Gestión individual de documentación | ind | human | inventory_admin | .15 | .15 | .25 | .20 | .15 | .15 | .05 | .45 | .35 | .45 | .25 | .60 | .20 | .15 | .30 | 0.50 |
| ISS_COL_001 | Preparación conjunta de experimentos | col | human | lab_procedure | .20 | .25 | .20 | .55 | .65 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.45 |
| ISS_COL_002 | Instalación de equipamiento científico | col | human | maintenance_preventive | .40 | .40 | .45 | .60 | .60 | .40 | .25 | .60 | .55 | .50 | .45 | .70 | .55 | .35 | .35 | 0.45 |
| ISS_COL_003 | Calibración de instrumentos | col | human | lab_procedure | .20 | .25 | .20 | .55 | .65 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.45 |
| ISS_COL_004 | Procesamiento conjunto de muestras | col | human | lab_procedure | .20 | .25 | .20 | .55 | .65 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.45 |
| ISS_COL_005 | Revisión de resultados experimentales | col | human | planning_coordination | .05 | .10 | .05 | .10 | .05 | .15 | .05 | .65 | .60 | .60 | .65 | .55 | .55 | .40 | .55 | 0.45 |
| ISS_COL_006 ⚠ | Reparación de componentes | col | human | repair_critical | .50 | .50 | .50 | .65 | .70 | .60 | .40 | .80 | .80 | .70 | .75 | .80 | .80 | .70 | .55 | 0.40 |
| ISS_COL_007 ⚠ | Mantenimiento de sistemas críticos | col | human | maintenance_preventive | .40 | .40 | .45 | .60 | .60 | .40 | .25 | .60 | .55 | .50 | .45 | .70 | .55 | .35 | .35 | 0.45 |
| ISS_COL_008 | Inspección conjunta de módulos | col | human | inspection_routine | .25 | .30 | .40 | .35 | .30 | .30 | .10 | .55 | .45 | .40 | .40 | .70 | .40 | .25 | .30 | 0.45 |
| ISS_COL_009 | Mantenimiento de brazos robóticos | col | human | maintenance_preventive | .40 | .40 | .45 | .60 | .60 | .40 | .25 | .60 | .55 | .50 | .45 | .70 | .55 | .35 | .35 | 0.45 |
| ISS_COL_010 ⚠ | Preparación de sistemas de soporte vital | col | human | maintenance_preventive | .40 | .40 | .45 | .60 | .60 | .40 | .25 | .60 | .55 | .50 | .45 | .70 | .55 | .35 | .35 | 0.45 |
| ISS_COL_011 ⚠ | Recepción de vehículos de carga | col | human | robotic_operation | .10 | .25 | .05 | .65 | .70 | .35 | .15 | .90 | .80 | .70 | .75 | .80 | .60 | .70 | .65 | 0.40 |
| ISS_COL_012 | Descarga de suministros | col | human | logistics_handling | .55 | .50 | .60 | .45 | .25 | .45 | .30 | .40 | .35 | .45 | .30 | .55 | .25 | .25 | .35 | 0.45 |
| ISS_COL_013 | Almacenamiento de materiales | col | human | logistics_handling | .55 | .50 | .60 | .45 | .25 | .45 | .30 | .40 | .35 | .45 | .30 | .55 | .25 | .25 | .35 | 0.45 |
| ISS_COL_014 | Preparación de vehículos de retorno | col | human | logistics_handling | .55 | .50 | .60 | .45 | .25 | .45 | .30 | .40 | .35 | .45 | .30 | .70 | .25 | .25 | .35 | 0.45 |
| ISS_COL_015 | Transferencia de suministros | col | human | logistics_handling | .55 | .50 | .60 | .45 | .25 | .45 | .30 | .40 | .35 | .45 | .30 | .55 | .25 | .25 | .35 | 0.45 |
| ISS_COL_016 | Gestión conjunta del inventario | col | human | inventory_admin | .15 | .15 | .25 | .20 | .15 | .15 | .05 | .45 | .35 | .45 | .25 | .60 | .20 | .15 | .30 | 0.50 |
| ISS_COL_017 ⚠ | Preparación de actividades EVA | col | human | eva_preparation | .35 | .35 | .35 | .55 | .60 | .35 | .20 | .70 | .60 | .60 | .50 | .85 | .45 | .40 | .40 | 0.40 |
| ISS_COL_018 ⚠ | Realización de actividades EVA | col | human | eva_orbital | .85 | .85 | .70 | .80 | .80 | .80 | .80 | .85 | .80 | .70 | .70 | .85 | .65 | .75 | .60 | 0.40 |
| ISS_COL_019 ⚠ | Simulacros de emergencia | col | human | emergency_drill | .40 | .35 | .60 | .50 | .35 | .40 | .20 | .75 | .70 | .70 | .75 | .60 | .60 | .70 | .65 | 0.40 |
| ISS_COL_020 ⚠ | Coordinación de evacuación | col | human | emergency_drill | .40 | .35 | .60 | .50 | .35 | .40 | .20 | .75 | .70 | .70 | .75 | .60 | .60 | .70 | .65 | 0.40 |
| ISS_COL_021 ⚠ | Revisión de sistemas de seguridad | col | human | inspection_routine | .25 | .30 | .40 | .35 | .30 | .30 | .10 | .55 | .45 | .40 | .40 | .70 | .40 | .25 | .30 | 0.45 |
| ISS_COL_022 | Reuniones de planificación | col | human | planning_coordination | .05 | .10 | .05 | .10 | .05 | .15 | .05 | .65 | .60 | .60 | .65 | .55 | .55 | .40 | .55 | 0.45 |
| ISS_COL_023 | Transferencia de conocimiento entre tripulaciones | col | human | planning_coordination | .05 | .10 | .05 | .10 | .05 | .15 | .05 | .65 | .60 | .60 | .65 | .55 | .55 | .40 | .55 | 0.45 |
| ISS_COL_024 ⚠ | Coordinación de operaciones robóticas | col | human | robotic_operation | .10 | .25 | .05 | .65 | .70 | .35 | .15 | .90 | .80 | .70 | .75 | .80 | .60 | .70 | .65 | 0.40 |

## Luna

| Tarea | Nombre | Tipo | Modo | Perfil | Esf | Res | Mov | Coo | Pre | Fat | Rec | Con | Car | Mem | Dec | Det | Pro | Est* | Mul | Conf. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MOON_IND_001 | Clasificación de muestras lunares | ind | human | sample_curation | .15 | .20 | .15 | .40 | .50 | .20 | .10 | .55 | .45 | .45 | .35 | .75 | .30 | .20 | .25 | 0.45 |
| MOON_IND_002 | Análisis geológico | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.50 |
| MOON_IND_003 | Procesamiento de datos sísmicos | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.50 |
| MOON_IND_004 | Análisis de datos de radiación | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.50 |
| MOON_IND_005 | Análisis de propiedades del regolito | ind | human | lab_procedure | .20 | .25 | .20 | .55 | .65 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.45 |
| MOON_IND_006 | Cartografía del terreno | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.50 |
| MOON_IND_007 | Monitorización de instrumentos científicos | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.50 |
| MOON_IND_008 | Análisis de datos de exploración | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.50 |
| MOON_IND_009 | Documentación de muestras | ind | human | sample_curation | .15 | .20 | .15 | .40 | .50 | .20 | .10 | .55 | .45 | .45 | .35 | .75 | .30 | .20 | .25 | 0.45 |
| MOON_IND_010 ⚠ | Inspección del hábitat | ind | human | inspection_routine | .25 | .30 | .40 | .35 | .30 | .30 | .10 | .55 | .45 | .40 | .40 | .70 | .40 | .25 | .30 | 0.40 |
| MOON_IND_011 ⚠ | Monitorización de sistemas energéticos | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.45 |
| MOON_IND_012 ⚠ | Supervisión de soporte vital | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.45 |
| MOON_IND_013 | Diagnóstico de equipos | ind | human | anomaly_diagnosis | .10 | .15 | .10 | .25 | .25 | .20 | .05 | .80 | .80 | .70 | .65 | .80 | .85 | .55 | .45 | 0.45 |
| MOON_IND_014 | Gestión de suministros | ind | human | inventory_admin | .15 | .15 | .25 | .20 | .15 | .15 | .05 | .45 | .35 | .45 | .25 | .60 | .20 | .15 | .30 | 0.45 |
| MOON_IND_015 | Monitorización de comunicaciones | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.45 |
| MOON_IND_016 ⚠ | Preparación individual para EVA | ind | human | eva_preparation | .35 | .35 | .35 | .55 | .60 | .35 | .20 | .70 | .60 | .60 | .50 | .85 | .45 | .40 | .40 | 0.40 |
| MOON_IND_017 | Ejercicio físico | ind | human | exercise | .75 | .75 | .40 | .35 | .15 | .60 | .60 | .20 | .10 | .10 | .10 | .15 | .05 | .15 | .10 | 0.45 |
| MOON_IND_018 | Formación y entrenamiento | ind | human | training | .10 | .15 | .10 | .15 | .10 | .20 | .05 | .60 | .55 | .60 | .35 | .55 | .40 | .20 | .25 | 0.45 |
| MOON_IND_019 | Revisión de protocolos de emergencia | ind | human | training | .10 | .15 | .10 | .15 | .10 | .20 | .05 | .60 | .55 | .60 | .35 | .55 | .40 | .20 | .25 | 0.45 |
| MOON_COL_001 ⚠ | Recogida de muestras lunares | col | human | eva_surface | .85 | .85 | .85 | .70 | .65 | .80 | .80 | .75 | .70 | .60 | .70 | .75 | .60 | .70 | .55 | 0.35 |
| MOON_COL_002 ⚠ | Exploración de cráteres | col | human | eva_surface | .85 | .85 | .85 | .70 | .65 | .80 | .80 | .75 | .70 | .60 | .70 | .75 | .60 | .70 | .55 | 0.35 |
| MOON_COL_003 ⚠ | Exploración de regiones permanentemente sombreadas | col | human | eva_surface | .85 | .85 | .85 | .70 | .65 | .85 | .80 | .75 | .70 | .60 | .70 | .75 | .60 | .85 | .55 | 0.35 |
| MOON_COL_004 ⚠ | Exploración de regiones volcánicas | col | human | eva_surface | .85 | .85 | .85 | .70 | .65 | .80 | .80 | .75 | .70 | .60 | .70 | .75 | .60 | .70 | .55 | 0.35 |
| MOON_COL_005 ⚠ | Exploración mediante rover | col | human | rover_traverse | .35 | .60 | .30 | .60 | .50 | .60 | .40 | .80 | .70 | .60 | .70 | .70 | .55 | .60 | .60 | 0.35 |
| MOON_COL_006 ⚠ | Perforación del regolito | col | human | drilling | .75 | .70 | .60 | .70 | .65 | .70 | .65 | .70 | .65 | .55 | .60 | .75 | .60 | .55 | .45 | 0.35 |
| MOON_COL_007 ⚠ | Instalación de instrumentos científicos | col | human | construction_assembly | .75 | .75 | .75 | .75 | .65 | .70 | .70 | .70 | .70 | .60 | .60 | .75 | .65 | .55 | .50 | 0.35 |
| MOON_COL_008 ⚠ | Despliegue de estaciones de monitorización | col | human | construction_assembly | .75 | .75 | .75 | .75 | .65 | .70 | .70 | .70 | .70 | .60 | .60 | .75 | .65 | .55 | .50 | 0.35 |
| MOON_COL_009 ⚠ | Instalación de instrumentos sísmicos | col | human | construction_assembly | .75 | .75 | .75 | .75 | .75 | .70 | .70 | .70 | .70 | .60 | .60 | .75 | .65 | .55 | .50 | 0.35 |
| MOON_COL_010 ⚠ | Estudios geológicos de campo | col | human | eva_surface | .85 | .85 | .85 | .70 | .65 | .80 | .80 | .75 | .70 | .60 | .70 | .75 | .60 | .70 | .55 | 0.35 |
| MOON_COL_011 ⚠ | Construcción de infraestructura | col | human | construction_assembly | .75 | .75 | .75 | .75 | .65 | .70 | .70 | .70 | .70 | .60 | .60 | .75 | .65 | .55 | .50 | 0.30 |
| MOON_COL_012 ⚠ | Instalación de sistemas energéticos | col | human | construction_assembly | .75 | .75 | .75 | .75 | .65 | .70 | .70 | .70 | .70 | .60 | .60 | .75 | .65 | .55 | .50 | 0.30 |
| MOON_COL_013 | Mantenimiento de rover | col | human | maintenance_preventive | .40 | .40 | .45 | .60 | .60 | .40 | .25 | .60 | .55 | .50 | .45 | .70 | .55 | .35 | .35 | 0.45 |
| MOON_COL_014 ⚠ | Reparación de equipamiento | col | human | repair_critical | .50 | .50 | .50 | .65 | .70 | .60 | .40 | .80 | .80 | .70 | .75 | .80 | .80 | .70 | .55 | 0.40 |
| MOON_COL_015 ⚠ | Preparación de instalaciones de superficie | col | human | construction_assembly | .75 | .75 | .75 | .75 | .65 | .70 | .70 | .70 | .70 | .60 | .60 | .75 | .65 | .55 | .50 | 0.30 |
| MOON_COL_016 | Gestión de recursos y suministros | col | human | planning_coordination | .05 | .10 | .05 | .10 | .05 | .15 | .05 | .65 | .60 | .60 | .65 | .55 | .55 | .40 | .55 | 0.40 |
| MOON_COL_017 ⚠ | Preparación de EVA | col | human | eva_preparation | .35 | .35 | .35 | .55 | .60 | .35 | .20 | .70 | .60 | .60 | .50 | .85 | .45 | .40 | .40 | 0.40 |
| MOON_COL_018 ⚠ | Realización de EVA | col | human | eva_surface | .85 | .85 | .85 | .70 | .65 | .80 | .80 | .75 | .70 | .60 | .70 | .75 | .60 | .70 | .55 | 0.35 |
| MOON_COL_019 ⚠ | Simulacros de emergencia | col | human | emergency_drill | .40 | .35 | .60 | .50 | .35 | .40 | .20 | .75 | .70 | .70 | .75 | .60 | .60 | .70 | .65 | 0.35 |
| MOON_COL_020 ⚠ | Coordinación de operaciones extravehiculares | col | human | robotic_supervision | .05 | .15 | .05 | .20 | .15 | .25 | .05 | .75 | .60 | .55 | .60 | .70 | .50 | .50 | .55 | 0.40 |
| MOON_COL_021 ⚠ | Transporte de equipamiento | col | human | logistics_handling | .75 | .75 | .60 | .45 | .25 | .75 | .70 | .40 | .35 | .45 | .30 | .55 | .25 | .25 | .35 | 0.45 |
| MOON_COL_022 ⚠ | Inspección conjunta de infraestructura | col | human | inspection_routine | .60 | .60 | .70 | .35 | .30 | .60 | .55 | .55 | .45 | .40 | .40 | .70 | .40 | .25 | .30 | 0.40 |

## Marte

| Tarea | Nombre | Tipo | Modo | Perfil | Esf | Res | Mov | Coo | Pre | Fat | Rec | Con | Car | Mem | Dec | Det | Pro | Est* | Mul | Conf. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MARS_IND_001 | Análisis de muestras geológicas | ind | human | lab_procedure | .20 | .25 | .20 | .55 | .65 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.40 |
| MARS_IND_002 | Clasificación y documentación de muestras | ind | human | sample_curation | .15 | .20 | .15 | .40 | .50 | .20 | .10 | .55 | .45 | .45 | .35 | .75 | .30 | .20 | .25 | 0.40 |
| MARS_IND_003 | Análisis de datos atmosféricos | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.45 |
| MARS_IND_004 | Análisis de datos geofísicos | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.45 |
| MARS_IND_005 | Monitorización de instrumentos científicos | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.45 |
| MARS_IND_006 | Análisis de posibles biofirmas | ind | human | lab_procedure | .20 | .25 | .20 | .55 | .65 | .25 | .10 | .65 | .55 | .50 | .40 | .90 | .40 | .30 | .35 | 0.40 |
| MARS_IND_007 | Cartografía y análisis del terreno | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.45 |
| MARS_IND_008 | Procesamiento de datos de exploración | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.45 |
| MARS_IND_009 ⚠ | Inspección de sistemas del hábitat | ind | human | inspection_routine | .25 | .30 | .40 | .35 | .30 | .30 | .10 | .55 | .45 | .40 | .40 | .70 | .40 | .25 | .30 | 0.40 |
| MARS_IND_010 | Mantenimiento de equipos científicos | ind | human | maintenance_preventive | .40 | .40 | .45 | .60 | .60 | .40 | .25 | .60 | .55 | .50 | .45 | .70 | .55 | .35 | .35 | 0.40 |
| MARS_IND_011 ⚠ | Diagnóstico de sistemas eléctricos | ind | human | anomaly_diagnosis | .10 | .15 | .10 | .25 | .25 | .20 | .05 | .80 | .80 | .70 | .75 | .80 | .85 | .55 | .45 | 0.40 |
| MARS_IND_012 ⚠ | Monitorización de soporte vital | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.45 |
| MARS_IND_013 ⚠ | Gestión de energía | ind | human | planning_coordination | .05 | .10 | .05 | .10 | .05 | .15 | .05 | .65 | .60 | .60 | .75 | .55 | .55 | .40 | .55 | 0.40 |
| MARS_IND_014 | Control de inventario y suministros | ind | human | inventory_admin | .15 | .15 | .25 | .20 | .15 | .15 | .05 | .45 | .35 | .45 | .25 | .60 | .20 | .15 | .30 | 0.45 |
| MARS_IND_015 | Monitorización de comunicaciones | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.45 |
| MARS_IND_016 | Gestión de datos de la misión | ind | human | inventory_admin | .15 | .15 | .25 | .20 | .15 | .15 | .05 | .45 | .35 | .45 | .25 | .60 | .20 | .15 | .30 | 0.45 |
| MARS_IND_017 | Ejercicio físico | ind | human | exercise | .75 | .75 | .40 | .35 | .15 | .60 | .60 | .20 | .10 | .10 | .10 | .15 | .05 | .15 | .10 | 0.45 |
| MARS_IND_018 | Formación y entrenamiento | ind | human | training | .10 | .15 | .10 | .15 | .10 | .20 | .05 | .60 | .55 | .60 | .35 | .55 | .40 | .20 | .25 | 0.45 |
| MARS_IND_019 | Revisión de procedimientos de emergencia | ind | human | training | .10 | .15 | .10 | .15 | .10 | .20 | .05 | .60 | .55 | .60 | .35 | .55 | .40 | .20 | .25 | 0.45 |
| MARS_IND_020 ⚠ | Preparación individual para EVA | ind | human | eva_preparation | .35 | .35 | .35 | .55 | .60 | .35 | .20 | .70 | .60 | .60 | .50 | .85 | .45 | .40 | .40 | 0.35 |
| MARS_COL_001 ⚠ | Recogida de muestras geológicas | col | human | eva_surface | .85 | .85 | .85 | .70 | .65 | .80 | .80 | .75 | .70 | .60 | .70 | .75 | .60 | .70 | .55 | 0.30 |
| MARS_COL_002 ⚠ | Exploración de terreno mediante rover | col | human | rover_traverse | .35 | .60 | .30 | .60 | .50 | .60 | .40 | .80 | .70 | .60 | .70 | .70 | .55 | .60 | .60 | 0.30 |
| MARS_COL_003 ⚠ | Perforación y extracción de muestras del subsuelo | col | human | drilling | .75 | .70 | .60 | .70 | .65 | .70 | .65 | .70 | .65 | .55 | .60 | .75 | .60 | .55 | .45 | 0.30 |
| MARS_COL_004 ⚠ | Instalación de instrumentos científicos | col | human | construction_assembly | .75 | .75 | .75 | .75 | .65 | .70 | .70 | .70 | .70 | .60 | .60 | .75 | .65 | .55 | .50 | 0.30 |
| MARS_COL_005 ⚠ | Despliegue de estaciones de monitorización | col | human | construction_assembly | .75 | .75 | .75 | .75 | .65 | .70 | .70 | .70 | .70 | .60 | .60 | .75 | .65 | .55 | .50 | 0.30 |
| MARS_COL_006 ⚠ | Exploración geológica de campo | col | human | eva_surface | .85 | .85 | .85 | .70 | .65 | .80 | .80 | .75 | .70 | .60 | .70 | .75 | .60 | .70 | .55 | 0.30 |
| MARS_COL_007 ⚠ | Estudios de astrobiología | col | human | eva_surface | .85 | .85 | .85 | .70 | .65 | .80 | .80 | .75 | .70 | .60 | .70 | .85 | .60 | .70 | .55 | 0.30 |
| MARS_COL_008 ⚠ | Inspección de regiones de interés científico | col | human | eva_surface | .85 | .85 | .85 | .70 | .65 | .80 | .80 | .75 | .70 | .60 | .70 | .75 | .60 | .70 | .55 | 0.30 |
| MARS_COL_009 ⚠ | Construcción y despliegue de infraestructura | col | human | construction_assembly | .75 | .75 | .75 | .75 | .65 | .70 | .70 | .70 | .70 | .60 | .60 | .75 | .65 | .55 | .50 | 0.30 |
| MARS_COL_010 ⚠ | Reparación de sistemas críticos del hábitat | col | human | repair_critical | .50 | .50 | .50 | .65 | .70 | .60 | .40 | .80 | .80 | .70 | .85 | .80 | .80 | .70 | .55 | 0.35 |
| MARS_COL_011 | Mantenimiento de vehículos de superficie | col | human | maintenance_preventive | .40 | .40 | .45 | .60 | .60 | .40 | .25 | .60 | .55 | .50 | .45 | .70 | .55 | .35 | .35 | 0.40 |
| MARS_COL_012 ⚠ | Preparación de vehículos de ascenso | col | human | maintenance_preventive | .40 | .40 | .45 | .60 | .60 | .40 | .25 | .80 | .55 | .50 | .65 | .85 | .55 | .35 | .35 | 0.40 |
| MARS_COL_013 ⚠ | Instalación de sistemas energéticos | col | human | construction_assembly | .75 | .75 | .75 | .75 | .65 | .70 | .70 | .70 | .70 | .60 | .60 | .75 | .65 | .55 | .50 | 0.30 |
| MARS_COL_014 ⚠ | Reparación de equipamiento extravehicular | col | human | repair_critical | .50 | .50 | .50 | .65 | .70 | .60 | .40 | .80 | .80 | .70 | .85 | .80 | .80 | .70 | .55 | 0.35 |
| MARS_COL_015 ⚠ | Preparación y coordinación de EVA | col | human | eva_preparation | .35 | .35 | .35 | .55 | .60 | .35 | .20 | .70 | .60 | .60 | .50 | .85 | .45 | .40 | .40 | 0.35 |
| MARS_COL_016 ⚠ | Simulacros de emergencia | col | human | emergency_drill | .40 | .35 | .60 | .50 | .35 | .40 | .20 | .75 | .70 | .70 | .85 | .60 | .60 | .70 | .65 | 0.35 |
| MARS_COL_017 ⚠ | Gestión de contingencias | col | human | repair_critical | .50 | .50 | .50 | .65 | .70 | .60 | .40 | .80 | .80 | .70 | .85 | .80 | .80 | .70 | .55 | 0.35 |
| MARS_COL_018 | Transferencia de suministros | col | human | logistics_handling | .55 | .50 | .60 | .45 | .25 | .45 | .30 | .40 | .35 | .45 | .30 | .55 | .25 | .25 | .35 | 0.40 |
| MARS_COL_019 | Planificación de exploraciones | col | human | planning_coordination | .05 | .10 | .05 | .10 | .05 | .15 | .05 | .65 | .60 | .60 | .75 | .55 | .55 | .40 | .55 | 0.40 |
| MARS_COL_020 ⚠ | Revisión conjunta de operaciones críticas | col | human | planning_coordination | .05 | .10 | .05 | .10 | .05 | .15 | .05 | .65 | .60 | .60 | .75 | .55 | .55 | .40 | .55 | 0.40 |

## Satélites

| Tarea | Nombre | Tipo | Modo | Perfil | Esf | Res | Mov | Coo | Pre | Fat | Rec | Con | Car | Mem | Dec | Det | Pro | Est* | Mul | Conf. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SAT_IND_001 ⚠ | Monitorización de telemetría | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.45 |
| SAT_IND_002 ⚠ | Supervisión de orientación | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.45 |
| SAT_IND_003 ⚠ | Monitorización de órbita | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.45 |
| SAT_IND_004 | Análisis de anomalías | ind | human | anomaly_diagnosis | .10 | .15 | .10 | .25 | .25 | .20 | .05 | .80 | .80 | .70 | .65 | .80 | .85 | .55 | .45 | 0.40 |
| SAT_IND_005 | Diagnóstico de sistemas eléctricos | ind | human | anomaly_diagnosis | .10 | .15 | .10 | .25 | .25 | .20 | .05 | .80 | .80 | .70 | .65 | .80 | .85 | .55 | .45 | 0.40 |
| SAT_IND_006 | Análisis de consumo energético | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.45 |
| SAT_IND_007 | Monitorización térmica | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.45 |
| SAT_IND_008 | Análisis de comunicaciones | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.45 |
| SAT_IND_009 | Supervisión de instrumentos científicos | ind | human | desk_monitoring | .05 | .10 | .05 | .15 | .10 | .15 | .05 | .65 | .50 | .45 | .45 | .60 | .35 | .35 | .50 | 0.50 |
| SAT_IND_010 | Diagnóstico de componentes electrónicos | ind | human | anomaly_diagnosis | .10 | .15 | .10 | .25 | .25 | .20 | .05 | .80 | .80 | .70 | .65 | .80 | .85 | .55 | .45 | 0.40 |
| SAT_IND_011 | Análisis de degradación de baterías | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.45 |
| SAT_IND_012 | Revisión de sistemas de propulsión | ind | human | anomaly_diagnosis | .10 | .15 | .10 | .25 | .25 | .20 | .05 | .80 | .80 | .70 | .65 | .80 | .85 | .55 | .45 | 0.40 |
| SAT_IND_013 | Calibración de instrumentos | ind | human | lab_procedure | .20 | .25 | .20 | .25 | .30 | .25 | .10 | .65 | .55 | .50 | .40 | .75 | .40 | .30 | .35 | 0.40 |
| SAT_IND_014 | Análisis de datos de inspección | ind | human | data_analysis | .05 | .10 | .05 | .15 | .15 | .15 | .05 | .70 | .65 | .55 | .45 | .65 | .60 | .20 | .30 | 0.45 |
| SAT_IND_015 ⚠ | Supervisión de operaciones robóticas | ind | human | robotic_supervision | .05 | .15 | .05 | .20 | .15 | .25 | .05 | .75 | .60 | .55 | .60 | .70 | .50 | .50 | .55 | 0.35 |
| SAT_IND_016 | Planificación de mantenimiento | ind | human | planning_coordination | .05 | .10 | .05 | .10 | .05 | .15 | .05 | .65 | .60 | .60 | .65 | .55 | .55 | .40 | .55 | 0.45 |
| SAT_COL_001 ⚠ | Captura y acoplamiento de satélites | col | operador | robotic_operation | .10 | .25 | .05 | .65 | .70 | .35 | .15 | .90 | .80 | .70 | .75 | .80 | .60 | .70 | .65 | 0.40 |
| SAT_COL_002 ⚠ | Repostaje de combustible | ind | robotic | robotic_supervision | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.40 |
| SAT_COL_003 ⚠ | Sustitución de baterías | col | human | eva_orbital | .85 | .85 | .70 | .80 | .80 | .80 | .80 | .85 | .80 | .70 | .70 | .85 | .65 | .75 | .60 | 0.40 |
| SAT_COL_004 ⚠ | Reparación de componentes | col | human | eva_orbital | .85 | .85 | .70 | .80 | .90 | .80 | .80 | .85 | .80 | .70 | .70 | .85 | .80 | .75 | .60 | 0.40 |
| SAT_COL_005 ⚠ | Sustitución de instrumentos científicos | col | human | eva_orbital | .85 | .85 | .70 | .80 | .80 | .80 | .80 | .85 | .80 | .70 | .70 | .85 | .65 | .75 | .60 | 0.40 |
| SAT_COL_006 | Instalación de módulos | ind | robotic | robotic_supervision | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.35 |
| SAT_COL_007 ⚠ | Inspección exterior de satélites | col | human | eva_orbital | .70 | .85 | .70 | .80 | .55 | .80 | .80 | .85 | .80 | .70 | .70 | .85 | .65 | .75 | .60 | 0.40 |
| SAT_COL_008 ⚠ | Reparación de aislamiento térmico | col | human | eva_orbital | .85 | .85 | .70 | .80 | .80 | .80 | .80 | .85 | .80 | .70 | .70 | .85 | .65 | .75 | .60 | 0.40 |
| SAT_COL_009 | Ensamblaje de estructuras orbitales | ind | robotic | robotic_supervision | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.35 |
| SAT_COL_010 ⚠ | Sustitución de componentes mecánicos | col | human | eva_orbital | .85 | .85 | .70 | .80 | .80 | .80 | .80 | .85 | .80 | .70 | .70 | .85 | .65 | .75 | .60 | 0.40 |
| SAT_COL_011 ⚠ | Recuperación de sistemas averiados | col | human | repair_critical | .50 | .50 | .50 | .65 | .70 | .60 | .40 | .80 | .80 | .70 | .75 | .80 | .80 | .70 | .55 | 0.40 |
| SAT_COL_012 ⚠ | Operaciones de brazos robóticos | col | operador | robotic_operation | .10 | .25 | .05 | .65 | .70 | .35 | .15 | .90 | .80 | .70 | .75 | .80 | .60 | .70 | .65 | 0.40 |
| SAT_COL_013 ⚠ | Transferencia de componentes entre vehículos | col | operador | robotic_operation | .10 | .25 | .05 | .65 | .70 | .35 | .15 | .90 | .80 | .70 | .75 | .80 | .60 | .70 | .65 | 0.40 |
| SAT_COL_014 ⚠ | Preparación de operaciones extravehiculares | col | human | eva_preparation | .35 | .35 | .35 | .55 | .60 | .35 | .20 | .70 | .60 | .60 | .50 | .85 | .45 | .40 | .40 | 0.40 |
| SAT_COL_015 ⚠ | Coordinación de operaciones de servicio orbital | col | human | planning_coordination | .05 | .10 | .05 | .10 | .05 | .15 | .05 | .80 | .60 | .60 | .65 | .55 | .55 | .40 | .75 | 0.45 |

⚠ = crítica para la seguridad.

## Tareas colectivas: coordinación del equipo

Ordenadas por interdependencia, que escala el peso de la compatibilidad social en el optimizador.

| Tarea | Nombre | Equipo | Coord | Com* | Interd | Lid* |
|---|---|---|---|---|---|---|
| ISS_COL_018 | Realización de actividades EVA | 2–2 | .90 | .90 | .90 | .60 |
| SAT_COL_003 | Sustitución de baterías | 2–2 | .90 | .90 | .90 | .60 |
| SAT_COL_004 | Reparación de componentes | 2–2 | .90 | .90 | .90 | .60 |
| SAT_COL_005 | Sustitución de instrumentos científicos | 2–2 | .90 | .90 | .90 | .60 |
| SAT_COL_007 | Inspección exterior de satélites | 2–2 | .90 | .90 | .90 | .60 |
| SAT_COL_008 | Reparación de aislamiento térmico | 2–2 | .90 | .90 | .90 | .60 |
| SAT_COL_010 | Sustitución de componentes mecánicos | 2–2 | .90 | .90 | .90 | .60 |
| ISS_COL_011 | Recepción de vehículos de carga | 2–3 | .80 | .85 | .85 | .50 |
| ISS_COL_019 | Simulacros de emergencia | 3–6 | .90 | .90 | .85 | .75 |
| ISS_COL_020 | Coordinación de evacuación | 2–6 | .90 | .90 | .85 | .75 |
| ISS_COL_024 | Coordinación de operaciones robóticas | 2–2 | .80 | .85 | .85 | .50 |
| MARS_COL_004 | Instalación de instrumentos científicos | 2–2 | .85 | .80 | .85 | .60 |
| MARS_COL_005 | Despliegue de estaciones de monitorización | 2–2 | .85 | .80 | .85 | .60 |
| MARS_COL_009 | Construcción y despliegue de infraestructura | 2–3 | .85 | .80 | .85 | .60 |
| MARS_COL_013 | Instalación de sistemas energéticos | 2–3 | .85 | .80 | .85 | .60 |
| MARS_COL_016 | Simulacros de emergencia | 2–6 | .90 | .90 | .85 | .75 |
| MOON_COL_007 | Instalación de instrumentos científicos | 2–2 | .85 | .80 | .85 | .60 |
| MOON_COL_008 | Despliegue de estaciones de monitorización | 2–2 | .85 | .80 | .85 | .60 |
| MOON_COL_009 | Instalación de instrumentos sísmicos | 2–2 | .85 | .80 | .85 | .60 |
| MOON_COL_011 | Construcción de infraestructura | 2–3 | .85 | .80 | .85 | .60 |
| MOON_COL_012 | Instalación de sistemas energéticos | 2–3 | .85 | .80 | .85 | .60 |
| MOON_COL_015 | Preparación de instalaciones de superficie | 2–3 | .85 | .80 | .85 | .60 |
| MOON_COL_019 | Simulacros de emergencia | 2–4 | .90 | .90 | .85 | .75 |
| SAT_COL_001 | Captura y acoplamiento de satélites | 2–3 | .80 | .85 | .85 | .50 |
| SAT_COL_012 | Operaciones de brazos robóticos | 2–2 | .80 | .85 | .85 | .50 |
| SAT_COL_013 | Transferencia de componentes entre vehículos | 2–2 | .80 | .85 | .85 | .50 |
| ISS_COL_006 | Reparación de componentes | 2–3 | .80 | .80 | .80 | .65 |
| MARS_COL_001 | Recogida de muestras geológicas | 2–2 | .85 | .85 | .80 | .55 |
| MARS_COL_003 | Perforación y extracción de muestras del subsuelo | 2–3 | .85 | .80 | .80 | .60 |
| MARS_COL_006 | Exploración geológica de campo | 2–2 | .85 | .85 | .80 | .55 |
| MARS_COL_007 | Estudios de astrobiología | 2–2 | .85 | .85 | .80 | .55 |
| MARS_COL_008 | Inspección de regiones de interés científico | 2–2 | .85 | .85 | .80 | .55 |
| MARS_COL_010 | Reparación de sistemas críticos del hábitat | 2–3 | .80 | .80 | .80 | .65 |
| MARS_COL_014 | Reparación de equipamiento extravehicular | 2–2 | .80 | .80 | .80 | .65 |
| MARS_COL_017 | Gestión de contingencias | 2–6 | .80 | .80 | .80 | .65 |
| MOON_COL_001 | Recogida de muestras lunares | 2–2 | .85 | .85 | .80 | .55 |
| MOON_COL_002 | Exploración de cráteres | 2–2 | .85 | .85 | .80 | .55 |
| MOON_COL_003 | Exploración de regiones permanentemente sombreadas | 2–2 | .85 | .85 | .80 | .55 |
| MOON_COL_004 | Exploración de regiones volcánicas | 2–2 | .85 | .85 | .80 | .55 |
| MOON_COL_006 | Perforación del regolito | 2–2 | .85 | .80 | .80 | .60 |
| MOON_COL_010 | Estudios geológicos de campo | 2–2 | .85 | .85 | .80 | .55 |
| MOON_COL_014 | Reparación de equipamiento | 2–2 | .80 | .80 | .80 | .65 |
| MOON_COL_018 | Realización de EVA | 2–2 | .85 | .85 | .80 | .55 |
| SAT_COL_011 | Recuperación de sistemas averiados | 2–3 | .80 | .80 | .80 | .65 |
| ISS_COL_017 | Preparación de actividades EVA | 2–3 | .75 | .80 | .75 | .50 |
| MARS_COL_002 | Exploración de terreno mediante rover | 2–2 | .75 | .80 | .75 | .55 |
| MARS_COL_015 | Preparación y coordinación de EVA | 2–3 | .75 | .80 | .75 | .50 |
| MOON_COL_005 | Exploración mediante rover | 2–2 | .75 | .80 | .75 | .55 |
| MOON_COL_017 | Preparación de EVA | 2–3 | .75 | .80 | .75 | .50 |
| SAT_COL_014 | Preparación de operaciones extravehiculares | 2–3 | .75 | .80 | .75 | .50 |
| ISS_COL_002 | Instalación de equipamiento científico | 2–3 | .60 | .60 | .55 | .40 |
| ISS_COL_007 | Mantenimiento de sistemas críticos | 2–3 | .60 | .60 | .55 | .40 |
| ISS_COL_009 | Mantenimiento de brazos robóticos | 2–2 | .60 | .60 | .55 | .40 |
| ISS_COL_010 | Preparación de sistemas de soporte vital | 2–2 | .60 | .60 | .55 | .40 |
| MARS_COL_011 | Mantenimiento de vehículos de superficie | 2–2 | .60 | .60 | .55 | .40 |
| MARS_COL_012 | Preparación de vehículos de ascenso | 2–3 | .60 | .60 | .55 | .40 |
| MOON_COL_013 | Mantenimiento de rover | 2–2 | .60 | .60 | .55 | .40 |
| ISS_COL_001 | Preparación conjunta de experimentos | 2–2 | .55 | .60 | .50 | .35 |
| ISS_COL_003 | Calibración de instrumentos | 2–2 | .55 | .60 | .50 | .35 |
| ISS_COL_004 | Procesamiento conjunto de muestras | 2–2 | .55 | .60 | .50 | .35 |
| ISS_COL_005 | Revisión de resultados experimentales | 2–4 | .60 | .80 | .50 | .60 |
| ISS_COL_022 | Reuniones de planificación | 2–6 | .60 | .80 | .50 | .60 |
| ISS_COL_023 | Transferencia de conocimiento entre tripulaciones | 2–6 | .60 | .80 | .50 | .60 |
| MARS_COL_019 | Planificación de exploraciones | 2–6 | .60 | .80 | .50 | .60 |
| MARS_COL_020 | Revisión conjunta de operaciones críticas | 2–6 | .60 | .80 | .50 | .60 |
| MOON_COL_016 | Gestión de recursos y suministros | 2–4 | .60 | .80 | .50 | .60 |
| MOON_COL_020 | Coordinación de operaciones extravehiculares | 1–2 | .55 | .70 | .50 | .40 |
| SAT_COL_015 | Coordinación de operaciones de servicio orbital | 1–2 | .60 | .80 | .50 | .60 |
| ISS_COL_012 | Descarga de suministros | 2–4 | .50 | .50 | .40 | .30 |
| ISS_COL_013 | Almacenamiento de materiales | 2–3 | .50 | .50 | .40 | .30 |
| ISS_COL_014 | Preparación de vehículos de retorno | 2–3 | .50 | .50 | .40 | .30 |
| ISS_COL_015 | Transferencia de suministros | 2–3 | .50 | .50 | .40 | .30 |
| MARS_COL_018 | Transferencia de suministros | 2–3 | .50 | .50 | .40 | .30 |
| MOON_COL_021 | Transporte de equipamiento | 2–2 | .50 | .50 | .40 | .30 |
| ISS_COL_008 | Inspección conjunta de módulos | 2–3 | .45 | .50 | .35 | .30 |
| ISS_COL_021 | Revisión de sistemas de seguridad | 2–2 | .45 | .50 | .35 | .30 |
| MOON_COL_022 | Inspección conjunta de infraestructura | 2–2 | .45 | .50 | .35 | .30 |
| ISS_COL_016 | Gestión conjunta del inventario | 2–2 | .35 | .45 | .30 | .25 |

## Cualificaciones obligatorias

Restricciones duras: sin ellas la tarea no es asignable. Vocabulario genérico de Orbivia, pendiente de validar frente a las certificaciones reales de cada programa.

| Cualificación | Tareas |
|---|---|
| Sistemas del vehículo de ascenso (`ascent_vehicle_systems`) | 1: MARS_COL_012 |
| Sistemas de comunicaciones (`communications_systems`) | 4: ISS_IND_015, MOON_IND_015, MARS_IND_015, SAT_IND_008 |
| Sistemas eléctricos y de energía (`electrical_systems`) | 9: ISS_IND_011, MOON_IND_011, MOON_COL_012, MARS_IND_011, MARS_IND_013, MARS_COL_013, SAT_IND_005, SAT_IND_010, SAT_IND_011 |
| Certificación de EVA (`eva_certified`) | 39: ISS_IND_021, ISS_COL_017, ISS_COL_018, MOON_IND_016, MOON_COL_001, MOON_COL_002, MOON_COL_003, MOON_COL_004, MOON_COL_006, MOON_COL_007, MOON_COL_008, MOON_COL_009, MOON_COL_010, MOON_COL_011, MOON_COL_012, MOON_COL_015, MOON_COL_017, MOON_COL_018, MOON_COL_021, MOON_COL_022, MARS_IND_020, MARS_COL_001, MARS_COL_003, MARS_COL_004, MARS_COL_005, MARS_COL_006, MARS_COL_007, MARS_COL_008, MARS_COL_009, MARS_COL_013, MARS_COL_014, MARS_COL_015, SAT_COL_003, SAT_COL_004, SAT_COL_005, SAT_COL_007, SAT_COL_008, SAT_COL_010, SAT_COL_014 |
| Geología de campo (`geology_fieldwork`) | 3: MOON_IND_001, MOON_IND_002, MARS_IND_001 |
| Sistemas de soporte vital (`life_support_systems`) | 5: ISS_IND_013, ISS_COL_007, ISS_COL_010, MOON_IND_012, MARS_IND_012 |
| Oficial médico de tripulación (`medical_officer`) | 1: ISS_IND_004 |
| Operaciones de misión (`mission_operations`) | 4: MOON_COL_020, MARS_COL_017, SAT_IND_003, SAT_COL_015 |
| Operaciones de carga científica (`payload_operations`) | 12: ISS_IND_001, ISS_IND_002, ISS_IND_003, ISS_IND_005, ISS_IND_023, ISS_COL_001, ISS_COL_002, ISS_COL_003, ISS_COL_004, MARS_IND_006, MARS_IND_010, SAT_IND_013 |
| Sistemas de propulsión (`propulsion_systems`) | 1: SAT_IND_012 |
| Operador de brazo robótico (`robotic_arm_operator`) | 7: ISS_COL_009, ISS_COL_011, ISS_COL_024, SAT_IND_015, SAT_COL_001, SAT_COL_012, SAT_COL_013 |
| Operador de rover (`rover_operator`) | 4: MOON_COL_005, MOON_COL_013, MARS_COL_002, MARS_COL_011 |
| Servicio de satélites (`satellite_servicing`) | 6: SAT_COL_003, SAT_COL_004, SAT_COL_005, SAT_COL_008, SAT_COL_010, SAT_COL_011 |

## Requisitos sobre el astronauta en las tareas críticas

Traducción de los vectores con `config/requirement_mapping.toml`. **Duro** = restricción de seguridad: si no se cumple, o el dato es desconocido, la persona no es elegible.

| Tarea | Requisitos |
|---|---|
| ISS_IND_011 | fatigue_self ≤ 3.875; grip_strength ≥ -2; pvt_lapses ≤ 1.25; sleep_duration_h ≥ 6; sleep_quality ≥ 63.75; work_hours_3d ≤ 33 |
| ISS_IND_013 | fatigue_self ≤ 3.875; grip_strength ≥ -2; pvt_lapses ≤ 1.25; sleep_duration_h ≥ 6; sleep_quality ≥ 63.75; work_hours_3d ≤ 33 |
| ISS_IND_014 | fatigue_self ≤ 3.75; pvt_lapses ≤ 1.375; sleep_duration_h ≥ 6.125; sleep_quality ≥ 62.5 |
| ISS_IND_021 | fatigue_self ≤ 4; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.25; sleep_quality ≥ 65 |
| ISS_COL_006 | fatigue_self ≤ 3.5; grip_strength ≥ -1.75; pvt_lapses ≤ 1 **duro**; sleep_duration_h ≥ 6.5 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 30 |
| ISS_COL_007 | fatigue_self ≤ 3.875; grip_strength ≥ -2; pvt_lapses ≤ 1.25; sleep_duration_h ≥ 6; sleep_quality ≥ 63.75; work_hours_3d ≤ 33 |
| ISS_COL_010 | fatigue_self ≤ 3.875; grip_strength ≥ -2; pvt_lapses ≤ 1.25; sleep_duration_h ≥ 6; sleep_quality ≥ 63.75; work_hours_3d ≤ 33 |
| ISS_COL_011 | fatigue_self ≤ 3.375; pvt_lapses ≤ 0.75 **duro**; sleep_duration_h ≥ 6.75 **duro**; sleep_quality ≥ 70 **duro** |
| ISS_COL_017 | fatigue_self ≤ 4; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.25; sleep_quality ≥ 65 |
| ISS_COL_018 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 26.25 **duro** |
| ISS_COL_019 | fatigue_self ≤ 3.375; grip_strength ≥ -2; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 33 |
| ISS_COL_020 | fatigue_self ≤ 3.375; grip_strength ≥ -2; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 33 |
| ISS_COL_021 | fatigue_self ≤ 4; pvt_lapses ≤ 1.25; sleep_duration_h ≥ 5.875; sleep_quality ≥ 61.25 |
| ISS_COL_024 | fatigue_self ≤ 3.375; pvt_lapses ≤ 0.75 **duro**; sleep_duration_h ≥ 6.75 **duro**; sleep_quality ≥ 70 **duro** |
| MOON_IND_010 | fatigue_self ≤ 4; pvt_lapses ≤ 1.25; sleep_duration_h ≥ 5.875; sleep_quality ≥ 61.25 |
| MOON_IND_011 | fatigue_self ≤ 3.75; pvt_lapses ≤ 1.375; sleep_duration_h ≥ 6.125; sleep_quality ≥ 62.5 |
| MOON_IND_012 | fatigue_self ≤ 3.75; pvt_lapses ≤ 1.375; sleep_duration_h ≥ 6.125; sleep_quality ≥ 62.5 |
| MOON_IND_016 | fatigue_self ≤ 4; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.25; sleep_quality ≥ 65 |
| MOON_COL_001 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 26.25 **duro** |
| MOON_COL_002 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 26.25 **duro** |
| MOON_COL_003 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 26.25 **duro** |
| MOON_COL_004 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 26.25 **duro** |
| MOON_COL_005 | fatigue_self ≤ 3.5; pvt_lapses ≤ 1 **duro**; sleep_duration_h ≥ 6.5 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 30 |
| MOON_COL_006 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.25; sleep_quality ≥ 66.25; work_hours_3d ≤ 28.5 |
| MOON_COL_007 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 27.75 **duro** |
| MOON_COL_008 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 27.75 **duro** |
| MOON_COL_009 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 27.75 **duro** |
| MOON_COL_010 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 26.25 **duro** |
| MOON_COL_011 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 27.75 **duro** |
| MOON_COL_012 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 27.75 **duro** |
| MOON_COL_014 | fatigue_self ≤ 3.5; grip_strength ≥ -1.75; pvt_lapses ≤ 1 **duro**; sleep_duration_h ≥ 6.5 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 30 |
| MOON_COL_015 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 27.75 **duro** |
| MOON_COL_017 | fatigue_self ≤ 4; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.25; sleep_quality ≥ 65 |
| MOON_COL_018 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 26.25 **duro** |
| MOON_COL_019 | fatigue_self ≤ 3.375; grip_strength ≥ -2; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 33 |
| MOON_COL_020 | fatigue_self ≤ 3.625; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 65 |
| MOON_COL_021 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.625; sleep_duration_h ≥ 6.375 **duro**; work_hours_3d ≤ 27.75 **duro** |
| MOON_COL_022 | fatigue_self ≤ 3.25; grip_strength ≥ -1.5; pvt_lapses ≤ 1.25; sleep_duration_h ≥ 6; sleep_quality ≥ 61.25; work_hours_3d ≤ 30 |
| MARS_IND_009 | fatigue_self ≤ 4; pvt_lapses ≤ 1.25; sleep_duration_h ≥ 5.875; sleep_quality ≥ 61.25 |
| MARS_IND_011 | fatigue_self ≤ 3.875; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.5 **duro**; sleep_quality ≥ 71.25 **duro** |
| MARS_IND_012 | fatigue_self ≤ 3.75; pvt_lapses ≤ 1.375; sleep_duration_h ≥ 6.125; sleep_quality ≥ 62.5 |
| MARS_IND_013 | fatigue_self ≤ 3.625; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 65 |
| MARS_IND_020 | fatigue_self ≤ 4; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.25; sleep_quality ≥ 65 |
| MARS_COL_001 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 26.25 **duro** |
| MARS_COL_002 | fatigue_self ≤ 3.5; pvt_lapses ≤ 1 **duro**; sleep_duration_h ≥ 6.5 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 30 |
| MARS_COL_003 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.25; sleep_quality ≥ 66.25; work_hours_3d ≤ 28.5 |
| MARS_COL_004 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 27.75 **duro** |
| MARS_COL_005 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 27.75 **duro** |
| MARS_COL_006 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 26.25 **duro** |
| MARS_COL_007 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 26.25 **duro** |
| MARS_COL_008 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 26.25 **duro** |
| MARS_COL_009 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 27.75 **duro** |
| MARS_COL_010 | fatigue_self ≤ 3.5; grip_strength ≥ -1.75; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 30 |
| MARS_COL_012 | fatigue_self ≤ 3.875; grip_strength ≥ -2; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.5 **duro**; sleep_quality ≥ 63.75; work_hours_3d ≤ 33 |
| MARS_COL_013 | fatigue_self ≤ 3.125 **duro**; grip_strength ≥ -1.125 **duro**; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 27.75 **duro** |
| MARS_COL_014 | fatigue_self ≤ 3.5; grip_strength ≥ -1.75; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 30 |
| MARS_COL_015 | fatigue_self ≤ 4; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.25; sleep_quality ≥ 65 |
| MARS_COL_016 | fatigue_self ≤ 3.375; grip_strength ≥ -2; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 67.5; work_hours_3d ≤ 33 |
| MARS_COL_017 | fatigue_self ≤ 3.5; grip_strength ≥ -1.75; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 30 |
| MARS_COL_020 | fatigue_self ≤ 3.625; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 65 |
| SAT_IND_001 | fatigue_self ≤ 3.75; pvt_lapses ≤ 1.375; sleep_duration_h ≥ 6.125; sleep_quality ≥ 62.5 |
| SAT_IND_002 | fatigue_self ≤ 3.75; pvt_lapses ≤ 1.375; sleep_duration_h ≥ 6.125; sleep_quality ≥ 62.5 |
| SAT_IND_003 | fatigue_self ≤ 3.75; pvt_lapses ≤ 1.375; sleep_duration_h ≥ 6.125; sleep_quality ≥ 62.5 |
| SAT_IND_015 | fatigue_self ≤ 3.625; pvt_lapses ≤ 1.125 **duro**; sleep_duration_h ≥ 6.375 **duro**; sleep_quality ≥ 65 |
| SAT_COL_001 | fatigue_self ≤ 3.375; pvt_lapses ≤ 0.75 **duro**; sleep_duration_h ≥ 6.75 **duro**; sleep_quality ≥ 70 **duro** |
| SAT_COL_003 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 26.25 **duro** |
| SAT_COL_004 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 0.75 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 26.25 **duro** |
| SAT_COL_005 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 26.25 **duro** |
| SAT_COL_007 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -1.25; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 26.25 **duro** |
| SAT_COL_008 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 26.25 **duro** |
| SAT_COL_010 | fatigue_self ≤ 2.875 **duro**; grip_strength ≥ -0.875 **duro**; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.625 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 26.25 **duro** |
| SAT_COL_011 | fatigue_self ≤ 3.5; grip_strength ≥ -1.75; pvt_lapses ≤ 1 **duro**; sleep_duration_h ≥ 6.5 **duro**; sleep_quality ≥ 70 **duro**; work_hours_3d ≤ 30 |
| SAT_COL_012 | fatigue_self ≤ 3.375; pvt_lapses ≤ 0.75 **duro**; sleep_duration_h ≥ 6.75 **duro**; sleep_quality ≥ 70 **duro** |
| SAT_COL_013 | fatigue_self ≤ 3.375; pvt_lapses ≤ 0.75 **duro**; sleep_duration_h ≥ 6.75 **duro**; sleep_quality ≥ 70 **duro** |
| SAT_COL_014 | fatigue_self ≤ 4; pvt_lapses ≤ 0.875 **duro**; sleep_duration_h ≥ 6.25; sleep_quality ≥ 65 |
| SAT_COL_015 | fatigue_self ≤ 3.125 **duro**; pvt_lapses ≤ 1 **duro**; sleep_duration_h ≥ 6.5 **duro**; sleep_quality ≥ 65 |

## Informe de calibración

Ninguna puntuación es oficial: todas necesitan validación con expertos (equipo médico, instructores de EVA y operaciones de misión) y, cuando existan, con datos de rendimiento reales.

Prioridad de calibración: primero las tareas críticas para la seguridad con menor confianza, porque sus umbrales derivados son restricciones duras.

| Prioridad | Tarea | Nombre | Crítica | Confianza | Ajustes sobre el perfil |
|---|---|---|---|---|---|
| 1 | MARS_COL_001 | Recogida de muestras geológicas | sí | 0.30 | — |
| 2 | MARS_COL_002 | Exploración de terreno mediante rover | sí | 0.30 | — |
| 3 | MARS_COL_003 | Perforación y extracción de muestras del subsuelo | sí | 0.30 | — |
| 4 | MARS_COL_004 | Instalación de instrumentos científicos | sí | 0.30 | — |
| 5 | MARS_COL_005 | Despliegue de estaciones de monitorización | sí | 0.30 | — |
| 6 | MARS_COL_006 | Exploración geológica de campo | sí | 0.30 | — |
| 7 | MARS_COL_007 | Estudios de astrobiología | sí | 0.30 | attention_to_detail 0.75→0.85: protección planetaria y control de contaminación de las muestras |
| 8 | MARS_COL_008 | Inspección de regiones de interés científico | sí | 0.30 | — |
| 9 | MARS_COL_009 | Construcción y despliegue de infraestructura | sí | 0.30 | — |
| 10 | MARS_COL_013 | Instalación de sistemas energéticos | sí | 0.30 | — |
| 11 | MOON_COL_011 | Construcción de infraestructura | sí | 0.30 | — |
| 12 | MOON_COL_012 | Instalación de sistemas energéticos | sí | 0.30 | — |
| 13 | MOON_COL_015 | Preparación de instalaciones de superficie | sí | 0.30 | — |
| 14 | MARS_COL_010 | Reparación de sistemas críticos del hábitat | sí | 0.35 | decision_making 0.75→0.85: autonomía de la tripulación: el retardo de las comunicaciones con Tierra impide la ayuda en tiempo real (arquitecturas de referencia de Marte) |
| 15 | MARS_COL_014 | Reparación de equipamiento extravehicular | sí | 0.35 | decision_making 0.75→0.85: autonomía de la tripulación: el retardo de las comunicaciones con Tierra impide la ayuda en tiempo real (arquitecturas de referencia de Marte) |
| 16 | MARS_COL_015 | Preparación y coordinación de EVA | sí | 0.35 | — |
| 17 | MARS_COL_016 | Simulacros de emergencia | sí | 0.35 | decision_making 0.75→0.85: autonomía de la tripulación: el retardo de las comunicaciones con Tierra impide la ayuda en tiempo real (arquitecturas de referencia de Marte) |
| 18 | MARS_COL_017 | Gestión de contingencias | sí | 0.35 | decision_making 0.75→0.85: autonomía de la tripulación: el retardo de las comunicaciones con Tierra impide la ayuda en tiempo real (arquitecturas de referencia de Marte) |
| 19 | MARS_IND_020 | Preparación individual para EVA | sí | 0.35 | — |
| 20 | MOON_COL_001 | Recogida de muestras lunares | sí | 0.35 | — |
| 21 | MOON_COL_002 | Exploración de cráteres | sí | 0.35 | — |
| 22 | MOON_COL_003 | Exploración de regiones permanentemente sombreadas | sí | 0.35 | stress_tolerance 0.7→0.85: frío extremo, oscuridad y márgenes térmicos estrechos del traje; fatigue_tolerance 0.8→0.85: márgenes térmicos y de consumibles del traje más estrechos |
| 23 | MOON_COL_004 | Exploración de regiones volcánicas | sí | 0.35 | — |
| 24 | MOON_COL_005 | Exploración mediante rover | sí | 0.35 | — |
| 25 | MOON_COL_006 | Perforación del regolito | sí | 0.35 | — |
| 26 | MOON_COL_007 | Instalación de instrumentos científicos | sí | 0.35 | — |
| 27 | MOON_COL_008 | Despliegue de estaciones de monitorización | sí | 0.35 | — |
| 28 | MOON_COL_009 | Instalación de instrumentos sísmicos | sí | 0.35 | physical_precision 0.65→0.75: nivelación y orientación precisa del sismómetro |
| 29 | MOON_COL_010 | Estudios geológicos de campo | sí | 0.35 | — |
| 30 | MOON_COL_018 | Realización de EVA | sí | 0.35 | — |
| 31 | MOON_COL_019 | Simulacros de emergencia | sí | 0.35 | — |
| 32 | SAT_IND_015 | Supervisión de operaciones robóticas | sí | 0.35 | — |
| 33 | ISS_COL_006 | Reparación de componentes | sí | 0.40 | — |
| 34 | ISS_COL_011 | Recepción de vehículos de carga | sí | 0.40 | — |
| 35 | ISS_COL_017 | Preparación de actividades EVA | sí | 0.40 | — |
| 36 | ISS_COL_018 | Realización de actividades EVA | sí | 0.40 | — |
| 37 | ISS_COL_019 | Simulacros de emergencia | sí | 0.40 | — |
| 38 | ISS_COL_020 | Coordinación de evacuación | sí | 0.40 | — |
| 39 | ISS_COL_024 | Coordinación de operaciones robóticas | sí | 0.40 | — |
| 40 | ISS_IND_021 | Preparación individual para EVA | sí | 0.40 | — |
| 41 | MARS_COL_012 | Preparación de vehículos de ascenso | sí | 0.40 | concentration 0.6→0.8: comprobaciones de un vehículo del que depende el regreso; attention_to_detail 0.7→0.85: listas de comprobación de un sistema crítico; decision_making 0.45→0.65: decidir si el vehículo está listo |
| 42 | MARS_COL_020 | Revisión conjunta de operaciones críticas | sí | 0.40 | decision_making 0.65→0.75: autonomía de la tripulación: el retardo de las comunicaciones con Tierra impide la ayuda en tiempo real (arquitecturas de referencia de Marte) |
| 43 | MARS_IND_009 | Inspección de sistemas del hábitat | sí | 0.40 | — |
| 44 | MARS_IND_011 | Diagnóstico de sistemas eléctricos | sí | 0.40 | decision_making 0.65→0.75: autonomía de la tripulación: el retardo de las comunicaciones con Tierra impide la ayuda en tiempo real (arquitecturas de referencia de Marte) |
| 45 | MARS_IND_013 | Gestión de energía | sí | 0.40 | decision_making 0.65→0.75: autonomía de la tripulación: el retardo de las comunicaciones con Tierra impide la ayuda en tiempo real (arquitecturas de referencia de Marte) |
| 46 | MOON_COL_014 | Reparación de equipamiento | sí | 0.40 | — |
| 47 | MOON_COL_017 | Preparación de EVA | sí | 0.40 | — |
| 48 | MOON_COL_020 | Coordinación de operaciones extravehiculares | sí | 0.40 | — |
| 49 | MOON_COL_022 | Inspección conjunta de infraestructura | sí | 0.40 | physical_effort 0.25→0.6: inspección con traje presurizado; endurance 0.3→0.6: EVA de varias horas; mobility 0.4→0.7: recorrido a pie con traje; fatigue_tolerance 0.3→0.6: EVA; recovery_requirement 0.1→0.55: EVA de duración media |
| 50 | MOON_IND_010 | Inspección del hábitat | sí | 0.40 | — |
| 51 | MOON_IND_016 | Preparación individual para EVA | sí | 0.40 | — |
| 52 | SAT_COL_001 | Captura y acoplamiento de satélites | sí | 0.40 | — |
| 53 | SAT_COL_003 | Sustitución de baterías | sí | 0.40 | — |
| 54 | SAT_COL_004 | Reparación de componentes | sí | 0.40 | problem_solving 0.65→0.8: reparación no prevista en el diseño del satélite; physical_precision 0.8→0.9: retirada de decenas de tornillos pequeños con guantes presurizados |
| 55 | SAT_COL_005 | Sustitución de instrumentos científicos | sí | 0.40 | — |
| 56 | SAT_COL_007 | Inspección exterior de satélites | sí | 0.40 | physical_precision 0.8→0.55: inspección y fotografía, sin manipulación de componentes; physical_effort 0.85→0.7: EVA con poca manipulación de cargas |
| 57 | SAT_COL_008 | Reparación de aislamiento térmico | sí | 0.40 | — |
| 58 | SAT_COL_010 | Sustitución de componentes mecánicos | sí | 0.40 | — |
| 59 | SAT_COL_011 | Recuperación de sistemas averiados | sí | 0.40 | — |
| 60 | SAT_COL_012 | Operaciones de brazos robóticos | sí | 0.40 | — |
| 61 | SAT_COL_013 | Transferencia de componentes entre vehículos | sí | 0.40 | — |
| 62 | SAT_COL_014 | Preparación de operaciones extravehiculares | sí | 0.40 | — |
| 63 | ISS_COL_007 | Mantenimiento de sistemas críticos | sí | 0.45 | — |
| 64 | ISS_COL_010 | Preparación de sistemas de soporte vital | sí | 0.45 | — |
| 65 | ISS_COL_021 | Revisión de sistemas de seguridad | sí | 0.45 | — |
| 66 | ISS_IND_011 | Mantenimiento eléctrico | sí | 0.45 | — |
| 67 | ISS_IND_013 | Mantenimiento de sistemas de soporte vital | sí | 0.45 | — |
| 68 | MARS_IND_012 | Monitorización de soporte vital | sí | 0.45 | — |
| 69 | MOON_COL_021 | Transporte de equipamiento | sí | 0.45 | physical_effort 0.55→0.75: carga de equipos con traje presurizado; endurance 0.5→0.75: trabajo sostenido con traje; fatigue_tolerance 0.45→0.75: EVA con carga física continua; recovery_requirement 0.3→0.7: EVA de varias horas |
| 70 | MOON_IND_011 | Monitorización de sistemas energéticos | sí | 0.45 | — |
| 71 | MOON_IND_012 | Supervisión de soporte vital | sí | 0.45 | — |
| 72 | SAT_COL_015 | Coordinación de operaciones de servicio orbital | sí | 0.45 | concentration 0.65→0.8: seguimiento continuo de una EVA de horas; multitasking 0.55→0.75: coordina EVA, brazo y comunicaciones a la vez |
| 73 | SAT_IND_001 | Monitorización de telemetría | sí | 0.45 | — |
| 74 | SAT_IND_002 | Supervisión de orientación | sí | 0.45 | — |
| 75 | SAT_IND_003 | Monitorización de órbita | sí | 0.45 | — |
| 76 | ISS_IND_014 | Monitorización ambiental | sí | 0.50 | — |
| 77 | MARS_COL_011 | Mantenimiento de vehículos de superficie | no | 0.40 | — |
| 78 | MARS_COL_018 | Transferencia de suministros | no | 0.40 | — |
| 79 | MARS_COL_019 | Planificación de exploraciones | no | 0.40 | decision_making 0.65→0.75: autonomía de la tripulación: el retardo de las comunicaciones con Tierra impide la ayuda en tiempo real (arquitecturas de referencia de Marte) |
| 80 | MARS_IND_001 | Análisis de muestras geológicas | no | 0.40 | — |
| 81 | MARS_IND_002 | Clasificación y documentación de muestras | no | 0.40 | — |
| 82 | MARS_IND_006 | Análisis de posibles biofirmas | no | 0.40 | attention_to_detail 0.75→0.9: protocolos de control de contaminación: un falso positivo tiene gran impacto |
| 83 | MARS_IND_010 | Mantenimiento de equipos científicos | no | 0.40 | — |
| 84 | MOON_COL_016 | Gestión de recursos y suministros | no | 0.40 | — |
| 85 | SAT_IND_004 | Análisis de anomalías | no | 0.40 | — |
| 86 | SAT_IND_005 | Diagnóstico de sistemas eléctricos | no | 0.40 | — |
| 87 | SAT_IND_010 | Diagnóstico de componentes electrónicos | no | 0.40 | — |
| 88 | SAT_IND_012 | Revisión de sistemas de propulsión | no | 0.40 | — |
| 89 | SAT_IND_013 | Calibración de instrumentos | no | 0.40 | physical_precision 0.65→0.3: calibración por mando desde consola, sin manipulación; coordination 0.55→0.25: trabajo en consola |
| 90 | ISS_COL_001 | Preparación conjunta de experimentos | no | 0.45 | — |
| 91 | ISS_COL_002 | Instalación de equipamiento científico | no | 0.45 | — |
| 92 | ISS_COL_003 | Calibración de instrumentos | no | 0.45 | — |
| 93 | ISS_COL_004 | Procesamiento conjunto de muestras | no | 0.45 | — |
| 94 | ISS_COL_005 | Revisión de resultados experimentales | no | 0.45 | — |
| 95 | ISS_COL_008 | Inspección conjunta de módulos | no | 0.45 | — |
| 96 | ISS_COL_009 | Mantenimiento de brazos robóticos | no | 0.45 | — |
| 97 | ISS_COL_012 | Descarga de suministros | no | 0.45 | — |
| 98 | ISS_COL_013 | Almacenamiento de materiales | no | 0.45 | — |
| 99 | ISS_COL_014 | Preparación de vehículos de retorno | no | 0.45 | attention_to_detail 0.55→0.7: muestras con requisitos de temperatura y registro de cada bulto |
| 100 | ISS_COL_015 | Transferencia de suministros | no | 0.45 | — |
| 101 | ISS_COL_022 | Reuniones de planificación | no | 0.45 | — |
| 102 | ISS_COL_023 | Transferencia de conocimiento entre tripulaciones | no | 0.45 | — |
| 103 | ISS_IND_001 | Experimentos de biología | no | 0.45 | — |
| 104 | ISS_IND_002 | Experimentos de física | no | 0.45 | — |
| 105 | ISS_IND_003 | Experimentos de medicina espacial | no | 0.45 | — |
| 106 | ISS_IND_004 | Recogida de muestras biológicas | no | 0.45 | physical_precision 0.65→0.75: punción y manipulación de fluidos biológicos en microgravedad |
| 107 | ISS_IND_005 | Procesamiento de muestras | no | 0.45 | — |
| 108 | ISS_IND_010 | Inspección de equipos | no | 0.45 | — |
| 109 | ISS_IND_012 | Diagnóstico de componentes | no | 0.45 | — |
| 110 | ISS_IND_015 | Inspección de sistemas de comunicaciones | no | 0.45 | — |
| 111 | ISS_IND_023 | Preparación de experimentos | no | 0.45 | physical_precision 0.65→0.55: montaje de material, menos manipulación fina que el experimento |
| 112 | MARS_IND_003 | Análisis de datos atmosféricos | no | 0.45 | — |
| 113 | MARS_IND_004 | Análisis de datos geofísicos | no | 0.45 | — |
| 114 | MARS_IND_005 | Monitorización de instrumentos científicos | no | 0.45 | — |
| 115 | MARS_IND_007 | Cartografía y análisis del terreno | no | 0.45 | — |
| 116 | MARS_IND_008 | Procesamiento de datos de exploración | no | 0.45 | — |
| 117 | MARS_IND_014 | Control de inventario y suministros | no | 0.45 | — |
| 118 | MARS_IND_015 | Monitorización de comunicaciones | no | 0.45 | — |
| 119 | MARS_IND_016 | Gestión de datos de la misión | no | 0.45 | — |
| 120 | MARS_IND_017 | Ejercicio físico | no | 0.45 | — |
| 121 | MARS_IND_018 | Formación y entrenamiento | no | 0.45 | — |
| 122 | MARS_IND_019 | Revisión de procedimientos de emergencia | no | 0.45 | — |
| 123 | MOON_COL_013 | Mantenimiento de rover | no | 0.45 | — |
| 124 | MOON_IND_001 | Clasificación de muestras lunares | no | 0.45 | — |
| 125 | MOON_IND_005 | Análisis de propiedades del regolito | no | 0.45 | — |
| 126 | MOON_IND_009 | Documentación de muestras | no | 0.45 | — |
| 127 | MOON_IND_013 | Diagnóstico de equipos | no | 0.45 | — |
| 128 | MOON_IND_014 | Gestión de suministros | no | 0.45 | — |
| 129 | MOON_IND_015 | Monitorización de comunicaciones | no | 0.45 | — |
| 130 | MOON_IND_017 | Ejercicio físico | no | 0.45 | — |
| 131 | MOON_IND_018 | Formación y entrenamiento | no | 0.45 | — |
| 132 | MOON_IND_019 | Revisión de protocolos de emergencia | no | 0.45 | — |
| 133 | SAT_IND_006 | Análisis de consumo energético | no | 0.45 | — |
| 134 | SAT_IND_007 | Monitorización térmica | no | 0.45 | — |
| 135 | SAT_IND_008 | Análisis de comunicaciones | no | 0.45 | — |
| 136 | SAT_IND_011 | Análisis de degradación de baterías | no | 0.45 | — |
| 137 | SAT_IND_014 | Análisis de datos de inspección | no | 0.45 | — |
| 138 | SAT_IND_016 | Planificación de mantenimiento | no | 0.45 | — |
| 139 | ISS_COL_016 | Gestión conjunta del inventario | no | 0.50 | — |
| 140 | ISS_IND_006 | Monitorización de experimentos | no | 0.50 | — |
| 141 | ISS_IND_007 | Análisis de datos científicos | no | 0.50 | — |
| 142 | ISS_IND_008 | Observación de la Tierra | no | 0.50 | physical_precision 0.15→0.4: encuadre y enfoque de cámara con objetivos largos |
| 143 | ISS_IND_009 | Documentación de resultados | no | 0.50 | — |
| 144 | ISS_IND_016 | Limpieza de módulos | no | 0.50 | — |
| 145 | ISS_IND_017 | Gestión de residuos | no | 0.50 | — |
| 146 | ISS_IND_018 | Control de inventario | no | 0.50 | — |
| 147 | ISS_IND_019 | Ejercicio físico | no | 0.50 | — |
| 148 | ISS_IND_020 | Formación y entrenamiento | no | 0.50 | — |
| 149 | ISS_IND_022 | Revisión de procedimientos | no | 0.50 | — |
| 150 | ISS_IND_024 | Gestión individual de documentación | no | 0.50 | — |
| 151 | MOON_IND_002 | Análisis geológico | no | 0.50 | — |
| 152 | MOON_IND_003 | Procesamiento de datos sísmicos | no | 0.50 | — |
| 153 | MOON_IND_004 | Análisis de datos de radiación | no | 0.50 | — |
| 154 | MOON_IND_006 | Cartografía del terreno | no | 0.50 | — |
| 155 | MOON_IND_007 | Monitorización de instrumentos científicos | no | 0.50 | — |
| 156 | MOON_IND_008 | Análisis de datos de exploración | no | 0.50 | — |
| 157 | SAT_IND_009 | Supervisión de instrumentos científicos | no | 0.50 | — |

Además, todas las duraciones son estimaciones configurables, salvo el ejercicio de la ISS, derivado del protocolo de unas dos horas diarias que describe la CSA.
