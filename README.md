# Orbivia

Sistema de monitorización biométrica, psicológica y social y de apoyo a la decisión para tripulaciones en misiones espaciales, cortas y largas. Detecta de forma temprana desviaciones respecto a la línea base de cada astronauta, mediante la consolidación diaria de señales multimodales en un Vector de Estado Colapsado, y propone repartos de tareas que la tripulación elige.

Orbivia no diagnostica ni trata enfermedades. Su finalidad es operativa, ayudar a decidir quién está en condiciones de hacer cada tarea. Toda decisión final la toma una persona.

**NASA Space Apps Challenge 2026, Valencia.** Reto "Create Health Monitoring Software for Astronauts on Space Missions".

## 0. Por qué Orbivia. Fundamento NASA

### El problema

El reto pide a los astronautas que vigilen su propia salud. NASA identifica seis límites a esa autovigilancia.

1. **Detección tardía de problemas psicológicos.** Según NASA, los problemas cognitivos o de conducta pueden derivar en trastornos mentales si no se detectan ni se mitigan a tiempo.
2. **Falta de sueño y sobrecarga de trabajo.** NASA documenta que las tripulaciones duermen unas 6 horas por noche en vuelo y que hay sobrecarga de trabajo y problemas de planificación, factores que aumentan los errores y reducen el rendimiento.
3. **Necesidad de sistemas de vigilancia a bordo.** En su hueco de investigación Sleep-102, NASA pide herramientas de planificación integradas e individualizadas y sistemas a bordo para vigilar y prevenir la falta de sueño crónica y la sobrecarga de trabajo.
4. **Límites de la autopercepción.** Algunos estados afectan justo a la capacidad de darse cuenta de ellos. En un estudio de laboratorio (Van Dongen et al., 2003, archivado en el repositorio técnico de NASA), quienes dormían 6 horas durante dos semanas acababan con la atención como tras una noche entera sin dormir, y apenas notaban el deterioro. A ello se suma el sesgo de deseabilidad social, que tiene cualquier persona.
5. **Ausencia de datos sobre el funcionamiento del equipo.** NASA reconoce que faltan datos de vuelo para cuantificar el efecto de las variables de equipo, y su informe de evidencia recoge que habrá conflicto en todas las misiones, por lo que la clave es prevenirlo y predecirlo.
6. **Autonomía médica lejos de la Tierra.** NASA solo dará por aceptado el riesgo médico en misiones lejanas cuando tenga mucha confianza en un sistema médico capaz de funcionar de forma autónoma.

### Los riesgos que vigilamos

Orbivia agrupa lo que mide en cuatro áreas, que coinciden con cuatro riesgos que NASA gestiona por separado en su Programa de Investigación Humana. NASA clasifica cada riesgo en tres colores. Verde es "aceptado", amarillo es "aceptado con vigilancia" y rojo es "requiere mitigación".

| Tipo de misión | Médico | Fatiga y sueño | Psicológico | Social y de equipo |
|---|---|---|---|---|
| Viaje corto al espacio profundo, 1 mes | Verde | Verde | Amarillo | Amarillo |
| Estación Espacial, 6 meses | Verde | Verde | Amarillo | Amarillo |
| Estación Espacial, 1 año | Verde | Verde | Rojo | Amarillo |
| Visita a la Luna | Rojo | Verde | Rojo | Amarillo |
| Espacio profundo, 1 año | Rojo | Rojo | Rojo | Rojo |
| Marte, 3 años | Rojo | Rojo | Rojo | Rojo |

Fuente, las fichas oficiales de riesgo del Human Research Roadmap de NASA (consultadas el 14 de noviembre de 2026). Las tablas se aprobaron en fechas distintas (fatiga en agosto de 2019, equipo en agosto de 2015, médico y psicológico sin fecha publicada).

Dos lecturas importan. En misiones cortas, NASA solo acepta los riesgos psicológicos y de equipo si alguien los vigila, y eso es lo que hace Orbivia. Y cuanto más larga y lejana es la misión, más riesgos pasan a rojo, hasta que en Marte lo son los cuatro.

### Origen de los datos que usa el sistema

El catálogo de tareas, sus requisitos y los límites de carga salen de documentos técnicos de NASA. Cada umbral del sistema indica su fuente en la interfaz.

