from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    index: int
    ts: str | None
    event: str
    task_id: str | None = None
    text: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    source: str
    format: str
    events: list[Event]
