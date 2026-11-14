# Orbivia

Sistema integral de monitorización biométrica, psicológica y social diseñado para detectar de forma temprana desviaciones en la salud física, mental y de cohesión grupal mediante la consolidación diaria de señales multimodales en un **Vector de Estado Colapsado**.

---

## 1. Contexto y Lógica Clínica del Proyecto

El sistema opera bajo un modelo longitudinal dividido en dos etapas:

1. **Fase de Baseline (6 Meses Iniciales):** Seguimiento continuo asumiendo un estado saludable del sujeto. Al finalizar este período, el sistema calcula y congela los parámetros estadísticos individuales (media, desviación estándar y percentiles) para cada variable. Este perfil actúa como **ancla clínica inmutable**, evitando que un deterioro lento y progresivo desplace silenciosamente los umbrales de normalidad (*concept drift*).
2. **Fase Operativa y Detección de Anomalías:** En cada ciclo diario, todas las fuentes de datos se normalizan contra el *baseline* individual (*Z-scores*) y se evalúan junto con **tendencias móviles** (7 y 30 días) y **acumuladores incrementales** (algoritmo de Welford) sobre todo el histórico acumulado. Ante desviaciones críticas o patrones similares a crisis previas, el motor dispara alertas y asigna protocolos de intervención (**Playbooks**).

### Privacidad y Contrato de Datos
* **Aislamiento de Identidad:** Los datos fisiológicos y psicológicos están desvinculados de la identidad real del sujeto mediante esquemas aislados (`vault_identity` vs. `biometrics`).
* **Grafos Anonimizados:** El análisis de proximidad e interacción social en tiempos de ocio utiliza exclusivamente hashes criptográficos (`social_graph_hash`), permitiendo detectar aislamiento sin exponer identidades individuales.
* **Descarte Multimedia:** Los archivos crudos de audio y video **nunca se almacenan en disco ni en base de datos**. Se procesan al vuelo en memoria y se conserva únicamente el vector numérico resultante.

---

## 2. Lógica de Negocio y Reglas de Operación

El núcleo funcional del sistema transforma mediciones heterogéneas en decisiones accionables bajo cinco reglas de negocio:

### A. Sincronización de Granularidad (*Forward-Fill* Controlado)
Dado que las variables tienen distintas frecuencias de captura (semanales, diarias y continuas nocturnas), el motor de colapso diario aplica una ventana de vigencia para construir el vector de estado:
* **Variables Semanales** (densidad ósea, glóbulos rojos, capacidad pulmonar): Se arrastran hacia adelante (*forward-fill*) durante un máximo de 7 días hasta la siguiente medición oficial. Si supera los 7 días sin registro, se marca una alerta de incumplimiento de protocolo.
* **Variables Diarias y Sueño:** Deben registrarse en el ciclo de 24 horas correspondiente.

### B. Evaluación Multicriterio de Alertas de Salud
Una alerta nunca se dispara por un único dato ruidoso aislado, sino mediante tres mecanismos complementarios:
1. **Desviación Aguda (*Z-score* contra Baseline):** Se activa cuando una variable crítica supera los $\pm 2\sigma$ respecto al perfil sano congelado de 6 meses del sujeto (ej. caída abrupta en fuerza de agarre o pico de ansiedad en voz/texto).
2. **Deterioro Progresivo (Pendiente Móvil):** Se activa cuando la tasa de cambio (`rolling_slope` a 14 o 30 días) muestra una tendencia negativa sostenida (ej. pérdida gradual de densidad muscular o aumento continuo de fatiga), incluso si el valor diario aún no cruza el umbral crítico absoluto.
3. **Similitud de Patrones Históricos (`pgvector`):** El vector normalizado del día se compara por distancia coseno contra todo el historial acumulado. Si la combinación multidimensional actual se aproxima a un estado que en el pasado precedió a una crisis o baja médica, se dispara una alerta preventiva.

