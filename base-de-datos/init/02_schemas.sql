-- Esquemas y tablas de Orbivia.
--
-- Separación estricta:
--   vault_identity  identidades reales, credenciales y roles de aplicación
--   biometrics      líneas base, Welford, mediciones, vector diario, alertas, disponibilidad
--   private_cycle   registro opcional del ciclo, cifrado; sin acceso del motor ni del planificador
--   operations      misión, tareas, planes y registro de decisiones humanas
--
-- Ningún esquema guarda audio, vídeo ni transcripciones: no existen columnas para ello.
-- Los permisos por rol de base de datos están en 03_roles.sh.

CREATE SCHEMA IF NOT EXISTS vault_identity;
CREATE SCHEMA IF NOT EXISTS biometrics;
CREATE SCHEMA IF NOT EXISTS private_cycle;
CREATE SCHEMA IF NOT EXISTS operations;

-- ---------------------------------------------------------------- vault_identity

-- Identidad real. Solo la lee el administrador; la API solo ve el seudónimo.
CREATE TABLE vault_identity.astronauts (
    pseudonym      text PRIMARY KEY CHECK (pseudonym ~ '^[A-Za-z0-9_-]{1,32}$'),
    real_name      text NOT NULL,
    simulated      boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE vault_identity.users (
    id             bigserial PRIMARY KEY,
    username       text NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9_.-]{3,64}$'),
    password_hash  text NOT NULL,
    role           text NOT NULL CHECK (role IN
                     ('astronaut', 'flight_surgeon', 'commander', 'earth_medical', 'earth_mission')),
    astronaut_id   text REFERENCES vault_identity.astronauts (pseudonym),
    active         boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    -- Astronautas y comandante son tripulantes (el comandante hace su propio check-in);
    -- el resto de roles no está ligado a ningún tripulante.
    CONSTRAINT users_crew_link CHECK (
        (role = 'astronaut' AND astronaut_id IS NOT NULL)
        OR (role = 'commander')
        OR (role NOT IN ('astronaut', 'commander') AND astronaut_id IS NULL))
);

-- ---------------------------------------------------------------- operations

CREATE TABLE operations.mission (
    id                  smallint PRIMARY KEY CHECK (id = 1),
    name                text NOT NULL,
    environment         text NOT NULL,
    start_date          date NOT NULL,
    duration_days       integer NOT NULL CHECK (duration_days > 0),
    adaptation_days     integer NOT NULL CHECK (adaptation_days >= 0),
    audio_interval_days integer NOT NULL DEFAULT 3 CHECK (audio_interval_days >= 1),
    simulated           boolean NOT NULL DEFAULT true
);

CREATE TABLE operations.task_catalog (
    task_id      text PRIMARY KEY,
    environment  text NOT NULL,
    category     text NOT NULL,
    name         text NOT NULL,
    reassignable boolean NOT NULL,
    safety_critical boolean NOT NULL DEFAULT false
);

CREATE TABLE operations.crew_constraints (
    astronaut_id   text PRIMARY KEY,
    qualifications text[] NOT NULL DEFAULT '{}',
    exercise_block text[] NOT NULL DEFAULT '{}',   -- ["HH:MM", "HH:MM"]
    workday        text[] NOT NULL DEFAULT '{08:00,17:00}'
);

CREATE TABLE operations.worked_hours (
    astronaut_id text NOT NULL,
    work_date    date NOT NULL,
    planned_h    double precision CHECK (planned_h >= 0),
    actual_h     double precision CHECK (actual_h >= 0),
    source       text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'sensor', 'simulated', 'plan')),
    PRIMARY KEY (astronaut_id, work_date)
);

CREATE TABLE operations.plan_runs (
    plan_date     date PRIMARY KEY,
    status        text NOT NULL,
    generated_at  timestamptz NOT NULL DEFAULT now(),
    original      jsonb,          -- plan de referencia sin ajustes por estado
    notes         jsonb NOT NULL DEFAULT '[]',
    weekly_limits jsonb NOT NULL DEFAULT '[]'
);

