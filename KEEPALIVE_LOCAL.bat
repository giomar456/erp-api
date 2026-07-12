@echo off
title ERP Oracle Keep Alive
REM Solo Oracle. No Render. No toca base de datos.
set URL=http://64.181.176.160:8000/health?db=1
echo ============================================
echo  ERP Oracle Keep Alive
echo  %URL%
echo  Ping cada 4 minutos. Ctrl+C para salir.
echo ============================================
:loop
curl.exe -sS --connect-timeout 10 --max-time 40 "%URL%"
echo.
echo --- %date% %time% ---
timeout /t 240 /nobreak >nul
goto loop
