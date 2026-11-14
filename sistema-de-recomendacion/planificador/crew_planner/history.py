"""Historial de asignaciones realizadas, para repetición y carga acumulada."""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import ValidationError, _asdict, _finite, _only, check_id


@dataclass(frozen=True)
class HistoryEntry:
    """Una tarea que un astronauta hizo un día."""

    day: int
    astronaut: str
    task_id: str
    category: str
    duration_min: float
    intensity: float = 0.5
    demanding: bool = False

    def __post_init__(self) -> None:
        where = f"Historial {self.astronaut}/{self.task_id} día {self.day}"
        if not isinstance(self.day, int) or isinstance(self.day, bool):
            raise ValidationError(f"{where}: day debe ser entero")
        check_id(self.astronaut, f"{where}: astronauta")
        check_id(self.task_id, f"{where}: tarea")
        check_id(self.category, f"{where}: categoría")
        if _finite(self.duration_min, f"{where}: duration_min") <= 0:
            raise ValidationError(f"{where}: duration_min debe ser > 0")
        if not 0 <= _finite(self.intensity, f"{where}: intensity") <= 1:
            raise ValidationError(f"{where}: intensity debe estar en [0, 1]")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "HistoryEntry":
        return cls(**_only(raw, cls, "entrada de historial"))

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)


class History:
    """Entradas ordenadas por día. Solo admite días anteriores al planificado."""

    def __init__(self, entries: Iterable[HistoryEntry] = ()) -> None:
        self.entries: tuple[HistoryEntry, ...] = tuple(
            sorted(entries, key=lambda e: (e.day, e.astronaut, e.task_id))
        )

    def __len__(self) -> int:
        return len(self.entries)

    def before(self, day: int, window_days: int | None = None) -> list[HistoryEntry]:
        """Entradas de los días [day − window_days, day − 1], o todas las anteriores."""
        first = day - window_days if window_days is not None else None
        return [
            e for e in self.entries if e.day < day and (first is None or e.day >= first)
        ]

    def for_astronaut(self, astronaut: str, day: int, window_days: int | None = None) -> list[HistoryEntry]:
        return [e for e in self.before(day, window_days) if e.astronaut == astronaut]

    def extend(self, entries: Iterable[HistoryEntry]) -> "History":
        """Historial nuevo con más entradas: así se encadenan días en la simulación."""
        return History(self.entries + tuple(entries))

    def check_before(self, day: int) -> None:
        late = [e for e in self.entries if e.day >= day]
        if late:
            raise ValidationError(
                f"El historial contiene {len(late)} entradas del día {day} o posteriores"
            )

    @classmethod
    def from_list(cls, raw: Iterable[Mapping[str, Any]]) -> "History":
        return cls(HistoryEntry.from_dict(r) for r in raw)

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.entries]

    @classmethod
    def load(cls, path: str | Path) -> "History":
        return cls.from_list(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_list(), indent=1, ensure_ascii=False), encoding="utf-8")