### C. Dinámica Social y Alerta de Aislamiento
El sistema monitoriza la cohesión del equipo sin invadir la privacidad individual:
* **Desincronización Circadiana:** Compara la ventana de sueño del sujeto contra la mediana del grupo. Si el sujeto desplaza repetidamente sus horas de descanso (no duerme cuando los demás), se incrementa su índice de desincronización.
* **Aislamiento en Tiempo de Ocio:** Durante las franjas declaradas como tiempo libre, el sistema mide la proximidad espacial mediante hashes anonimizados. Una caída sostenida en la centralidad del grafo o un aumento del ratio de tiempo aislado dispara una alerta psicosocial.

### D. Motor de Recomendación y Gobernanza de Playbooks
* **Asignación Determinista + Contextual:** Cada combinación de alertas activas se mapea contra el catálogo de *playbooks* (`playbooks_catalog`) para generar tareas concretas (ajustes de carga física, pautas de exposición lumínica, ejercicios de recuperación o sesiones de seguimiento).
* **Supresión de Fatiga de Alertas (*Cooldown*):** Si un *playbook* ya está activo para una anomalía específica, el sistema evita duplicar notificaciones idénticas en días consecutivos mientras la tendencia muestre signos de estabilización o mejora.

### E. Segregación de Visibilidad por Rol
* **Rol Sujeto / Participante:** Solo visualiza sus propias tareas recomendadas (`muestra-de-recomendaciones`) y accede al módulo de captura de audio/video (`obtencion-de-audio`). No tiene acceso a métricas comparativas ni a datos de terceros.
* **Rol Misión / Supervisión:** Accede a la topología global de cohesión grupal (`visualizacion-de-grafos-sociales`) y al estado agregado de alertas, manteniendo el aislamiento legal sobre los datos biométricos crudos individuales según el contrato de datos.

---

## 3. Flujo de Datos y Variables Monitorizadas

* **Mediciones Semanales:** Densidad ósea, densidad muscular, estado cardíaco estructural, capacidad pulmonar y movilidad articular.
* **PING Diario (Datos Físicos):** Fuerza de agarre (*grip*), conteo de glóbulos rojos, peso, latencia en test de reflejos, oxigenación, reportaje de horarios, nivel de fatiga y exposición a radiación.
* **Streaming Continuo / Sueño:** Ritmo circadiano, calidad del sueño, ritmo cardíaco, exposición a la luz, bandas espectrales de electroencefalografía (EEG: Alfa, Beta, Theta, Delta), temperatura corporal y tensión arterial.
* **Evaluación Psicológica (Audio, Video y Texto):** Respuestas a preguntas abiertas procesadas mediante extracción acústica (`openSMILE`), visión artificial (CNN de expresiones faciales) y análisis de texto para inferir niveles de estrés, ansiedad, depresión y rasgos base.
* **Dinámica Social (Grafos):** Eventos de proximidad anonimizados en tiempos de ocio y métricas diarias de centralidad y aislamiento.

---

## 4. Arquitectura de Almacenamiento y Contenedores (Docker)

La infraestructura utiliza una **arquitectura híbrida en dos niveles** desplegada mediante contenedores Docker aislados según su perfil de consumo de recursos (CPU/RAM) y operaciones de entrada/salida (I/O):


```

[Sensores Stream] ──► [Redis Streams] ──► [worker-stream] ──┐
[Audio/Video/Txt] ──► [worker-ml] ──────────────────────────┼──► [PostgreSQL + pgvector]
[PING / Semanal]  ──► [api] ────────────────────────────────┘             │
▼
[daily_state_vectors]
│
[Sistema Recomendación] ──► [Frontend]

```

