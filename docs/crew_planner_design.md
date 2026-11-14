# Planificador diario de tareas — documento de diseño

Estado: implementado (fases 2 a 6) en `sistema-de-recomendacion/planificador/`. El catálogo de tareas por entorno (ISS, Luna, Marte, satélites) y su traducción a requisitos están en [task_catalog_methodology.md](task_catalog_methodology.md); añadió al modelo de tarea `only_for` (tareas de una persona concreta) e `interdependence`, que multiplica el término de compatibilidad: `C_comp = γ · I_j · d_j · (K_ref − K(G))`. Uso, entrada, salida y configuración en su [README](../sistema-de-recomendacion/planificador/README.md). Este documento recoge el modelo y las decisiones de diseño, con los cambios hechos durante la implementación.

Módulo de ORBIVIA que genera una planificación diaria de tareas individuales y colectivas a partir del estado de cada astronauta, los requisitos de las tareas, el historial y, de forma acotada, las salidas del grafo social. Es una **herramienta de apoyo: propone, no decide**. Toda planificación la valida una persona.

## 1. Qué hay hoy en el repositorio

| Elemento | Estado | Se reutiliza |
|---|---|---|
| Grafo social (`procesamiento/grafos/social_graph/`) | Completo, 140 funciones de test, servicio Docker | Sí, solo en lectura |
| Astronautas | Solo identificadores seudónimos (`A1`…`A6`, `SG_CREW`) | Los mismos identificadores |
| Horarios | `Schedule` (sueño y trabajo por astronauta), `FixedSchedule` | Sí: disponibilidad y descanso |
| Álgebra de intervalos | `intervals.py` (unión, intersección, complemento) | Sí, se importa |
| Tareas, cualificaciones, historial de asignaciones | No existen | Se definen aquí |
| Datos fisiológicos y cognitivos | No existen. `procesamiento/datos-fisicos-ping-diario/`, `streaming-valores-continuos-sueno/`, `semanales/` y `base-de-datos/vector-colapsado/` están vacíos | Se define un contrato de entrada |
| Análisis de texto (rama `feature/analisisTranscripcionAudio`) | Puntuaciones de un clasificador de salud mental, en memoria | **No**: es inferencia psicológica |
| API (`sistema-de-recomendacion/api/main.py`) | Solo endpoints de salud; la rama de audio la modifica | No se toca en las primeras fases |
| Optimización | Ninguna dependencia de optimización | Se añade OR-Tools |

Salidas del grafo que consume el planificador, tal como se guardan en `social_graph.daily_result.result`:

- `crew`: orden de la tripulación.
- `isolation.structure.smoothed_weights`: matriz `W̄` de 7 días, simétrica, en [0, 1], con `null` en la diagonal y en las parejas nunca evaluables.
- `isolation.astronauts[a].status` y `.signals`: `normal`, `follow_up`, `review`, `warming_up`, `no_data`, `not_evaluable`.
- `isolation.crew.drop`: descenso de toda la tripulación.

Los ficheros `volumenes/social-graph/day_NNNN.json` son la exportación para el panel y **no** contienen `W̄`. La fuente es la tabla de PostgreSQL, o un volcado JSON de ese documento para la demo sin base de datos.

## 2. Conflictos detectados

### 2.1 Uso del grafo en el reparto de tareas

Tres documentos del proyecto dicen lo contrario de lo que pide este módulo:

- `README.md.2.0.` (rama `develop`), sección D: «El grafo social […] no se usa para repartir tareas ni para separar a miembros de la tripulación».
- `docs/social_graph_design.md`, sección 7: «El grafo no determina compatibilidad profesional ni quién trabaja con quién en operaciones críticas».
- `procesamiento/grafos/README.md`: «El grafo no se usa para asignar tareas operativas».

**Decisión (Eduardo, 2026-11-14):**

- **Compatibilidad en todas las tareas colectivas**, también las críticas, porque un equipo que ya se relaciona trabaja mejor. Es un objetivo blando del coste operativo, nunca una restricción: no sustituye a cualificaciones ni a umbrales.
- **Inclusión por aislamiento solo en tareas de baja carga.** En tareas exigentes, meter a alguien con poca integración puede agravar el problema.