- **Límites de carga.** NASA-STD-3001 considera sobrecarga crítica las jornadas de 10 horas tres días por semana o más de 60 horas semanales.
- **Tests.** PVT-B y batería Cognition, ambos usados por NASA en vuelo y en análogos.
- **Planificación.** Inspirada en Playbook, la herramienta de autoplanificación de tripulaciones de NASA Ames.
- **Tripulación simulada.** Los datos de la demo son simulados y se calibran con los valores que NASA publica para vuelo (por ejemplo, unas 6 horas de sueño por noche).

## 1. Contexto y lógica operativa

El sistema compara a cada astronauta consigo mismo, nunca con una media de población. Para ello trabaja con dos líneas base.

**Línea base terrestre (6 meses previos a la misión).** Seguimiento continuo asumiendo un estado saludable. Al terminar, el sistema calcula y congela los parámetros estadísticos individuales (media, desviación estándar y percentiles) de cada variable. Este perfil fijo evita que un deterioro lento y progresivo desplace los umbrales de normalidad (concept drift).

**Línea base de adaptación (primeros días de misión).** En microgravedad varias variables cambian de forma esperable. Para no disparar alertas en todos los astronautas nada más despegar, las variables diarias afectadas se comparan contra una segunda línea base calculada con los primeros días de misión. Es un parámetro configurable según la duración de la misión. Por defecto son 10 días en misiones largas y 2 o 3 días en misiones cortas, y en misiones muy cortas se puede usar solo la línea base terrestre. La línea base terrestre se mantiene siempre como referencia de largo plazo.

**Fase operativa.** En cada ciclo diario, todas las fuentes se normalizan contra la línea base que corresponda (Z-scores) y se evalúan junto con tendencias móviles (7 y 30 días) y acumuladores incrementales (algoritmo de Welford) sobre el histórico. Ante desviaciones relevantes, el motor genera avisos y propone acciones y repartos de tareas.

### Privacidad y protección de datos

**Base jurídica.** Artículo 9.2.h del RGPD (medicina preventiva o laboral y evaluación de la capacidad para trabajar). No se usa el consentimiento como base, porque en el contexto laboral existe un desequilibrio claro entre el astronauta y la agencia (considerando 43 del RGPD).

**Uso del historial para investigación.** El análisis longitudinal que hace el equipo médico en Tierra para seguir a cada astronauta entra en la misma base. Si los datos se usan además para investigación, es una finalidad distinta (principio de limitación de la finalidad, artículo 5.1.b del RGPD), que se apoya en el artículo 9.2.j (investigación científica) con las garantías del artículo 89.

**Seudonimización, no anonimización.** Los datos fisiológicos y psicológicos se almacenan separados de la identidad real (esquemas aislados vault_identity y biometrics). Esto es seudonimización. Según el considerando 26 del RGPD, los datos seudonimizados siguen siendo datos personales, y en una tripulación pequeña cualquier persona es fácilmente identificable por singularización. Por eso la protección real se basa en el acceso por rol, no en el anonimato.

**Minimización y acceso por rol (artículo 5.1.c del RGPD).** Cada rol ve solo lo que necesita para su función (ver sección 2.F).

**Privacidad desde el diseño (artículo 25 del RGPD).** El audio y las imágenes de vídeo nunca se almacenan en disco ni en base de datos y nunca se envían a Tierra. Se procesan al vuelo en memoria, se purgan y solo se conservan los valores numéricos resultantes.

**Inferencia de estados psicológicos.** El análisis de texto y voz solo se usa con fines médicos y su resultado solo lo ven el médico de a bordo y el equipo médico en Tierra, dentro de la excepción médica del artículo 5.1.f del Reglamento Europeo de Inteligencia Artificial (prohibición en vigor desde el 2 de febrero de 2025). El vídeo no se usa para inferir emociones, solo para detectar signos físicos de fatiga.

**Obligaciones de alto riesgo de la Ley de IA.** *(Referencia pendiente de verificación.)* Tras el Reglamento (UE) 2026/1744 (Digital Omnibus), las obligaciones para los sistemas de alto riesgo del anexo III se aplican desde el 2 de diciembre de 2027. Orbivia las tiene en cuenta desde el diseño (supervisión humana, registro de decisiones, explicaciones).

