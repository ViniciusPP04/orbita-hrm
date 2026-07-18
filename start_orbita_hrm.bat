@echo off
cd /d "%~dp0"
start "" /b python server.py
timeout /t 1 /nobreak >nul
start "Orbita HRM" http://localhost:4173
