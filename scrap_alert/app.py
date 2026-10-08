"""启动监控、单次查询，或预览提醒窗口。"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import subprocess
import sys
import threading
import tkinter
from datetime import datetime
from pathlib import Path
from typing import Optional

from scrap_alert.client import ApiError, ScrapClient
from scrap_alert.config import Config
from scrap_alert.detector import Detector
from scrap_alert.models import Station, merge_detail, status_name
from scrap_alert.store import StateStore
from scrap_alert.ui import ReminderUI, open_detail_page

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


def main(argv: Optional[list[str]] = None) -> None:
    _configure_stdio()
    args = _parse_args(argv)
    _configure_logging(ROOT / "logs" / "alert.log")
    config_path = Path(args.config) if args.config else ROOT / "config.json"
    try:
        config = Config.load(config_path)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    if args.once:
        sys.exit(run_once(config))
    _ensure_tk()
    if args.preview:
        run_preview(config)
        return
    run_watch(config)


def run_once(config: Config) -> int:
    """登录并打印当前工位。给启动前的连通性检查用。"""
    client = ScrapClient(
        config.base_url,
        config.employee_id,
        config.password,
        config.request_timeout_seconds,
    )
    try:
        name = client.login()
        stations = client.homepage_stations()
    except ApiError as exc:
        print(f"查询失败：{exc}", file=sys.stderr)
        return 1
    watched = {station.station_number: station for station in stations if station.station_number in set(config.station_numbers)}
    print(f"登录人：{name}")
    for number in config.station_numbers:
        station = watched.get(number)
        if station is None or not station.is_active():
            print(f"{number}#工位  空闲  车牌 --")
            continue
        print(
            f"{number}#工位  {status_name(station.status) or '有车'}  "
            f"车牌 {station.car_number or '--'}  车次 {station.flow_code or '--'}"
        )
    return 0


def run_preview(config: Config) -> None:
    """弹出一张样例提醒，用来确认窗口必须手动关闭。不会连接现场。"""
    station = Station(
        station_number=config.station_numbers[0],
        car_number="鲁A12345",
        flow_code="FLOW-PREVIEW",
        status=2,
        steel_type="重废1",
        gross_weight="41230 Kg",
        net_weight="",
        weight_bill_no="WB20261008001",
        dangerous_goods="0",
        check_start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    detector = Detector()
    decision = detector.consider([station], set(config.station_numbers))
    ui = _build_ui(config, detector, StateStore(ROOT / "state" / "preview-state.json"))

    def paint() -> None:
        ui.set_status(f"{station.station_number}#工位  质检中  {station.car_number}", "这是预览，没有连接现场")
        ui.set_pending([trip.to_dict() for trip in decision.pending], focus_new=True)

    ui.root.after(200, paint)
    ui.run()


def run_watch(config: Config) -> None:
    lock_path = ROOT / "state" / "instance.lock"
    _acquire_lock(lock_path)
    store = StateStore(ROOT / "state" / "trips.json")
    pending, acked = store.load()
    detector = Detector(pending, acked)
    client = ScrapClient(
        config.base_url,
        config.employee_id,
        config.password,
        config.request_timeout_seconds,
    )
    lock = threading.Lock()
    stop = threading.Event()
    user_name = {"value": config.employee_id}
    delay_ms = int(config.poll_interval_seconds * 1000)

    ui = _build_ui(config, detector, store, lock)

    def poll_once() -> None:
        # 网络请求留在窗口线程里。macOS 上另开线程访问网络，Tk 过一会儿会崩溃。
        if stop.is_set() or ui.closing:
            return
        try:
            if not ui.root.winfo_exists():
                return
        except tkinter.TclError:
            return
        try:
            if not client.logged_in:
                user_name["value"] = client.login()
            stations = client.homepage_stations()
            with lock:
                decision = detector.consider(stations, set(config.station_numbers))
                if decision.changed:
                    store.save(detector.pending, detector.acked_ids)
                pending_rows = [trip.to_dict() for trip in detector.pending]
                active = list(decision.active)
                new_ids = list(decision.new_card_ids)
            text, hint = _status_text(active, config.station_numbers, user_name["value"])
            ui.set_status(text, hint)
            ui.set_pending(pending_rows, focus_new=bool(new_ids))
            for card_id in new_ids:
                refreshed = _enrich(client, detector, store, lock, card_id)
                if refreshed is not None:
                    ui.set_pending(refreshed, focus_new=False)
        except ApiError as exc:
            client.mark_logged_out()
            logger.error("轮询失败：%s", exc)
            ui.set_status("暂时连不上检判系统", "请确认已经连上永锋 VPN。网络恢复后会自动重试。")
        except tkinter.TclError:
            return
        except Exception as exc:
            logger.error("轮询出现意外错误：%s", exc)
            ui.set_status("暂时连不上检判系统", "请确认已经连上永锋 VPN。网络恢复后会自动重试。")
        try:
            if stop.is_set() or ui.closing or not ui.root.winfo_exists():
                return
            ui.root.after(delay_ms, poll_once)
        except tkinter.TclError:
            return

    if detector.pending:
        ui.set_pending([trip.to_dict() for trip in detector.pending], focus_new=True)
    ui.root.after(200, poll_once)
    try:
        ui.run()
    finally:
        stop.set()


def _build_ui(
    config: Config,
    detector: Detector,
    store: StateStore,
    lock: Optional[threading.Lock] = None,
) -> ReminderUI:
    guard = lock or threading.Lock()

    def on_ack(card_id: str) -> None:
        with guard:
            detector.acknowledge(card_id)
            store.save(detector.pending, detector.acked_ids)
            pending_rows = [trip.to_dict() for trip in detector.pending]
        ui.set_pending(pending_rows, focus_new=False)

    ui = ReminderUI(
        on_ack=on_ack,
        open_url=lambda station: open_detail_page(config.base_url, station),
        enable_sound=True,
    )
    return ui


def _enrich(
    client: ScrapClient,
    detector: Detector,
    store: StateStore,
    lock: threading.Lock,
    card_id: str,
) -> Optional[list[dict]]:
    with lock:
        trip = next((item for item in detector.pending if item.card_id == card_id), None)
        flow_code = trip.station.flow_code if trip else ""
    if not flow_code:
        return None
    try:
        detail = client.check_detail(flow_code)
    except ApiError as exc:
        logger.info("车次详情没取到：%s", exc)
        return None
    with lock:
        trip = next((item for item in detector.pending if item.card_id == card_id), None)
        if trip is None:
            return None
        trip.station = merge_detail(trip.station, detail)
        store.save(detector.pending, detector.acked_ids)
        return [item.to_dict() for item in detector.pending]


def _status_text(active: list[Station], watch: list[int], user_name: str) -> tuple[str, str]:
    by_number = {station.station_number: station for station in active}
    lines: list[str] = []
    for number in watch:
        station = by_number.get(number)
        if station is None:
            lines.append(f"{number}#工位  空闲")
            continue
        plate = station.car_number or "车牌未识别"
        lines.append(f"{number}#工位  {status_name(station.status) or '有车'}  {plate}")
    refreshed = datetime.now().strftime("%H:%M:%S")
    return "\n".join(lines), f"已连接 {user_name} · {refreshed} 刷新"


def _acquire_lock(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            pid = int(path.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            pid = 0
        if pid and _pid_alive(pid):
            print(f"提醒程序已经在运行（进程 {pid}）。不需要再开一个。", file=sys.stderr)
            sys.exit(1)
    path.write_text(str(os.getpid()), encoding="utf-8")

    def _release() -> None:
        try:
            current = int(path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            return
        if current == os.getpid():
            path.unlink(missing_ok=True)

    atexit.register(_release)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="永锋废钢检判开始提醒")
    parser.add_argument("--config", help="配置文件路径，默认是项目里的 config.json")
    parser.add_argument("--once", action="store_true", help="只查询一次当前工位，不弹窗")
    parser.add_argument("--preview", action="store_true", help="弹出样例提醒，用来看窗口，不连接现场")
    return parser.parse_args(argv)


def _ensure_tk() -> None:
    """Mac 自带的 Tk 8.5 会画出空白窗口。能找到新 Python 就换过去。"""
    if tkinter.TkVersion >= 8.6:
        return
    if sys.platform == "darwin" and os.environ.get("SCRAP_ALERT_REEXEC") != "1":
        for candidate in _newer_pythons():
            if not _supports_modern_tk(candidate):
                continue
            os.environ["SCRAP_ALERT_REEXEC"] = "1"
            os.execv(str(candidate), [str(candidate), "-m", "scrap_alert", *sys.argv[1:]])
    print(
        "当前 Python 的窗口库太旧，提醒窗口会是一片空白。\n"
        "Mac 请安装 Python 3.12：https://www.python.org/downloads/macos/\n"
        "Windows 请安装 Python 3.12，并勾选 tcl/tk：https://www.python.org/downloads/",
        file=sys.stderr,
    )
    sys.exit(1)


def _newer_pythons() -> list[Path]:
    home = Path.home()
    return [
        home / ".local/bin/python3.12",
        home / ".local/bin/python3",
        Path("/opt/anaconda3/bin/python3"),
        Path("/opt/homebrew/bin/python3"),
        Path("/usr/local/bin/python3"),
    ]


def _supports_modern_tk(executable: Path) -> bool:
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return False
    result = subprocess.run(
        [str(executable), "-c", "import tkinter,sys; sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