**Producto sanitario.** *(Referencia pendiente de verificación.)* Según la sentencia del TJUE de 2 de julio de 2026 (C-427/24, Diagramm Halbach), un software es producto sanitario cuando procesa datos del paciente y genera recomendaciones con finalidad médica. Orbivia genera repartos de tareas con finalidad operativa y no da recomendaciones clínicas. Lo clínico lo deciden el médico de a bordo y el equipo médico en Tierra.

**Supervisión humana (artículo 22 del RGPD).** Orbivia propone varias opciones y la tripulación decide. Ninguna decisión con efectos sobre un astronauta se toma de forma exclusivamente automatizada.

## 2. Lógica de negocio y reglas de operación

### A. Sincronización de granularidad (forward-fill controlado)

Las variables tienen distintas frecuencias de captura (línea base, semanales, diarias y continuas nocturnas). El motor de colapso diario aplica una ventana de vigencia para construir el vector de estado.

- **Variables semanales.** Se arrastran hacia adelante (forward-fill) durante un máximo de 7 días hasta la siguiente medición. Si se superan los 7 días sin registro, se marca un aviso de incumplimiento de protocolo.
- **Variables diarias y de sueño.** Deben registrarse en el ciclo de 24 horas correspondiente.
- **Variables de línea base.** Se miden una vez y no se arrastran, solo sirven de referencia.

### B. Evaluación multicriterio de avisos

Un aviso nunca se dispara por un único dato aislado. Hay tres mecanismos activos y uno futuro.

- **Desviación aguda.** Una variable relevante supera ±2σ respecto a la línea base del astronauta durante 3 días seguidos.
- **Deterioro progresivo.** La pendiente móvil (rolling_slope a 14 o 30 días) muestra una tendencia negativa sostenida, aunque el valor diario aún no cruce el umbral.
- **Combinación de señales.** Varias señales empeoran a la vez, aunque ninguna por separado cruce el umbral (por ejemplo, sueño, ánimo y aislamiento).
- **Similitud con estados anteriores (función futura).** Comparación del vector del día contra el histórico por distancia coseno (pgvector) para detectar patrones que en el pasado precedieron a un problema. Requiere historial de varias misiones, por lo que no está activa en una misión nueva.

### C. Capa conductual

- **Check-in diario.** Cinco preguntas de 1 a 5 (sueño, cansancio, carga de trabajo, ánimo y convivencia), siempre a la misma hora.
- **PVT-B diario.** Test de atención de 3 minutos, justo después del check-in, para que el astronauta no conozca su resultado al responder.
- **Brecha de autopercepción.** Diferencia entre el cansancio que declara el astronauta en el check-in y el que mide el PVT-B, ambos expresados como desviación respecto a su línea base. Si el astronauta dice estar bien y su rendimiento empeora, se genera un aviso. Se basa en la evidencia de que las personas con falta de sueño apenas perciben su propio deterioro (Van Dongen et al., 2003).
- **Pregunta doble semanal.** La pregunta de convivencia se acompaña de una segunda, "¿qué nota crees que pondrá de media el resto del equipo?". La diferencia entre lo que cada uno cree y lo que el grupo responde es una señal de desconexión. Método inspirado en el Bayesian Truth Serum (Prelec, 2004), sin incentivo económico. Las respuestas individuales nunca se muestran al resto de la tripulación.
- **Entrevista de audio cada 3 días.** Preguntas abiertas y neutras que rotan. No preguntan por emociones ni usan palabras negativas, para no inducir respuestas negativas. Cada pregunta tiene su propia línea base. Las preguntas son las siguientes.
    1. ¿Cómo describirías tu día de ayer?
    2. ¿En qué has estado pensando estos días?
    3. ¿Qué has hecho en tus ratos libres?
    4. ¿Cómo describirías el ambiente en la nave esta semana?
    5. ¿Qué tienes previsto para los próximos días?
    6. Cuéntame cómo fue tu última conversación larga con alguien del equipo.
    7. ¿Cómo ha ido tu trabajo esta semana?
    8. ¿Qué has notado distinto en ti desde que empezó la misión?
