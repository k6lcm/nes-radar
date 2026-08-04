@echo off
setlocal
cd /d "%~dp0"
py -3 start_nes_radar_server.py %*
if errorlevel 1 pause
