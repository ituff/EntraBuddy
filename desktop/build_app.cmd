@echo off
rem EntraBuddy Windows build: bundle Python runtime + web assets into one exe
rem Requires: pip install pyinstaller pywebview
cd /d "%~dp0.."

pyinstaller --noconfirm --onefile --windowed --name EntraBuddy --add-data "web;web" --hidden-import pywebview desktop_win.py
if %errorlevel% neq 0 (
  echo Build failed.
  exit /b 1
)
echo.
echo Build complete: dist\EntraBuddy.exe
echo Copy it to any Windows x64 machine (Python runtime bundled).