Los documentos del grafo social se actualizan en consecuencia. `README.md.2.0.` es de la rama `develop` y lo mantiene el equipo: hay que acordar allí el cambio.

### 2.2 Compatibilidad frente a inclusión

`C_compatibilidad` premia equipos de personas que ya pasan tiempo juntas. `C_aislamiento` premia incluir a quien pasa poco tiempo con los demás, que por definición tiene `W` bajo con todos. Si actuaran con el mismo nivel de prioridad sobre las mismas tareas, se anularían y el resultado dependería solo de la relación entre `γ` y `μ`.

La decisión anterior lo resuelve en buena parte:

- En tareas de carga media o alta solo actúa la compatibilidad.
- En tareas de baja carga actúan las dos, pero en niveles distintos: la compatibilidad forma parte del coste operativo (etapa 2) y la inclusión solo puede empeorarlo hasta `ε` (etapa 3). La inclusión gana cuando el coste de incluir a alguien es pequeño, y pierde cuando no.

Hipótesis que conviene declarar: `W̄` mide proximidad en ocio. Que eso prediga el rendimiento de un equipo en el trabajo es razonable pero no está validado; por eso el peso `γ` es configurable y la puntuación se muestra desglosada en cada equipo.

### 2.3 Otras correcciones al modelo propuesto

| Fórmula del enunciado | Problema | Corrección |
|---|---|---|
| `D_ij = sqrt(Σ q (z − t)²)` | Simétrica: penaliza estar mejor de lo requerido | Déficit unilateral según el tipo de parámetro (4.2) |
| Mahalanobis | Necesita una covarianza que no se puede estimar con 4–8 personas y sin datos reales; mide rareza estadística, no déficit | Euclídea ponderada. Las correlaciones se tratan agrupando parámetros por dominio y limitando el peso de cada dominio |
| `P_estado = I_j · D_ij` | Si una tarea es aplazable, multiplicar su coste por la importancia hace que lo barato sea no cubrir las importantes | La cobertura se resuelve antes, en una etapa propia (5.3) |
| `P_aislamiento = −μ Σ A_i` | Crece con el tamaño del equipo y con el número de personas señaladas: premia equipos grandes formados solo por ellas | Premio por persona, saturante, y solo si el equipo incluye a alguien sin señales (4.7) |
| `A_i` como indicador normalizado | El analizador no produce una puntuación comparable entre astronautas, a propósito | `A_i` se deriva del estado, que ya exige persistencia temporal (4.7) |
| `Z` como suma única | Mezcla objetivos no conmensurables; un peso mal elegido cambia seguridad por comodidad | Optimización lexicográfica en tres etapas, con la suma ponderada como modo alternativo (5.3) |

### 2.4 Diferencias con el motor descrito en `README.md.2.0.`

Ese documento define el reparto con: solo tareas comunes y de mantenimiento, ejercicio diario fijo, dos o tres planes alternativos entre los que elige la tripulación, y mínimo cambio respecto al plan original.

- Ejercicio y otros compromisos fijos: se modelan como bloques ocupados.
- Planes alternativos: se obtienen resolviendo con varios perfiles de pesos y una restricción de diversidad (sección 5.3b).
- Mínimo cambio respecto a un plan previo: fuera de alcance; el modelo lo admite como un término más.

## 3. Arquitectura