### Servicios en Docker
* **`db` (`pgvector/pgvector:pg16`):** Instancia única de PostgreSQL con particionamiento nativo por fechas. Aloja el *baseline* congelado, los históricos particionados, los resúmenes de sueño, las métricas de grafos y la tabla `daily_state_vectors` indexada con **HNSW** para búsqueda de similitud de estados históricos por distancia coseno.
* **`broker` (`redis:7-alpine`):** Búfer en memoria RAM (*Redis Streams* con persistencia AOF) que absorbe la ingesta de alta frecuencia del sueño/EEG antes de ser consolidada, evitando la fragmentación y el bloqueo de disco en PostgreSQL.
* **`api` (`python-core`):** Servicio ligero (FastAPI) que gestiona la ingesta de reportes diarios/semanales, expone los endpoints para el frontend y ejecuta la lógica de asignación de *playbooks*.
* **`worker-stream` (`python-core`):** Procesador en segundo plano que consume las ventanas de tiempo de Redis, calcula las métricas topológicas de los grafos sociales (`NetworkX`) y colapsa el vector diario.
* **`worker-ml` (`python-ml`):** Contenedor aislado con límite estricto de memoria encargado de ejecutar `openSMILE`, la CNN de video y los modelos de NLP al vuelo sobre las sesiones multimedia.
* **`frontend` (`node` / `nginx`):** Interfaz web para captura de audio/video, visualización de tareas recomendadas y consulta de grafos de cohesión (restringido a roles de misión).

---

## 5. Estructura del Repositorio

```text
orbivia/
├── base-de-datos/                        # Scripts SQL de inicialización, esquemas y particiones
│   ├── grafos/                           # Tablas de interacciones anonimizadas y snapshots diarios
│   ├── historico-de-datos/               # Esquemas de identidad, baseline congelado y logs de alertas
│   ├── mediciones-semanales/             # Definiciones para biomarcadores puntuales y resúmenes de sueño
│   └── vector-colapsado/                 # Tabla core con pgvector e índices HNSW[cite: 1]
│
├── frontend/                             # Aplicación cliente[cite: 1]
│   ├── muestra-de-recomendaciones/       # Vista de playbooks y tareas asignadas al sujeto
│   ├── obtencion-de-audio/               # Módulo de grabación y envío seguro de preguntas abiertas
│   └── visualizacion-de-grafos-sociales/ # Renderizado de red de interacción (solo vista de misión)
│
├── procesamiento/                        # Pipelines de extracción, transformación y colapso
│   ├── audio/raw-audio/                  # Extracción de características acústicas con openSMILE
│   ├── datos-fisicos-ping-diario/        # Validación y normalización de métricas diarias
│   ├── grafos/                           # Cálculo de centralidad y alertas de aislamiento social
│   ├── posicion/                         # Procesamiento de proximidad espacial en tiempos de ocio
│   ├── semanales/                        # Ingesta de analíticas médicas y métricas estructurales
│   ├── streaming-valores-continuos/      # Consumidores de Redis Streams para sueño y bandas EEG
│   ├── texto/                            # Análisis NLP de ansiedad, depresión y estrés
│   └── video/                            # Inferencia de microexpresiones y estado emocional (CNN)
│
├── sistema-de-recomendacion/             # Motor de reglas clínicas, Z-scores y catálogo de playbooks
│
├── volumenes/                            # Persistencia local de contenedores (ignorado en Git)
│   ├── postgre/                          # Archivos físicos de datos de PostgreSQL[cite: 1]
│   └── redis/                            # Archivos AOF de respaldo de Redis Streams[cite: 1]
│
├── .gitignore                            # Exclusión de volúmenes, modelos pesados y variables de entorno
└── README.md                             # Documentación general de arquitectura y negocio

```

---

## 6. Despliegue Rápido

1. **Configurar variables de entorno:** Crear un archivo `.env` en la raíz con las credenciales de `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` y la clave de salting criptográfico para los hashes de grafos sociales.
2. **Verificar carpetas de volúmenes:** Asegurar que `volumenes/postgre` y `volumenes/redis` estén incluidos en `.gitignore` antes de levantar los servicios.
3. **Levantar la infraestructura:**
```bash
docker compose up -d --build

```



```