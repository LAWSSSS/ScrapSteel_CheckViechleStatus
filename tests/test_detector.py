"""检判开始的判断：空闲不响，同一车次只响一次，没确认就一直留着。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scrap_alert.detector import Detector
from scrap_alert.models import Station, merge_detail, parse_homepage
from scrap_alert.store import StateStore


def station(**kwargs: object) -> Station:
    raw = {
        "stationNumber": 1,
        "carNumber": "",
        "flowCode": "",
        "status": None,
        "steelType": "",
        "grossWeight": "",
        "netWeight": "",
        "weightBillNo": "",
        "dangerousGoods": "",
        "checkStartTime": "",
    }
    raw.update(kwargs)
    return Station.from_api(raw)


class DetectorTest(unittest.TestCase):
    def test_empty_homepage_is_idle(self) -> None:
        stations = parse_homepage({"data": {"stationInfoDTOList": []}})
        decision = Detector().consider(stations, {1})
        self.assertEqual(decision.active, [])
        self.assertEqual(decision.pending, [])

    def test_other_station_is_ignored(self) -> None:
        current = station(stationNumber=2, carNumber="鲁B00001", flowCode="FLOW-2", status=2)
        decision = Detector().consider([current], {1})
        self.assertEqual(decision.pending, [])

    def test_plate_starts_one_alert_and_same_flow_does_not_repeat(self) -> None:
        detector = Detector()
        first = detector.consider(
            [station(carNumber="鲁A12345", flowCode="FLOW-1", status=2, declaredSteelType=1)],
            {1},
        )
        self.assertEqual(len(first.new_card_ids), 1)
        self.assertEqual(first.pending[0].station.car_number, "鲁A12345")
        self.assertEqual(first.pending[0].station.steel_type, "重废1")
        second = detector.consider(
            [station(carNumber="鲁A12345", flowCode="FLOW-1", status=2, grossWeight=41000)],
            {1},
        )
        self.assertEqual(second.new_card_ids, [])
        self.assertEqual(len(second.pending), 1)
        self.assertEqual(second.pending[0].station.gross_weight, "41000 Kg")

    def test_missing_then_same_flow_does_not_alert_again(self) -> None:
        detector = Detector()
        detector.consider([station(carNumber="鲁A12345", flowCode="FLOW-1", status=2)], {1})
        detector.consider([], {1})
        again = detector.consider([station(carNumber="鲁A12345", flowCode="FLOW-1", status=2)], {1})
        self.assertEqual(again.new_card_ids, [])
        self.assertEqual(len(again.pending), 1)

    def test_new_flow_alerts_again(self) -> None:
        detector = Detector()
        detector.consider([station(carNumber="鲁A12345", flowCode="FLOW-1", status=2)], {1})
        detector.acknowledge(detector.pending[0].card_id)
        nxt = detector.consider([station(carNumber="鲁A67890", flowCode="FLOW-2", status=2)], {1})
        self.assertEqual(len(nxt.new_card_ids), 1)

    def test_acked_flow_stays_quiet_even_if_still_on_station(self) -> None:
        detector = Detector()
        detector.consider([station(carNumber="鲁A12345", flowCode="FLOW-1", status=2)], {1})
        detector.acknowledge(detector.pending[0].card_id)
        again = detector.consider([station(carNumber="鲁A12345", flowCode="FLOW-1", status=2)], {1})
        self.assertEqual(again.pending, [])
        self.assertEqual(len(again.active), 1)

    def test_quality_check_without_plate_still_alerts(self) -> None:
        decision = Detector().consider([station(status=2, flowCode="FLOW-1")], {1})
        self.assertEqual(len(decision.new_card_ids), 1)

    def test_finished_without_plate_is_idle(self) -> None:
        decision = Detector().consider([station(status=4, flowCode="FLOW-1")], {1})
        self.assertEqual(decision.active, [])
        self.assertEqual(decision.pending, [])

    def test_plate_arriving_later_updates_same_card(self) -> None:
        detector = Detector()
        first = detector.consider([station(status=2, flowCode="FLOW-1")], {1})
        second = detector.consider(
            [station(status=2, flowCode="FLOW-1", carNumber="鲁A12345")],
            {1},
        )
        self.assertEqual(second.new_card_ids, [])
        self.assertEqual(second.pending[0].card_id, first.pending[0].card_id)
        self.assertEqual(second.pending[0].station.car_number, "鲁A12345")

    def test_dash_plate_is_empty(self) -> None:
        current = station(carNumber="--", status=None)
        self.assertFalse(current.is_active())

    def test_merge_detail_fills_weight_ticket(self) -> None:
        current = station(carNumber="鲁A12345", flowCode="FLOW-1", status=2)
        merged = merge_detail(
            current,
            {"grossWeight": 20000, "weightBillNo": "WB1", "checkStartTime": "2026-10-08 08:50:28"},
        )
        self.assertEqual(merged.gross_weight, "20000 Kg")
        self.assertEqual(merged.weight_bill_no, "WB1")
        self.assertEqual(merged.car_number, "鲁A12345")


class StoreTest(unittest.TestCase):
    def test_pending_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "trips.json"
            store = StateStore(path)
            detector = Detector()
            detector.consider([station(carNumber="鲁A12345", flowCode="FLOW-1", status=2)], {1})
            store.save(detector.pending, detector.acked_ids)
            loaded_pending, loaded_acked = StateStore(path).load()
            restored = Detector(loaded_pending, loaded_acked)
            again = restored.consider([station(carNumber="鲁A12345", flowCode="FLOW-1", status=2)], {1})
            self.assertEqual(again.new_card_ids, [])
            self.assertEqual(again.pending[0].card_id, detector.pending[0].card_id)


if __name__ == "__main__":
    unittest.main()
