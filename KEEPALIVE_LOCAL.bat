@echo off
REM Keep-alive local del ERP en Render. NO toca base de datos ni archivos.
REM Deja esta ventana abierta en la PC de la tienda si quieres respaldo extra del GitHub Action.
title ERP Render Keep Alive
set URL=https://erp-api-7x3d.onrender.com/health
echo Pingeando %URL% cada 7 minutos. Ctrl+C para salir.
:loop
curl.exe -sS --max-time 90 "%URL%"
echo.
echo --- %date% %time% ---
timeout /t 420 /nobreak >nul
goto loop