```
 estado de astronautas      tareas del día       historial de        social_graph.daily_result
 (contrato JSON; futuro:    (catálogo JSON)      asignaciones        (solo lectura)
  vector colapsado)               │                   │                     │
        │                         │                   │                     │
        ▼                         ▼                   ▼                     ▼
   state.py                   model.py           history.py            social.py
   normalización,                                 R_ij                  W̄ + máscara, A_i
   vigencia, incertidumbre                                                  │
        └────────────┬────────────┴─────────┬─────────┘                     │
                     ▼                      ▼                               │
           eligibility.py              costs.py                             │
           restricciones duras,        D_ij, U_ij, R_ij,                    │
           con motivo                  carga objetivo                       │
                     └──────────┬───────────┘                               │
                                ▼                                           │
                           teams.py  ◄──────────────────────────────────────┘
                           equipos candidatos y su coste
                                ▼
                         optimizer.py (CP-SAT, 3 etapas) ──► diagnosis.py
                                ▼                            (si no hay solución)
                           explain.py
                                ▼
                    plan diario (JSON): asignaciones, equipos,
                    información global y justificaciones
```

- **Núcleo puro**, sin E/S: todo lo anterior recibe y devuelve estructuras de datos. Se prueba con datos construidos a mano.
- **El grafo social no se modifica.** `social.py` lee su documento diario a través de un adaptador. Un test de contrato ejecuta el `IsolationAnalyzer` real y comprueba que el adaptador entiende su salida.
- **Dependencia de código:** se importan `social_graph.intervals` y `social_graph.schedule`, que solo usan la biblioteca estándar. No se duplican.
- **Ubicación:** `sistema-de-recomendacion/planificador/`, con el paquete `crew_planner/`, `tests/`, `config/default.toml` y `README.md`. Imagen propia en `docker/planner/`.

## 4. Modelo matemático

Conjuntos: astronautas `i ∈ A`, tareas `j ∈ T = T_ind ∪ T_col`, parámetros `k ∈ P`, día `d`. El día se divide en tramos de 15 minutos.

### 4.1 Estado y normalización

Cada parámetro `k` se declara en configuración con:

- **Tipo:** `higher_better`, `lower_better` o `range`.
- **Normalización:** `minmax` sobre un rango fisiológico `[lo_k, hi_k]`, o `baseline_z` respecto a la línea base propia del astronauta, recortado a ±3 y llevado a [0, 1].
- **Vigencia:** 24 h para variables diarias y de sueño, 7 días para las semanales. Son las reglas de `README.md.2.0.`, no valores elegidos aquí.
- **Dominio:** sueño, fatiga, cognitivo, físico.

Cada medición lleva valor, instante, fuente y, solo si la fuente la da, confianza. Un parámetro es **conocido** para `i` si existe, está dentro de su vigencia y, si es `baseline_z`, hay línea base. Si no, es **desconocido**: no se rellena ni se estima.

Catálogo inicial, tomado de las variables previstas en `README.md.2.0.`: duración y calidad del sueño, latencia PVT-B, cansancio declarado en el check-in, fuerza de agarre, oxigenación, frecuencia cardíaca en reposo, horas trabajadas en los últimos días. Quedan fuera por diseño: ánimo, personalidad y puntuaciones de voz o texto.

### 4.2 Adecuación

Cada tarea fija, por parámetro, un umbral mínimo, un máximo o un intervalo `[a, b]`, un peso `q_jk ≥ 0` y si es crítico. El déficit es unilateral:

```
δ_ijk = max(0, t_jk − z_ik)                       mínimo requerido
δ_ijk = max(0, z_ik − t_jk)                       máximo admitido
δ_ijk = max(0, a_jk − z_ik, z_ik − b_jk)          intervalo óptimo
```

Con `K_ij` los parámetros de la tarea conocidos para `i`:

```
D_ij = sqrt( Σ_{k∈K_ij} q_jk · δ_ijk² / Σ_{k∈K_ij} q_jk )        ∈ [0, 1]
```

El peso total de un dominio dentro de una tarea se limita (`max_domain_share`), para que tres variables de sueño correlacionadas no cuenten como tres evidencias.

### 4.3 Incertidumbre

```
U_ij = Σ_k q_jk · u_ik / Σ_k q_jk        ∈ [0, 1]
u_ik = 1            si k es desconocido para i
u_ik = 1 − c_ik     si es conocido y la fuente da una confianza c_ik
u_ik = 0            si es conocido y no hay confianza declarada
```