- **Ejercicio.** Se registra cada día. Si un astronauta lo omite dos días seguidos, se le propone formular un plan del tipo "si pasa X, haré Y" (intención de implementación, Gollwitzer y Sheeran, 2006). El texto del plan solo lo ve el astronauta.
- **Personalidad y deseabilidad social.** Se miden una vez en la línea base. No entran en la nota de disponibilidad ni en el reparto de tareas. La deseabilidad social no mide si alguien miente, sino cuánto tiende cualquier persona a dar una imagen positiva de sí misma. Se usa para dar más peso a los datos objetivos frente al autoinforme cuando la puntuación es alta (por defecto, el autoinforme pesa la mitad cuando la fiabilidad es baja).
- **Registro privado del ciclo menstrual (opcional).** Ver sección 2.G.

### Cómo se interpretan las puntuaciones del modelo de texto

El modelo de texto devuelve cuatro números entre 0 y 1 (neutral, depresión, ansiedad y estable). Son la confianza del clasificador, no la gravedad, y no equivalen a escalas clínicas como el PHQ-9 o el GAD-7. Por eso no se interpretan en valor absoluto. Se comparan contra la línea base de cada astronauta y de cada pregunta. En la interfaz la etiqueta "depresión" se muestra como "ánimo bajo". Si el equipo médico lo considera necesario, aplica una escala clínica validada. **En esta versión el modelo de texto está desactivado por defecto** (`ENABLE_NLP=false`, ver §7).

### D. Dinámica social y aviso de aislamiento

- **Desincronización circadiana.** Se compara la ventana de sueño del astronauta con la mediana del grupo. Si desplaza repetidamente su descanso (no duerme cuando los demás), aumenta su índice de desincronización.
- **Aislamiento en tiempo de ocio.** En las franjas de tiempo libre se mide la proximidad con el resto de la tripulación. Una caída sostenida de la centralidad en el grafo o un aumento del tiempo aislado genera un aviso al médico de a bordo.
- **Uso del grafo.** El grafo social se almacena y solo se muestra a misión ante una incidencia. No se usa para repartir tareas ni para separar a miembros de la tripulación.

### E. Motor de recomendación

Tiene dos partes.

**1. Acciones recomendadas.** Cada combinación de avisos activos se asocia a un catálogo de acciones (ajustes de carga, pautas de exposición a la luz, ejercicios de recuperación o seguimiento con el médico). Si una acción ya está activa para un aviso, no se repite la notificación en días consecutivos mientras la tendencia se estabilice o mejore (cooldown).

**2. Reparto de tareas.** Solo se reparten tareas comunes y de mantenimiento, no la investigación propia de cada especialista.

- **Restricciones fijas.** Capacidad de cada astronauta para cada categoría, nota mínima por tarea, ejercicio diario fijo, horas máximas de trabajo según NASA-STD-3001, respeto del descanso y número de personas por tarea.
- **Objetivos.** Seguridad en las tareas de riesgo, encaje con el tipo de cansancio, equilibrio de carga (evitando tanto la sobrecarga como la falta de trabajo), rotación y mínimo cambio respecto al plan original.
- **Salida.** Cada mañana, tres planes distintos, cada uno con sus ventajas y con una explicación en lenguaje natural de cada cambio. La tripulación elige uno o los rechaza indicando el motivo. Si un astronauta pide otro plan por un motivo propio, en el registro solo consta "motivo personal".
- **Registro de decisiones.** Se guarda qué plan se eligió o si se rechazaron todos, para medir si la tripulación confía demasiado o demasiado poco en el sistema.
- **Método.** Optimización con reglas explicables, sin modelo entrenado, porque no existen datos reales de astronautas en vuelo para entrenarlo. Inspirado en Playbook, la herramienta de autoplanificación de tripulaciones de NASA Ames.

**3. Funciones futuras del reparto.** (Por cerrar)

- **Cuándo, además de quién.** Proponer la franja horaria en la que cada astronauta rinde mejor según su sueño y su PVT-B. Responde directamente al hueco Sleep-102 de NASA.
- **Parejas compatibles.** Para tareas de dos personas, como las salidas al exterior, emparejar a quienes tienen el sueño sincronizado. Usa solo datos de sueño, nunca el grafo social.
- **Horizonte semanal.** Repartir mirando también los días siguientes, para que nadie acumule cansancio, y mostrar cómo quedaría la carga de cada uno al final de la semana.

