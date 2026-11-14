"""Utilidades comunes de la API."""

from __future__ import annotations

import math
import os
from datetime import date

from fastapi import HTTPException

# Variables que se pueden ingerir por API (canales del README §3). `validated` dice si
# la medición a bordo está validada instrumentalmente; las que no, se marcan como tales.
MEASUREMENT_REGISTRY = {
    # PING diario
    "grip_strength_kg": ("kg", "daily", True),
    "weight_kg": ("kg", "daily", False),
    "spo2_pct": ("%", "daily", True),
    "resting_hr_bpm": ("bpm", "daily", True),
    "radiation_mSv_cumulative": ("mSv", "daily", True),
    "red_blood_cells_10e12_L": ("10^12/L", "daily", False),
    # sueño y continuos (si no llegan por el módulo de sueño)
    "sleep_duration_h": ("h", "daily", True),
    "sleep_efficiency": ("0-1", "daily", True),
    "sleep_midpoint_h": ("h", "daily", True),
    "sleep_heart_rate_bpm": ("bpm", "continuous", True),
    "sleep_hrv_ms": ("ms", "continuous", True),
    "light_exposure_lux_h": ("lux·h", "continuous", True),
    "body_temperature_c": ("°C", "continuous", True),
    "blood_pressure_systolic": ("mmHg", "continuous", True),
    "blood_pressure_diastolic": ("mmHg", "continuous", True),
    "eeg_alpha_rel": ("0-1", "continuous", False),
    # semanales y mensuales
    "lung_capacity_l": ("L", "weekly", True),
    "panas_positive": ("10-50", "weekly", True),
    "panas_negative": ("10-50", "weekly", True),
    "poms_tmd": ("puntos", "weekly", True),
    "psqi_global": ("0-21", "monthly", True),
    "team_climate_inventory": ("1-5", "monthly", True),
    # dinámica social (seudonimizada)
    "social_centrality": ("0-1", "daily", True),
    "leisure_isolated_ratio": ("0-1", "daily", True),
}

# Las que todavía no se pueden medir a bordo (README §3): configurables
PENDING_VALIDATION = {k for k, (_, _, ok) in MEASUREMENT_REGISTRY.items() if not ok}


def today() -> date:
    raw = os.environ.get("ORBIVIA_TODAY")
    return date.fromisoformat(raw) if raw else date.today()


def parse_day(value: str | None) -> date:
    if value in (None, "", "today"):
        return today()
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Fecha en formato AAAA-MM-DD") from error


def mission(conn) -> dict:
    row = conn.execute("SELECT name, environment, start_date, duration_days, adaptation_days, audio_interval_days, "
                       "simulated FROM operations.mission WHERE id = 1").fetchone()
    if row is None:
        raise HTTPException(status_code=409, detail="No hay misión configurada: ejecuta seed_mission.py")
    keys = ("name", "environment", "start_date", "duration_days", "adaptation_days", "audio_interval_days", "simulated")
    return dict(zip(keys, row))


def mission_day(conn, day: date) -> int:
    return (day - mission(conn)["start_date"]).days + 1


def clean(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value
