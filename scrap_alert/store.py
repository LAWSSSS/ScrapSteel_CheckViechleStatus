"""把没关掉的提醒记到磁盘。进程被杀掉之后，下次还能把窗口拉回来。"""

from __future__ import annotations

import json
from pathlib import Path

from scrap_alert.detector import PendingTrip


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[list[PendingTrip], list[str]]:
        if not self.path.exists():
            return [], []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return [], []
        pending = [PendingTrip.from_dict(item) for item in raw.get("pending") or [] if isinstance(item, dict)]
        acked = [str(item) for item in raw.get("acked_ids") or []]
        return pending, acked

    def save(self, pending: list[PendingTrip], acked_ids: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pending": [trip.to_dict() for trip in pending],
            "acked_ids": acked_ids[-500:],
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
