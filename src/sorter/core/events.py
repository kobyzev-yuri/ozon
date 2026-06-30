from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Event:
    event: str
    frame: int
    track_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row.update(row.pop("payload", {}))
        return row


class EventLogger:
    """Append-only audit log (WCS-style), JSONL."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: TextIO | None = None

    def _handle(self) -> TextIO:
        if self._fh is None:
            self._fh = self.path.open("a", encoding="utf-8")
        return self._fh

    def emit(self, event: Event) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        self._fh = self._handle()
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


class EventBus:
    """In-process pub/sub between Field, WCS, WMS layers."""

    def __init__(self, logger: EventLogger | None = None) -> None:
        self._subscribers: list[Any] = []
        self.logger = logger

    def subscribe(self, handler) -> None:
        self._subscribers.append(handler)

    def publish(self, event: Event) -> None:
        if self.logger is not None:
            self.logger.emit(event)
        for handler in self._subscribers:
            handler(event)
