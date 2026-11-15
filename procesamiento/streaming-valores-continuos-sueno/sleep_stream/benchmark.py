"""Comparación medida entre guardar todo y agregar de forma incremental.

Los mismos registros sintéticos pasan por dos escenarios sobre el mismo Redis:

A. Sin agregación: cada registro se guarda en un stream por sesión y el resumen
   se calcula al final, leyendo y recorriendo todos los registros.
B. Incremental: el flujo real del módulo (ingesta, ventanas, colapso, recorte
   del stream) y el resumen a partir de los acumuladores.

    python -m sleep_stream.benchmark --astronauts 5 --hours 8 --period 1

La memoria de Redis se mide clave a clave con MEMORY USAGE (SAMPLES 0), solo
sobre las claves del benchmark. Los tiempos son de un solo proceso y un solo
consumidor. El escenario A hace de referencia exacta para medir la precisión.
"""

import argparse
import json
import math
import os
import platform
import statistics
import time
import tracemalloc
import uuid
from dataclasses import replace
from typing import Any

import redis

from .config import Settings, load_settings
from .processor import SleepProcessor
from .simulate import night_records, profile_for
from .store import MemoryStore, PostgresStore

METRICS = ("heart_rate", "heart_rate_variability", "spo2", "respiratory_rate", "skin_temperature", "movement")


def memory(client: redis.Redis, pattern: str) -> tuple[int, int]:
    """(bytes, número de claves) de las claves que casan con el patrón."""
    keys = list(client.scan_iter(match=pattern, count=1000))
    pipe = client.pipeline(transaction=False)
    for key in keys:
        pipe.memory_usage(key, samples=0)
    return sum(size or 0 for size in pipe.execute()), len(keys)


