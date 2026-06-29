import os
import sys
import tempfile
import subprocess
import requests

APP_VERSION = "1.0.72"
VERSION_INFO_URL = os.getenv(
    "ERP_VERSION_INFO_URL",
    "https://erp-api-7x3d.onrender.com/app/version"
)


def parse_version(v):
    parts = []
    for x in str(v).strip().split("."):
        try:
            parts.append(int(x))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def check_update():
    try:
        r = requests.get(VERSION_INFO_URL, timeout=8)
        r.raise_for_status()
        data = r.json()
        remote_version = str(data.get("version", "")).strip()
        url = str(data.get("url", "")).strip()
        name = str(data.get("name", "erp_sql_pro_v20.exe")).strip() or "erp_sql_pro_v20.exe"
        update_available = parse_version(remote_version) > parse_version(APP_VERSION)
        return {
            "ok": True,
            "success": True,
            "update_available": update_available and bool(url),
            "remote_version": remote_version,
            "download_url": url,
            "exe_name": name,
            "notes": data.get("notes", ""),
            "force_update": bool(data.get("force_update", False))
        }
    except Exception as e:
        return {"ok": False, "success": False, "msg": str(e)}


def update_exe_and_restart(url, exe_name):
    if not getattr(sys, "frozen", False):
        return {"ok": False, "success": False, "msg": "El auto update reemplaza el archivo solo cuando usas el .EXE compilado."}
    if not url:
        return {"ok": False, "success": False, "msg": "La API no tiene URL de descarga para la nueva version."}
    try:
        current = sys.executable
        current_dir = os.path.dirname(current)
        updates_dir = os.path.join(current_dir, "updates")
        try:
            os.makedirs(updates_dir, exist_ok=True)
        except Exception:
            updates_dir = tempfile.gettempdir()
        temp = updates_dir if os.path.isdir(updates_dir) else tempfile.gettempdir()
        safe_name = os.path.basename(exe_name or "erp_sql_pro_v20.exe")
        new_exe = os.path.join(temp, safe_name)
        log_path = os.path.join(temp, "update_erp.log")
        r = requests.get(url, stream=True, timeout=120)
        r.raise_for_status()
        with open(new_exe, "wb") as f:
            for chunk in r.iter_content(1024 * 256):
                if chunk:
                    f.write(chunk)

        if os.path.getsize(new_exe) < 1024 * 1024:
            return {"ok": False, "success": False, "msg": "El archivo descargado parece incompleto."}

        new_size = os.path.getsize(new_exe)
        current_pid = os.getpid()
        bat = os.path.join(temp, "update_erp.bat")
        with open(bat, "w", encoding="utf-8") as f:
            f.write(f'''@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "NEW={new_exe}"
set "CUR={current}"
set "LOG={log_path}"
set "PID={current_pid}"
set "NEWSIZE={new_size}"
echo ==== G&G ERP update %date% %time% ==== > "%LOG%"
echo Nuevo: "%NEW%" >> "%LOG%"
echo Actual: "%CUR%" >> "%LOG%"
set /a WAIT_TRIES=0
:wait_app
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if not errorlevel 1 (
    echo Esperando cierre del ERP intento !WAIT_TRIES! >> "%LOG%"
    timeout /t 1 /nobreak >nul
    set /a WAIT_TRIES+=1
    if !WAIT_TRIES! LSS 45 goto wait_app
)
set /a COPY_TRIES=0
:copy_try
echo Copiando intento !COPY_TRIES! >> "%LOG%"
copy /Y "%NEW%" "%CUR%" >> "%LOG%" 2>&1
set "CURSIZE=0"
if exist "%CUR%" for %%A in ("%CUR%") do set "CURSIZE=%%~zA"
echo Tamano actual !CURSIZE! esperado %NEWSIZE% >> "%LOG%"
if "!CURSIZE!"=="%NEWSIZE%" goto copied
timeout /t 1 /nobreak >nul
set /a COPY_TRIES+=1
if !COPY_TRIES! LSS 45 goto copy_try
echo ERROR: no se pudo reemplazar el ejecutable. >> "%LOG%"
start notepad "%LOG%"
exit /b 1
:copied
echo OK actualizado. Reiniciando ERP. >> "%LOG%"
start "" "%CUR%"
del "%NEW%" >> "%LOG%" 2>&1
del "%~f0"
''')
        subprocess.Popen(
            ["cmd", "/c", bat],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        return {"ok": True, "success": True, "log": log_path}
    except Exception as e:
        return {"ok": False, "success": False, "msg": str(e)}