### F. Visibilidad por rol

| Rol | Qué ve |
|---|---|
| Astronauta | Sus propios datos, sus tareas, los planes propuestos, su plan de ejercicio y, si lo activa, su registro del ciclo y sus avisos. No ve datos de otros astronautas. |
| Médico de a bordo | El estado actual y los avisos de todos los astronautas, incluidas las puntuaciones de check-in, voz y texto. El registro del ciclo solo si la astronauta lo comparte. |
| Comandante | La nota de disponibilidad de cada astronauta y el motivo general (fatiga, aislamiento, carga). Nunca las respuestas del check-in, los datos psicológicos ni el ciclo. Si alguien cambia de plan por un motivo propio, solo ve "motivo personal". |
| Equipo médico en Tierra | El historial completo de valores de cada astronauta, para seguir su evolución semana a semana. Nunca audio, vídeo ni el registro del ciclo. |
| Resto de la misión en Tierra | El estado agregado de avisos y, solo ante una incidencia, el grafo de cohesión del grupo. Nunca el registro del ciclo. |

### G. Registro privado del ciclo menstrual

Registro opcional que solo ve la astronauta. Nunca entra en la nota de disponibilidad, en los avisos de los demás roles ni en el reparto de tareas. El motor de nota y el planificador no tienen acceso técnico a este dato. Se procesa en un módulo privado de su vista.

- **Por qué no se usa para repartir.** Un metaanálisis de 2025 (Jang, Zhang y Elfenbein, PLOS One, 102 artículos y 3.943 participantes) no encontró diferencias sólidas de rendimiento cognitivo entre las fases del ciclo. La revisión de NASA y el NSBRI de 2014 sobre sexo y adaptación al espacio tampoco encontró diferencias por sexo en las respuestas conductuales o psicológicas al vuelo. Usarlo para repartir sería discriminar sin pruebas.
- **Aviso individualizado.** A partir de su propio registro, el módulo privado detecta los síntomas que ella suele tener en cada fase (dolor, sueño, ánimo) y le avisa solo a ella, para que sea consciente y lo tenga en cuenta al elegir entre los tres planes propuestos.
- **Otros usos.** Permite registrar sangrados inesperados si suprime la regla con la píldora continua, algo habitual en misiones largas (Jain y Wotring, 2016), y compartirlo con el médico de a bordo si quiere.
- **Motivo conocido.** Si un día de síntomas baja su check-in, puede marcarlo como "motivo conocido" en su vista. La nota de disponibilidad no cambia.
- **Base legal.** Dato de salud del artículo 9.1 del RGPD. Es opcional, se puede borrar, no se agrega ni se envía a Tierra (en una tripulación de cuatro identificaría a la persona, considerando 26).

## 3. Flujo de datos y variables monitorizadas

**Línea base (una vez, antes de la misión).**

- Densidad ósea por DXA en tierra, solo como referencia (no se mide a bordo).
- Personalidad, cuestionario BFI-2-XS.
- Deseabilidad social, escala de deseabilidad social de Marlowe-Crowne (versión española).
- Rendimiento cognitivo, batería Cognition de NASA.

**Mediciones semanales.**

- Capacidad pulmonar.
- Estado de ánimo, PANAS o POMS.
- Pregunta doble de convivencia.
- Otras variables pendientes de confirmar que se pueden medir a bordo.

**Mediciones mensuales.**

- Calidad del sueño, PSQI.
- Clima de equipo, Team Climate Inventory.

**PING diario.**

- Fuerza de agarre (grip).
- Peso, si se puede medir a bordo.
- Latencia en el PVT-B.
- Oxigenación.
- Check-in de 5 preguntas.
- Horas de trabajo reales frente a planificadas.
- Ejercicio realizado.
- Dosis de radiación acumulada.
- Glóbulos rojos, pendiente de confirmar que se puede medir a bordo.

**Streaming continuo durante el sueño.**

- Ritmo circadiano, calidad del sueño, ritmo cardíaco, exposición a la luz, temperatura corporal y tensión arterial.
- EEG por bandas, pendiente de confirmar que se puede medir a bordo.