CREATE TABLE operations.plans (
    plan_date   date NOT NULL REFERENCES operations.plan_runs (plan_date) ON DELETE CASCADE,
    option_id   text NOT NULL,
    label       text NOT NULL,
    payload     jsonb NOT NULL,   -- asignaciones, carga, ventajas, inconvenientes, cambios
    PRIMARY KEY (plan_date, option_id)
);

-- Registro de decisiones humanas. Con motivo privado solo consta "motivo personal".
CREATE TABLE operations.plan_decisions (
    id              bigserial PRIMARY KEY,
    plan_date       date NOT NULL REFERENCES operations.plan_runs (plan_date) ON DELETE CASCADE,
    decision        text NOT NULL CHECK (decision IN ('selected', 'rejected_all')),
    option_id       text,
    reason_category text NOT NULL CHECK (reason_category IN
                      ('none', 'operational', 'safety', 'workload', 'personal')),
    reason_text     text,
    decided_by_role text NOT NULL,
    decided_by_user bigint,
    decided_at      timestamptz NOT NULL DEFAULT now(),
    CHECK ((decision = 'selected') = (option_id IS NOT NULL)),
    CHECK (reason_category <> 'personal' OR reason_text = 'motivo personal')
);

-- ---------------------------------------------------------------- biometrics

-- Líneas base: terrestre (congelada antes de la misión) y de adaptación.
CREATE TABLE biometrics.baselines (
    astronaut_id text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('terrestrial', 'adaptation')),
    variable     text NOT NULL,
    mean         double precision NOT NULL,
    sd           double precision NOT NULL CHECK (sd > 0),
    p05          double precision,
    p50          double precision,
    p95          double precision,
    n            integer NOT NULL CHECK (n > 0),
    frozen_at    timestamptz NOT NULL DEFAULT now(),
    source       text NOT NULL DEFAULT 'simulated',
    PRIMARY KEY (astronaut_id, kind, variable)
);

-- La línea base terrestre no se actualiza durante la misión.
CREATE FUNCTION biometrics.forbid_terrestrial_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.kind = 'terrestrial' THEN
        RAISE EXCEPTION 'La línea base terrestre de % está congelada', OLD.astronaut_id;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;
CREATE TRIGGER terrestrial_baseline_frozen
    BEFORE UPDATE OR DELETE ON biometrics.baselines
    FOR EACH ROW EXECUTE FUNCTION biometrics.forbid_terrestrial_change();

-- Perfil de una vez: personalidad y deseabilidad social. No entra en disponibilidad ni reparto,
-- salvo social_desirability_high, que reduce al 50 % el peso del autoinforme.
CREATE TABLE biometrics.baseline_profile (
    astronaut_id             text PRIMARY KEY,
    bfi2xs                   jsonb,
    marlowe_crowne           double precision,
    social_desirability_high boolean NOT NULL DEFAULT false,
    dxa_reference            jsonb,
    nasa_cognition           jsonb,
    source                   text NOT NULL DEFAULT 'simulated'
);

-- Acumuladores de Welford por astronauta y variable, durante la misión.
CREATE TABLE biometrics.welford_state (
    astronaut_id text NOT NULL,
    variable     text NOT NULL,
    n            bigint NOT NULL,
    mean         double precision NOT NULL,
    m2           double precision NOT NULL,
    last_date    date,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (astronaut_id, variable)
);

-- Mediciones de todos los canales (diarias, semanales, mensuales).
CREATE TABLE biometrics.measurements (
    astronaut_id text NOT NULL,
    cycle_date   date NOT NULL,
    variable     text NOT NULL,
    value        double precision NOT NULL,
    unit         text,
    frequency    text NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly', 'continuous')),
    source       text NOT NULL CHECK (source IN ('sensor', 'manual', 'simulated', 'derived')),
    validated    boolean NOT NULL DEFAULT false,   -- validación instrumental a bordo
    recorded_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (astronaut_id, cycle_date, variable)
);