- Un dato ausente nunca vale como sano: sale del cálculo de `D_ij` y entra en `U_ij`.
- Si el parámetro desconocido es **crítico** para la tarea, el astronauta no es elegible para ella (4.8).
- No se inventa una degradación gradual por antigüedad: dentro de la vigencia el dato vale, fuera no.

Consecuencia que hay que conocer: un dato desconocido cuesta más que uno sano y que uno moderadamente malo, pero puede costar menos que uno conocido y muy malo. Es coherente: no saber no equivale a saber que está mal.

### 4.4 Repetición

```
R_ij = Σ_{d'∈H} 1[i hizo la categoría de j el día d'] · e^{−(d−d')/τ}  /  Σ_{d'∈H} e^{−(d−d')/τ}     ∈ [0, 1]
```

`H` son los últimos `window_days` días (14 por defecto) y `τ` la vida media en días (3). Se cuenta por categoría de tarea, no solo por identificador. El coeficiente por tarea es `λ_j = monotony_j`, que por defecto vale `1 − I_j`: una tarea crítica casi no se penaliza por repetirse.

### 4.5 Coste individual

```
C_ij = α_estado · I_j · D_ij  +  α_rep · λ_j · R_ij  +  α_inc · I_j · U_ij
```

`I_j ∈ (0, 1]` es la importancia, obtenida de una escala configurable (por defecto 1–5). Los tres sumandos están en [0, 1], así que los `α` son comparables entre sí.

### 4.6 Carga y equidad

```
w_j  = duración_j · (0.5 + 0.5 · intensidad_j)   carga ponderada de la tarea, en horas
L_i  = Σ_j w_j · a_ij                            carga asignada a i
s_i  = h_i · g_i / Σ_i h_i · g_i                 cuota objetivo de i
```

Con `duración · intensidad`, una tarea de intensidad 0 no contaría como carga; así el tiempo ocupado siempre cuenta al menos la mitad.

`h_i` son las horas disponibles del día y `g_i ∈ [g_min, 1]` la capacidad relativa, calculada con los parámetros del dominio de fatiga. Si esos parámetros son desconocidos, `g_i` toma el valor conservador `g_min`.

```
C_equidad = Σ_i | L_i − s_i · Σ_i L_i | / L_ref   +   β · ( max_i L_i/s_i − min_i L_i/s_i ) / L_ref
```

El primer término mide la desviación de cada uno respecto a su carga objetivo. El segundo, la diferencia entre el más y el menos cargado, y evita que el desequilibrio se concentre en una persona. Los dos son lineales.

### 4.7 Equipos e indicadores sociales

Para cada tarea colectiva se enumeran los equipos candidatos `G` con tamaño en `[m_min, m_max]`, formados por personas elegibles y que cumplen las cualificaciones de equipo. Con 6 personas y tamaños de 2 a 4 son como mucho 50 por tarea.

```
C_ind(j, G)  = media_{i∈G} C_ij
K(G)         = Σ_{parejas evaluables de G} W̄_ij / nº de parejas evaluables      (indefinido si no hay ninguna)
C_comp(j, G) = γ · I_j · (K_ref − K(G))         0 si K(G) está indefinido
C_op(j, G)   = C_ind(j, G) + C_comp(j, G)
```

- `K_ref` es la mediana de `W̄` de la tripulación. Un equipo por encima de lo habitual reduce su coste y uno por debajo lo aumenta.
- Las parejas no evaluables se excluyen, no cuentan como cero. Si ninguna pareja es evaluable, el término es neutro: la falta de datos no premia ni castiga.
- Se multiplica por `I_j`: la compatibilidad pesa más donde la tarea importa más, en línea con la decisión de 2.1.
- Si el grafo no está disponible o hay descenso de tripulación, `γ` se toma como 0 y la salida lo dice.
- Para tareas individuales `K` no está definido y el término no existe.

Indicador de integración por persona, a partir del estado del analizador:

```
A_i = 1     review
A_i = 0.5   follow_up
A_i = 0     normal, warming_up, no_data, not_evaluable, o descenso de tripulación activo
```