**Evaluación psicológica (depende la longitud de la mision aumneta la frecuencia si la mision es mas corta)..**

- Audio de las respuestas abiertas, con extracción acústica mediante openSMILE.
- Texto transcrito, con análisis de lenguaje que devuelve cuatro puntuaciones (neutral, ánimo bajo, ansiedad y estable), interpretadas contra la línea base de cada pregunta.
- Vídeo, solo para signos físicos de fatiga (ojos cerrados, parpadeo lento). No se infieren emociones.

**Dinámica social.**

- Eventos de proximidad seudonimizados en tiempo de ocio, métricas diarias de centralidad, aislamiento y desincronización circadiana.

**Registro opcional.**

- Ciclo menstrual y síntomas, solo en la vista de la astronauta (sección 2.G).

### Almacenamiento y envío a Tierra

| Dónde | Qué se guarda | Para qué |
|---|---|---|
| Al capturar | Nada. El audio y el vídeo se procesan en memoria y se purgan | Privacidad desde el diseño |
| A bordo | Medias, desviaciones típicas y recuentos de cada variable (algoritmo de Welford), puntuaciones Z del día y tendencias | Analizar cada mañana y proponer los planes sin depender de la Tierra |
| Tierra, equipo médico | Historial completo de vectores diarios, incluidas las características acústicas y las puntuaciones del modelo de texto, no la transcripción | Seguir la evolución semana a semana y comparar tendencias |
| No sale nunca de la nave | Audio, vídeo, transcripciones y registro del ciclo menstrual | Minimización de datos |

El vector diario colapsado de cada astronauta ocupa del orden de decenas de bytes (estimación propia, unos 80 bytes). Para una tripulación de cuatro en una misión a Marte de unos 900 días, el historial completo son menos de 300 KB, así que enviarlo entero a Tierra es viable incluso con poco ancho de banda. El perfil de línea base (personalidad y deseabilidad social) se guarda una sola vez por astronauta.

---

## 4. Arquitectura desplegada

```
 sensores ──► broker (Redis Streams, AOF) ──► worker-stream ──┐  sueño + colapso diario programado
 navegador ─► frontend (Nginx) ─► api (FastAPI, RBAC) ────────┼──► db (PostgreSQL 16 + pgvector)
                                    │                         │      vault_identity · biometrics
                                    └─► media-broker (Redis   │      private_cycle · operations
                                        solo RAM, MAXLEN 10) ─► worker-ml (openSMILE, vídeo, NLP opcional)
 db ──► sync-tierra ══ red enlace-tierra ══► earth-receiver (Tierra simulada)
```

| Servicio | Imagen | Rol de BD | Qué hace |
|---|---|---|---|
| `db` | pgvector/pgvector:pg16 | administrador | Esquemas separados y roles (`base-de-datos/init`) |
| `broker` | redis:7-alpine | — | Streams de sueño, caché de ventanas 7/14/30 y de cooldown |
| `media-broker` | redis:7-alpine | — | Stream multimedia efímero, sin persistencia, en tmpfs |
| `api` | python-core | api / engine / cycle | REST, autenticación, RBAC, ingesta, planes, ciclo privado |
| `worker-stream` | python-core | engine | Sueño (`sleep_stream`) y colapso diario a `DAILY_COLLAPSE_HOUR` |
| `worker-ml` | python-ml (4 GB, 2 CPU) | engine | Audio y vídeo en memoria |
| `sync-tierra` | python-core | sync | Envío de vectores con lista blanca cuando hay enlace |
| `earth-receiver` | python-core | — | Receptor simulado en Tierra (solo red `enlace-tierra`) |
| `frontend` | nginx:alpine | — | Interfaz; proxy `/api/` → `http://api:8000` |
| `seed` (perfil `tools`) | python-core | administrador | Misión simulada |
| `social-graph` (perfil `social`) | social-graph | engine | Grafo social en vivo; su reloj simulado no coincide con la misión sembrada |
| `planner` (perfil `planner`) | planner | — | Planificador como herramienta de línea de comandos |

Más detalle: [docs/vector_estado_colapsado.md](docs/vector_estado_colapsado.md) (vector, avisos y nota) y [docs/privacidad_y_alcance.md](docs/privacidad_y_alcance.md) (garantías, alcance del NLP y afirmaciones por verificar).

