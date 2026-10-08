"""读取本地配置。账号放在 config.json，不写进代码。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    base_url: str
    employee_id: str
    password: str
    station_numbers: list[int]
    poll_interval_seconds: float
    request_timeout_seconds: float

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            raise ValueError(f"找不到配置文件：{path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"配置文件不是合法 JSON：{path}") from exc
        employee_id = str(raw.get("employee_id") or "").strip()
        password = str(raw.get("password") or "")
        base_url = str(raw.get("base_url") or "").strip()
        if not employee_id or not password or not base_url:
            raise ValueError("配置里需要 base_url、employee_id、password")
        numbers = raw.get("station_numbers") or [1]
        try:
            station_numbers = [int(number) for number in numbers]
        except (TypeError, ValueError) as exc:
            raise ValueError("station_numbers 必须是工位号列表，例如 [1]") from exc
        if not station_numbers:
            raise ValueError("至少要监控一个工位")
        interval = float(raw.get("poll_interval_seconds") or 3)
        timeout = float(raw.get("request_timeout_seconds") or 8)
        return cls(
            base_url=base_url,
            employee_id=employee_id,
            password=password,
            station_numbers=station_numbers,
            poll_interval_seconds=max(1.0, interval),
            request_timeout_seconds=max(2.0, timeout),
        )
