from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StatusEvent:
    event: str = "status"
    node: str = ""
    phase: str = "started"
    label: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "event": self.event,
            "node": self.node,
            "phase": self.phase,
            "label": self.label,
            "timestamp": self.timestamp,
        }
        if self.detail:
            d["detail"] = self.detail
        return d
