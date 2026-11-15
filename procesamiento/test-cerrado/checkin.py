"""Daily closed-question check-ins and weekly peer-mean comparisons."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CheckIn:
    participant_id: str
    date: date
    sleep_quality: int
    rested: int
    workload: int
    mood: int
    team_cohesion: int
    estimated_team_mean: int | None = None

    def __post_init__(self) -> None:
        if not self.participant_id.strip():
            raise ValueError("El identificador del participante no puede estar vacío.")
        for field in (
            "sleep_quality",
            "rested",
            "workload",
            "mood",
            "team_cohesion",
        ):
            _validate_rating(field, getattr(self, field))
        if self.estimated_team_mean is not None:
            _validate_rating("estimated_team_mean", self.estimated_team_mean)

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        record["date"] = self.date.isoformat()
        return record

    @classmethod
    def from_record(cls, record: dict[str, object]) -> CheckIn:
        participant_id = record.get("participant_id")
        date_value = record.get("date")
        if not isinstance(participant_id, str) or not isinstance(date_value, str):
            raise ValueError("participant_id y date deben ser cadenas.")
        estimated_team_mean = record.get("estimated_team_mean")
        return cls(
            participant_id=participant_id,
            date=date.fromisoformat(date_value),
            sleep_quality=_record_rating(record, "sleep_quality"),
            rested=_record_rating(record, "rested"),
            workload=_record_rating(record, "workload"),
            mood=_record_rating(record, "mood"),
            team_cohesion=_record_rating(record, "team_cohesion"),
            estimated_team_mean=(
                None
                if estimated_team_mean is None
                else _record_rating(record, "estimated_team_mean")
            ),
        )


@dataclass(frozen=True)
class PeerComparison:
    participant_id: str
    predicted_mean: int
    actual_peer_mean: float
    difference: float
    peers_count: int


def _validate_rating(field: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValueError(f"{field} debe ser un número entero entre 1 y 5.")


def _record_rating(record: dict[str, object], field: str) -> int:
    value = record.get(field)
    _validate_rating(field, value)
    return value


def load_checkins(storage_path: Path) -> list[CheckIn]:
    if not storage_path.exists():
        return []

    checkins: list[CheckIn] = []
    with storage_path.open(encoding="utf-8") as storage:
        for line_number, line in enumerate(storage, start=1):
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("el registro debe ser un objeto JSON")
                checkins.append(CheckIn.from_record(record))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Registro inválido en {storage_path}, línea {line_number}: {error}"
                ) from error
    return checkins


def save_checkin(storage_path: Path, checkin: CheckIn) -> None:
    existing = load_checkins(storage_path)
    if any(
        entry.participant_id == checkin.participant_id and entry.date == checkin.date
        for entry in existing
    ):
        raise ValueError("Ya existe un check-in de esta persona para esa fecha.")

    if checkin.estimated_team_mean is not None and any(
        entry.participant_id == checkin.participant_id
        and entry.estimated_team_mean is not None
        and _iso_week(entry.date) == _iso_week(checkin.date)
        for entry in existing
    ):
        raise ValueError("Ya existe una respuesta semanal de esta persona para esa semana.")

    storage_path.parent.mkdir(parents=True, exist_ok=True)
    # TODO: Integrar con el almacenamiento temporal propio del módulo para comparar
    # respuestas semanales sin depender de este archivo local JSONL.
    with storage_path.open("a", encoding="utf-8") as storage:
        storage.write(json.dumps(checkin.to_record(), ensure_ascii=False) + "\n")


def compare_weekly_team_means(
    checkins: Iterable[CheckIn], week_of: date
) -> list[PeerComparison]:
    target_week = _iso_week(week_of)
    submissions = [
        entry
        for entry in checkins
        if entry.estimated_team_mean is not None and _iso_week(entry.date) == target_week
    ]

    participant_ids = [entry.participant_id for entry in submissions]
    if len(participant_ids) != len(set(participant_ids)):
        raise ValueError("Hay más de una respuesta semanal por participante.")

    comparisons: list[PeerComparison] = []
    for submission in submissions:
        peer_ratings = [
            entry.team_cohesion
            for entry in submissions
            if entry.participant_id != submission.participant_id
        ]
        if not peer_ratings:
            continue

        actual_mean = sum(peer_ratings) / len(peer_ratings)
        predicted_mean = submission.estimated_team_mean
        comparisons.append(
            PeerComparison(
                participant_id=submission.participant_id,
                predicted_mean=predicted_mean,
                actual_peer_mean=actual_mean,
                difference=predicted_mean - actual_mean,
                peers_count=len(peer_ratings),
            )
        )
    return comparisons


def _iso_week(value: date) -> tuple[int, int]:
    iso = value.isocalendar()
    return iso[0], iso[1]