CREATE TABLE biometrics.checkins (
    astronaut_id text NOT NULL,
    cycle_date   date NOT NULL,
    sleep        smallint NOT NULL CHECK (sleep BETWEEN 1 AND 5),
    fatigue      smallint NOT NULL CHECK (fatigue BETWEEN 1 AND 5),   -- cansancio: 5 = muy cansado
    workload     smallint NOT NULL CHECK (workload BETWEEN 1 AND 5),
    mood         smallint NOT NULL CHECK (mood BETWEEN 1 AND 5),
    cohesion     smallint NOT NULL CHECK (cohesion BETWEEN 1 AND 5),
    known_reason boolean NOT NULL DEFAULT false,  -- "motivo conocido", sin causa
    source       text NOT NULL DEFAULT 'manual',
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (astronaut_id, cycle_date)
);

CREATE TABLE biometrics.pvt_results (
    astronaut_id   text NOT NULL,
    cycle_date     date NOT NULL,
    mean_rt_ms     double precision NOT NULL CHECK (mean_rt_ms > 0),
    lapses         integer NOT NULL CHECK (lapses >= 0),
    false_starts   integer NOT NULL CHECK (false_starts >= 0),
    trials         integer NOT NULL CHECK (trials >= 0),
    duration_s     double precision NOT NULL,
    source         text NOT NULL DEFAULT 'manual',
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (astronaut_id, cycle_date)
);

-- Pregunta doble semanal. Las respuestas individuales nunca se muestran a otros astronautas.
CREATE TABLE biometrics.weekly_double (
    astronaut_id        text NOT NULL,
    iso_year            integer NOT NULL,
    iso_week            integer NOT NULL,
    cohesion            smallint NOT NULL CHECK (cohesion BETWEEN 1 AND 5),
    predicted_team_mean smallint NOT NULL CHECK (predicted_team_mean BETWEEN 1 AND 5),
    source              text NOT NULL DEFAULT 'manual',
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (astronaut_id, iso_year, iso_week)
);

CREATE TABLE biometrics.exercise_log (
    astronaut_id text NOT NULL,
    cycle_date   date NOT NULL,
    done         boolean NOT NULL,
    minutes      integer CHECK (minutes >= 0),
    source       text NOT NULL DEFAULT 'manual',
    PRIMARY KEY (astronaut_id, cycle_date)
);