## 5. Estructura del repositorio

```text
orbivia/
├── base-de-datos/init/            # Extensiones, esquemas, tablas y roles de privilegio mínimo
├── docker/                        # Dockerfiles (python-core, python-ml, frontend, planner, social-graph, sleep-stream)
├── docs/                          # Diseño de cada módulo, vector, privacidad
├── frontend/                      # Interfaz sin framework, servida por Nginx
│   ├── assets/                    # Arranque, sesión, vistas por rol, estilos
│   ├── check-in/                  # Check-in diario, PVT-B, pregunta doble semanal y ejercicio
│   ├── eleccion-de-planes/        # Vista de los 3 planes, elección y registro de rechazos
│   ├── muestra-de-recomendaciones/# Acciones recomendadas y tareas del astronauta
│   ├── obtencion-de-audio/        # Entrevista de audio y vídeo opcional de fatiga
│   ├── registro-personal/         # Registro privado del ciclo y avisos, solo para la astronauta
│   └── visualizacion-de-grafos-solo-mision/  # Grafo de cohesión, solo misión y ante incidencia
├── procesamiento/
│   ├── audio/raw-audio/           # Prototipo de escritorio original (no se despliega; ver §7)
│   ├── colapso/                   # Vector de 20 float32, Welford, ventanas, forward-fill
│   ├── conductual/                # Check-in, PVT-B, brecha de autopercepción, entrevista, ejercicio, pregunta doble
│   ├── grafos/                    # Grafo social de ocio (solo vigilancia)
│   ├── streaming-valores-continuos-sueno/  # Sueño sobre Redis Streams
│   ├── test-cerrado/              # Modelo y validación del check-in (reutilizado por conductual)
│   ├── texto/                     # Transcripción faster-whisper int8 y clasificador de texto
│   └── video/                     # Signos físicos de fatiga (MediaPipe + ONNX), también desde memoria
├── simulador/seed_mission.py      # Misión simulada y reproducible
├── sistema-de-recomendacion/
│   ├── api/                       # FastAPI: auth, RBAC, ingesta, vistas, planes, ciclo
│   ├── motor/                     # Avisos C1-C4, nota, acciones con cooldown, colapso diario, puente al planificador
│   └── planificador/              # Optimizador CP-SAT determinista (sin grafo social) y catálogo de tareas
├── sync-tierra/                   # Sincronización con Tierra y receptor simulado
├── tests/integration/             # Pruebas contra el despliegue en marcha
└── workers/                       # worker-ml (multimedia) y worker-stream (sueño + colapso)
```

## 6. Despliegue y demo

1. `cp .env.example .env` y cambia todas las claves. Los secretos necesitan al menos 32 caracteres. Si `volumenes/postgre` ya tiene una base inicializada sin estos esquemas, usa otro `POSTGRES_DATA_DIR`: los scripts de init solo corren sobre un directorio vacío.
2. Arranca:

```bash
docker compose up -d --build
```

3. Siembra la misión simulada. Imprime las credenciales de demo una sola vez y las guarda en `volumenes/demo/credenciales.txt`:

```bash
docker compose run --rm seed
```

4. Abre http://127.0.0.1:8080. Usuarios: `astro1`…`astro4` (astronautas A1-A4), `surgeon`, `commander`, `earth.medical` y `earth.mission`.

Guion de demo:

- **Médico** (`surgeon`): avisos con su referencia, auditoría de la nota, acústica (NLP desactivado), historial y ciclo compartido.
- **Comandante** (`commander`): solo nota y motivo general. Botón «Ejecutar colapso diario» (`POST /api/v1/ops/trigger-daily-collapse`). Elegir un plan.
- **Astronauta** `astro3`: hacer el check-in y el PVT-B (con `?pvt30` en la URL dura 30 s). Volver a ejecutar el colapso y ver la brecha de autopercepción (C1).
- **Astronauta** `astro4`: registro privado del ciclo, aviso individual, compartir 24 h con el médico.
- **Astronauta** `astro1`: dos omisiones de ejercicio, asistente «si pasa X, haré Y», entrevista de audio.
- **Tierra**: `earth.medical` ve el historial de vectores; `earth.mission`, solo agregados.
- **Sincronización**: `volumenes/tierra/received.jsonl` contiene lo recibido en Tierra.

