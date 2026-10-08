"""循环播放提示音，直到提醒被手动关掉或人按了静音。

播放挂在窗口自己的定时器上，不再另开线程。
macOS 上 Tk 和后台线程待在同一个进程里，过一会儿会把窗口库弄崩。
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Callable, Optional

try:
    import winsound
except ImportError:  # 非 Windows 没有这个模块
    winsound = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_MAC_SOUND = "/System/Library/Sounds/Sosumi.aiff"
Schedule = Callable[..., object]


class AlarmSound:
    def __init__(self, schedule: Schedule) -> None:
        self._schedule = schedule
        self._playing = False
        self._closed = False
        self._proc: Optional[subprocess.Popen[bytes]] = None

    def start(self) -> None:
        if self._closed or self._playing:
            return
        self._playing = True
        self._tick()

    def stop(self) -> None:
        self._playing = False

    def close(self) -> None:
        self._closed = True
        self._playing = False
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()

    def _tick(self) -> None:
        if self._closed or not self._playing:
            return
        self._play()
        self._schedule(4000, self._tick)

    def _play(self) -> None:
        try:
            if sys.platform == "darwin":
                proc = self._proc
                if proc is not None and proc.poll() is None:
                    return
                self._proc = subprocess.Popen(
                    ["afplay", _MAC_SOUND],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            if winsound is not None:
                winsound.Beep(880, 350)
                winsound.Beep(1174, 450)
        except Exception:
            logger.warning("播放提示音失败", exc_info=True)