def exact_summary(records: list[dict[str, Any]], cfg: Settings, start: int, end: int) -> dict[str, Any]:
    """El resumen como lo haría el escenario A: con todos los registros en memoria."""
    out: dict[str, Any] = {"metrics": {}}
    for metric in METRICS:
        points = [(r["timestamp"], r["metrics"][metric]) for r in records if r["metrics"].get(metric) is not None]
        values = [x for _, x in points]
        ordered = sorted(values)
        mean_t = statistics.fmean(t for t, _ in points)
        mean_x = statistics.fmean(values)
        slope = (sum((t - mean_t) * (x - mean_x) for t, x in points)
                 / sum((t - mean_t) ** 2 for t, _ in points))
        out["metrics"][metric] = {
            "n": len(values), "mean": mean_x, "std": statistics.stdev(values),
            "min": ordered[0], "max": ordered[-1],
            "p05": ordered[int(0.05 * len(ordered))], "median": ordered[len(ordered) // 2],
            "p95": ordered[int(0.95 * len(ordered))], "trend_per_h": slope * 3600.0,
        }
    epoch = cfg.levels_s[0]
    minutes: dict[int, list[float]] = {}
    for r in records:
        value = r["metrics"].get(cfg.activity_metric)
        if value is not None:
            minutes.setdefault(int(r["timestamp"] // epoch), []).append(value)
    scored = active = bouts = 0
    previous = None
    for minute in range(int(start // epoch), math.ceil(end / epoch)):
        if minute not in minutes:
            previous = None
            continue
        scored += 1
        is_active = statistics.fmean(minutes[minute]) > cfg.activity_threshold
        active += is_active
        bouts += is_active and previous is not True
        previous = is_active
    out["sleep"] = {"scored_epochs": scored, "active_epochs": active, "activity_bouts": bouts}
    return out


def relative(got: float, exact: float) -> float:
    return abs(got - exact) / max(abs(exact), 1e-12)


def run(astronauts: int, hours: float, period: int, seed: int, cfg: Settings, store: Any) -> dict[str, Any]:
    client = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"),
                         port=int(os.environ.get("REDIS_PORT", "6379")))
    tag = uuid.uuid4().hex[:8]
    start = 1794672000
    duration = int(hours * 3600)
    end = start + duration
    crew = [f"BENCH{tag}_{k + 1:03d}" for k in range(astronauts)]
    session = "SLEEP_BENCH"
    data, truth = {}, {}
    for k, astronaut in enumerate(crew):
        data[astronaut], truth[astronaut] = night_records(
            astronaut, session, start, duration, period, seed=seed, profile=profile_for(k))
    total = sum(len(d) for d in data.values())
    chunk_s = 600  # se envían 10 min de datos de todos y después se procesan
    chunks = []
    for begin in range(0, duration, chunk_s):
        chunks.append([r for a in crew for r in data[a]
                       if start + begin <= r["timestamp"] < start + begin + chunk_s])

    # --- A: sin agregación -------------------------------------------------------------
    prefix_a = f"bench:{tag}:a"
    t = time.perf_counter()
    for chunk in chunks:
        pipe = client.pipeline(transaction=False)
        for r in chunk:
            pipe.xadd(f"{prefix_a}:raw:{r['astronaut_id']}", {"data": json.dumps(r)})
        pipe.execute()
    a_ingest = time.perf_counter() - t
    a_bytes, a_keys = memory(client, f"{prefix_a}:*")
    a_entries = sum(client.xlen(f"{prefix_a}:raw:{a}") for a in crew)

    exact = {}
    a_finalize = []
    tracemalloc.start()
    for astronaut in crew:
        t = time.perf_counter()
        raw = client.xrange(f"{prefix_a}:raw:{astronaut}")
        records = [json.loads(fields[b"data"]) for _, fields in raw]
        exact[astronaut] = exact_summary(records, cfg, start, end)
        a_finalize.append(time.perf_counter() - t)
        del raw, records
    a_peak_python = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    # --- B: incremental ------------------------------------------------------------------
    prefix_b = f"bench:{tag}:b"
    processor = SleepProcessor(client, store, replace(cfg, prefix=prefix_b))
    for astronaut in crew:
        processor.start_session({"astronaut_id": astronaut, "sleep_session_id": session,
                                 "start_timestamp": start, "sample_period_s": period})
    b_submit = b_process = 0.0
    b_peak_bytes = b_peak_backlog = b_peak_aggregates = 0
    for chunk in chunks:
        t = time.perf_counter()
        for begin in range(0, len(chunk), 500):
            processor.submit_many(chunk[begin:begin + 500])
        b_submit += time.perf_counter() - t
        b_peak_backlog = max(b_peak_backlog, memory(client, f"{prefix_b}:*")[0])
        t = time.perf_counter()
        processor.drain("bench")
        b_process += time.perf_counter() - t
        b_peak_bytes = max(b_peak_bytes, memory(client, f"{prefix_b}:*")[0])
        b_peak_aggregates = max(b_peak_aggregates, max(
            sum(processor.status(a, session)["stored_aggregates"].values()) for a in crew))
    b_bytes, b_keys = memory(client, f"{prefix_b}:*")
    b_aggregates = {a: processor.status(a, session)["stored_aggregates"] for a in crew}
    b_raw_left = client.xlen(processor.keys.ingest)

    b_finalize = []
    tracemalloc.start()
    for astronaut in crew:
        t = time.perf_counter()
        processor.end_session(astronaut, session, end)
        processor.process(processor.read("bench"))
        processor.finalize_ready()
        b_finalize.append(time.perf_counter() - t)
    b_peak_python = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    processor.trim()
    b_final_bytes, _ = memory(client, f"{prefix_b}:*")
    summaries = {a: processor.get_summary(a, session) for a in crew}

    # --- precisión y pérdida de información -----------------------------------------------
    errors = {"mean": 0.0, "std": 0.0, "trend": 0.0}
    quantile_bins = 0.0
    exact_extremes = exact_counts = actigraphy_equal = True
    retained: dict[str, list[float]] = {m: [] for m in METRICS}
    spikes_found = spikes_total = 0
    for astronaut in crew:
        summary, reference = summaries[astronaut], exact[astronaut]
        for metric in METRICS:
            got, want = summary["metrics"][metric], reference["metrics"][metric]
            exact_counts &= got["valid_count"] == want["n"]
            exact_extremes &= (got["min"], got["max"]) == (want["min"], want["max"])
            errors["mean"] = max(errors["mean"], relative(got["mean"], want["mean"]))
            errors["std"] = max(errors["std"], relative(got["std"], want["std"]))
            errors["trend"] = max(errors["trend"], relative(got["trend_per_h"], want["trend_per_h"]))
            width = cfg.specs[metric].bin_width
            for q in ("p05", "median", "p95"):
                quantile_bins = max(quantile_bins, abs(got[q] - want[q]) / width)
            # Varianza que explica la línea temporal final: lo que queda de la forma de la noche
            within = sum((w["metrics"][metric]["n"] - 1) * (w["metrics"][metric]["std"] or 0.0) ** 2
                         for w in summary["timeline"] if w["metrics"][metric]["n"] > 1)
            retained[metric].append(1.0 - within / ((want["n"] - 1) * want["std"] ** 2))
        actigraphy_equal &= all(summary["sleep"][k] == reference["sleep"][k] for k in reference["sleep"])
        episodes = [a for a in summary["anomalies"] if a["metric"] == "heart_rate"]
        for begin, finish in truth[astronaut]["spikes"]:
            # Un pico de 10 s puede no caer en ninguna muestra: entonces no está en los datos
            if not any(begin <= r["timestamp"] < finish and r["metrics"]["heart_rate"] is not None
                       for r in data[astronaut]):
                continue
            spikes_total += 1
            spikes_found += any(a["start_ts"] < finish and a["end_ts"] >= begin for a in episodes)

    sample = summaries[crew[0]]
    result = {
        "conditions": {
            "astronauts": astronauts, "hours": hours, "period_s": period, "seed": seed,
            "records": total, "levels_s": list(cfg.levels_s), "retain_s": list(cfg.retain_s),
            "python": platform.python_version(), "machine": platform.machine(),
            "redis": client.info("server")["redis_version"],
            "durable_store": type(store).__name__,
        },
        "A_raw": {
            "stored_records": a_entries,
            "redis_bytes": a_bytes,
            "redis_bytes_per_record": a_bytes / total,
            "ingest_s": a_ingest,
            "ingest_us_per_record": 1e6 * a_ingest / total,
            "finalize_s_per_session": statistics.fmean(a_finalize),
            "finalize_python_peak_bytes": a_peak_python,
        },
        "B_incremental": {
            "raw_records_left_in_redis": b_raw_left,
            "aggregates_per_session_end_of_night": b_aggregates[crew[0]],
            "aggregates_per_session_peak": b_peak_aggregates,
            "aggregates_per_session_final": len(sample["timeline"]),
            "redis_bytes_end_of_night": b_bytes,
            "redis_bytes_peak_after_processing": b_peak_bytes,
            "redis_bytes_peak_with_10min_backlog": b_peak_backlog,
            "redis_bytes_after_finalize": b_final_bytes,
            "submit_s": b_submit,
            "process_s": b_process,
            "process_us_per_record": 1e6 * b_process / total,
            "finalize_s_per_session": statistics.fmean(b_finalize),
            "finalize_python_peak_bytes": b_peak_python,
            "summary_json_bytes": len(json.dumps(sample)),
        },
        "comparison": {
            "redis_memory_ratio_end_of_night": a_bytes / b_bytes,
            "finalize_speedup": statistics.fmean(a_finalize) / statistics.fmean(b_finalize),
            "processing_overhead_us_per_record": 1e6 * (b_submit + b_process - a_ingest) / total,
        },
        "accuracy": {
            "counts_exact": exact_counts,
            "min_max_exact": exact_extremes,
            "actigraphy_identical": actigraphy_equal,
            "max_relative_error_mean": errors["mean"],
            "max_relative_error_std": errors["std"],
            "max_relative_error_trend": errors["trend"],
            "max_quantile_error_in_bins": quantile_bins,
        },
        "information_loss": {
            "time_resolution_s": {"A": period, "B_final": cfg.levels_s[-1]},
            "time_points_per_metric": {"A": total // astronauts, "B_final": len(sample["timeline"])},
            "variance_explained_by_final_timeline": {m: statistics.fmean(v) for m, v in retained.items()},
            "injected_spikes_kept_as_anomalies": f"{spikes_found}/{spikes_total}",
            "anomaly_episodes_per_session": statistics.fmean(len(s["anomalies"]) for s in summaries.values()),
        },
    }

    keys = list(client.scan_iter(match=f"bench:{tag}:*", count=1000))
    if keys:
        client.delete(*keys)
    if isinstance(store, PostgresStore):
        with store._connect() as connection:
            connection.execute("DELETE FROM biometrics.sleep_session_summary WHERE astronaut_id LIKE %s", (f"BENCH{tag}_%",))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark de almacenamiento y rendimiento")
    parser.add_argument("--astronauts", type=int, default=5)
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--period", type=int, default=1, help="segundos entre registros")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    store = PostgresStore.from_env() if os.environ.get("POSTGRES_HOST") else MemoryStore()
    result = run(args.astronauts, args.hours, args.period, args.seed, load_settings(os.environ), store)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