Esos estados ya exigen persistencia (3 de 5 días, o 5 de 7), así que una observación aislada no produce `A_i > 0`.

```
C_integración = −μ · Σ_i A_i · u_i
u_i = 1   si i participa en al menos una tarea colectiva de baja carga
          en un equipo que incluye a alguien con A = 0
```

Una tarea colectiva es **de baja carga** si cumple las tres condiciones:

- `intensidad_j ≤ low_load_max` (por defecto 0.4 en una escala de 0 a 1),
- no está marcada como `demanding`,
- `I_j ≤ low_load_max_importance` (por defecto 0.6).

Cada tarea puede forzar `low_load = false` en el catálogo, nunca `true` si no cumple las condiciones.

Es saturante: una segunda tarea colectiva para la misma persona no añade premio, y un equipo formado solo por personas señaladas tampoco.

### 4.8 Restricciones duras

| # | Restricción | Cómo se modela |
|---|---|---|
| 1 | Tareas obligatorias cubiertas | `cubierta_j = 1` |
| 2 | Sin solapes por astronauta | Intervalos opcionales y `NoOverlap` por astronauta |
| 3 | Cualificaciones individuales | Elegibilidad `e_ij = 0` |
| 4 | Requisitos fisiológicos críticos | `e_ij = 0` si se incumple el umbral **o el dato es desconocido** |
| 5 | Disponibilidad | Lo que no es horario de trabajo se bloquea; no disponible → `e_ij = 0` |
| 6 | Descanso | Sueño bloqueado; margen de descanso tras tareas exigentes; máximo de horas y de tareas exigentes por día |
| 7 | Tamaño de equipo | Enumeración de candidatos |
| 8 | Cualificaciones de equipo | «Todos» o «al menos n con la cualificación c», en la enumeración |
| 9 | Duración y simultaneidad | Ventana `[inicio más temprano, fin más tardío]`; `NoOverlap` entre tareas que comparten recurso |

Ninguna de estas restricciones tiene peso ni se relaja.

## 5. Optimización

### 5.1 Variables

- `z_{j,G} ∈ {0, 1}`: la tarea `j` la hace el equipo `G`. Para las individuales, los equipos son de una persona, con lo que `x_ij` es el caso particular.
- `a_ij = Σ_{G∋i} z_{j,G}`: el astronauta `i` participa en `j`.
- `cubierta_j = Σ_G z_{j,G} ∈ {0, 1}`.
- `inicio_j`: tramo de inicio, entero, dentro de la ventana de la tarea.

### 5.2 Método: CP-SAT de OR-Tools

| Criterio | CP-SAT | MILP (CBC, SCIP) |
|---|---|---|
| Variables binarias | Nativo | Nativo |
| Restricciones temporales | Intervalos y `NoOverlap` nativos | Hay que linealizar con big-M: más variables y peor relajación |
| Formación de equipos | Enumeración + una binaria por equipo | Igual |
| Costes | Enteros: se escalan ×10 000 | Reales |
| Diagnóstico de infactibilidad | Supuestos y núcleo insatisfacible | Solo con IIS, que CBC no ofrece |
| Reproducibilidad | Determinista con un hilo y semilla fija | Determinista |
| Tamaño real (6 personas, ~15 tareas) | Menos de 1 000 binarias; milisegundos | Similar |

Se elige CP-SAT por los intervalos y por el diagnóstico. Enumerar a mano, como hace el `CollaborationRecommender`, deja de ser viable al añadir horarios y equidad.

Límite conocido: la enumeración de equipos crece de forma combinatoria. Con más de unas 10 personas habría que sustituirla por variables por pareja. Se pone un tope configurable y un error claro si se supera.

### 5.3 Etapas

1. **Cobertura.** Maximizar `Σ I_j · cubierta_j` sobre las tareas aplazables. Las obligatorias ya son restricción. El resultado se fija.
2. **Coste operativo.** Minimizar `Z_op = Σ C_op + α_eq · C_equidad`, que reúne estado, repetición, incertidumbre, compatibilidad y equidad.
3. **Inclusión.** Minimizar `C_integración` con la restricción `Z_op ≤ (1 + ε) · Z_op*`. Por defecto `ε = 0.05`.

