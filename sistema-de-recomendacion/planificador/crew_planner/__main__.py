"""Línea de comandos: python -m crew_planner entrada.json [--config f.toml] [--out plan.json]

Por defecto propone varios planes alternativos (alternatives.count en la configuración);
con --plans 1 devuelve un único plan.

El grafo social no se lee nunca: no es una entrada del planificador.

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
from .options import plan_options
from .planner import plan_day
from .report import CREW, GROUND, render_html, render_options_html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crew_planner", description="Planificación diaria de tareas")
    parser.add_argument("input", help="fichero JSON con la entrada del día")
    parser.add_argument("--config", help="fichero TOML (por defecto config/default.toml o CP_CONFIG_FILE)")
    parser.add_argument("--out", help="fichero de salida; por defecto, la salida estándar")
    parser.add_argument("--plans", type=int,
                        help="número de planes alternativos (por defecto alternatives.count; 1 = un solo plan)")
    parser.add_argument("--html", help="además, informe visual en HTML (para Tierra)")
    parser.add_argument("--html-crew", help="además, informe HTML para la tripulación: solo el horario")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config, env=os.environ)
        problem, warnings = load_input(args.input, config)
    except (ValidationError, OSError) as error:
        print(f"Entrada inválida: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"Aviso: {warning}", file=sys.stderr)

    count = args.plans or config.alternatives.count
    if not 1 <= count <= len(config.alternatives.profiles):
        print(f"--plans debe estar entre 1 y {len(config.alternatives.profiles)}", file=sys.stderr)
        return 1
    if count == 1:
        plan, render = plan_day(problem, config), render_html
    else:
        plan, render = plan_options(problem, config, count), render_options_html
    text = json.dumps(plan, indent=1, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    elif not (args.html or args.html_crew):
        print(text)
    if args.html or args.html_crew:
        raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
        for path, audience in ((args.html, GROUND), (args.html_crew, CREW)):
            if path:
                Path(path).write_text(render(plan, raw, audience), encoding="utf-8")
                print(f"Informe ({audience}): {path}", file=sys.stderr)
    return 0 if plan["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
