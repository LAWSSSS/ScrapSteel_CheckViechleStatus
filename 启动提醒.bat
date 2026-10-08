@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m scrap_alert
if errorlevel 1 (
  echo.
  echo 启动失败。请安装 Python 3.9 或更高版本，安装时勾选 tcl/tk。
  echo https://www.python.org/downloads/
  pause
)
