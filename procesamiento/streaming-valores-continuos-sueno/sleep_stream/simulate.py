"""Datos biométricos sintéticos de una noche y simulación de varios astronautas.

Los datos son inventados y solo sirven para probar el sistema: no proceden de
astronautas reales ni pretenden ser fisiológicamente exactos.

Uso (con Redis accesible):

    python -m sleep_stream.simulate --astronauts 5 --hours 8 --period 1
"""

import argparse
import json
import math
import os
import random
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Profile:
    heart_rate: float = 58.0
    heart_rate_variability: float = 70.0
    spo2: float = 97.5
    respiratory_rate: float = 14.0
    skin_temperature: float = 33.8


def profile_for(index: int) -> Profile:
    """Perfiles distintos entre astronautas, para comprobar que no se mezclan."""
    return Profile(
        heart_rate=52.0 + 4.0 * index,
        heart_rate_variability=85.0 - 6.0 * index,
        spo2=98.0 - 0.3 * index,
        respiratory_rate=12.5 + 0.7 * index,
        skin_temperature=33.4 + 0.2 * index,
    )


def night_records(
    astronaut_id: str,
    session_id: str,
    start_ts: int,
    duration_s: int,
    period_s: int = 1,
    seed: int = 0,
    profile: Profile | None = None,
    dropout: float = 0.01,
    missing_rate: float = 0.01,
    bouts: int = 6,
    spikes: int = 3,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Registros de una noche, en orden, y lo que se inyectó (rachas y picos).

    `dropout`: probabilidad de que un registro entero no exista.
    `missing_rate`: probabilidad de que una métrica falte en un registro.
    `bouts`: rachas de movimiento de 1 a 4 minutos.
    `spikes`: picos breves de frecuencia cardíaca, que deben verse como anomalías.
    """
    rng = random.Random(f"{seed}:{astronaut_id}:{session_id}")
    profile = profile or Profile()
    steps = duration_s // period_s

    bout_spans = []
    for _ in range(bouts):
        begin = rng.randrange(600, max(duration_s - 600, 601))
        bout_spans.append((begin, begin + rng.randrange(60, 240)))
    spike_spans = []
    for _ in range(spikes):
        begin = rng.randrange(1800, max(duration_s - 600, 1801))
        spike_spans.append((begin, begin + 10))

    records = []
    noise = {"hr": 0.0, "hrv": 0.0, "rr": 0.0}
    for step in range(steps):
        offset = step * period_s
        # El ruido correlacionado avanza aunque el registro se pierda
        for key, scale in (("hr", 0.6), ("hrv", 1.5), ("rr", 0.15)):
            noise[key] = 0.95 * noise[key] + rng.gauss(0.0, scale)
        if rng.random() < dropout:
            continue
        night = math.sin(math.pi * offset / duration_s)  # 0 al acostarse, 1 a media noche
        moving = any(a <= offset < b for a, b in bout_spans)
        spiking = any(a <= offset < b for a, b in spike_spans)
        metrics: dict[str, Any] = {
            "heart_rate": round(profile.heart_rate - 6.0 * night + noise["hr"]
                                + (8.0 if moving else 0.0) + (45.0 if spiking else 0.0), 1),
            "heart_rate_variability": round(max(profile.heart_rate_variability + 10.0 * night
                                                + noise["hrv"] - (12.0 if moving else 0.0), 5.0), 1),
            "spo2": round(min(profile.spo2 + rng.gauss(0.0, 0.3), 100.0), 1),
            "respiratory_rate": round(profile.respiratory_rate - 1.5 * night + noise["rr"], 1),
            "skin_temperature": round(profile.skin_temperature + 0.4 * night + rng.gauss(0.0, 0.03), 2),
            "movement": round(abs(rng.gauss(0.8, 0.2)) if moving else abs(rng.gauss(0.03, 0.02)), 3),
        }
        for name in list(metrics):
            if rng.random() < missing_rate:
                metrics[name] = None
        records.append({
            "astronaut_id": astronaut_id,
            "sleep_session_id": session_id,
            "timestamp": start_ts + offset,
            "metrics": metrics,
        })
    truth = {
        "bouts": [(start_ts + a, start_ts + b) for a, b in bout_spans],
        "spikes": [(start_ts + a, start_ts + b) for a, b in spike_spans],
    }
    return records, truth


def main() -> None:
    import redis

    from .config import load_settings
    from .processor import SleepProcessor
    from .store import MemoryStore, PostgresStore

    parser = argparse.ArgumentParser(description="Simula una noche de varios astronautas")
    parser.add_argument("--astronauts", type=int, default=5)
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--period", type=int, default=1, help="segundos entre registros")
    parser.add_argument("--start", type=int, default=1794672000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--session", default="SLEEP_SIM_001")
    parser.add_argument("--no-worker", action="store_true",
                        help="solo envía los datos; los procesa el servicio worker-stream")
    args = parser.parse_args()

    client = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"),
                         port=int(os.environ.get("REDIS_PORT", "6379")))
    store = PostgresStore.from_env() if os.environ.get("POSTGRES_HOST") else MemoryStore()
    processor = SleepProcessor(client, store, load_settings(os.environ))
    duration = int(args.hours * 3600)
    crew = [f"ASTRO_{k + 1:03d}" for k in range(args.astronauts)]

    def produce(index: int, astronaut: str) -> None:
        records, _ = night_records(astronaut, args.session, args.start, duration, args.period,
                                   seed=args.seed, profile=profile_for(index))
        processor.start_session({"astronaut_id": astronaut, "sleep_session_id": args.session,
                                 "start_timestamp": args.start, "sample_period_s": args.period})
        for begin in range(0, len(records), 500):
            processor.submit_many(records[begin:begin + 500])
        processor.end_session(astronaut, args.session, args.start + duration)

    threads = [threading.Thread(target=produce, args=(k, a)) for k, a in enumerate(crew)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if args.no_worker:
        print(f"Enviadas las sesiones de {len(crew)} astronautas; las procesa worker-stream")
        return

    processor.drain("simulator")
    for astronaut in crew:
        summary = processor.get_summary(astronaut, args.session)
        meta = summary["session_metadata"]
        print(json.dumps({
            "astronaut_id": astronaut,
            "observations": meta["total_observations"],
            "anomalies": meta["anomalies_count"],
            "vector": {k: None if v is None else round(v, 3)
                       for k, v in summary["sleep_summary_vector"].items()},
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
