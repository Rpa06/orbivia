"""Comprobación de recuperación ante un reinicio de Redis, en tres fases.

Envía una noche sintética de varios astronautas en dos mitades. Entre una y otra
se reinicia (o se mata) Redis a mano. Al final se compara cada resumen con las
estadísticas exactas de los datos enviados.

    python -m sleep_stream.recovery_check first     # sesiones y primera mitad
    (reiniciar Redis mientras el worker aún procesa)
    python -m sleep_stream.recovery_check rest      # reenvío del final de la primera mitad, resto y fin
    python -m sleep_stream.recovery_check verify    # espera los resúmenes y compara

En `rest` se reenvían los últimos `--overlap` registros de la primera mitad, como
haría un sensor al reconectar: la deduplicación hace que reenviar sea inocuo.
"""

import argparse
import json
import os
import statistics
import sys
import time

import redis

from .config import load_settings
from .processor import SleepProcessor
from .simulate import night_records, profile_for
from .store import PostgresStore

METRICS = ("heart_rate", "heart_rate_variability", "spo2", "respiratory_rate", "skin_temperature", "movement")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", choices=("first", "rest", "verify"))
    parser.add_argument("--astronauts", type=int, default=5)
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--period", type=int, default=1)
    parser.add_argument("--start", type=int, default=1794672000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--session", default="SLEEP_RECOVERY")
    parser.add_argument("--overlap", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()

    client = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"),
                         port=int(os.environ.get("REDIS_PORT", "6379")))
    processor = SleepProcessor(client, PostgresStore.from_env(), load_settings(os.environ))
    duration = int(args.hours * 3600)
    crew = [f"ASTRO_{k + 1:03d}" for k in range(args.astronauts)]
    data = {a: night_records(a, args.session, args.start, duration, args.period, seed=args.seed,
                             profile=profile_for(k))[0] for k, a in enumerate(crew)}

    def send(records: list) -> None:
        for begin in range(0, len(records), 500):
            processor.submit_many(records[begin:begin + 500])

    if args.phase == "first":
        for astronaut in crew:
            processor.start_session({"astronaut_id": astronaut, "sleep_session_id": args.session,
                                     "start_timestamp": args.start, "sample_period_s": args.period})
            send(data[astronaut][:len(data[astronaut]) // 2])
        print(json.dumps({"phase": "first", "sent": sum(len(d) // 2 for d in data.values())}))
        return 0

    if args.phase == "rest":
        for astronaut in crew:
            half = len(data[astronaut]) // 2
            send(data[astronaut][max(half - args.overlap, 0):])
            processor.end_session(astronaut, args.session, args.start + duration)
        print(json.dumps({"phase": "rest", "resent_per_astronaut": args.overlap}))
        return 0

    deadline = time.monotonic() + args.timeout
    summaries = {}
    while time.monotonic() < deadline and len(summaries) < len(crew):
        for astronaut in crew:
            if astronaut not in summaries:
                summary = processor.get_summary(astronaut, args.session)
                if summary:
                    summaries[astronaut] = summary
        time.sleep(0.5)

    report = {"phase": "verify", "astronauts": {}, "ok": len(summaries) == len(crew)}
    for astronaut in crew:
        summary = summaries.get(astronaut)
        if summary is None:
            report["astronauts"][astronaut] = {"summary": "missing"}
            continue
        meta = summary["session_metadata"]
        worst = 0.0
        exact_counts = True
        for metric in METRICS:
            values = [r["metrics"][metric] for r in data[astronaut] if r["metrics"][metric] is not None]
            got = summary["metrics"][metric]
            exact_counts &= got["valid_count"] == len(values)
            exact_counts &= (got["min"], got["max"]) == (min(values), max(values))
            for key, exact in (("mean", statistics.fmean(values)), ("std", statistics.stdev(values))):
                worst = max(worst, abs(got[key] - exact) / abs(exact))
        ok = (exact_counts and worst < 1e-9 and meta["aggregates_consistent"]
              and meta["total_observations"] == len(data[astronaut]))
        report["ok"] &= ok
        report["astronauts"][astronaut] = {
            "sent": len(data[astronaut]),
            "total_observations": meta["total_observations"],
            "duplicates_ignored": meta["duplicates"],
            "counts_min_max_exact": exact_counts,
            "worst_relative_error_mean_std": worst,
            "aggregates_consistent": meta["aggregates_consistent"],
            "ok": ok,
        }
    report["pending_in_stream"] = client.xpending(processor.keys.ingest, processor.cfg.group)["pending"]
    report["dead_letters"] = client.xlen(processor.keys.dead)
    print(json.dumps(report, indent=1))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