La etapa 3 da una garantía que se puede enunciar: **la inclusión nunca empeora el coste operativo más de `max(ε · (Z_op* + F), ε_abs)`**, y nunca cambia qué tareas se cubren. Es el método ε-restricción, estándar en optimización multiobjetivo.

La tolerancia absoluta `ε_abs` (0.2 por defecto) se añadió en la Fase 5. Con una tripulación en buen estado el óptimo es casi cero y un 5 % de casi nada no deja margen: en el escenario de aislamiento, incluir a la persona en revisión costaba 0.17 y la regla relativa lo impedía siempre. Se fija igual a `μ`: incluir a alguien en `review` puede costar, como mucho, lo que vale su premio, que es lo mismo que haría la suma ponderada para una sola persona.

Modo alternativo `weighted`: una sola resolución de la suma del enunciado, más un término de tareas no cubiertas (`stages.uncovered_penalty × I_j`). Se mantiene para comparar.

Detalles de la implementación (Fase 4):

- **ε sobre una cantidad positiva.** La compatibilidad puede restar coste, así que `Z_op*` puede ser negativo y `(1 + ε) · Z_op*` sería más estricto que el óptimo. La cota se aplica a `Z_op + F`, con `F = Σ γ · I_j · (1 − K_ref)` sobre las tareas colectivas cubiertas, que es la mayor rebaja posible: `Z_op + F ≤ (1 + ε) · (Z_op* + F)`.
- **Desempate.** Tras la etapa 3 se fija la inclusión obtenida y se vuelve a minimizar `Z_op`, para no aceptar empeoramientos gratuitos dentro de ε.
- **Descanso.** Una tarea exigente ocupa, para cada participante, su duración más el descanso mínimo. Así ninguna otra tarea puede empezar antes.
- **Tramos.** Los inicios van en múltiplos de `slot_min` y la duración se redondea hacia arriba en el modelo: el redondeo siempre reserva tiempo de más, nunca de menos.
- **Enteros.** CP-SAT trabaja con enteros: los costes se escalan ×10¹². La equidad se discretiza a milésimas de hora; los costes de la salida se recalculan en coma flotante.
- **Red de seguridad.** Todo plan pasa por un verificador independiente del optimizador (`verify_plan`). Si incumpliera una restricción dura, el sistema lanza un error en vez de devolverlo.
- **Tiempo límite.** Si el optimizador no responde a tiempo, la salida es `timeout`, no `infeasible`: no haber encontrado solución no prueba que no exista.

### 5.3b Planes alternativos

Se proponen varios planes completos para que elijan la tripulación y el control de misión, como pide `README.md.2.0.`. Por defecto son tres.

**Generación.** Cada plan se obtiene con su propio enfoque, que multiplica los pesos globales (`[alternatives.profiles]`): equilibrado, mejor adecuación, y reparto y rotación. Pasa por las mismas etapas y el mismo verificador. Para que no salgan planes casi iguales, el plan k exige

```
Σ_{o ∈ P_j} z_o ≤ |P_j| − d        para cada plan anterior j
```

siendo `P_j` las opciones (tarea, personas) elegidas en el plan j y `d = min_difference`. Si es infactible, `d` baja hasta 1, y si ni así se puede, se devuelven menos planes con una nota. Relajar la diversidad no toca la seguridad.

**Comparación.** Los costes de cada plan no son comparables entre sí, porque cada uno usa sus pesos. La comparación usa métricas independientes de los pesos:

- adecuación media;
- incertidumbre;
- repetición reciente;
- diferencia de carga y carga máxima frente al objetivo;
- interacción media de los equipos;
- inclusión y tareas cubiertas.

Una métrica solo se presenta como ventaja de un plan si es el mejor con una diferencia apreciable (umbral por métrica). Así se evitan frases como «3 % frente a 3 %».

