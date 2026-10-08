#!/bin/bash
# 双击这个文件，开始监控 1#工位。
# 右上角小窗表示正在监控。检判一开始会弹出红色窗口，必须点「我已查看并记录」才会关。
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8

choose_python() {
  local candidate
  local candidates=(
    "$HOME/.local/bin/python3.12"
    "$HOME/.local/bin/python3"
    "/opt/anaconda3/bin/python3"
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3"
    "python3"
  )
  for candidate in "${candidates[@]}"; do
    if [ -x "$candidate" ] || command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import tkinter,sys; raise SystemExit(0 if tkinter.TkVersion >= 8.6 else 1)' >/dev/null 2>&1; then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PY="$(choose_python)" || {
  echo "找不到能画窗口的 Python。Mac 自带的 /usr/bin/python3 太旧，提醒窗口会是空白。"
  echo "请安装 Python 3.12：https://www.python.org/downloads/macos/"
  exit 1
}

exec "$PY" -m scrap_alert