Tests:

```bash
python -m pytest procesamiento/colapso procesamiento/conductual sistema-de-recomendacion/motor sync-tierra
```

```bash
python -m pytest tests/integration
```

Cada módulo tiene además su propia suite (`pytest` dentro de su carpeta: planificador, grafos, sueño, test-cerrado, texto).

## 7. Estado real y limitaciones

- **Datos simulados.** No hay mediciones de astronautas ni datos de NASA. Umbrales y pesos sin calibrar.
- **NLP desactivado por defecto** (`ENABLE_NLP=false`). Ver la tensión con el Reglamento de IA en [docs/privacidad_y_alcance.md](docs/privacidad_y_alcance.md). Activarlo descarga los modelos de Hugging Face, así que necesita red.
- **C4** (similitud histórica) está preparado y desactivado: no hay histórico etiquetado.
- **Planificador.** Se eliminaron los objetivos que usaban el grafo social. La mínima perturbación se mide (cambios frente al plan de referencia), pero no es un término del optimizador. Si nadie puede hacer una actividad planificada no recurrente, se proponen los planes con esa actividad aplazada y la tripulación decide. El mantenimiento y la seguridad recurrentes nunca se aplazan solos. Franja óptima, parejas de EVA y proyección a 7 días son interfaces sin implementar (`motor/planning.py`).
- **Investigación especializada.** El catálogo no trae el responsable de cada experimento. Se asigna uno fijo y estable entre los cualificados, que nunca se reasigna.
- **`procesamiento/audio/raw-audio/codigo_voces.py`** se conserva como prototipo, pero no se despliega: graba en disco, guarda transcripciones y usa etiquetas clínicas (PHQ-9, GAD-7). De él se reutiliza el enfoque openSMILE eGeMAPS en memoria.
- **Grafo social en vivo** opcional (perfil `social`). En la demo, la centralidad sale del simulador.
- **Línea base de adaptación.** Con 2-3 días la desviación se toma como la mayor entre la de adaptación y la terrestre.
- Las referencias jurídicas de §1 están **pendientes de verificación** (ver docs).

## Fuentes

- [NASA Human Research Roadmap, riesgo médico](https://humanresearchroadmap.nasa.gov/Risks/risk.aspx?i=95)
- [NASA Human Research Roadmap, riesgo de sueño y fatiga](https://humanresearchroadmap.nasa.gov/Risks/risk.aspx?i=100)
- [NASA Human Research Roadmap, hueco Sleep-102](https://humanresearchroadmap.nasa.gov/Gaps/gap.aspx?i=401)
- [NASA Human Research Roadmap, riesgo psicológico](https://humanresearchroadmap.nasa.gov/Risks/risk.aspx?i=99)
- [NASA Human Research Roadmap, riesgo de equipo](https://humanresearchroadmap.nasa.gov/Risks/risk.aspx?i=101)
- [NASA, informe de evidencia de salud conductual](https://humanresearchroadmap.nasa.gov/evidence/other/BMed.pdf)
- [NASA, informe de evidencia del riesgo de equipo (2022)](https://ntrs.nasa.gov/api/citations/20220007465/downloads/Evidence%20Report%20-%20Team%202022%20FINAL4PUB%20rev%201.docx.pdf)
- [Van Dongen et al. 2003, Sleep, ficha en el repositorio técnico de NASA](https://ntrs.nasa.gov/citations/20040087752)
- [National Academies, Safe Passage (2001)](https://www.nationalacademies.org/read/10218/chapter/8)
- [Jang, Zhang y Elfenbein 2025, PLOS One](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0318576)
- [Leon et al. 2014, Effects of Sex and Gender on Adaptation to Space: Behavioral Health](https://pmc.ncbi.nlm.nih.gov/articles/PMC4235984)
- [Jain y Wotring 2016, npj Microgravity](https://pmc.ncbi.nlm.nih.gov/articles/PMC5516549)
- [Reglamento General de Protección de Datos](https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32016R0679)
- [Reglamento de Inteligencia Artificial](https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32024R1689)
