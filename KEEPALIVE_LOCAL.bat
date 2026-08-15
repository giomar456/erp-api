@echo off
title ERP Oracle Keep Alive
REM Solo Oracle. No Render. No toca base de datos.
set URL=https://64.181.176.160.sslip.io/health?db=1
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
