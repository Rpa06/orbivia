"""Línea de comandos: python -m crew_planner entrada.json [--config f.toml] [--out plan.json]

Códigos de salida: 0 plan generado, 2 sin solución factible o sin tiempo, 1 entrada inválida.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from .config import load_config
from .inputs import load_input
from .model import ValidationError
from .planner import plan_day


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crew_planner", description="Planificación diaria de tareas")
    parser.add_argument("input", help="fichero JSON con la entrada del día")
    parser.add_argument("--config", help="fichero TOML (por defecto config/default.toml o CP_CONFIG_FILE)")
    parser.add_argument("--out", help="fichero de salida; por defecto, la salida estándar")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config, env=os.environ)
        problem, warnings = load_input(args.input, config)
    except (ValidationError, OSError) as error:
        print(f"Entrada inválida: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"Aviso: {warning}", file=sys.stderr)

    plan = plan_day(problem, config)
    text = json.dumps(plan, indent=1, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0 if plan["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
