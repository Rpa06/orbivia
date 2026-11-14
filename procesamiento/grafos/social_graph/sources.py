"""Fuentes de instantáneas de posición.

El servicio solo conoce la interfaz `SampleSource`; la lógica es la misma en
simulación y en producción.
"""

import json
import logging
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# (identificador del mensaje, contenido). None = pausa sin mensajes, para que el
# servicio pueda guardar el checkpoint o detenerse aunque no lleguen datos.
Message = tuple[str, Any]


class SampleSource(Protocol):
    def stream(self, cursor: Mapping[str, Any] | None) -> Iterator[Message | None]:
        """Emite mensajes posteriores al cursor guardado en el checkpoint.

        El cursor tiene `id` (último mensaje procesado) y `t` (su timestamp).
        """
        ...


class ListSource:
    """Fuente finita en memoria, para tests."""

    def __init__(self, messages: Iterable[Message]) -> None:
        self._messages = list(messages)

    def stream(self, cursor: Mapping[str, Any] | None) -> Iterator[Message | None]:
        start = 0
        if cursor and cursor.get("id") is not None:
            ids = [message_id for message_id, _ in self._messages]
            start = ids.index(cursor["id"]) + 1
        yield from self._messages[start:]


class RedisStreamSource:
    """Lee un stream de Redis. Cada entrada lleva el campo `data` con el JSON:

        {"t": 86400.0, "positions": {"A1": [x, y, z], "A2": null}}
    """

    def __init__(self, client: Any, stream: str, block_ms: int = 1000, count: int = 500) -> None:
        self._client = client
        self._stream = stream
        self._block_ms = block_ms
        self._count = count

    def stream(self, cursor: Mapping[str, Any] | None) -> Iterator[Message | None]:
        # Sin checkpoint se procesa el stream desde el principio
        last_id = (cursor or {}).get("id") or "0-0"
        while True:
            batches = self._client.xread(
                {self._stream: last_id}, count=self._count, block=self._block_ms
            )
            if not batches:
                yield None
                continue
            for _name, entries in batches:
                for entry_id, fields in entries:
                    last_id = _text(entry_id)
                    yield last_id, _decode(fields)


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _decode(fields: Mapping[Any, Any]) -> Any:
    """Devuelve el mensaje decodificado, o None si no es JSON válido."""
    data = fields.get(b"data", fields.get("data"))
    if data is None:
        return None
    try:
        return json.loads(data)
    except (ValueError, TypeError):
        return None
