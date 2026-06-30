from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from sorter.core.types import DivertCommand


@dataclass(order=True)
class _Queued:
    execute_at_frame: int
    command: DivertCommand = field(compare=False)


class CommandQueue:
    """ПЛК-логика: неблокирующая очередь команд актуатору."""

    def __init__(self) -> None:
        self._heap: list[_Queued] = []
        self._scheduled_tracks: set[int] = set()

    def schedule(self, command: DivertCommand) -> bool:
        if command.track_id in self._scheduled_tracks:
            return False
        heapq.heappush(self._heap, _Queued(command.execute_at_frame, command))
        self._scheduled_tracks.add(command.track_id)
        return True

    def pop_due(self, frame_idx: int) -> list[DivertCommand]:
        due: list[DivertCommand] = []
        while self._heap and self._heap[0].execute_at_frame <= frame_idx:
            item = heapq.heappop(self._heap)
            due.append(item.command)
        return due

    def pending_count(self) -> int:
        return len(self._heap)
