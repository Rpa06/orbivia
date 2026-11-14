"""Colapso diario y generación de planes sobre PostgreSQL y Redis.

Se ejecuta con el rol `orbivia_engine`, que no tiene permisos sobre
`private_cycle` ni `vault_identity`: este módulo no puede leer el ciclo ni
las identidades reales aunque lo intentara.

Pasos de `run_daily_collapse(cycle_date)`:
1. Puentes: resúmenes de sueño y grafo social del día → `biometrics.measurements`.
2. Desincronización circadiana: punto medio del sueño frente a la mediana de la tripulación.
3. Línea base de adaptación, una sola vez, al terminar los días de adaptación.
4. Vector de 20 float32 por astronauta, Welford y ventanas 7/14/30 (caché en Redis).
5. Alertas C1-C3 (C4 desactivado), nota de disponibilidad y acciones con cooldown.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from colapso.builder import build_vector
from colapso.stats import WINDOWS, Baseline, Welford, baseline_from, window_stats
from colapso.vector import FIELDS, SCHEMA_VERSION, CollapsedVector, deterioration, unpack

from . import actions as actions_mod
from . import alerts as alerts_mod
from . import availability as availability_mod
from . import planning

logger = logging.getLogger("orbivia.pipeline")

HISTORY_DAYS = 30
ADAPTATION_VARIABLES = ("sleep_duration_h", "grip_strength_kg", "spo2_pct", "sleep_heart_rate_bpm",
                        "sleep_hrv_ms", "pvt_mean_rt_ms")
CHECKIN_SOURCES = {"checkin.sleep": "sleep", "checkin.fatigue": "fatigue", "checkin.workload": "workload",
                   "checkin.mood": "mood", "checkin.cohesion": "cohesion"}
MEDIA_FIELDS = {"nlp_neutral_z": ("nlp", "neutral"), "nlp_low_mood_z": ("nlp", "low_mood"),
                "nlp_anxiety_z": ("nlp", "anxiety"), "nlp_stable_z": ("nlp", "stable"),
                "acoustic_f0_z": ("acoustic", "f0_mean"), "acoustic_pause_z": ("acoustic", "pause_mean_s")}


def _mission(conn) -> dict[str, Any]:
    row = conn.execute(
        "SELECT name, environment, start_date, duration_days, adaptation_days, audio_interval_days "
        "FROM operations.mission WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError("No hay misión configurada (operations.mission). Ejecuta seed_mission.py")
    keys = ("name", "environment", "start_date", "duration_days", "adaptation_days", "audio_interval_days")
    return dict(zip(keys, row))


def _astronauts(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT astronaut_id FROM biometrics.baseline_profile ORDER BY astronaut_id").fetchall()]


def _upsert_measurement(conn, astronaut: str, day: date, variable: str, value: float, unit: str,
                        source: str, frequency: str = "daily") -> None:
    conn.execute(
        "INSERT INTO biometrics.measurements (astronaut_id, cycle_date, variable, value, unit, frequency, source) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (astronaut_id, cycle_date, variable) "
        "DO UPDATE SET value = EXCLUDED.value, source = EXCLUDED.source, recorded_at = now()",
        (astronaut, day, variable, value, unit, frequency, source))


# --- 1 y 2: puentes -------------------------------------------------------------------


def import_sleep_and_social(conn, day: date, mission: dict) -> dict[str, int]:
    """Copia al formato común lo que han producido los servicios de sueño y grafo."""
    counts = {"sleep": 0, "social": 0}
    start = mission["start_date"]
    rows = conn.execute(
        "SELECT astronaut_id, end_ts, summary FROM biometrics.sleep_session_summary").fetchall()
    for astronaut, end_ts, summary in rows:
        # Los tiempos del módulo de sueño son segundos de misión (SLEEP_MISSION_EPOCH_S)
        end_day = start + timedelta(seconds=float(end_ts))
        if end_day != day:
            continue
        vec = (summary or {}).get("sleep_summary_vector") or {}
        for key, var, unit in (("estimated_sleep_h", "sleep_duration_h", "h"),
                               ("sleep_efficiency", "sleep_efficiency", "0-1"),
                               ("mean_heart_rate", "sleep_heart_rate_bpm", "bpm"),
                               ("mean_hrv", "sleep_hrv_ms", "ms")):
            if vec.get(key) is not None:
                _upsert_measurement(conn, astronaut, day, var, float(vec[key]), unit, "sensor")
                counts["sleep"] += 1
    mission_day = (day - start).days + 1
    row = conn.execute("SELECT result FROM biometrics.social_graph_daily_result WHERE day = %s",
                       (mission_day - 1,)).fetchone()
    if row:
        for astronaut, info in ((row[0].get("isolation") or {}).get("astronauts") or {}).items():
            value = (((info or {}).get("indicators") or {}).get("intensity") or {}).get("value")
            if value is not None:
                _upsert_measurement(conn, astronaut, day, "social_centrality", float(value), "0-1", "sensor")
                counts["social"] += 1
    return counts


def compute_circadian_desync(conn, day: date) -> int:
    rows = conn.execute(
        "SELECT astronaut_id, value, source FROM biometrics.measurements "
        "WHERE cycle_date = %s AND variable = 'sleep_midpoint_h'", (day,)).fetchall()
    if len(rows) < 2:
        return 0
    median = statistics.median(v for _, v, _ in rows)
    for astronaut, value, source in rows:
        diff = abs(value - median)
        diff = min(diff, 24 - diff)
        _upsert_measurement(conn, astronaut, day, "circadian_desync_h", round(diff, 3), "h",
                            "simulated" if source == "simulated" else "derived")
    return len(rows)


# --- 3: líneas base ----------------------------------------------------------------------


def _baselines(conn, astronaut: str) -> dict[str, tuple[Baseline | None, Baseline | None]]:
    out: dict[str, list] = defaultdict(lambda: [None, None])
    for kind, variable, mean, sd, p05, p50, p95, n in conn.execute(
            "SELECT kind, variable, mean, sd, p05, p50, p95, n FROM biometrics.baselines WHERE astronaut_id = %s",
            (astronaut,)).fetchall():
        b = Baseline(mean, sd, p05, p50, p95, n, kind)
        out[variable][0 if kind == "terrestrial" else 1] = b
    return {k: (v[0], v[1]) for k, v in out.items()}


def ensure_adaptation_baseline(conn, astronaut: str, day: date, mission: dict) -> int:
    a_days = mission["adaptation_days"]
    mission_day = (day - mission["start_date"]).days + 1
    if a_days <= 0 or mission_day <= a_days:
        return 0
    existing = {r[0] for r in conn.execute(
        "SELECT variable FROM biometrics.baselines WHERE astronaut_id = %s AND kind = 'adaptation'",
        (astronaut,)).fetchall()}
    end = mission["start_date"] + timedelta(days=a_days - 1)
    created = 0
    for variable in ADAPTATION_VARIABLES:
        if variable in existing:
            continue
        if variable == "pvt_mean_rt_ms":
            values = [r[0] for r in conn.execute(
                "SELECT mean_rt_ms FROM biometrics.pvt_results WHERE astronaut_id = %s AND cycle_date BETWEEN %s AND %s",
                (astronaut, mission["start_date"], end)).fetchall()]
        else:
            values = [r[0] for r in conn.execute(
                "SELECT value FROM biometrics.measurements WHERE astronaut_id = %s AND variable = %s "
                "AND cycle_date BETWEEN %s AND %s", (astronaut, variable, mission["start_date"], end)).fetchall()]
        if len(values) < 2:
            continue
        b = baseline_from(values, "adaptation")
        # Con 2-3 días la desviación se subestima: nunca menor que la terrestre
        terr = conn.execute("SELECT sd FROM biometrics.baselines WHERE astronaut_id = %s AND kind = 'terrestrial' "
                            "AND variable = %s", (astronaut, variable)).fetchone()
        if terr and terr[0] > b.sd:
            b = Baseline(b.mean, terr[0], b.p05, b.p50, b.p95, b.n, "adaptation")
        conn.execute(
            "INSERT INTO biometrics.baselines (astronaut_id, kind, variable, mean, sd, p05, p50, p95, n, source) "
            "VALUES (%s, 'adaptation', %s, %s, %s, %s, %s, %s, %s, 'derived') ON CONFLICT DO NOTHING",
            (astronaut, variable, b.mean, b.sd, b.p05, b.p50, b.p95, b.n))
        created += 1
    return created


# --- 4: vector --------------------------------------------------------------------------


def _raw_series(conn, astronaut: str, day: date) -> tuple[dict[str, dict[date, float]], set[str]]:
    since = day - timedelta(days=HISTORY_DAYS)
    raw: dict[str, dict[date, float]] = defaultdict(dict)
    simulated: set[str] = set()
    for d, variable, value, source in conn.execute(
            "SELECT cycle_date, variable, value, source FROM biometrics.measurements "
            "WHERE astronaut_id = %s AND cycle_date BETWEEN %s AND %s", (astronaut, since, day)).fetchall():
        raw[variable][d] = value
        if source == "simulated" and d == day:
            simulated.add(variable)
    for row in conn.execute(
            "SELECT cycle_date, sleep, fatigue, workload, mood, cohesion, source FROM biometrics.checkins "
            "WHERE astronaut_id = %s AND cycle_date BETWEEN %s AND %s", (astronaut, since, day)).fetchall():
        d, *answers, source = row
        for (src, _), v in zip(CHECKIN_SOURCES.items(), answers):
            raw[src][d] = float(v)
            if source == "simulated" and d == day:
                simulated.add(src)
    for d, rt, source in conn.execute(
            "SELECT cycle_date, mean_rt_ms, source FROM biometrics.pvt_results "
            "WHERE astronaut_id = %s AND cycle_date BETWEEN %s AND %s", (astronaut, since, day)).fetchall():
        raw["pvt_mean_rt_ms"][d] = rt
        if source == "simulated" and d == day:
            simulated.add("pvt_mean_rt_ms")
    return raw, simulated


def _media_z(conn, astronaut: str, day: date) -> dict[str, dict[date, float]]:
    """z de cada puntuación frente a la línea base de esa pregunta (variable 'nlp.x@qN')."""
    since = day - timedelta(days=HISTORY_DAYS)
    base = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT variable, mean, sd FROM biometrics.baselines WHERE astronaut_id = %s AND kind = 'terrestrial' "
        "AND (variable LIKE 'nlp.%%' OR variable LIKE 'acoustic.%%')", (astronaut,)).fetchall()}
    out: dict[str, dict[date, float]] = defaultdict(dict)
    for d, q, acoustic, nlp in conn.execute(
            "SELECT cycle_date, question_id, acoustic, nlp FROM biometrics.media_results "
            "WHERE astronaut_id = %s AND kind = 'audio' AND status = 'completed' AND cycle_date BETWEEN %s AND %s",
            (astronaut, since, day)).fetchall():
        groups = {"nlp": nlp or {}, "acoustic": acoustic or {}}
        for field_name, (group, key) in MEDIA_FIELDS.items():
            value = groups[group].get(key)
            mean_sd = base.get(f"{group}.{key}@q{q}") or base.get(f"{group}.{key}")
            if value is None or not mean_sd or mean_sd[1] <= 0:
                continue
            out[field_name][d] = (float(value) - mean_sd[0]) / mean_sd[1]
    return out


def _update_welford(conn, astronaut: str, day: date, raw: dict[str, dict[date, float]]) -> None:
    for variable, series in raw.items():
        if day not in series:
            continue
        row = conn.execute(
            "SELECT n, mean, m2, last_date FROM biometrics.welford_state WHERE astronaut_id = %s AND variable = %s",
            (astronaut, variable)).fetchone()
        acc = Welford(*row) if row else Welford()
        new = acc.add(series[day], on=day)
        if new is acc:
            continue
        conn.execute(
            "INSERT INTO biometrics.welford_state (astronaut_id, variable, n, mean, m2, last_date) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (astronaut_id, variable) DO UPDATE SET "
            "n = EXCLUDED.n, mean = EXCLUDED.mean, m2 = EXCLUDED.m2, last_date = EXCLUDED.last_date, updated_at = now()",
            (astronaut, variable, new.n, new.mean, new.m2, new.last_date))


def _store_vector(conn, v: CollapsedVector) -> None:
    conn.execute(
        "INSERT INTO biometrics.daily_vector (astronaut_id, cycle_date, schema_version, vector, missing_mask, "
        "simulated_mask, embedding) VALUES (%s, %s, %s, %s, %s, %s, %s::vector) "
        "ON CONFLICT (astronaut_id, cycle_date) DO UPDATE SET schema_version = EXCLUDED.schema_version, "
        "vector = EXCLUDED.vector, missing_mask = EXCLUDED.missing_mask, simulated_mask = EXCLUDED.simulated_mask, "
        "embedding = EXCLUDED.embedding, created_at = now()",
        (v.astronaut_id, v.cycle_date, v.schema_version, v.to_bytes(), v.missing_mask, v.simulated_mask,
         "[" + ",".join(f"{x:.6g}" for x in v.embedding()) + "]"))


def _history(conn, astronaut: str, day: date) -> dict[date, tuple[float, ...]]:
    rows = conn.execute(
        "SELECT cycle_date, vector FROM biometrics.daily_vector WHERE astronaut_id = %s AND cycle_date BETWEEN %s AND %s "
        "AND schema_version = %s", (astronaut, day - timedelta(days=HISTORY_DAYS - 1), day, SCHEMA_VERSION)).fetchall()
    return {d: unpack(bytes(b)) for d, b in rows}


def _cache_windows(redis_client, astronaut: str, day: date, history: dict[date, tuple[float, ...]]) -> dict:
    windows = {}
    for f in FIELDS:
        series = {d: deterioration(f, v[f.index]) for d, v in history.items()}
        windows[f.name] = {str(w): _round_stats(window_stats(series, day, w)) for w in WINDOWS}
    if redis_client is not None:
        try:
            redis_client.set(f"orbivia:windows:{astronaut}", json.dumps({"date": day.isoformat(), "windows": windows}),
                             ex=7 * 86400)
        except Exception:  # la caché es una optimización: nunca rompe el colapso
            logger.warning("No se pudo guardar la caché de ventanas en Redis")
    return windows


def _round_stats(s: dict) -> dict:
    return {k: (None if isinstance(v, float) and math.isnan(v) else (round(v, 4) if isinstance(v, float) else v))
            for k, v in s.items()}


# --- 5: alertas, disponibilidad, acciones ------------------------------------------------


def _store_alerts(conn, astronaut: str, day: date, evaluation) -> None:
    conn.execute("DELETE FROM biometrics.alerts WHERE astronaut_id = %s AND cycle_date = %s", (astronaut, day))
    for a in evaluation.alerts:
        conn.execute(
            "INSERT INTO biometrics.alerts (astronaut_id, cycle_date, criterion, area, variables, detail, reference) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (astronaut, day, a.criterion, a.area, list(a.variables), json.dumps(a.detail), a.reference))


def _actions(conn, redis_client, astronaut: str, day: date, evaluation) -> list[dict]:
    proposed = actions_mod.actions_for(evaluation.alerts)
    severity = actions_mod.severity(evaluation.alerts)
    active = {(s, c): sev for s, c, sev in conn.execute(
        "SELECT signature, action_code, last_severity FROM biometrics.actions WHERE astronaut_id = %s AND active "
        "AND last_notified < %s", (astronaut, day)).fetchall()}
    decisions = actions_mod.apply_cooldown(proposed, severity, active)
    keep = {(d.signature, d.action_code) for d in decisions}
    for s, c in active:
        if (s, c) not in keep:
            conn.execute("UPDATE biometrics.actions SET active = false WHERE astronaut_id = %s AND signature = %s "
                         "AND action_code = %s", (astronaut, s, c))
    out = []
    for d in decisions:
        if d.notify:
            conn.execute(
                "INSERT INTO biometrics.actions (astronaut_id, signature, action_code, first_date, last_notified, "
                "last_severity, active) VALUES (%s, %s, %s, %s, %s, %s, true) "
                "ON CONFLICT (astronaut_id, signature, action_code) DO UPDATE SET last_notified = EXCLUDED.last_notified, "
                "last_severity = EXCLUDED.last_severity, active = true",
                (astronaut, d.signature, d.action_code, day, day, d.severity))
        out.append({"signature": d.signature, "action": d.action_code, "notify": d.notify, "status": d.status,
                    **actions_mod.CATALOG[d.action_code]})
    if redis_client is not None:
        try:
            redis_client.set(f"orbivia:cooldown:{astronaut}", json.dumps(out), ex=7 * 86400)
        except Exception:
            logger.warning("No se pudo guardar el estado de cooldown en Redis")
    return out


def run_daily_collapse(conn, day: date, redis_client=None) -> dict[str, Any]:
    mission = _mission(conn)
    mission_day = (day - mission["start_date"]).days + 1
    summary: dict[str, Any] = {"cycle_date": day.isoformat(), "mission_day": mission_day, "astronauts": {}}
    summary["imported"] = import_sleep_and_social(conn, day, mission)
    summary["circadian"] = compute_circadian_desync(conn, day)
    for astronaut in _astronauts(conn):
        ensure_adaptation_baseline(conn, astronaut, day, mission)
        raw, simulated = _raw_series(conn, astronaut, day)
        result = build_vector(astronaut, day, mission_day, mission["adaptation_days"], raw,
                              _baselines(conn, astronaut), _media_z(conn, astronaut, day),
                              mission["audio_interval_days"], simulated)
        _store_vector(conn, result.vector)
        _update_welford(conn, astronaut, day, raw)
        history = _history(conn, astronaut, day)
        windows = _cache_windows(redis_client, astronaut, day, history)
        evaluation = alerts_mod.evaluate(history, day, mission_day, mission["adaptation_days"])
        _store_alerts(conn, astronaut, day, evaluation)
        profile = conn.execute("SELECT social_desirability_high FROM biometrics.baseline_profile WHERE astronaut_id = %s",
                               (astronaut,)).fetchone()
        known = conn.execute("SELECT known_reason FROM biometrics.checkins WHERE astronaut_id = %s AND cycle_date = %s",
                             (astronaut, day)).fetchone()
        avail = availability_mod.compute(result.vector.values, bool(profile and profile[0]), bool(known and known[0]))
        if avail.score is not None:
            conn.execute(
                "INSERT INTO biometrics.availability (astronaut_id, cycle_date, score, reason_category, areas, audit) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (astronaut_id, cycle_date) DO UPDATE SET "
                "score = EXCLUDED.score, reason_category = EXCLUDED.reason_category, areas = EXCLUDED.areas, "
                "audit = EXCLUDED.audit, created_at = now()",
                (astronaut, day, avail.score, avail.reason_category, json.dumps(avail.areas),
                 json.dumps({**avail.audit, "vector_details": result.details, "windows": windows})))
        acts = _actions(conn, redis_client, astronaut, day, evaluation)
        summary["astronauts"][astronaut] = {
            "missing_fields": bin(result.vector.missing_mask).count("1"),
            "alerts": [f"{a.criterion}:{a.area}" for a in evaluation.alerts],
            "suppressed": len(evaluation.suppressed),
            "availability": avail.score,
            "actions_notified": [a["action"] for a in acts if a["notify"]],
            "c4": evaluation.c4,
        }
    return summary


# --- planes -------------------------------------------------------------------------------


# resting_hr es la FC en reposo despierto (PING diario), no la nocturna: el módulo de
# sueño advierte que no son equivalentes, así que no se sustituye una por otra.
PLANNER_FROM = {
    "sleep_duration_h": "sleep_duration_h", "grip_strength": "grip_strength_kg", "spo2": "spo2_pct",
    "resting_hr": "resting_hr_bpm",
}


def _latest(conn, sql: str, astronaut: str, day: date):
    """Valor de hoy o, si aún no existe (check-in pendiente), el de ayer con su antigüedad.

    Devuelve (valor, horas antes de la medianoche del día planificado) o None. La
    vigencia del planificador es de 24 h: un dato de ayer por la mañana sigue valiendo."""
    row = conn.execute(sql, (astronaut, day)).fetchone()
    if row and row[0] is not None:
        return row[0], 2.0
    row = conn.execute(sql, (astronaut, day - timedelta(days=1))).fetchone()
    if row and row[0] is not None:
        return row[0], 15.0
    return None


def _planner_states(conn, day: date, crew: list[str]) -> tuple[dict, dict]:
    states, baselines = {}, {}
    measurement = ("SELECT value FROM biometrics.measurements WHERE astronaut_id = %s AND cycle_date = %s "
                   "AND variable = '{}'")
    for a in crew:
        s: dict[str, Any] = {}
        for p, var in PLANNER_FROM.items():
            got = _latest(conn, measurement.format(var), a, day)
            if got:
                s[p] = got
        got = _latest(conn, measurement.format("sleep_efficiency"), a, day)
        if got:
            s["sleep_quality"] = (got[0] * 100 if got[0] <= 1 else got[0], got[1])
        got = _latest(conn, "SELECT lapses FROM biometrics.pvt_results WHERE astronaut_id = %s AND cycle_date = %s",
                      a, day)
        if got:
            s["pvt_lapses"] = got
        got = _latest(conn, "SELECT fatigue FROM biometrics.checkins WHERE astronaut_id = %s AND cycle_date = %s",
                      a, day)
        if got:
            s["fatigue_self"] = got
        row = conn.execute("SELECT coalesce(sum(coalesce(actual_h, planned_h)), 0) FROM operations.worked_hours "
                           "WHERE astronaut_id = %s AND work_date BETWEEN %s AND %s",
                           (a, day - timedelta(days=3), day - timedelta(days=1))).fetchone()
        s["work_hours_3d"] = float(row[0])
        states[a] = s
        b = {}
        for p, var in (("grip_strength", "grip_strength_kg"), ("resting_hr", "resting_hr_bpm"),
                       ("pvt_lapses", "pvt_lapses")):
            row = conn.execute("SELECT mean, sd FROM biometrics.baselines WHERE astronaut_id = %s AND kind = 'terrestrial' "
                               "AND variable = %s", (a, var)).fetchone()
            if row:
                b[p] = (row[0], row[1])
        baselines[a] = b
    return states, baselines


def generate_plans(conn, day: date, force: bool = False) -> dict[str, Any]:
    mission = _mission(conn)
    existing = conn.execute("SELECT count(*) FROM operations.plan_decisions WHERE plan_date = %s", (day,)).fetchone()[0]
    if existing and not force:
        return {"status": "kept", "reason": "ya hay una decisión registrada para ese día; no se regeneran los planes"}
    crew = [r[0] for r in conn.execute("SELECT astronaut_id FROM operations.crew_constraints ORDER BY astronaut_id")]
    exercise = {r[0]: r[1] for r in conn.execute(
        "SELECT astronaut_id, exercise_block FROM operations.crew_constraints WHERE cardinality(exercise_block) = 2")}
    worked = defaultdict(list)
    for a, d, h in conn.execute(
            "SELECT astronaut_id, work_date, coalesce(actual_h, planned_h, 0) FROM operations.worked_hours "
            "WHERE work_date BETWEEN %s AND %s ORDER BY work_date", (day - timedelta(days=6), day - timedelta(days=1))):
        worked[a].append(h)
    states, baselines = _planner_states(conn, day, crew)
    mission_day = (day - mission["start_date"]).days + 1
    doc = planning.generate(mission["environment"], mission_day, states, baselines, exercise, worked)
    conn.execute("DELETE FROM operations.plan_runs WHERE plan_date = %s", (day,))
    conn.execute(
        "INSERT INTO operations.plan_runs (plan_date, status, original, notes, weekly_limits) VALUES (%s, %s, %s, %s, %s)",
        (day, doc["status"], json.dumps(doc.get("original")), json.dumps(doc.get("notes", []) + (
            [c["summary"] for c in doc.get("conflicts", [])] if doc["status"] != "ok" else [])),
         json.dumps(doc.get("weekly_limits", []))))
    # Las tareas aplazadas también quedan en el registro del día
    if doc.get("deferred_tasks"):
        conn.execute("UPDATE operations.plan_runs SET notes = notes || %s::jsonb WHERE plan_date = %s",
                     (json.dumps([{"deferred_tasks": doc["deferred_tasks"]}]), day))
    for plan in doc.get("plans", []):
        conn.execute("INSERT INTO operations.plans (plan_date, option_id, label, payload) VALUES (%s, %s, %s, %s)",
                     (day, plan["option"]["id"], plan["option"]["label"], json.dumps(plan)))
    return {"status": doc["status"], "plans": [p["option"]["id"] for p in doc.get("plans", [])],
            "notes": doc.get("notes", []), "deferred_tasks": doc.get("deferred_tasks", [])}
