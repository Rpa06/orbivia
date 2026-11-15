# Vector de Estado Colapsado, avisos y nota de disponibilidad

Implementación: `procesamiento/colapso/` (vector, Welford, ventanas), `sistema-de-recomendacion/motor/` (avisos, nota, acciones, colapso diario y planes).

## Formato

- 20 valores `float32` little-endian = **80 bytes exactos** (`CHECK (octet_length(vector) = 80)` en `biometrics.daily_vector`).
- Metadatos fuera del vector: `astronaut_id`, `cycle_date`, `schema_version` (1), `missing_mask` (bit *i* = campo *i* ausente) y `simulated_mask` (bit *i* = valor del simulador).
- Ausente = `NaN`. En la columna `embedding vector(20)` (para C4) los ausentes cuentan como 0.
- Cada campo es una puntuación z frente a la línea base individual. Durante la fase operativa se usa la de adaptación, si existe para esa variable. La terrestre queda siempre como referencia.

| # | Campo | Fuente | Dirección | Área | Vigencia |
|---|---|---|---|---|---|
| 0 | sleep_duration_z | sueño estimado (h) | + | Fatiga y sueño | 24 h |
| 1 | pvt_rt_z | PVT-B, tiempo medio | − | Fatiga y sueño | 24 h |
| 2 | self_perception_gap | z(PVT-B) − z(cansancio declarado) | − | Fatiga y sueño | 24 h |
| 3-7 | checkin_{sleep,fatigue,workload,mood,cohesion}_z | check-in 1-5 | +, −, −, +, + | F/S, F/S, F/S, Psic., Social | 24 h |
| 8 | grip_strength_z | PING diario | + | Médico | 24 h |
| 9 | spo2_z | PING diario | + | Médico | 24 h |
| 10 | sleep_heart_rate_z | FC nocturna | − | Médico | 24 h |
| 11 | sleep_hrv_z | VFC nocturna | + | Médico | 24 h |
| 12 | social_centrality_z | intensidad en el grafo de ocio | + | Social | 24 h |
| 13 | circadian_desync_z | distancia del punto medio del sueño a la mediana | − | Social | 24 h |
| 14-17 | nlp_{neutral,low_mood,anxiety,stable}_z | confianza del modelo de texto, frente a la línea base de cada pregunta | +, −, −, + | Psicológico | intervalo de entrevista (3 días) |
| 18 | acoustic_f0_z | eGeMAPS F0 media | bilateral | Psicológico | 3 días |
| 19 | acoustic_pause_z | eGeMAPS duración media de pausas | − | Psicológico | 3 días |

**Agregaciones decididas.** No se combinan variables físicas distintas en un mismo campo. Las variables que no caben en los 20 campos se guardan en `biometrics.measurements` y no se pierden: peso, radiación, temperatura, tensión, luz, capacidad pulmonar, PANAS/POMS, PSQI, TCI, EEG y glóbulos rojos.

**Forward-fill.** Las variables diarias y de sueño solo valen en su ciclo de 24 h. Las semanales se arrastran como máximo 7 días; después, `protocol_warning`. La entrevista vale durante su intervalo.

**Welford.** Hay un acumulador por astronauta y variable (`biometrics.welford_state`). Un ciclo ya contado no se vuelve a contar (`last_date`), así que re-ejecutar el colapso de un día no mezcla ciclos.

## Avisos (README §2.B)

| | Regla implementada |
|---|---|
| C1 | Campo crítico con empeoramiento > 2σ tres días seguidos. |
| C2 | Pendiente de empeoramiento en 14 días (≥ 0,08σ/día, ≥ 10 puntos) o en 30 días (≥ 0,04σ/día, ≥ 20 puntos). Además: t de la pendiente ≥ 2,5, positiva en ambas mitades de la ventana y media de los últimos 7 días ≥ 0,5σ. |
| C3 | ≥ 3 campos de ≥ 2 áreas con empeoramiento medio en 3 días entre 1σ y 2σ. |
| C4 | Preparado (`motor.alerts.c4_query`, índice HNSW coseno) y desactivado (`ENABLE_HISTORICAL_VECTOR_MATCH=false`). Si se activa, informa `insufficient_history`: no hay histórico etiquetado de otras misiones y no se simula. |

Durante los días de adaptación los avisos se registran como suprimidos.

Los umbrales extra de C2 y C3 son una decisión propia, no del README. Con 20 campos con ruido, la regla literal ("tres señales por encima de 1σ el mismo día") se cumple casi a diario por azar. Lo comprueba `test_noise_rarely_alerts`.

## Nota de disponibilidad (0-100)

1. *s* = empeoramiento del campo en σ, en su dirección mala.
2. *p(s)* = max(0, s) + 1,5 · max(0, s − 1,5). Por encima de 1,5σ cada σ pesa 2,5 veces más.
3. Peso 1. Los campos de autoinforme pesan 0,5 si `baseline_profile.social_desirability_high`.
4. Con "motivo conocido" en el check-in del día, las caídas de los campos de autoinforme no penalizan. Los objetivos no cambian.
5. Área = max(0, 100 − 25 · media ponderada de *p*). Nota = media de las áreas con datos.
6. El comandante solo ve el motivo general: fatiga, aislamiento, carga o seguimiento médico. Médico y psicológico se agrupan como "seguimiento médico".

El desglose campo a campo se guarda en `biometrics.availability.audit` y el médico lo ve en su vista.