**Pendiente.** Registrar la elección o el rechazo, con su motivo.

### 5.4 Cuando no hay solución

1. **Comprobación previa**, sin optimizador: para cada tarea obligatoria, cuántos astronautas son elegibles y por qué se descarta a cada uno de los demás. Cubre la mayoría de los casos.
2. **Núcleo de conflicto:** cada grupo de restricciones se activa con un supuesto. Si el modelo es infactible, CP-SAT devuelve un subconjunto suficiente, que se reduce probando a quitar uno a uno.
3. **Salida:** el conjunto mínimo de restricciones en conflicto, en lenguaje llano, y qué decisiones no relacionadas con la seguridad podría tomar una persona (aplazar la tarea X, ampliar una ventana). El sistema no aplica ninguna.

## 6. Estructuras de datos

Dataclasses inmutables con ida y vuelta a JSON.

```
ParameterSpec    id, kind, normalization, lo, hi, validity_h, domain
Measurement      parameter, value, measured_at, source, confidence?
Baseline         parameter, mean, sd
Astronaut        id, qualifications, work, sleep, unavailable, measurements, baselines, max_work_h
Requirement      parameter, min?, max?, weight, critical
TeamQualification  qualification, mode (all | at_least), count
Task             id, name, category, kind (individual | collective), importance,
                 requirements, qualifications, team_qualifications, duration_min,
                 min_people, max_people, intensity, demanding, earliest, latest,
                 mandatory, resources, low_load (solo para desactivar)
HistoryEntry     day, astronaut, task_id, category, duration_min, intensity, demanding
SocialSnapshot   day, crew, weights (con None), status, signals, crew_drop
PlannerConfig    pesos α, β, γ, μ, ε, escala de importancia, repetición, límites, semilla
PlanningInput    day, as_of, crew, tasks, history, social
Plan             day, individual[], collective[], global, diagnostics, config_version
```

Convenciones fijadas en la Fase 2:

- Las horas del día van en «HH:MM» desde la medianoche del día planificado. Un sueño que cruza la medianoche se escribe en dos tramos (`00:00–06:00` y `22:00–24:00`).
- Los umbrales de un requisito van en la escala natural del parámetro: unidades físicas si se normaliza por rango, puntuación z si se normaliza por línea base.
- `mandatory = false` equivale a aplazable; no hay un campo aparte.
- La simultaneidad se expresa con `resources`: dos tareas que comparten un recurso no se solapan.
- La vigencia de un dato se mide desde `as_of` (por defecto, la medianoche del día). Una medición posterior a `as_of` es un error, no un dato.
- Un campo desconocido en el JSON o en el TOML es un error, para que una errata no se convierta en un valor por defecto silencioso.

Configuración en `config/default.toml` (se lee con `tomllib`, de la biblioteca estándar, y admite comentarios), con sobrescritura por variables `CP_*`. Los datos de entrada y la salida van en JSON.

Cada asignación de la salida lleva su desglose de coste, las cualificaciones satisfechas, los candidatos descartados con su motivo y la alternativa elegible más cercana con la diferencia de coste. Hay dos textos, igual que en el recomendador: una justificación con cifras para Tierra y un texto neutro para la tripulación que no menciona indicadores sociales.

## 7. Dependencias

- `ortools>=9.12,<10`: única dependencia nueva de ejecución. Hay ruedas para Python 3.12 y 3.13 en Linux y macOS ARM.
- `pytest`, ya usado en el proyecto.
- `networkx` y `numpy`, solo para el test de contrato con el analizador real.
- Python 3.12, como el resto de imágenes.

Archivos compartidos tocados en la Fase 6:

- `docker-compose.yml`: servicio `planner` con el perfil `planner`, que no arranca con `docker compose up`.
- `.env.example`: ejemplos comentados de `CP_*`.
- `.gitignore`: la carpeta de salida `volumenes/planner/`.

`sistema-de-recomendacion/api/main.py` no se ha tocado: no hay endpoint todavía.

Fuera del grafo social, `psycopg` se usa solo para leer `social_graph.daily_result` con `--social-db`.

