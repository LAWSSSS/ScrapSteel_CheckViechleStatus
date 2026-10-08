"""判断「这一车要不要再响一次」。

主键是 flowCode。同一车次无论接口闪断多少次，只提醒一次。
人关掉窗口之后，这个 flowCode 记入已确认，重启也不会再弹。
没关就退出程序的，下次启动还会把这张提醒拉回来。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4

from scrap_alert.models import Station


@dataclass
class PendingTrip:
    card_id: str
    detected_at: str
    station: Station

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "detected_at": self.detected_at,
            "station": self.station.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "PendingTrip":
        return cls(
            card_id=str(raw["card_id"]),
            detected_at=str(raw.get("detected_at") or ""),
            station=Station.from_dict(raw.get("station") or {}),
        )


@dataclass
class Decision:
    active: list[Station] = field(default_factory=list)
    pending: list[PendingTrip] = field(default_factory=list)
    new_card_ids: list[str] = field(default_factory=list)
    changed: bool = False


class Detector:
    def __init__(
        self,
        pending: Optional[list[PendingTrip]] = None,
        acked_ids: Optional[list[str]] = None,
    ) -> None:
        self.pending: list[PendingTrip] = list(pending or [])
        self.acked_ids: list[str] = list(acked_ids or [])

    def consider(self, stations: list[Station], watch: set[int], now: Optional[datetime] = None) -> Decision:
        """根据这一轮工位数据，决定新增提醒、刷新已有提醒，以及当前在检的车。"""
        moment = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        active = [station for station in stations if station.station_number in watch and station.is_active()]
        new_ids: list[str] = []
        changed = False

        for station in active:
            if self._is_acked(station):
                continue
            matched = self._match(station)
            if matched is None:
                trip = PendingTrip(card_id=uuid4().hex, detected_at=moment, station=station)
                self.pending.append(trip)
                new_ids.append(trip.card_id)
                changed = True
                continue
            if _station_changed(matched.station, station):
                matched.station = station
                changed = True

        return Decision(active=active, pending=list(self.pending), new_card_ids=new_ids, changed=changed)

    def acknowledge(self, card_id: str) -> Optional[PendingTrip]:
        """人点了「已记录」才算关掉这一车。"""
        for index, trip in enumerate(self.pending):
            if trip.card_id != card_id:
                continue
            self.pending.pop(index)
            identity = trip.station.identity()
            if identity not in self.acked_ids:
                self.acked_ids.append(identity)
            self.acked_ids = self.acked_ids[-500:]
            return trip
        return None

    def _is_acked(self, station: Station) -> bool:
        return station.identity() in set(self.acked_ids)

    def _match(self, station: Station) -> Optional[PendingTrip]:
        for trip in self.pending:
            old = trip.station
            if station.flow_code and old.flow_code:
                if station.flow_code == old.flow_code:
                    return trip
                continue
            if station.station_number != old.station_number:
                continue
            if old.car_number and station.car_number and old.car_number != station.car_number:
                continue
            return trip
        return None


def _station_changed(old: Station, new: Station) -> bool:
    return old.to_dict() != new.to_dict()
