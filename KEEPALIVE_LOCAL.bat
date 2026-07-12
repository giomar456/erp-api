@echo off
title ERP Oracle Keep Alive
set URL=http://64.181.176.160:8000/health?db=1
echo Solo Oracle. No Render. Ctrl+C para salir.
:loop
curl.exe -sS --max-time 40 "%URL%"
echo.
echo --- %date% %time% ---
timeout /t 600 /nobreak >nul
goto loop
