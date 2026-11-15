#!/bin/sh
# Roles de base de datos de Orbivia, con privilegio mínimo.
#
#   orbivia_api     API: autenticación (solo seudónimos), ingesta y lectura filtrada por rol
#   orbivia_engine  colapso, alertas, disponibilidad, planificador y workers de sueño y grafo
#   orbivia_cycle   módulo privado del ciclo: solo el esquema private_cycle
#   orbivia_sync    sync-tierra: solo lectura de la lista blanca y su tabla de control
#
# Ni orbivia_engine ni orbivia_sync tienen USAGE sobre private_cycle: el motor de
# disponibilidad y el planificador no pueden consultar ese esquema ni por error.
# Las contraseñas llegan por variables de entorno (.env), nunca en el repositorio.
set -eu

: "${ORBIVIA_DB_API_PASSWORD:?Define ORBIVIA_DB_API_PASSWORD en .env}"
: "${ORBIVIA_DB_ENGINE_PASSWORD:?Define ORBIVIA_DB_ENGINE_PASSWORD en .env}"
: "${ORBIVIA_DB_CYCLE_PASSWORD:?Define ORBIVIA_DB_CYCLE_PASSWORD en .env}"
: "${ORBIVIA_DB_SYNC_PASSWORD:?Define ORBIVIA_DB_SYNC_PASSWORD en .env}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v api_pw="$ORBIVIA_DB_API_PASSWORD" \
  -v engine_pw="$ORBIVIA_DB_ENGINE_PASSWORD" \
  -v cycle_pw="$ORBIVIA_DB_CYCLE_PASSWORD" \
  -v sync_pw="$ORBIVIA_DB_SYNC_PASSWORD" \
  -v dbname="$POSTGRES_DB" <<'SQL'
CREATE ROLE orbivia_api    LOGIN PASSWORD :'api_pw';
CREATE ROLE orbivia_engine LOGIN PASSWORD :'engine_pw';
CREATE ROLE orbivia_cycle  LOGIN PASSWORD :'cycle_pw';
CREATE ROLE orbivia_sync   LOGIN PASSWORD :'sync_pw';

REVOKE ALL ON SCHEMA vault_identity, biometrics, private_cycle, operations FROM PUBLIC;
GRANT CONNECT ON DATABASE :"dbname" TO orbivia_api, orbivia_engine, orbivia_cycle, orbivia_sync;

-- orbivia_api ------------------------------------------------------------------
GRANT USAGE ON SCHEMA vault_identity, biometrics, operations TO orbivia_api;
GRANT SELECT ON vault_identity.users TO orbivia_api;
GRANT SELECT (pseudonym) ON vault_identity.astronauts TO orbivia_api;   -- nunca real_name
GRANT SELECT ON ALL TABLES IN SCHEMA biometrics TO orbivia_api;
GRANT INSERT, UPDATE ON biometrics.measurements, biometrics.checkins, biometrics.pvt_results,
      biometrics.weekly_double, biometrics.exercise_log, biometrics.media_results
      TO orbivia_api;
GRANT INSERT, DELETE ON biometrics.implementation_intentions TO orbivia_api;
GRANT SELECT ON ALL TABLES IN SCHEMA operations TO orbivia_api;
GRANT INSERT ON operations.plan_decisions TO orbivia_api;
GRANT INSERT, UPDATE ON operations.worked_hours TO orbivia_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA biometrics, operations TO orbivia_api;

-- orbivia_engine ---------------------------------------------------------------
GRANT USAGE, CREATE ON SCHEMA biometrics TO orbivia_engine;
GRANT USAGE ON SCHEMA operations TO orbivia_engine;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA biometrics TO orbivia_engine;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA operations TO orbivia_engine;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA biometrics, operations TO orbivia_engine;
-- Las líneas base terrestres solo se insertan antes de la misión (seed, como administrador)
REVOKE UPDATE, DELETE ON biometrics.baselines FROM orbivia_engine;
-- Los servicios de sueño y grafo social son dueños de sus tablas (ejecutan su propio DDL idempotente)
ALTER TABLE biometrics.sleep_session_summary OWNER TO orbivia_engine;
ALTER TABLE biometrics.social_graph_daily_result OWNER TO orbivia_engine;
ALTER TABLE biometrics.social_graph_checkpoint OWNER TO orbivia_engine;
GRANT SELECT ON biometrics.sleep_session_summary, biometrics.social_graph_daily_result TO orbivia_api;

-- orbivia_cycle ----------------------------------------------------------------
GRANT USAGE ON SCHEMA private_cycle TO orbivia_cycle;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA private_cycle TO orbivia_cycle;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA private_cycle TO orbivia_cycle;

-- orbivia_sync -----------------------------------------------------------------
GRANT USAGE ON SCHEMA biometrics TO orbivia_sync;
GRANT SELECT ON biometrics.daily_vector TO orbivia_sync;
GRANT SELECT (astronaut_id, cycle_date, kind, question_id, status, acoustic, nlp, video)
      ON biometrics.media_results TO orbivia_sync;
GRANT SELECT, INSERT, UPDATE ON biometrics.sync_log TO orbivia_sync;
SQL