## 8. Plan de implementación

| Fase | Contenido | Prueba de cierre |
|---|---|---|
| 2. Modelo de datos | Dataclasses, validación, JSON, configuración TOML, adaptador del grafo, historial | Ida y vuelta JSON; adaptador contra la salida real del analizador |
| 3. Costes y restricciones | Normalización, `D`, `U`, `R`, carga, elegibilidad con motivos, equipos candidatos, `K` y `A` | Propiedades: cotas en [0, 1], dato ausente nunca mejora el coste, sin cualificación nunca elegible |
| 4. Optimización | Modelo CP-SAT, tres etapas, diagnóstico, explicaciones, salida | Casos pequeños con óptimo conocido; determinismo; garantía de `ε` |
| 4b | Dos o tres planes por perfiles de pesos (hecho, sección 5.3b) | Planes distintos, válidos y comparados |
| 5. Simulación | Tripulación sintética y los ocho escenarios del enunciado, con semilla | Un test por escenario que comprueba restricciones y el comportamiento esperado |
| 6. Documentación | Este documento actualizado, README del módulo, ejemplos de ejecución | — |

Al cerrar cada fase: tests pasando, resumen corto, commits pequeños y lista de pendientes.

Estado: fases 2 a 6 terminadas, con 123 tests que pasan en local (Python 3.13) y en la imagen Docker (Python 3.12). Se ha probado de principio a fin contra el grafo real guardado en PostgreSQL por la demo `drift` del servicio social-graph.

## 9. Escenarios de validación

| Escenario | Qué debe ocurrir |
|---|---|
| Fatiga elevada | No recibe tareas con umbral crítico de fatiga; su cuota de carga baja |
| Datos incompletos | No es elegible para tareas donde el dato es crítico; en las demás, coste de incertidumbre visible |
| Tarea crítica exigente | La reciben quienes cumplen todos los umbrales, aunque rompa la rotación |
| Sin cualificación | Nunca asignado, con cualquier combinación de pesos |
| Repetición alta | Rota cuando hay alternativa de coste similar; no rota si es el único cualificado |
| Indicadores de aislamiento | Entra en una tarea colectiva de baja carga solo si cabe dentro de `ε`; nunca en una exigente por este motivo |
| Compatibilidad | Ante dos equipos de coste individual parecido, se elige el de mayor `K(G)`; con `γ = 0` la elección cambia |
| Desequilibrio de carga | El plan reduce la diferencia frente al mismo caso con `α_eq = 0` |
| Sin solución | No hay plan; se devuelve el conjunto mínimo de restricciones en conflicto |

## 10. Limitaciones

- No hay datos fisiológicos reales en el proyecto: toda la validación es con datos sintéticos, y los umbrales y pesos no están calibrados.
- Los rangos de normalización y los umbrales de cada tarea son una decisión de quien configura, no del algoritmo.
- `W̄` mide proximidad en ocio. Usarlo como predictor del rendimiento de un equipo es una hipótesis no validada.
- Favorecer equipos que ya se relacionan tiende a reforzar los grupos existentes; la inclusión en tareas de baja carga es el contrapeso.
- El descanso entre el final de un día y el inicio del siguiente solo se garantiza a través del bloque de sueño.
- Todos los miembros de un equipo trabajan a la vez y durante toda la tarea.
- Asignar tareas colectivas cambia el tiempo que las personas pasan juntas, pero el grafo solo mide ocio: el planificador no verá el efecto directo de sus propias decisiones.

## 11. Decisiones pendientes

- **`README.md.2.0.` (develop):** dice que el grafo no se usa para repartir tareas. Hay que acordar el cambio con el equipo.
- **Valores por defecto** de `γ`, `μ`, `ε` y de los umbrales de baja carga: puntos de partida, a revisar con los escenarios de la Fase 5.

**Rama.** `feature/planificador` sale de `feature/grafos`, que aún no está integrada en `develop` (33 commits por delante). Al integrarse, el planificador arrastra el grafo.