-- Plan "si pasa X, haré Y": solo lo lee el propio astronauta (filtro en la API).
CREATE TABLE biometrics.implementation_intentions (
    id           bigserial PRIMARY KEY,
    astronaut_id text NOT NULL,
    if_text      text NOT NULL CHECK (length(if_text) <= 300),
    then_text    text NOT NULL CHECK (length(then_text) <= 300),
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Resultado numérico de la entrevista de audio o de la sesión de vídeo. Sin transcripción.
CREATE TABLE biometrics.media_results (
    job_id       uuid PRIMARY KEY,
    astronaut_id text NOT NULL,
    cycle_date   date NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('audio', 'video')),
    question_id  smallint CHECK (question_id BETWEEN 1 AND 8),
    status       text NOT NULL CHECK (status IN ('queued', 'completed', 'failed')),
    acoustic     jsonb,       -- rasgos openSMILE agregados
    nlp          jsonb,       -- cuatro puntuaciones de confianza; NULL si el NLP está desactivado
    video        jsonb,       -- signos físicos de fatiga (no emociones)
    error_code   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

-- Vector de Estado Colapsado: 20 float32 = 80 bytes exactos. Metadatos fuera del vector.
CREATE TABLE biometrics.daily_vector (
    astronaut_id   text NOT NULL,
    cycle_date     date NOT NULL,
    schema_version smallint NOT NULL,
    vector         bytea NOT NULL CHECK (octet_length(vector) = 80),
    missing_mask   integer NOT NULL,        -- bit i = campo i ausente
    simulated_mask integer NOT NULL DEFAULT 0, -- bit i = campo i procede del simulador
    embedding      vector(20),              -- para C4 (similitud coseno); ausentes a 0
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (astronaut_id, cycle_date)
);
CREATE INDEX daily_vector_embedding_hnsw
    ON biometrics.daily_vector USING hnsw (embedding vector_cosine_ops);

CREATE TABLE biometrics.alerts (
    id           bigserial PRIMARY KEY,
    astronaut_id text NOT NULL,
    cycle_date   date NOT NULL,
    criterion    text NOT NULL CHECK (criterion IN ('C1', 'C2', 'C3', 'C4')),
    area         text NOT NULL CHECK (area IN ('medical', 'fatigue_sleep', 'psychological', 'social_team')),
    variables    text[] NOT NULL,
    detail       jsonb NOT NULL,
    reference    text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (astronaut_id, cycle_date, criterion, area)
);

CREATE TABLE biometrics.availability (
    astronaut_id    text NOT NULL,
    cycle_date      date NOT NULL,
    score           double precision NOT NULL CHECK (score BETWEEN 0 AND 100),
    reason_category text NOT NULL,   -- general: 'none', 'fatigue', 'isolation', 'workload', 'medical'
    areas           jsonb NOT NULL,
    audit           jsonb NOT NULL,  -- fórmula y aportación de cada variable
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (astronaut_id, cycle_date)
);

-- Acciones recomendadas activas, con cooldown.
CREATE TABLE biometrics.actions (
    id              bigserial PRIMARY KEY,
    astronaut_id    text NOT NULL,
    signature       text NOT NULL,   -- combinación de alertas que la origina
    action_code     text NOT NULL,
    first_date      date NOT NULL,
    last_notified   date NOT NULL,
    last_severity   double precision NOT NULL,
    active          boolean NOT NULL DEFAULT true,
    UNIQUE (astronaut_id, signature, action_code)
);

-- Control de sincronización con Tierra: evita duplicados y permite reintentos.
CREATE TABLE biometrics.sync_log (
    astronaut_id   text NOT NULL,
    cycle_date     date NOT NULL,
    schema_version smallint NOT NULL,
    payload_sha256 text NOT NULL,
    status         text NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
    attempts       integer NOT NULL DEFAULT 0,
    last_attempt   timestamptz,
    acked_at       timestamptz,
    last_error     text,
    PRIMARY KEY (astronaut_id, cycle_date, schema_version)
);

-- Tablas de los módulos de sueño y grafo social (las crean también sus servicios si faltan).
CREATE TABLE biometrics.sleep_session_summary (
    astronaut_id text NOT NULL,
    sleep_session_id text NOT NULL,
    start_ts double precision NOT NULL,
    end_ts double precision NOT NULL,
    config_version text NOT NULL,
    summary jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (astronaut_id, sleep_session_id)
);
CREATE INDEX sleep_session_summary_by_start
    ON biometrics.sleep_session_summary (astronaut_id, start_ts);

CREATE TABLE biometrics.social_graph_daily_result (
    day integer PRIMARY KEY,
    params_version text NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE biometrics.social_graph_checkpoint (
    id smallint PRIMARY KEY CHECK (id = 1),
    state jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- private_cycle

-- Contenido cifrado con pgp_sym_encrypt (clave CYCLE_ENCRYPTION_KEY, solo en la API).
CREATE TABLE private_cycle.entries (
    id           bigserial PRIMARY KEY,
    astronaut_id text NOT NULL,
    entry_date   date NOT NULL,
    payload      bytea NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX entries_by_astronaut ON private_cycle.entries (astronaut_id, entry_date);

-- Compartición temporal con el médico de a bordo, decidida por la astronauta.
CREATE TABLE private_cycle.shares (
    astronaut_id text PRIMARY KEY,
    expires_at   timestamptz NOT NULL,
    granted_at   timestamptz NOT NULL DEFAULT now()
);
