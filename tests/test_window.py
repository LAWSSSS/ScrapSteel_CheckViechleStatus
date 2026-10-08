"""提醒窗口点叉不会关，只有「已记录」会关。"""

from __future__ import annotations

import unittest

import tkinter as tk

from scrap_alert.detector import Detector
from scrap_alert.models import Station
from scrap_alert.ui import ReminderUI


class WindowPersistTest(unittest.TestCase):
    def test_close_button_does_not_dismiss_until_ack(self) -> None:
        detector = Detector()
        station = Station.from_api(
            {
                "stationNumber": 1,
                "carNumber": "鲁A12345",
                "flowCode": "FLOW-1",
                "status": 2,
                "declaredSteelType": 1,
                "grossWeight": 41000,
            }
        )
        decision = detector.consider([station], {1})
        acked: list[str] = []

        def on_ack(card_id: str) -> None:
            acked.append(card_id)
            detector.acknowledge(card_id)
            ui.set_pending([trip.to_dict() for trip in detector.pending], focus_new=False)

        ui = ReminderUI(on_ack=on_ack, open_url=lambda _station: None, enable_sound=False)
        try:
            ui.set_pending([trip.to_dict() for trip in decision.pending], focus_new=True)
            ui.root.update_idletasks()
            self.assertIsNotNone(ui._alert)
            assert ui._alert is not None
            self.assertTrue(ui._alert.winfo_exists())
            ui._reject_close()
            ui._flash()
            ui.root.update_idletasks()
            self.assertTrue(ui._alert.winfo_exists())
            self.assertIn("请先点击红色按钮", ui._banner_text)
            self.assertEqual(acked, [])
            ui._acknowledge(decision.pending[0].card_id)
            ui.root.update_idletasks()
            self.assertIsNone(ui._alert)
            self.assertEqual(acked, [decision.pending[0].card_id])
            ui.close()
            ui._keep_status_visible()
            self.assertTrue(ui.closing)
            try:
                still_there = bool(ui.root.winfo_exists())
            except tk.TclError:
                still_there = False
            self.assertFalse(still_there)
        finally:
            if not ui.closing:
                ui.close()


if __name__ == "__main__":
    unittest.main()
