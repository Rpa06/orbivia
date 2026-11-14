"""Interactive command line for daily check-ins and weekly comparisons."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from checkin import CheckIn, compare_weekly_team_means, load_checkins, save_checkin


DEFAULT_STORAGE = Path(__file__).with_name("respuestas.jsonl")


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Usa el formato de fecha AAAA-MM-DD.") from error


def _ask_rating(question: str) -> int:
    while True:
        answer = input(f"{question} (1-5): ").strip()
        try:
            rating = int(answer)
        except ValueError:
            print("Introduce un número entero del 1 al 5.")
            continue
        if 1 <= rating <= 5:
            return rating
        print("La respuesta debe estar entre 1 y 5.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check-in diario de preguntas cerradas.")
    commands = parser.add_subparsers(dest="command", required=True)

    checkin = commands.add_parser("check-in", help="Registrar el check-in diario.")
    checkin.add_argument("--participant", required=True, help="Alias seudónimo del participante.")
    checkin.add_argument("--date", type=_parse_date, default=date.today())
    checkin.add_argument("--weekly", action="store_true", help="Añadir la estimación semanal del equipo.")
    checkin.add_argument("--storage", type=Path, default=DEFAULT_STORAGE)

    compare = commands.add_parser("compare", help="Comparar estimaciones con la media de compañeros.")
    compare.add_argument("--date", type=_parse_date, required=True, help="Fecha de la semana a comparar.")
    compare.add_argument("--storage", type=Path, default=DEFAULT_STORAGE)
    return parser


def _run_checkin(args: argparse.Namespace) -> None:
    print("Check-in diario (1 = peor, 5 = mejor)")
    sleep_quality = _ask_rating("¿Cómo has dormido esta noche? (1 fatal, 5 genial)")
    rested = _ask_rating("¿Cómo de descansado te sientes ahora? (1 agotado, 5 muy descansado)")
    workload = _ask_rating("¿Cómo llevas la carga de trabajo? (1 me supera, 5 muy bien)")
    mood = _ask_rating("¿Cómo estás de ánimo? (1 muy bajo, 5 muy bien)")
    team_cohesion = _ask_rating("¿Cómo va la convivencia con el equipo? (1 muy mal, 5 muy bien)")
    estimate = None
    if args.weekly:
        estimate = _ask_rating("¿Qué nota crees que pondrá de media el resto del equipo?")

    checkin = CheckIn(
        participant_id=args.participant,
        date=args.date,
        sleep_quality=sleep_quality,
        rested=rested,
        workload=workload,
        mood=mood,
        team_cohesion=team_cohesion,
        estimated_team_mean=estimate,
    )
    save_checkin(args.storage, checkin)
    print(f"Check-in guardado en {args.storage}.")
    print("Ahora puedes continuar con el PVT-B.")


def _run_comparison(args: argparse.Namespace) -> None:
    comparisons = compare_weekly_team_means(load_checkins(args.storage), args.date)
    if not comparisons:
        print("Aún no hay suficientes respuestas semanales de compañeros para comparar.")
        return

    print("Comparación semanal (solo media del resto; sin mostrar respuestas individuales)")
    for result in comparisons:
        print(
            f"{result.participant_id}: estimación {result.predicted_mean}, "
            f"media del resto {result.actual_peer_mean:.1f}, "
            f"diferencia {result.difference:+.1f} "
            f"({result.peers_count} compañeros)"
        )


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "check-in":
            _run_checkin(args)
        else:
            _run_comparison(args)
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
