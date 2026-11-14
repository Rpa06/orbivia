#!/usr/bin/env bash
# Demo completa del grafo social: borra el histórico, compila, levanta la pila,
# simula DIAS días de misión y muestra los resultados.
#
#   bash procesamiento/grafos/demo.sh            # escenario drift, 30 días
#   bash procesamiento/grafos/demo.sh cliques 15
#
# Escenarios: homogeneous, low_integration, cliques, drift, unequal_leisure,
# shifted_schedules, schedule_change, simultaneous, sensor_loss, crew_wide_drop

ESCENARIO="${1:-drift}"
DIAS="${2:-30}"

cd "$(dirname "$0")/../.." || exit 1
export PATH="$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

# </dev/null es imprescindible: docker compose exec lee la entrada estándar y,
# sin esto, se tragaría lo que venga después (por ejemplo, líneas pegadas).
q() { docker compose exec -T db psql -U orbivia -d orbivia -P pager=off "$@" </dev/null; }

# Fija una variable en .env (la añade en su propia línea o sustituye su valor)
set_env() {
  touch .env
  [ -n "$(tail -c1 .env)" ] && echo >> .env
  if grep -q "^$1=" .env; then
    sed -i '' "s|^$1=.*|$1=$2|" .env
  else
    echo "$1=$2" >> .env
  fi
}

[ -f .env ] || cp .env.example .env
set_env SG_SIM_SCENARIO "$ESCENARIO"
set_env SG_SIM_SPEEDUP 86400   # un día de misión por segundo, más el cálculo

echo "== Arrancando Docker"
open -a Docker
until docker info >/dev/null 2>&1; do sleep 2; done

echo "== Borrando el histórico anterior (con el servicio parado)"
docker compose stop social-graph </dev/null
docker compose up -d db </dev/null
until q -At -c "SELECT 1" >/dev/null 2>&1; do sleep 2; done
q -q -c "DROP SCHEMA IF EXISTS social_graph CASCADE" 2>&1 | grep -v -E "NOTICE|DETAIL|drop cascades"
find volumenes/social-graph -type f ! -name .gitkeep -delete

echo "== Compilando y levantando la pila"
if ! docker compose up -d --build </dev/null; then
  echo "Error al compilar o arrancar. Revisa el mensaje de arriba."
  exit 1
fi

echo "== Simulando $DIAS días del escenario $ESCENARIO"
while :; do
  ultimo="$(q -At -c 'SELECT coalesce(max(day), -1) FROM biometrics.social_graph_daily_result' 2>/dev/null)"
  [ "${ultimo:--1}" -ge $((DIAS - 1)) ] 2>/dev/null && break
  if docker compose ps social-graph --format '{{.Status}}' </dev/null | grep -q -E "Restarting|Exited"; then
    echo; echo "El servicio se ha caído. Últimas líneas del log:"
    docker compose logs --tail 15 social-graph </dev/null
    exit 1
  fi
  printf '\r  días cerrados: %s de %s ' "$(( ${ultimo:--1} + 1 ))" "$DIAS"
  sleep 3
done
echo; echo

echo "== Estado de integración por día"
q -c "SELECT day AS dia,
         result#>>'{isolation,astronauts,A1,status}' AS a1,
         result#>>'{isolation,astronauts,A2,status}' AS a2,
         result#>>'{isolation,astronauts,A3,status}' AS a3,
         result#>>'{isolation,astronauts,A4,status}' AS a4,
         result#>>'{isolation,astronauts,A5,status}' AS a5,
         result#>>'{isolation,astronauts,A6,status}' AS a6,
         result#>>'{isolation,crew,drop}' AS descenso_grupo
      FROM biometrics.social_graph_daily_result WHERE day < $DIAS ORDER BY day"

echo "== Propuestas de actividades voluntarias"
q -c "SELECT day AS dia, p->>'crew_text' AS texto_tripulacion
      FROM biometrics.social_graph_daily_result,
           jsonb_array_elements(result->'recommendations'->'proposals') p
      WHERE day < $DIAS ORDER BY day"

echo "== Justificación para Tierra de la última propuesta"
q -At -c "SELECT p->>'justification'
          FROM biometrics.social_graph_daily_result,
               jsonb_array_elements(result->'recommendations'->'proposals') p
          WHERE day < $DIAS ORDER BY day DESC LIMIT 1"

imagen="volumenes/social-graph/$(printf 'day_%04d.png' $((DIAS - 1)))"
echo; echo "Imagen del último día: $imagen"
[ -z "$DEMO_NO_OPEN" ] && open "$imagen" volumenes/social-graph
