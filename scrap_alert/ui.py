"""常驻状态窗 + 必须手动关闭的检判提醒。

macOS 自带的 Tk 会忽略 Label 的背景色，白字会铺在白底上，等于没画。
所以提醒内容画在 Canvas 上，颜色才稳定。Windows 上同一套代码也能画。

系统通知会自己消失，所以这里用桌面窗口。
关闭按钮被截住，只有「我已记录」会真正关掉。
"""

from __future__ import annotations

import json
import logging
import sys
import tkinter as tk
import webbrowser
from typing import Callable, Optional

from scrap_alert.models import Station, detail_lines
from scrap_alert.sound import AlarmSound

logger = logging.getLogger(__name__)

OnAck = Callable[[str], None]
BANNER_TEXT = "检判开始\n请马上查看车次并记录"
REJECT_TEXT = "请先点击红色按钮\n确认已经查看并记录"


def ui_font(size: int, weight: str = "normal") -> tuple[str, int, str]:
    family = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei"
    return (family, size, weight)


class ReminderUI:
    """状态窗一直在。有未确认车次时，另开一个置顶大窗。"""

    def __init__(self, on_ack: OnAck, open_url: Callable[[Station], None], enable_sound: bool = True) -> None:
        self._on_ack = on_ack
        self._open_url = open_url
        self.root = tk.Tk()
        self.root.title("永锋废钢检判提醒")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.request_quit)
        self._place_status_window()

        self._status_text = tk.StringVar(value="正在连接检判系统…")
        self._hint_text = tk.StringVar(value="窗口会一直留着。有车开始检判时弹出红色提醒。")
        self._quit_armed = False
        self._closing = False
        self._in_mainloop = False
        self._pending: list[dict] = []
        self._pending_signature = ""
        self._muted = False
        self._flash_on = False
        self._banner_text = BANNER_TEXT
        self._alert: Optional[tk.Toplevel] = None
        self._alert_canvas: Optional[tk.Canvas] = None
        self._alert_size = (0, 0)
        self._status_canvas: Optional[tk.Canvas] = None
        self._sound = AlarmSound(self.root.after) if enable_sound else None

        self._build_status()
        self.root.after(400, self._keep_status_visible)

    def _place_status_window(self) -> None:
        width, height = 360, 176
        screen_w = self.root.winfo_screenwidth()
        x = max(screen_w - width - 24, 0)
        y = 48
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_status(self) -> None:
        canvas = tk.Canvas(self.root, bg="#102A43", highlightthickness=0, borderwidth=0)
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Configure>", self._on_status_configure)
        self._status_canvas = canvas

    @property
    def closing(self) -> bool:
        return self._closing

    def set_status(self, text: str, hint: str) -> None:
        if self._closing:
            return
        self._status_text.set(text)
        self._hint_text.set(hint)
        self._draw_status()

    def set_pending(self, trips: list[dict], *, focus_new: bool) -> None:
        """用最新的未确认车次重画提醒。空列表就关掉大窗，但不会自动关。"""
        previous = {item["card_id"] for item in self._pending}
        signature = json.dumps(trips, ensure_ascii=False, sort_keys=True)
        self._pending = trips
        if not trips:
            self._pending_signature = ""
            self._banner_text = BANNER_TEXT
            self._destroy_alert()
            return
        new_ids = {item["card_id"] for item in trips} - previous
        if new_ids:
            self._banner_text = BANNER_TEXT
        self._ensure_alert()
        if signature != self._pending_signature:
            self._pending_signature = signature
            self._draw_alert()
        if new_ids or (focus_new and not previous):
            self._alert_started()

    def request_quit(self) -> None:
        if self._closing:
            return
        if self._pending and not self._quit_armed:
            self._quit_armed = True
            self._hint_text.set("还有未确认的车次。再点一次「退出监控」才会退出。")
            self._draw_status()
            if self._alert is not None:
                self._force_front(self._alert)
            return
        self.close()

    def close(self) -> None:
        """结束监控。点按钮时不能立刻销毁窗口，否则 Tk 报错，定时器还会把窗口拉回来。"""
        if self._closing:
            return
        self._closing = True
        if self._sound is not None:
            self._sound.close()
        try:
            self.root.after_idle(self._finish_close)
            if not self._in_mainloop:
                self.root.update()
        except tk.TclError:
            self._finish_close()

    def run(self) -> None:
        self._in_mainloop = True
        try:
            self.root.mainloop()
        finally:
            self._in_mainloop = False
            self._finish_close()

    def _finish_close(self) -> None:
        self._closing = True
        try:
            self.root.quit()
        except tk.TclError:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            return

    def _on_status_configure(self, event: tk.Event) -> None:
        if event.widget is not self._status_canvas or event.width < 40:
            return
        self._draw_status()

    def _draw_status(self) -> None:
        canvas = self._status_canvas
        if canvas is None:
            return
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 40 or height < 40:
            return
        text = self._status_text.get()
        if "连不上" in text:
            dot = "#FB7185"
        elif "空闲" in text and "质检" not in text and "有车" not in text:
            dot = "#2DD4BF"
        else:
            dot = "#FBBF24"
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#102A43", outline="")
        canvas.create_oval(16, 18, 30, 32, fill=dot, outline="")
        canvas.create_text(40, 25, anchor="w", text="永锋废钢检判提醒", fill="white", font=ui_font(16, "bold"))
        canvas.create_text(
            16,
            52,
            anchor="nw",
            text=text,
            fill="white",
            font=ui_font(15, "bold"),
            width=width - 32,
        )
        canvas.create_text(
            16,
            96,
            anchor="nw",
            text=self._hint_text.get(),
            fill="#B6C5D6",
            font=ui_font(12),
            width=width - 140,
        )
        canvas.create_rectangle(width - 108, height - 44, width - 16, height - 14, fill="#F8FAFC", outline="")
        canvas.create_text(
            width - 62,
            height - 29,
            text="退出监控",
            fill="#102A43",
            font=ui_font(12, "bold"),
            tags="quit",
        )
        canvas.tag_bind("quit", "<Button-1>", lambda _event: self.request_quit())

    def _keep_status_visible(self) -> None:
        if self._closing:
            return
        try:
            if not self.root.winfo_exists():
                return
            if str(self.root.state()) == "iconic":
                self.root.deiconify()
            self.root.attributes("-topmost", True)
            alert = self._alert
            if alert is not None and alert.winfo_exists():
                alert.attributes("-topmost", True)
                if str(alert.state()) == "iconic":
                    alert.deiconify()
                    alert.lift()
        except tk.TclError:
            return
        self.root.after(2000, self._keep_status_visible)

    def _ensure_alert(self) -> None:
        if self._alert is not None and self._alert.winfo_exists():
            return
        alert = tk.Toplevel(self.root)
        alert.title("检判开始，请查看并记录")
        alert.protocol("WM_DELETE_WINDOW", self._reject_close)
        alert.bind("<Escape>", lambda _event: self._reject_close())
        self._place_alert(alert)
        canvas = tk.Canvas(alert, bg="white", highlightthickness=0, borderwidth=0)
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Configure>", self._on_alert_configure)
        self._alert = alert
        self._alert_canvas = canvas
        self._alert_size = (0, 0)
        try:
            alert.attributes("-topmost", True)
        except tk.TclError:
            logger.debug("提醒窗置顶失败", exc_info=True)
        alert.after(700, self._flash)

    def _place_alert(self, alert: tk.Toplevel) -> None:
        screen_w = alert.winfo_screenwidth()
        screen_h = alert.winfo_screenheight()
        width = min(920, max(720, screen_w - 80))
        height = min(760, max(620, screen_h - 120))
        x = max((screen_w - width) // 2, 0)
        y = max((screen_h - height) // 2, 20)
        alert.geometry(f"{width}x{height}+{x}+{y}")
        alert.minsize(680, 520)

    def _on_alert_configure(self, event: tk.Event) -> None:
        if event.widget is not self._alert_canvas or event.width < 80:
            return
        size = (event.width, event.height)
        if size == self._alert_size:
            return
        self._alert_size = size
        self._draw_alert()

    def _draw_alert(self) -> None:
        canvas = self._alert_canvas
        if canvas is None or not self._pending:
            return
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 80 or height < 80:
            return
        banner_color = "#E65100" if self._flash_on else "#B71C1C"
        canvas.delete("all")
        banner_h = 168
        canvas.create_rectangle(0, 0, width, banner_h, fill=banner_color, outline="")
        canvas.create_text(
            width / 2,
            banner_h / 2,
            text=self._banner_text,
            fill="white",
            font=ui_font(32, "bold"),
            justify="center",
        )
        y = banner_h + 28
        for trip in self._pending:
            y = self._draw_trip(canvas, trip, y, width)
        canvas.create_text(32, height - 28, anchor="w", text="这个窗口不会自动关闭", fill="#9AA5B1", font=ui_font(13))
        mute_text = "取消静音" if self._muted else "静音（窗口仍会留着）"
        canvas.create_text(width - 32, height - 28, anchor="e", text=mute_text, fill="#334E68", font=ui_font(14, "bold"), tags="mute")
        canvas.tag_bind("mute", "<Button-1>", lambda _event: self._toggle_mute())

    def _draw_trip(self, canvas: tk.Canvas, trip: dict, top: int, width: int) -> int:
        station = Station.from_dict(trip["station"])
        plate = station.car_number or "车牌还没出来，请看现场画面"
        canvas.create_text(32, top, anchor="nw", text=plate, fill="#102A43", font=ui_font(40, "bold"), width=width - 64)
        y = top + 72
        for label, value in detail_lines(station, trip.get("detected_at") or ""):
            canvas.create_text(32, y, anchor="w", text=f"{label}：", fill="#627D98", font=ui_font(16))
            canvas.create_text(250, y, anchor="w", text=value, fill="#243B53", font=ui_font(16, "bold"))
            y += 32
        y += 16
        button_tag = f"ack:{trip['card_id']}"
        ack_text = "我已查看并记录，关闭提醒" if len(self._pending) == 1 else "这个车次我已记录"
        canvas.create_rectangle(32, y, width - 32, y + 58, fill="#B71C1C", outline="", tags=button_tag)
        canvas.create_text(
            width / 2,
            y + 29,
            text=ack_text,
            fill="white",
            font=ui_font(20, "bold"),
            tags=button_tag,
        )
        canvas.tag_bind(button_tag, "<Button-1>", lambda _event, card_id=trip["card_id"]: self._acknowledge(card_id))
        y += 74
        open_tag = f"open:{trip['card_id']}"
        canvas.create_text(32, y, anchor="w", text="打开检判页面", fill="#B71C1C", font=ui_font(15, "bold"), tags=open_tag)
        canvas.tag_bind(open_tag, "<Button-1>", lambda _event, current=station: self._open_url(current))
        return y + 36

    def _acknowledge(self, card_id: str) -> None:
        self._on_ack(card_id)

    def _toggle_mute(self) -> None:
        self._muted = not self._muted
        if self._sound is not None:
            if self._muted:
                self._sound.stop()
            elif self._pending:
                self._sound.start()
        self._draw_alert()

    def _alert_started(self) -> None:
        if self._sound is not None and not self._muted:
            self._sound.start()
        try:
            self.root.bell()
        except tk.TclError:
            logger.debug("系统提示音不可用", exc_info=True)
        if self._alert is not None:
            self._force_front(self._alert)

    def _reject_close(self) -> None:
        """点窗口叉、按 Esc，都不关。只把窗口重新拉到前面。"""
        self._banner_text = REJECT_TEXT
        self._draw_alert()
        if self._alert is not None:
            self._force_front(self._alert)
        try:
            self.root.bell()
        except tk.TclError:
            return

    def _flash(self) -> None:
        if self._closing:
            return
        alert = self._alert
        if alert is None:
            return
        try:
            if not alert.winfo_exists():
                return
        except tk.TclError:
            return
        self._flash_on = not self._flash_on
        self._draw_alert()
        alert.after(900, self._flash)

    def _force_front(self, window: tk.Misc) -> None:
        """置顶并拉到前面。不抢键盘焦点，否则人没法去别的窗口记车牌。"""
        try:
            window.attributes("-topmost", True)
            window.deiconify()
            window.lift()
        except tk.TclError:
            logger.debug("窗口置顶失败", exc_info=True)

    def _destroy_alert(self) -> None:
        if self._sound is not None:
            self._sound.stop()
        alert = self._alert
        self._alert = None
        self._alert_canvas = None
        self._alert_size = (0, 0)
        self._flash_on = False
        if alert is not None:
            try:
                alert.destroy()
            except tk.TclError:
                return


def open_detail_page(base_url: str, station: Station) -> None:
    """打开业务系统里这一工位的检判页。flow 为空时页面本身也是这个地址。"""
    root = base_url.rstrip("/")
    url = (
        f"{root}/#/judgement/judgement-detail"
        f"?stationNumber={station.station_number}&flowCode={station.flow_code}"
    )
    webbrowser.open(url)
