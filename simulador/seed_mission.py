"""Simulador de misión para la demo de Orbivia: `python -m simulador.seed_mission --reset`.

TODOS LOS DATOS SON SIMULADOS. No son mediciones de astronautas ni datos de NASA.
Los valores se calibran solo de forma orientativa (p. ej. ~6-7 h de sueño en vuelo).

Genera, de forma reproducible (semilla fija):
- 4 astronautas seudonimizados (A1-A4) y 5 usuarios de demo, uno por rol, con
  contraseñas aleatorias que se imprimen una vez (o DEMO_PASSWORD si se define);
- líneas base terrestres (media, desviación y percentiles de 180 días previos
  simulados), perfil BFI-2-XS, Marlowe-Crowne, referencia DXA y NASA Cognition;
- 16 días de misión: mediciones diarias, sueño, check-in, PVT-B, ejercicio,
  horas de trabajo, proximidad social, semanales y entrevistas cada 3 días;
- casos de demostración:
    A1  nominal; omite el ejercicio los dos últimos días (intención de implementación)
    A2  deterioro progresivo durante 14 días (C2)
    A3  brecha de autopercepción: declara poco cansancio y el PVT-B empeora (C1)
    A4  señales combinadas (C3: VFC nocturna, ánimo, centralidad y desincronización)
        y registro privado del ciclo activo
- colapso de cada día con el rol del motor, planes de ayer y hoy, una elección
  registrada y un rechazo con "motivo personal".

Se ejecuta con el usuario administrador de PostgreSQL (POSTGRES_USER). El colapso
se ejecuta con el rol `orbivia_engine`, igual que en producción.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg

from colapso.stats import baseline_from
from crew_planner.catalog import load_catalog
from motor import pipeline

SEED = 20261114
ENVIRONMENT = "moon"
MISSION_DAYS = 30
ADAPTATION_DAYS = 3          # misión corta: 2-3 días de adaptación (README §1)
HISTORY_DAYS = 16            # días de misión ya transcurridos antes de hoy
AUDIO_INTERVAL = 3
CREW = ("A1", "A2", "A3", "A4")
USERS = (
    ("astro1", "astronaut", "A1"), ("astro2", "astronaut", "A2"), ("astro3", "astronaut", "A3"), ("astro4", "astronaut", "A4"),
    ("surgeon", "flight_surgeon", None), ("commander", "commander", None),
    ("earth.medical", "earth_medical", None), ("earth.mission", "earth_mission", None),
)
EXERCISE = {"A1": ["09:00", "10:00"], "A2": ["10:00", "11:00"], "A3": ["14:00", "15:00"], "A4": ["15:00", "16:00"]}

# Variable: (media de población para generar individuos, dispersión entre individuos, sd intraindividual)
PROFILE = {
    "sleep_duration_h": (7.1, 0.3, 0.4),
    "sleep_efficiency": (0.86, 0.03, 0.03),
    "sleep_midpoint_h": (3.5, 0.3, 0.35),
    "sleep_heart_rate_bpm": (56, 4, 2.5),
    "sleep_hrv_ms": (55, 8, 6),
    "grip_strength_kg": (42, 6, 1.5),
    "spo2_pct": (97.6, 0.4, 0.5),
    "resting_hr_bpm": (62, 5, 2.5),
    "social_centrality": (0.55, 0.05, 0.06),
    "circadian_desync_h": (0.35, 0.05, 0.2),
    "pvt_mean_rt_ms": (255, 15, 14),
    "pvt_lapses": (1.5, 0.5, 1.0),
    "checkin.sleep": (3.8, 0.3, 0.6),
    "checkin.fatigue": (2.3, 0.3, 0.6),
    "checkin.workload": (3.0, 0.3, 0.6),
    "checkin.mood": (3.9, 0.3, 0.55),
    "checkin.cohesion": (4.0, 0.3, 0.5),
}
MEDIA_PROFILE = {
    "nlp.neutral": (0.55, 0.08), "nlp.low_mood": (0.12, 0.05), "nlp.anxiety": (0.15, 0.05),
    "nlp.stable": (0.6, 0.08), "acoustic.f0_mean": (30.0, 1.2), "acoustic.pause_mean_s": (0.32, 0.05),
}
EXTRA_DAILY = {"weight_kg": (72, 9, 0.3), "body_temperature_c": (36.6, 0.1, 0.12),
               "blood_pressure_systolic": (118, 6, 4), "blood_pressure_diastolic": (76, 4, 3),
               "light_exposure_lux_h": (2400, 300, 250)}


def admin_connect() -> psycopg.Connection:
    return psycopg.connect(host=os.environ.get("POSTGRES_HOST", "db"), port=int(os.environ.get("POSTGRES_PORT", "5432")),
                           dbname=os.environ.get("POSTGRES_DB", "orbivia"), user=os.environ["POSTGRES_USER"],
                           password=os.environ["POSTGRES_PASSWORD"])


def engine_connect() -> psycopg.Connection:
    return psycopg.connect(host=os.environ.get("POSTGRES_HOST", "db"), port=int(os.environ.get("POSTGRES_PORT", "5432")),
                           dbname=os.environ.get("POSTGRES_DB", "orbivia"),
                           user=os.environ.get("ORBIVIA_DB_ENGINE_USER", "orbivia_engine"),
                           password=os.environ["ORBIVIA_DB_ENGINE_PASSWORD"])


def today() -> date:
    raw = os.environ.get("ORBIVIA_TODAY")
    return date.fromisoformat(raw) if raw else date.today()


def reset(conn) -> None:
    conn.execute("""
        TRUNCATE vault_identity.users, vault_identity.astronauts, operations.mission, operations.task_catalog,
                 operations.crew_constraints, operations.worked_hours, operations.plan_runs, operations.plans,
                 operations.plan_decisions, biometrics.baseline_profile, biometrics.welford_state,
                 biometrics.measurements, biometrics.checkins, biometrics.pvt_results, biometrics.weekly_double,
                 biometrics.exercise_log, biometrics.implementation_intentions, biometrics.media_results,
                 biometrics.daily_vector, biometrics.alerts, biometrics.availability, biometrics.actions,
                 biometrics.sync_log, biometrics.sleep_session_summary, biometrics.social_graph_daily_result,
                 biometrics.social_graph_checkpoint, private_cycle.entries, private_cycle.shares RESTART IDENTITY CASCADE""")
    # Las líneas base terrestres están protegidas por un trigger: solo el reset de la demo las borra
    conn.execute("ALTER TABLE biometrics.baselines DISABLE TRIGGER terrestrial_baseline_frozen")
    conn.execute("DELETE FROM biometrics.baselines")
    conn.execute("ALTER TABLE biometrics.baselines ENABLE TRIGGER terrestrial_baseline_frozen")


def individuals(rng: random.Random) -> dict[str, dict[str, tuple[float, float]]]:
    out = {}
    for a in CREW:
        out[a] = {v: (rng.gauss(m, between), within) for v, (m, between, within) in PROFILE.items()}
        out[a].update({v: (rng.gauss(m, between), within) for v, (m, between, within) in EXTRA_DAILY.items()})
    return out


def seed_identities(conn, password: str | None) -> list[tuple[str, str, str]]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from api.auth import hash_password  # misma función que usa el login

    for i, a in enumerate(CREW, start=1):
        conn.execute("INSERT INTO vault_identity.astronauts (pseudonym, real_name, simulated) VALUES (%s, %s, true)",
                     (a, f"Astronauta simulado {i}"))
    creds = []
    for username, role, astronaut in USERS:
        pw = password or secrets.token_urlsafe(9)
        conn.execute("INSERT INTO vault_identity.users (username, password_hash, role, astronaut_id) VALUES (%s, %s, %s, %s)",
                     (username, hash_password(pw), role, astronaut))
        creds.append((username, role, pw))
    return creds


def seed_mission(conn, start: date) -> None:
    conn.execute("INSERT INTO operations.mission (id, name, environment, start_date, duration_days, adaptation_days, "
                 "audio_interval_days, simulated) VALUES (1, %s, %s, %s, %s, %s, %s, true)",
                 ("Orbivia · misión lunar simulada", ENVIRONMENT, start, MISSION_DAYS, ADAPTATION_DAYS, AUDIO_INTERVAL))
    catalog = load_catalog()
    env = catalog.environments[ENVIRONMENT]
    for t in catalog.environment_tasks(ENVIRONMENT):
        conn.execute("INSERT INTO operations.task_catalog (task_id, environment, category, name, reassignable, "
                     "safety_critical) VALUES (%s, %s, %s, %s, %s, %s)",
                     (t["task_id"], ENVIRONMENT, t["category"], t["name"], t["category"] != "science",
                      bool(t["safety_critical"])))
    for a in CREW:
        conn.execute("INSERT INTO operations.crew_constraints (astronaut_id, qualifications, exercise_block, workday) "
                     "VALUES (%s, %s, %s, %s)", (a, list(env["crew"][a]), EXERCISE[a], list(env["workday"])))


def seed_baselines(conn, rng: random.Random, people) -> None:
    for a in CREW:
        for variable, (mean, sd) in people[a].items():
            sample = [rng.gauss(mean, sd) for _ in range(180)]  # 6 meses previos simulados
            b = baseline_from(sample)
            conn.execute("INSERT INTO biometrics.baselines (astronaut_id, kind, variable, mean, sd, p05, p50, p95, n, source) "
                         "VALUES (%s, 'terrestrial', %s, %s, %s, %s, %s, %s, %s, 'simulated')",
                         (a, variable, b.mean, b.sd, b.p05, b.p50, b.p95, b.n))
        for q in range(1, 9):  # línea base de cada pregunta de la entrevista
            for variable, (mean, sd) in MEDIA_PROFILE.items():
                m = rng.gauss(mean, sd * 0.3)
                sample = [rng.gauss(m, sd) for _ in range(12)]
                b = baseline_from(sample)
                conn.execute("INSERT INTO biometrics.baselines (astronaut_id, kind, variable, mean, sd, p05, p50, p95, n, "
                             "source) VALUES (%s, 'terrestrial', %s, %s, %s, %s, %s, %s, %s, 'simulated')",
                             (a, f"{variable}@q{q}", b.mean, b.sd, b.p05, b.p50, b.p95, b.n))
        conn.execute(
            "INSERT INTO biometrics.baseline_profile (astronaut_id, bfi2xs, marlowe_crowne, social_desirability_high, "
            "dxa_reference, nasa_cognition, source) VALUES (%s, %s, %s, %s, %s, %s, 'simulated')",
            (a, json.dumps({k: round(rng.uniform(2.5, 4.5), 2) for k in
                            ("extraversion", "agreeableness", "conscientiousness", "negative_emotionality", "open_mindedness")}),
             26 if a == "A3" else round(rng.uniform(10, 18)), a == "A3",
             json.dumps({"bmd_lumbar_g_cm2": round(rng.uniform(1.0, 1.3), 3), "note": "referencia terrestre, no se mide a bordo"}),
             json.dumps({"battery": "NASA Cognition (10 tests)", "accuracy": round(rng.uniform(0.85, 0.95), 3)})))


def clamp_rating(x: float) -> int:
    return int(min(5, max(1, round(x))))


def day_values(a: str, k: int, rng: random.Random, people) -> dict[str, float]:
    """Valores del día de misión k (1..) para el astronauta a, con sus escenarios."""
    p = people[a]
    v = {name: rng.gauss(mean, sd) for name, (mean, sd) in p.items()}
    # Adaptación: los primeros días el sueño y la FC cambian algo en todos
    if k <= ADAPTATION_DAYS:
        v["sleep_duration_h"] -= 0.4
        v["sleep_heart_rate_bpm"] += 2
    # A2: deterioro progresivo durante los últimos 14 días, sin cruzar 2σ al principio
    if a == "A2" and k >= 3:
        t = k - 2
        sd = lambda n: p[n][1]
        v["sleep_duration_h"] -= 0.11 * t * sd("sleep_duration_h")
        v["grip_strength_kg"] -= 0.12 * t * sd("grip_strength_kg")
        v["pvt_mean_rt_ms"] += 0.11 * t * sd("pvt_mean_rt_ms")
        v["sleep_hrv_ms"] -= 0.1 * t * sd("sleep_hrv_ms")
    # A3: brecha de autopercepción desde el día 12: rinde mucho peor y declara estar bien
    if a == "A3" and k >= 12:
        v["pvt_mean_rt_ms"] = p["pvt_mean_rt_ms"][0] + 3.2 * p["pvt_mean_rt_ms"][1] + rng.gauss(0, 4)
        v["pvt_lapses"] = 6 + rng.randint(0, 2)
        v["checkin.fatigue"] = p["checkin.fatigue"][0] - 0.8
    # A4: varias señales empeoran a la vez, ninguna sobre 2σ (últimos 3 días)
    if a == "A4" and k >= HISTORY_DAYS - 2:
        for name, z in (("sleep_hrv_ms", -1.4), ("checkin.mood", -1.4), ("social_centrality", -1.6),
                        ("sleep_midpoint_h", +1.5)):
            v[name] = p[name][0] + z * p[name][1] * (1 if name != "sleep_midpoint_h" else 1.6)
    return v


def seed_days(conn, rng: random.Random, people, start: date, last_day: int, include_checkin_today: bool) -> None:
    for k in range(1, last_day + 1):
        day = start + timedelta(days=k - 1)
        is_today = day == today()
        for a in CREW:
            v = day_values(a, k, rng, people)
            for variable, unit, freq in (
                    ("sleep_duration_h", "h", "daily"), ("sleep_efficiency", "0-1", "daily"),
                    ("sleep_midpoint_h", "h", "daily"), ("sleep_heart_rate_bpm", "bpm", "continuous"),
                    ("sleep_hrv_ms", "ms", "continuous"), ("grip_strength_kg", "kg", "daily"),
                    ("spo2_pct", "%", "daily"), ("resting_hr_bpm", "bpm", "daily"),
                    ("social_centrality", "0-1", "daily"), ("weight_kg", "kg", "daily"),
                    ("body_temperature_c", "°C", "continuous"), ("blood_pressure_systolic", "mmHg", "continuous"),
                    ("blood_pressure_diastolic", "mmHg", "continuous"), ("light_exposure_lux_h", "lux·h", "continuous")):
                value = v[variable]
                if variable == "sleep_efficiency":
                    value = min(0.99, max(0.5, value))
                conn.execute("INSERT INTO biometrics.measurements (astronaut_id, cycle_date, variable, value, unit, "
                             "frequency, source) VALUES (%s, %s, %s, %s, %s, %s, 'simulated')",
                             (a, day, variable, round(value, 4), unit, freq))
            conn.execute("INSERT INTO biometrics.measurements (astronaut_id, cycle_date, variable, value, unit, frequency, "
                         "source) VALUES (%s, %s, 'radiation_mSv_cumulative', %s, 'mSv', 'daily', 'simulated')",
                         (a, day, round(0.55 * k + rng.uniform(-0.02, 0.02), 3)))
            if k % 7 == 0:
                for variable, unit, value in (("lung_capacity_l", "L", rng.gauss(5.2, 0.2)),
                                              ("panas_positive", "10-50", rng.gauss(36, 3)),
                                              ("panas_negative", "10-50", rng.gauss(15, 2))):
                    conn.execute("INSERT INTO biometrics.measurements (astronaut_id, cycle_date, variable, value, unit, "
                                 "frequency, source) VALUES (%s, %s, %s, %s, %s, 'weekly', 'simulated')",
                                 (a, day, variable, round(value, 3), unit))
            if is_today and not include_checkin_today:
                continue  # el check-in, el PVT-B y el ejercicio de hoy se hacen en directo en la demo
            conn.execute("INSERT INTO biometrics.checkins (astronaut_id, cycle_date, sleep, fatigue, workload, mood, "
                         "cohesion, known_reason, source) VALUES (%s, %s, %s, %s, %s, %s, %s, false, 'simulated')",
                         (a, day, clamp_rating(v["checkin.sleep"]), clamp_rating(v["checkin.fatigue"]),
                          clamp_rating(v["checkin.workload"]), clamp_rating(v["checkin.mood"]),
                          clamp_rating(v["checkin.cohesion"])))
            conn.execute("INSERT INTO biometrics.pvt_results (astronaut_id, cycle_date, mean_rt_ms, lapses, false_starts, "
                         "trials, duration_s, source) VALUES (%s, %s, %s, %s, %s, %s, 180, 'simulated')",
                         (a, day, round(v["pvt_mean_rt_ms"], 1), max(0, round(v["pvt_lapses"])), rng.randint(0, 1),
                          rng.randint(85, 100)))
            skipped = a == "A1" and k >= last_day - 1
            conn.execute("INSERT INTO biometrics.exercise_log (astronaut_id, cycle_date, done, minutes, source) "
                         "VALUES (%s, %s, %s, %s, 'simulated')", (a, day, not skipped, None if skipped else 60))
            conn.execute("INSERT INTO operations.worked_hours (astronaut_id, work_date, planned_h, actual_h, source) "
                         "VALUES (%s, %s, %s, %s, 'simulated')",
                         (a, day, 8.0, round(rng.uniform(7.5, 9.0) if a != "A2" else rng.uniform(8.2, 9.8), 2)))
            if (k - 1) % AUDIO_INTERVAL == 0:
                q = ((k - 1) // AUDIO_INTERVAL) % 8 + 1
                nlp = {key.split(".")[1]: round(min(1, max(0, rng.gauss(*MEDIA_PROFILE[key]))), 4)
                       for key in MEDIA_PROFILE if key.startswith("nlp.")}
                acoustic = {"f0_mean": round(rng.gauss(*MEDIA_PROFILE["acoustic.f0_mean"]), 3),
                            "pause_mean_s": round(rng.gauss(*MEDIA_PROFILE["acoustic.pause_mean_s"]), 4)}
                if a == "A4" and k >= HISTORY_DAYS - 3:
                    acoustic["pause_mean_s"] = round(MEDIA_PROFILE["acoustic.pause_mean_s"][0] + 0.07, 4)
                # Coherente con ENABLE_NLP: si el NLP está desactivado no hay puntuaciones de texto
                nlp_json = json.dumps(nlp) if os.environ.get("ENABLE_NLP", "false").lower() in ("1", "true", "yes") else None
                conn.execute("INSERT INTO biometrics.media_results (job_id, astronaut_id, cycle_date, kind, question_id, "
                             "status, acoustic, nlp, completed_at) VALUES (gen_random_uuid(), %s, %s, 'audio', %s, "
                             "'completed', %s, %s, now())", (a, day, q, json.dumps(acoustic), nlp_json))
        if k % 7 == 0:
            iso = day.isocalendar()
            for a in CREW:
                cohesion = 4 if a != "A4" else 2
                conn.execute("INSERT INTO biometrics.weekly_double (astronaut_id, iso_year, iso_week, cohesion, "
                             "predicted_team_mean, source) VALUES (%s, %s, %s, %s, %s, 'simulated') ON CONFLICT DO NOTHING",
                             (a, iso[0], iso[1], cohesion, 4 if a != "A4" else 3))


def seed_cycle(conn, start: date, key: str) -> None:
    """Registro privado de A4 (simulado). Cifrado con la misma clave que usa la API."""
    pattern = [("menstrual", "medium", ["pain", "fatigue"]), ("menstrual", "light", ["pain"]),
               ("follicular", "none", []), ("ovulatory", "none", ["headache"]),
               ("luteal", "none", ["sleep", "mood"]), ("luteal", "none", ["sleep"])]
    for k in range(0, HISTORY_DAYS + 12, 4):
        phase, flow, symptoms = pattern[(k // 4) % len(pattern)]
        payload = {"phase": phase, "flow": flow, "symptoms": symptoms, "unexpected_bleeding": k == 20,
                   "note": "registro simulado"}
        conn.execute("INSERT INTO private_cycle.entries (astronaut_id, entry_date, payload) "
                     "VALUES ('A4', %s, pgp_sym_encrypt(%s, %s))",
                     (start - timedelta(days=12) + timedelta(days=k), json.dumps(payload), key))


def collapse_all(start: date, last_day: int) -> list[dict]:
    summaries = []
    for k in range(1, last_day + 1):
        day = start + timedelta(days=k - 1)
        with engine_connect() as conn:
            summaries.append(pipeline.run_daily_collapse(conn, day))
    return summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Siembra una misión simulada de Orbivia (datos ficticios)")
    parser.add_argument("--reset", action="store_true", help="borra los datos de demo existentes")
    parser.add_argument("--credentials-file", default=os.environ.get("DEMO_CREDENTIALS_FILE"),
                        help="además, escribe las credenciales de demo en este fichero")
    parser.add_argument("--checkin-today", action="store_true", help="simula también el check-in de hoy")
    args = parser.parse_args(argv)
    key = os.environ.get("CYCLE_ENCRYPTION_KEY", "")
    if len(key) < 32:
        print("Falta CYCLE_ENCRYPTION_KEY (mínimo 32 caracteres)", file=sys.stderr)
        return 1
    rng = random.Random(SEED)
    start = today() - timedelta(days=HISTORY_DAYS)
    last_day = HISTORY_DAYS + 1  # hoy incluido (sin check-in salvo --checkin-today)
    with admin_connect() as conn:
        if conn.execute("SELECT 1 FROM operations.mission").fetchone() and not args.reset:
            print("Ya hay una misión sembrada. Usa --reset para regenerarla.", file=sys.stderr)
            return 2
        reset(conn)
        creds = seed_identities(conn, os.environ.get("DEMO_PASSWORD"))
        seed_mission(conn, start)
        people = individuals(rng)
        seed_baselines(conn, rng, people)
        seed_days(conn, rng, people, start, last_day, args.checkin_today)
        seed_cycle(conn, start, key)
    summaries = collapse_all(start, last_day)
    yesterday, now = today() - timedelta(days=1), today()
    with engine_connect() as conn:
        plans_yesterday = pipeline.generate_plans(conn, yesterday)
        plans_today = pipeline.generate_plans(conn, now)
        plans_before = pipeline.generate_plans(conn, yesterday - timedelta(days=1))
    with admin_connect() as conn:
        if plans_yesterday.get("plans"):
            conn.execute("INSERT INTO operations.plan_decisions (plan_date, decision, option_id, reason_category, "
                         "reason_text, decided_by_role) VALUES (%s, 'selected', %s, 'none', NULL, 'commander')",
                         (yesterday, plans_yesterday["plans"][min(1, len(plans_yesterday["plans"]) - 1)]))
        if plans_before.get("plans"):
            conn.execute("INSERT INTO operations.plan_decisions (plan_date, decision, option_id, reason_category, "
                         "reason_text, decided_by_role) VALUES (%s, 'rejected_all', NULL, 'personal', 'motivo personal', "
                         "'astronaut')", (yesterday - timedelta(days=1),))

    last = summaries[-1]
    print("== Misión simulada sembrada (DATOS FICTICIOS) ==")
    print(f"Inicio {start}  ·  hoy es el día {last['mission_day']}  ·  adaptación {ADAPTATION_DAYS} días")
    for a, s in last["astronauts"].items():
        print(f"  {a}: disponibilidad {s['availability']}  avisos {s['alerts'] or '-'}")
    alerts_seen = sorted({al for s in summaries for st in s["astronauts"].values() for al in st["alerts"]})
    print("Avisos durante la misión:", ", ".join(alerts_seen) or "ninguno")
    print(f"Planes: ayer {plans_yesterday.get('status')} {plans_yesterday.get('plans')}, "
          f"hoy {plans_today.get('status')} {plans_today.get('plans')}")
    lines = [f"{u:<14} {r:<15} {pw}" for u, r, pw in creds]
    print("\nCredenciales de demo (se muestran una sola vez; no son secretos reales):")
    print("\n".join("  " + l for l in lines))
    if args.credentials_file:
        path = Path(args.credentials_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Credenciales de la demo de Orbivia (datos simulados)\n" + "\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        print(f"Guardadas también en {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
