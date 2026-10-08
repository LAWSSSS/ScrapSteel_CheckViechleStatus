"""工位状态的解析。

页面上的「空闲」不是单独的业务字段。前端拿
`stationInfoDTOList` 画工位条：没有车牌、状态也不是「质检中/暂停」时，
就画成「空闲」和一排「--」。检判开始后，这条记录会出现车牌，
通常还会带上 `flowCode`（这一车次的唯一编号）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

# 与前端字典 V_DICT_PROCESS_STATUS 一致。
STATUS_NAMES = {
    1: "毛重计量完成",
    2: "质检中",
    3: "暂停",
    4: "质检完成",
    5: "皮重计量完成",
}

# 前端只有这两个状态不画「空闲」。
ACTIVE_STATUSES = {2, 3}

STEEL_TYPES = {
    0: "其他",
    1: "重废1",
    2: "重废2",
    3: "重废3",
    4: "统料1",
    5: "统料2",
    6: "统料3",
    7: "轻薄料",
}

_EMPTY_TEXT = {"", "--", "null", "none", "undefined"}


def clean_text(value: Any) -> str:
    """把接口里的空值收成空字符串。"""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in _EMPTY_TEXT:
        return ""
    return text


def as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_weight(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return f"{int(number)} Kg"
    return f"{number:.1f} Kg"


def steel_name(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    number = as_int(text)
    if number is None:
        return text
    return STEEL_TYPES.get(number, text)


def status_name(value: Optional[int]) -> str:
    if value is None:
        return ""
    return STATUS_NAMES.get(value, str(value))


def first_value(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and clean_text(raw.get(key)):
            return raw.get(key)
    return None


@dataclass
class Station:
    """一次轮询里，一个工位的当前车次。"""

    station_number: int
    car_number: str
    flow_code: str
    status: Optional[int]
    steel_type: str
    gross_weight: str
    net_weight: str
    weight_bill_no: str
    dangerous_goods: str
    check_start_time: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Station":
        station_number = as_int(raw.get("stationNumber")) or 0
        dangerous = first_value(raw, "dangerousGoods", "dgCount")
        return cls(
            station_number=station_number,
            car_number=clean_text(raw.get("carNumber")),
            flow_code=clean_text(raw.get("flowCode")),
            status=as_int(raw.get("status")),
            steel_type=steel_name(first_value(raw, "steelType", "declaredSteelType")),
            gross_weight=format_weight(raw.get("grossWeight")),
            net_weight=format_weight(raw.get("netWeight")),
            weight_bill_no=clean_text(raw.get("weightBillNo")),
            dangerous_goods=clean_text(dangerous),
            check_start_time=clean_text(raw.get("checkStartTime")),
        )

    def is_active(self) -> bool:
        """这一工位现在是不是有车在检判流程里。"""
        if self.car_number:
            return True
        return self.status in ACTIVE_STATUSES

    def identity(self) -> str:
        """同一车次的稳定编号。有 flowCode 就用它，它是这一趟的主键。"""
        if self.flow_code:
            return f"flow:{self.flow_code}"
        if self.car_number:
            return f"plate:{self.station_number}:{self.car_number}"
        return f"status:{self.station_number}:{self.status}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Station":
        return cls(
            station_number=int(raw.get("station_number") or 0),
            car_number=clean_text(raw.get("car_number")),
            flow_code=clean_text(raw.get("flow_code")),
            status=as_int(raw.get("status")),
            steel_type=clean_text(raw.get("steel_type")),
            gross_weight=clean_text(raw.get("gross_weight")),
            net_weight=clean_text(raw.get("net_weight")),
            weight_bill_no=clean_text(raw.get("weight_bill_no")),
            dangerous_goods=clean_text(raw.get("dangerous_goods")),
            check_start_time=clean_text(raw.get("check_start_time")),
        )


def parse_homepage(payload: dict[str, Any]) -> list[Station]:
    """从首页接口正文里取出工位列表。调用方要先确认 meta.success。"""
    data = payload.get("data") or {}
    rows = data.get("stationInfoDTOList") or []
    stations: list[Station] = []
    for row in rows:
        if isinstance(row, dict):
            stations.append(Station.from_api(row))
    return stations


def merge_detail(station: Station, detail: dict[str, Any]) -> Station:
    """用检判详情补全首页里没有的磅单、重量。已有的车牌和状态以首页为准。"""
    if not detail:
        return station
    filled = Station.from_api(
        {
            "stationNumber": station.station_number,
            "carNumber": station.car_number or detail.get("carNumber"),
            "flowCode": station.flow_code or detail.get("flowCode"),
            "status": station.status if station.status is not None else detail.get("status"),
            "steelType": station.steel_type or detail.get("steelType") or detail.get("declaredSteelType"),
            "grossWeight": detail.get("grossWeight") or station.gross_weight,
            "netWeight": detail.get("netWeight") or station.net_weight,
            "weightBillNo": detail.get("weightBillNo") or station.weight_bill_no,
            "dangerousGoods": station.dangerous_goods or detail.get("dangerousGoods") or detail.get("dgCount"),
            "checkStartTime": detail.get("checkStartTime") or station.check_start_time,
        }
    )
    return filled


def detail_lines(station: Station, detected_at: str) -> list[tuple[str, str]]:
    """提醒窗口里要给人看的字段，空值不占一行。"""
    rows = [
        ("工位", f"{station.station_number}#工位" if station.station_number else "--"),
        ("状态", status_name(station.status) or "--"),
        ("上报废钢类型", station.steel_type),
        ("磅单号", station.weight_bill_no),
        ("毛重", station.gross_weight),
        ("净重", station.net_weight),
        ("危险品", station.dangerous_goods),
        ("检判开始", station.check_start_time),
        ("本机发现", detected_at),
        ("车次号", station.flow_code),
    ]
    return [(label, value) for label, value in rows if value]
