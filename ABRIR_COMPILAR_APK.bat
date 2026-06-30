@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "compilar_apk_android.ps1"
pause