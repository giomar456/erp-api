import os
import json
import tempfile
import webbrowser
import re
import sys
import time
import ctypes
import base64
import hashlib
import io
import struct
import threading
import queue
import mimetypes
import shutil
import urllib.parse
import urllib.request
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from PIL import Image, ImageTk, ImageDraw
try:
    import fitz
except Exception:
    fitz = None
try:
    from tkcalendar import DateEntry
except Exception:
    DateEntry = None
try:
    import api_client
except Exception:
    api_client = None
try:
    import winsound
except Exception:
    winsound = None
try:
    from updater import APP_VERSION, check_update, update_exe_and_restart
except Exception:
    APP_VERSION = "1.0.1"

    def check_update():
        return {"ok": False, "msg": "Módulo de actualización no disponible."}

    def update_exe_and_restart(url, exe_name):
        return {"ok": False, "msg": "Módulo de actualización no disponible."}


def validar_usuario(usuario, clave):
    fn = getattr(api_client, "validar_usuario", None) if api_client is not None else None
    if callable(fn):
        return fn(usuario, clave)
    return _api_json("post", "/login", {"ok": False}, json={"usuario": usuario, "clave": clave})


def _api_json(method, path, default=None, **kwargs):
    try:
        requests_mod = getattr(api_client, "requests", None) if api_client is not None else None
        base_url = getattr(api_client, "BASE_URL", "https://erp-api-7x3d.onrender.com").rstrip("/") if api_client is not None else "https://erp-api-7x3d.onrender.com"
        if requests_mod is not None:
            func = getattr(requests_mod, method.lower())
            r = func(f"{base_url}{path}", timeout=20, **kwargs)
            return r.json()

        payload = kwargs.get("json")
        headers = {"Content-Type": "application/json"}
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method.upper())
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return default


def _api_func(name, fallback):
    fn = getattr(api_client, name, None)
    return fn if callable(fn) else fallback


class ModernDesktopBridge:
    def _safe_pdf_name(self, name):
        base = os.path.basename(str(name or "documento.pdf").replace("\\", "/"))
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
        if not base.lower().endswith(".pdf"):
            base += ".pdf"
        return base or "documento.pdf"

    def download_pdf(self, url, file_name="documento.pdf"):
        try:
            url = str(url or "").strip()
            if not url.startswith("https://erp-api-7x3d.onrender.com/"):
                return {"ok": False, "msg": "URL de PDF no permitida."}
            downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            os.makedirs(downloads, exist_ok=True)
            name = self._safe_pdf_name(file_name)
            target = os.path.join(downloads, name)
            if os.path.exists(target):
                root, ext = os.path.splitext(name)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                target = os.path.join(downloads, f"{root}_{stamp}{ext}")
            req = urllib.request.Request(url, headers={"User-Agent": "G&G ERP Desktop"})
            with urllib.request.urlopen(req, timeout=35) as response:
                data = response.read()
            if not data.startswith(b"%PDF"):
                return {"ok": False, "msg": "El servidor no devolvio un PDF valido."}
            with open(target, "wb") as f:
                f.write(data)
            return {"ok": True, "path": target, "displayName": os.path.basename(target)}
        except Exception as e:
            return {"ok": False, "msg": str(e)}


def run_modern_desktop_app():
    api_base = getattr(api_client, "BASE_URL", "https://erp-api-7x3d.onrender.com").rstrip("/") if api_client is not None else "https://erp-api-7x3d.onrender.com"
    modern_url = f"{api_base}/erp/?desktop=pc"
    try:
        import webview
        webview.create_window(
            "G&G ERP",
            modern_url,
            width=1360,
            height=820,
            min_size=(1040, 680),
            js_api=ModernDesktopBridge(),
            confirm_close=False,
        )
        webview.start(gui="edgechromium")
        return True
    except Exception as e:
        try:
            root_err = tk.Tk()
            root_err.withdraw()
            messagebox.showwarning(
                "ERP Moderno",
                "No se pudo abrir la interfaz moderna interna.\n"
                "Abrire el modo clasico como respaldo.\n\n"
                f"{e}"
            )
            root_err.destroy()
        except Exception:
            pass
        return False


def _emitir_documento_fallback(payload):
    resp = _api_json("post", "/documentos/emitir", {"ok": False}, json=payload)
    if api_response_ok(resp):
        return resp
    return _api_json("post", "/ventas", {"ok": False}, json=payload)


def _comprobante_pago_payload(path):
    if not path or not os.path.isfile(path):
        return {}
    size = os.path.getsize(path)
    if size > 15 * 1024 * 1024:
        raise ValueError("Comprobante mayor a 15 MB.")
    mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return {
        "comprobante_pago": path,
        "comprobante_pago_nombre": os.path.basename(path),
        "comprobante_pago_mime": mime_type,
        "comprobante_pago_tamano": size,
        "comprobante_pago_base64": encoded,
        "comprobante_pago_data_url": f"data:{mime_type};base64,{encoded}",
    }


def _comprobantes_pago_payload(paths):
    items = []
    for path in paths or []:
        payload = _comprobante_pago_payload(path)
        payload["nombre"] = payload.get("comprobante_pago_nombre")
        payload["mime"] = payload.get("comprobante_pago_mime")
        payload["tamano"] = payload.get("comprobante_pago_tamano")
        payload["base64"] = payload.get("comprobante_pago_base64")
        payload["data_url"] = payload.get("comprobante_pago_data_url")
        items.append(payload)
    result = {"comprobantes_pago": items}
    if items:
        result.update(items[0])
    return result


def _observacion_con_comprobante(observacion_pago="", comprobante_pago=""):
    comprobante_pago = str(comprobante_pago or "").strip()
    if not comprobante_pago:
        return observacion_pago
    base = str(observacion_pago or "").strip()
    detalle = f"Comprobante: {os.path.basename(comprobante_pago)}"
    return f"{base} | {detalle}" if base else detalle


DEFAULT_PRODUCT_CATEGORIES = [
    "PROCESADOR",
    "PLACA MADRE",
    "ALMACENAMIENTO",
    "TARJ. GRAFICA",
    "CASE",
    "MONITOR",
    "ESTABILIZADOR",
    "ACCESORIOS DE CASE",
    "SISTEMA LIQUIDO",
    "FUENTE DE PODER",
    "MEMORIA RAM",
]

FERRETERIA_PRODUCT_CATEGORIES = [
    "HERRAMIENTAS MANUALES",
    "HERRAMIENTAS ELECTRICAS",
    "TORNILLERIA Y FIJACIONES",
    "PINTURAS",
    "ELECTRICIDAD",
    "GASFITERIA",
    "CONSTRUCCION",
    "SEGURIDAD INDUSTRIAL",
    "CERRAJERIA",
    "ADHESIVOS Y SELLADORES",
    "JARDINERIA",
    "LIMPIEZA",
]


def current_branch_key():
    try:
        value = getattr(api_client, "EMPRESA", "") if api_client is not None else ""
    except Exception:
        value = ""
    return str(value or "computer_army").strip().lower().replace(" ", "_")


def product_category_options(branch=None):
    branch = str(branch or current_branch_key()).strip().lower().replace(" ", "_")
    return list(FERRETERIA_PRODUCT_CATEGORIES if branch == "ferreteria" else DEFAULT_PRODUCT_CATEGORIES)


def default_product_category(branch=None):
    options = product_category_options(branch)
    return options[0] if options else ""


def _actualizar_estado_pago_fallback(documento_id, estado_pago, metodo_pago="", monto_pagado=None, observacion_pago="", comprobante_pago="", comprobante_pago_payload=None, pagos_detalle=None):
    payload = {"estado_pago": estado_pago, "metodo_pago": metodo_pago, "observacion_pago": observacion_pago}
    if monto_pagado is not None:
        payload["monto_pagado"] = monto_pagado
    if pagos_detalle:
        payload["pagos_detalle"] = pagos_detalle
    if comprobante_pago:
        payload["comprobante_pago"] = comprobante_pago
        payload.update(comprobante_pago_payload if isinstance(comprobante_pago_payload, dict) else _comprobante_pago_payload(comprobante_pago))
    resp = _api_json("put", f"/documentos/{documento_id}/estado-pago", {"ok": False}, json=payload)
    if api_response_ok(resp) or not comprobante_pago:
        return resp
    payload = {"estado_pago": estado_pago, "metodo_pago": metodo_pago, "observacion_pago": _observacion_con_comprobante(observacion_pago, comprobante_pago)}
    if monto_pagado is not None:
        payload["monto_pagado"] = monto_pagado
    if pagos_detalle:
        payload["pagos_detalle"] = pagos_detalle
    return _api_json("put", f"/documentos/{documento_id}/estado-pago", {"ok": False}, json=payload)


def _actualizar_documento_fallback(documento_id, payload):
    for method, path in (
        ("put", f"/documentos/{documento_id}"),
        ("patch", f"/documentos/{documento_id}"),
        ("put", f"/documentos/{documento_id}/editar"),
        ("post", f"/documentos/{documento_id}/editar"),
    ):
        resp = _api_json(method, path, {"ok": False}, json=payload)
        if api_response_ok(resp):
            return resp
    return {"ok": False, "msg": "La API no acepto la actualizacion del documento."}


def _api_get_branch(path, default=None):
    empresa = "computer_army"
    try:
        empresa = getattr(api_client, "EMPRESA", "computer_army") if api_client is not None else "computer_army"
    except Exception:
        pass
    sep = "&" if "?" in path else "?"
    q = f"{sep}sucursal={urllib.parse.quote(str(empresa))}&empresa={urllib.parse.quote(str(empresa))}"
    return _api_json("get", f"{path}{q}", default)


dashboard = _api_func("dashboard", lambda: _api_get_branch("/dashboard", {}) or {})
buscar_productos = _api_func("buscar_productos", lambda texto: _api_json("get", f"/productos/buscar?q={texto}", []) or [])
obtener_productos = _api_func("obtener_productos", lambda: _api_json("get", "/productos", []) or [])
guardar_producto = _api_func("guardar_producto", lambda d: _api_json("post", "/productos", {"ok": False}, json=d))
obtener_clientes = _api_func("obtener_clientes", lambda: _api_json("get", "/clientes", []) or [])
buscar_cliente_por_documento = _api_func("buscar_cliente_por_documento", lambda doc: _api_json("get", f"/clientes/{doc}", {"found": False}) or {"found": False})
consultar_documento_api = _api_func("consultar_documento", lambda doc: _api_json("get", f"/consulta/documento/{urllib.parse.quote(str(doc))}", {"ok": False, "found": False}) or {"ok": False, "found": False})
guardar_cliente = _api_func("guardar_cliente", lambda d: _api_json("post", "/clientes", {"ok": False}, json=d))
obtener_series = _api_func("obtener_series", lambda q="": _api_json("get", f"/series?q={q}", []) or [])
obtener_series_producto = _api_func("obtener_series_producto", lambda producto_id: _api_json("get", f"/productos/{int(producto_id)}/series", []) or [])
guardar_serie = _api_func("guardar_serie", lambda d: _api_json("post", "/series", {"ok": False}, json=d))
actualizar_serie = _api_func("actualizar_serie", lambda serie_id, d: _api_json("put", f"/series/{serie_id}", {"ok": False}, json=d))
eliminar_serie = _api_func("eliminar_serie", lambda serie_id: _api_json("delete", f"/series/{serie_id}", {"ok": False}))
siguiente_numero = _api_func("siguiente_numero", lambda tipo: api_response_get(_api_json("get", f"/series/{urllib.parse.quote(str(tipo))}", {}), "numero", ""))
_raw_emitir_documento = _api_func("emitir_documento", _emitir_documento_fallback)
_raw_actualizar_documento = _api_func("actualizar_documento", _actualizar_documento_fallback)


def emitir_documento(payload):
    resp = _raw_emitir_documento(payload)
    if api_response_ok(resp):
        return resp
    fallback = _emitir_documento_fallback(payload)
    return fallback if api_response_ok(fallback) else resp


def actualizar_documento(documento_id, payload):
    resp = _raw_actualizar_documento(documento_id, payload)
    if api_response_ok(resp):
        return resp
    fallback = _actualizar_documento_fallback(documento_id, payload)
    return fallback if api_response_ok(fallback) else resp


def play_document_sound(action="success"):
    try:
        if winsound is not None:
            patterns = {
                "open": [(660, 70), (880, 80)],
                "success": [(880, 120), (1175, 140)],
                "print": [(740, 90), (988, 90), (1319, 110)],
                "edit": [(587, 80), (784, 100)],
                "delete": [(440, 120), (330, 150)],
                "warning": [(523, 120), (392, 120)],
            }
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            for freq, duration in patterns.get(action, patterns["success"]):
                winsound.Beep(freq, duration)
        else:
            print("\a", end="")
    except Exception:
        pass


def app_resource_path(*parts):
    candidates = []
    try:
        if getattr(sys, "frozen", False):
            candidates.append(os.path.join(os.path.dirname(sys.executable), *parts))
        candidates.append(os.path.join(getattr(sys, "_MEIPASS", os.path.abspath(".")), *parts))
        candidates.append(os.path.join(os.getcwd(), *parts))
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts))
    except Exception:
        pass
    for path in candidates:
        try:
            if path and os.path.exists(path):
                return path
        except Exception:
            pass
    return os.path.join(os.getcwd(), *parts)


def play_cash_sound_file():
    path = app_resource_path("sonidos", "cash_register_kaching.mp3")
    if not os.path.exists(path):
        return False
    if os.name != "nt":
        return False

    def _run():
        alias = f"ggcash{int(time.time() * 1000)}"
        try:
            winmm = ctypes.windll.winmm
            winmm.mciSendStringW(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
            winmm.mciSendStringW(f"play {alias} wait", None, 0, None)
            winmm.mciSendStringW(f"close {alias}", None, 0, None)
        except Exception:
            try:
                if winsound is not None:
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass

    try:
        threading.Thread(target=_run, daemon=True).start()
        return True
    except Exception:
        return False


def play_click_sound():
    try:
        if winsound is not None:
            winsound.Beep(740, 28)
        else:
            print("\a", end="")
    except Exception:
        pass


def play_cash_approved_sound():
    if not play_cash_sound_file():
        if self.v_doc_tipo.get() in ("BOLETA", "FACTURA", "NOTA DE VENTA"):
            play_cash_approved_sound()
        else:
            play_document_sound("success")


_boquitoqui_audio_queue = queue.Queue()
_boquitoqui_audio_worker_started = False
_boquitoqui_audio_worker_lock = threading.Lock()


def play_boquitoqui_audio(audio_base64="", audio_mime="audio/wav"):
    if not audio_base64:
        return False
    try:
        raw = base64.b64decode(str(audio_base64), validate=False)
    except Exception:
        return False
    start_boquitoqui_audio_worker()
    _boquitoqui_audio_queue.put((raw, str(audio_mime or "audio/wav").lower()))
    return True


def start_boquitoqui_audio_worker():
    global _boquitoqui_audio_worker_started
    with _boquitoqui_audio_worker_lock:
        if _boquitoqui_audio_worker_started:
            return
        _boquitoqui_audio_worker_started = True
        threading.Thread(target=boquitoqui_audio_worker, daemon=True).start()


def boquitoqui_audio_worker():
    while True:
        raw, mime = _boquitoqui_audio_queue.get()
        path = None
        try:
            suffix = ".wav" if "wav" in mime else ".webm"
            fd, path = tempfile.mkstemp(prefix="gg_radio_", suffix=suffix)
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            if suffix == ".wav" and winsound is not None:
                winsound.PlaySound(path, winsound.SND_FILENAME)
            elif os.name == "nt":
                alias = f"ggradio{int(time.time() * 1000)}"
                winmm = ctypes.windll.winmm
                winmm.mciSendStringW(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
                winmm.mciSendStringW(f"play {alias} wait", None, 0, None)
                winmm.mciSendStringW(f"close {alias}", None, 0, None)
        except Exception:
            try:
                if winsound is not None:
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        finally:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
            try:
                _boquitoqui_audio_queue.task_done()
            except Exception:
                pass


def play_boquitoqui_start_sound():
    try:
        if winsound is not None:
            winsound.Beep(580, 70)
            winsound.Beep(880, 90)
    except Exception:
        pass


def play_boquitoqui_stop_sound():
    try:
        if winsound is not None:
            winsound.Beep(720, 70)
            winsound.Beep(420, 90)
    except Exception:
        pass


def _old_play_boquitoqui_audio_direct(audio_base64="", audio_mime="audio/wav"):
    if not audio_base64:
        return False
    try:
        raw = base64.b64decode(str(audio_base64), validate=False)
    except Exception:
        return False
    mime = str(audio_mime or "audio/wav").lower()
    suffix = ".wav" if "wav" in mime else ".webm"
    try:
        fd, path = tempfile.mkstemp(prefix="gg_radio_", suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        if suffix == ".wav" and winsound is not None:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            threading.Timer(8.0, lambda: os.path.exists(path) and os.remove(path)).start()
            return True
        if os.name == "nt":
            alias = f"ggradio{int(time.time() * 1000)}"

            def _play_mci():
                try:
                    winmm = ctypes.windll.winmm
                    winmm.mciSendStringW(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
                    winmm.mciSendStringW(f"play {alias} wait", None, 0, None)
                    winmm.mciSendStringW(f"close {alias}", None, 0, None)
                finally:
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                    except Exception:
                        pass

            threading.Thread(target=_play_mci, daemon=True).start()
            return True
    except Exception:
        try:
            if "path" in locals() and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    return False


def wav_bytes_from_pcm(pcm_bytes, sample_rate=16000, channels=1, bits_per_sample=16):
    pcm_bytes = pcm_bytes or b""
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm_bytes)) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample)
        + b"data" + struct.pack("<I", len(pcm_bytes)) + pcm_bytes
    )


def record_microphone_wav_chunk(duration_ms=260, sample_rate=16000):
    if os.name != "nt":
        return None
    try:
        winmm = ctypes.windll.winmm

        class WAVEFORMATEX(ctypes.Structure):
            _fields_ = [
                ("wFormatTag", ctypes.c_ushort),
                ("nChannels", ctypes.c_ushort),
                ("nSamplesPerSec", ctypes.c_uint),
                ("nAvgBytesPerSec", ctypes.c_uint),
                ("nBlockAlign", ctypes.c_ushort),
                ("wBitsPerSample", ctypes.c_ushort),
                ("cbSize", ctypes.c_ushort),
            ]

        class WAVEHDR(ctypes.Structure):
            _fields_ = [
                ("lpData", ctypes.c_char_p),
                ("dwBufferLength", ctypes.c_uint),
                ("dwBytesRecorded", ctypes.c_uint),
                ("dwUser", ctypes.c_void_p),
                ("dwFlags", ctypes.c_uint),
                ("dwLoops", ctypes.c_uint),
                ("lpNext", ctypes.c_void_p),
                ("reserved", ctypes.c_void_p),
            ]

        channels = 1
        bits = 16
        block_align = channels * bits // 8
        fmt = WAVEFORMATEX(
            1,
            channels,
            sample_rate,
            sample_rate * block_align,
            block_align,
            bits,
            0,
        )
        h_wave = ctypes.c_void_p()
        if winmm.waveInOpen(ctypes.byref(h_wave), 0xFFFFFFFF, ctypes.byref(fmt), 0, 0, 0) != 0:
            return None
        buffer_size = max(1024, int(sample_rate * block_align * duration_ms / 1000))
        buffer = ctypes.create_string_buffer(buffer_size)
        header = WAVEHDR(ctypes.cast(buffer, ctypes.c_char_p), buffer_size, 0, None, 0, 0, None, None)
        try:
            if winmm.waveInPrepareHeader(h_wave, ctypes.byref(header), ctypes.sizeof(header)) != 0:
                return None
            if winmm.waveInAddBuffer(h_wave, ctypes.byref(header), ctypes.sizeof(header)) != 0:
                return None
            if winmm.waveInStart(h_wave) != 0:
                return None
            deadline = time.time() + max(0.15, duration_ms / 1000.0 + 0.7)
            while time.time() < deadline and not (int(header.dwFlags) & 0x00000001):
                time.sleep(0.008)
            try:
                winmm.waveInStop(h_wave)
            except Exception:
                pass
            recorded = int(header.dwBytesRecorded or buffer_size)
            pcm = buffer.raw[:max(0, min(recorded, buffer_size))]
            return wav_bytes_from_pcm(pcm, sample_rate=sample_rate, channels=channels, bits_per_sample=bits) if pcm else None
        finally:
            try:
                winmm.waveInReset(h_wave)
            except Exception:
                pass
            try:
                winmm.waveInUnprepareHeader(h_wave, ctypes.byref(header), ctypes.sizeof(header))
            except Exception:
                pass
            try:
                winmm.waveInClose(h_wave)
            except Exception:
                pass
    except Exception:
        return None


def today_ymd():
    from datetime import date
    return date.today().isoformat()


def now_local_api_timestamp():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def pdf_date_from_value(value):
    from datetime import datetime
    text = str(value or "").strip()
    if not text:
        return datetime.now().strftime("%d/%m/%Y")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:len(fmt)], fmt).strftime("%d/%m/%Y")
        except Exception:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except Exception:
        return text[:10]


def actualizar_estado_pago_documento(documento_id, estado_pago, metodo_pago="", monto_pagado=None, observacion_pago="", comprobante_pago="", comprobante_pago_payload=None, pagos_detalle=None):
    try:
        return _raw_actualizar_estado_pago_documento(
            documento_id, estado_pago, metodo_pago, monto_pagado, observacion_pago, comprobante_pago, comprobante_pago_payload, pagos_detalle
        )
    except TypeError:
        obs = _observacion_con_comprobante(observacion_pago, comprobante_pago) if comprobante_pago else observacion_pago
        return _raw_actualizar_estado_pago_documento(documento_id, estado_pago, metodo_pago, monto_pagado, obs)
    except Exception as e:
        return {"ok": False, "msg": str(e)}


obtener_documentos = _api_func("obtener_documentos", lambda: _api_json("get", "/documentos", []) or [])
obtener_ultimo_documento_caja = _api_func("obtener_ultimo_documento_caja", lambda: _api_json("get", "/documentos/ultimo", {"ok": False}) or {"ok": False})
obtener_detalle_documento = _api_func("obtener_detalle_documento", lambda doc_id: _api_json("get", f"/documentos/{doc_id}", []) or [])
actualizar_series_detalle_documento = _api_func("actualizar_series_detalle_documento", lambda detalle_id, series_texto="", usuario="": _api_json("put", f"/documentos/detalle/{detalle_id}/series", {"ok": False}, json={"series_texto": series_texto, "usuario": usuario}))
crear_documento_manual_series = _api_func("crear_documento_manual_series", lambda payload: _api_json("post", "/documentos/manual-series", {"ok": False}, json=payload))
eliminar_documento = _api_func("eliminar_documento", lambda doc_id: _api_json("delete", f"/documentos/{doc_id}", {"ok": False}))
obtener_compras = _api_func("obtener_compras", lambda: _api_json("get", "/compras", []) or [])
guardar_compra = _api_func("guardar_compra", lambda d: _api_json("post", "/compras", {"ok": False}, json=d))
obtener_proveedores = _api_func("obtener_proveedores", lambda: _api_json("get", "/proveedores", []) or [])
obtener_caja = _api_func("obtener_caja", lambda: _api_json("get", "/caja", []) or [])
guardar_mov_caja = _api_func("guardar_mov_caja", lambda d: _api_json("post", "/caja", {"ok": False}, json=d))
_raw_actualizar_estado_pago_documento = _api_func("actualizar_estado_pago_documento", _actualizar_estado_pago_fallback)
actualizar_estado_sunat = _api_func("actualizar_estado_sunat", lambda documento_id, sunat_estado="PROCESO", sunat_modo="MANUAL": _api_json("put", f"/documentos/{documento_id}/sunat", {"ok": False}, json={"sunat_estado": sunat_estado, "sunat_modo": sunat_modo}))
obtener_sunat_config_api = _api_func("obtener_sunat_config", lambda: _api_json("get", "/sunat/config", {"ok": False}) or {"ok": False})
enviar_documento_sunat_api = _api_func("enviar_documento_sunat", lambda documento_id, regenerar=True, permitir_sin_firma=False: _api_json("post", f"/sunat/documentos/{documento_id}/enviar", {"ok": False}, json={"regenerar": bool(regenerar), "permitir_sin_firma": bool(permitir_sin_firma)}) or {"ok": False})
obtener_estado_documento_sunat_api = _api_func("obtener_estado_documento_sunat", lambda documento_id: _api_json("get", f"/sunat/documentos/{documento_id}/estado", {"ok": False}) or {"ok": False})
obtener_usuarios = _api_func("obtener_usuarios", lambda: _api_json("get", "/usuarios", []) or [])
guardar_usuario = _api_func("guardar_usuario", lambda d: _api_json("post", "/usuarios", {"ok": False}, json=d))
obtener_boquitoqui_mensajes = _api_func("obtener_boquitoqui_mensajes", lambda usuario, since_id=0, limit=10: _api_get_branch(
    f"/boquitoqui/mensajes?usuario={urllib.parse.quote(str(usuario or ''))}&since_id={int(since_id or 0)}&limit={int(limit or 10)}",
    {"ok": False, "data": []}
) or {"ok": False, "data": []})
obtener_boquitoqui_live = _api_func("obtener_boquitoqui_live", lambda usuario, since_id=0, limit=20: _api_get_branch(
    f"/boquitoqui/live?usuario={urllib.parse.quote(str(usuario or ''))}&since_id={int(since_id or 0)}&limit={int(limit or 20)}",
    {"ok": False, "data": []}
) or {"ok": False, "data": []})
enviar_boquitoqui_live = _api_func("enviar_boquitoqui_live", lambda payload: _api_json("post", "/boquitoqui/live", {"ok": False}, json=payload))
obtener_usuarios_online = _api_func("obtener_usuarios_online", lambda: _api_get_branch("/usuarios/online", {"ok": False, "data": []}) or {"ok": False, "data": []})
ajustar_stock_producto = _api_func("ajustar_stock_producto", lambda producto_id, payload: _api_json("post", f"/productos/{producto_id}/ajustar-stock", {"ok": False}, json=payload))
eliminar_producto = _api_func("eliminar_producto", lambda producto_id: _api_json("delete", f"/productos/{producto_id}", {"ok": False}))
actualizar_producto = _api_func("actualizar_producto", lambda producto_id, payload: _api_json("put", f"/productos/{producto_id}", {"ok": False}, json=payload))
transferir_stock_api = _api_func("transferir_stock", lambda producto_id, cantidad, sucursal_destino, usuario="", nota="": _api_json("post", "/stock/transferir", {"ok": False}, json={
    "producto_id": producto_id,
    "cantidad": cantidad,
    "sucursal_origen": getattr(api_client, "EMPRESA", "computer_army") if api_client is not None else "computer_army",
    "sucursal_destino": sucursal_destino,
    "usuario": usuario,
    "nota": nota,
}))
iniciar_inventario_conteo_api = _api_func("iniciar_inventario_conteo", lambda categoria, usuario="": _api_json("post", "/inventario/conteos", {"ok": False}, json={
    "categoria": categoria,
    "usuario": usuario,
    "sucursal": getattr(api_client, "EMPRESA", "computer_army") if api_client is not None else "computer_army",
}))
obtener_inventario_conteo_api = _api_func("obtener_inventario_conteo", lambda conteo_id: _api_get_branch(f"/inventario/conteos/{int(conteo_id)}", {"ok": False}) or {"ok": False})
escanear_inventario_conteo_api = _api_func("escanear_inventario_conteo", lambda conteo_id, serie, usuario="": _api_json("post", f"/inventario/conteos/{int(conteo_id)}/scan", {"ok": False}, json={"serie": serie, "usuario": usuario}))
cerrar_inventario_conteo_api = _api_func("cerrar_inventario_conteo", lambda conteo_id: _api_json("post", f"/inventario/conteos/{int(conteo_id)}/cerrar", {"ok": False}))


def _normalize_producto(p):
    if isinstance(p, dict):
        return p
    if isinstance(p, (list, tuple)):
        values = list(p) + [""] * 9
        return {
            "id": values[0],
            "nombre": values[1],
            "categoria": values[2],
            "marca": values[3],
            "modelo": values[4],
            "precio_compra": values[5],
            "precio_venta": values[6],
            "stock": values[7],
            "imagen_url": values[8],
        }
    return {}


def _normalize_cliente(c):
    if isinstance(c, dict):
        return c
    if isinstance(c, (list, tuple)):
        values = list(c) + [""] * 5
        return {
            "id": values[0],
            "tipo_documento": values[1],
            "numero_documento": values[2],
            "nombre": values[3],
            "direccion": values[4],
        }
    return {}


_raw_obtener_productos = obtener_productos
_raw_buscar_productos = buscar_productos
_raw_obtener_clientes = obtener_clientes
_raw_buscar_cliente_por_documento = buscar_cliente_por_documento


def obtener_productos():
    data = _raw_obtener_productos() or []
    return [_normalize_producto(p) for p in data]


def buscar_productos(texto):
    q = str(texto or "").strip().lower()
    tokens = [t for t in q.replace("|", " ").replace("-", " ").split() if t]
    base = [_normalize_producto(p) for p in (obtener_productos() or [])]

    if not tokens:
        return base[:50]

    def score_producto(p):
        campos = [
            str(p.get("id", "")),
            str(p.get("nombre", "")),
            str(p.get("categoria", "")),
            str(p.get("marca", "")),
            str(p.get("modelo", "")),
        ]
        texto_busqueda = " ".join(campos).lower()
        if not all(token in texto_busqueda for token in tokens):
            return -1
        score = 0
        nombre = str(p.get("nombre", "")).lower()
        marca = str(p.get("marca", "")).lower()
        modelo = str(p.get("modelo", "")).lower()
        pid = str(p.get("id", "")).lower()
        for token in tokens:
            if token == pid:
                score += 100
            if nombre.startswith(token):
                score += 40
            if token in nombre:
                score += 25
            if token in marca or token in modelo:
                score += 15
            if token in texto_busqueda:
                score += 5
        return score

    resultados = []
    for p in base:
        score = score_producto(p)
        if score >= 0:
            resultados.append((score, p))
    resultados.sort(key=lambda item: (-item[0], str(item[1].get("nombre", ""))))
    return [p for _, p in resultados[:50]]


def obtener_clientes():
    data = _raw_obtener_clientes() or []
    return [_normalize_cliente(c) for c in data]


def buscar_cliente_por_documento(documento):
    data = _raw_buscar_cliente_por_documento(documento)
    if isinstance(data, dict) and data.get("found"):
        return data
    doc = str(documento or "").strip()
    for c in obtener_clientes():
        if str(c.get("numero_documento", "")).strip() == doc:
            return {
                "found": True,
                "id": c.get("id"),
                "tipo_documento": c.get("tipo_documento"),
                "numero_documento": c.get("numero_documento"),
                "nombre": c.get("nombre", ""),
                "direccion": c.get("direccion", ""),
            }
    return {"found": False}

def api_response_ok(resp):
    if not isinstance(resp, dict):
        return False
    if resp.get("ok") is True or resp.get("success") is True:
        return True
    data = resp.get("data")
    return data not in (None, False)


def api_response_get(resp, key, default=None):
    if isinstance(resp, dict):
        if key in resp:
            return resp.get(key, default)
        data = resp.get("data")
        if isinstance(data, dict):
            return data.get(key, default)
    return default


def api_response_error(resp, default="Error desconocido"):
    if isinstance(resp, dict):
        data = resp.get("data")
        if isinstance(data, dict):
            for key in ("detail", "msg", "message", "error"):
                if data.get(key):
                    return str(data.get(key))
        for key in ("detail", "msg", "message", "error"):
            if resp.get(key):
                return str(resp.get(key))
        return str(resp)
    return default


LOCAL_DOCS_FILE = "documentos_emitidos_local.json"
IMAGE_CACHE_DIR = os.path.join(os.getenv("LOCALAPPDATA") or tempfile.gettempdir(), "GF_ERP", "image_cache")
PAYMENT_RECEIPTS_DIR = os.path.join(os.getenv("LOCALAPPDATA") or tempfile.gettempdir(), "GF_ERP", "comprobantes_pago")
PAYMENT_RECEIPTS_FILE = os.path.join(os.getenv("LOCALAPPDATA") or tempfile.gettempdir(), "GF_ERP", "comprobantes_pago.json")


def _load_local_documents():
    try:
        if os.path.exists(LOCAL_DOCS_FILE):
            with open(LOCAL_DOCS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_local_documents(data):
    try:
        with open(LOCAL_DOCS_FILE, "w", encoding="utf-8") as f:
            json.dump(data[-1000:], f, indent=4, ensure_ascii=False)
    except Exception:
        pass


def _load_payment_receipts():
    try:
        if os.path.exists(PAYMENT_RECEIPTS_FILE):
            with open(PAYMENT_RECEIPTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_payment_receipts(data):
    try:
        os.makedirs(os.path.dirname(PAYMENT_RECEIPTS_FILE), exist_ok=True)
        with open(PAYMENT_RECEIPTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception:
        pass


def _safe_file_name(name):
    base = os.path.basename(str(name or "comprobante"))
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "comprobante"


def _remember_payment_receipt(documento_id, source_path):
    if not source_path or not os.path.isfile(source_path):
        return None
    os.makedirs(PAYMENT_RECEIPTS_DIR, exist_ok=True)
    safe = _safe_file_name(source_path)
    stamp = re.sub(r"[^0-9]", "", str(documento_id or "")) or hashlib.sha1(str(documento_id).encode("utf-8")).hexdigest()[:8]
    dest = os.path.join(PAYMENT_RECEIPTS_DIR, f"{stamp}_{safe}")
    if os.path.abspath(source_path) != os.path.abspath(dest):
        shutil.copy2(source_path, dest)
    data = _load_payment_receipts()
    data[str(documento_id)] = {
        "path": dest,
        "nombre": os.path.basename(source_path),
        "mime": mimetypes.guess_type(source_path)[0] or "application/octet-stream",
    }
    _save_payment_receipts(data)
    return data[str(documento_id)]


def _remember_payment_receipts(documento_id, source_paths):
    saved = []
    for source_path in source_paths or []:
        item = _remember_payment_receipt(documento_id, source_path)
        if item:
            saved.append(item)
    if saved:
        data = _load_payment_receipts()
        data[str(documento_id)] = {"items": saved, **saved[0]}
        _save_payment_receipts(data)
    return saved


def _payment_receipts_from_doc(doc, documento_id=None):
    doc = doc or {}
    receipts = []
    data = _load_payment_receipts()
    local = data.get(str(documento_id or doc.get("id", "")))
    if isinstance(local, dict):
        if isinstance(local.get("items"), list):
            receipts.extend([x for x in local.get("items") if isinstance(x, dict)])
        elif local.get("path"):
            receipts.append(local)
    raw_items = doc.get("comprobantes_pago")
    if not raw_items and doc.get("comprobantes_pago_json"):
        try:
            raw_items = json.loads(doc.get("comprobantes_pago_json") or "[]")
        except Exception:
            raw_items = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            receipts.append({
                "data_url": item.get("data_url") or item.get("comprobante_pago_data_url"),
                "base64": item.get("base64") or item.get("comprobante_pago_base64"),
                "mime": item.get("mime") or item.get("comprobante_pago_mime") or "application/octet-stream",
                "nombre": item.get("nombre") or item.get("comprobante_pago_nombre") or "comprobante_pago",
                "path": item.get("path") or item.get("comprobante_pago") or "",
            })
    seen = set()
    unique = []
    for receipt in receipts:
        key = str(receipt.get("data_url") or receipt.get("base64") or receipt.get("path") or receipt.get("nombre") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(receipt)
    return unique


def _payment_receipt_from_doc(doc, documento_id=None):
    receipts = _payment_receipts_from_doc(doc, documento_id)
    if receipts:
        return receipts[0]
    doc = doc or {}
    data = _load_payment_receipts()
    local = data.get(str(documento_id or doc.get("id", "")))
    if isinstance(local, dict) and local.get("path"):
        return local
    for key in ("comprobante_pago_data_url", "pago_comprobante_data_url", "comprobante_data_url"):
        if doc.get(key):
            return {"data_url": doc.get(key), "nombre": doc.get("comprobante_pago_nombre") or "comprobante_pago"}
    for key in ("comprobante_pago_base64", "pago_comprobante_base64", "comprobante_base64"):
        if doc.get(key):
            return {
                "base64": doc.get(key),
                "mime": doc.get("comprobante_pago_mime") or "application/octet-stream",
                "nombre": doc.get("comprobante_pago_nombre") or "comprobante_pago",
            }
    for key in ("comprobante_pago", "pago_comprobante", "comprobante_url", "comprobante_pago_url"):
        value = str(doc.get(key) or "").strip()
        if value:
            return {"path": value, "nombre": os.path.basename(value) or value}
    obs = str(doc.get("observacion_pago") or "")
    m = re.search(r"Comprobante:\s*([^|]+)", obs, flags=re.IGNORECASE)
    if m:
        return {"nombre": m.group(1).strip()}
    return None


def _receipt_search_sources(source, documento_id=None, depth=0):
    if depth > 4 or source is None:
        return None
    if isinstance(source, dict):
        receipt = _payment_receipt_from_doc(source, documento_id)
        if receipt:
            return receipt
        for key in ("data", "documento", "doc", "venta", "pago", "payment", "cabecera"):
            if key in source:
                receipt = _receipt_search_sources(source.get(key), documento_id, depth + 1)
                if receipt:
                    return receipt
        for key in ("detalle", "items", "lineas", "lines", "detalles"):
            value = source.get(key)
            if isinstance(value, list):
                receipt = _receipt_search_sources(value, documento_id, depth + 1)
                if receipt:
                    return receipt
    elif isinstance(source, list):
        for row in source:
            receipt = _receipt_search_sources(row, documento_id, depth + 1)
            if receipt:
                return receipt
    return None


def _documento_payload_desde_api(doc_id):
    try:
        return _remote_obtener_detalle_documento(doc_id)
    except Exception:
        return {}


def _documento_record_from_payload(payload):
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        nested = _documento_record_from_payload(data)
        if nested:
            return nested
    for key in ("documento", "doc", "venta", "cabecera"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {k: v for k, v in payload.items() if k not in ("detalle", "items", "lineas", "lines", "detalles")}


def _payment_receipt_for_document(doc, documento_id=None, payload=None, detail=None):
    for source in (doc, payload, detail):
        receipt = _receipt_search_sources(source, documento_id)
        if receipt:
            return receipt
    return None


def _payment_receipts_for_document(doc, documento_id=None, payload=None, detail=None):
    receipts = []
    for source in (doc, payload, detail):
        if isinstance(source, dict):
            receipts.extend(_payment_receipts_from_doc(source, documento_id))
        receipt = _receipt_search_sources(source, documento_id)
        if receipt:
            receipts.append(receipt)
    seen = set()
    unique = []
    for receipt in receipts:
        key = str(receipt.get("data_url") or receipt.get("base64") or receipt.get("path") or receipt.get("nombre") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(receipt)
    return unique


def _receipt_to_openable_path(receipt):
    if not receipt:
        return None
    path = str(receipt.get("path") or "").strip()
    if path and os.path.exists(path):
        return path
    data_url = str(receipt.get("data_url") or "").strip()
    raw_b64 = str(receipt.get("base64") or "").strip()
    mime = str(receipt.get("mime") or "application/octet-stream").strip()
    if data_url.startswith("data:"):
        header, raw_b64 = data_url.split(",", 1) if "," in data_url else ("", "")
        if ";" in header:
            mime = header[5:].split(";", 1)[0] or mime
    if raw_b64:
        ext = mimetypes.guess_extension(mime) or os.path.splitext(str(receipt.get("nombre") or ""))[1] or ".bin"
        out = os.path.join(tempfile.gettempdir(), f"comprobante_pago_{hashlib.sha1(raw_b64[:64].encode('ascii', 'ignore')).hexdigest()[:10]}{ext}")
        if not os.path.exists(out):
            with open(out, "wb") as f:
                f.write(base64.b64decode(raw_b64))
        return out
    return path or None


def recordar_documento_local(doc, detalle):
    """Obsoleto: los documentos viven solo en la API. Se mantiene la firma por compatibilidad."""
    return


_remote_obtener_documentos = obtener_documentos
_remote_obtener_detalle_documento = obtener_detalle_documento


def _documentos_list_desde_api():
    """Lista devuelta por GET /documentos sin mezclar copia local (sirve para enlazar ID real al guardar pago)."""
    remote = _remote_obtener_documentos() or []
    if isinstance(remote, dict):
        data = remote.get("data")
        remote = data if isinstance(data, list) else []
    return remote if isinstance(remote, list) else []


def obtener_documentos():
    """Solo documentos en el servidor (sin documentos_emitidos_local.json)."""
    remote = _remote_obtener_documentos() or []
    if isinstance(remote, dict):
        data = remote.get("data")
        remote = data if isinstance(data, list) else []
    return remote if isinstance(remote, list) else []


def obtener_documentos_api_reales():
    """Documentos cuyo id es numerico (compatibilidad con codigo que asume ID entero de BD)."""
    return [d for d in _documentos_list_desde_api() if str(d.get("id", "")).strip().isdigit()]


def _extract_documento_detalle_lines(payload):
    """
    GET /documentos/:id suele devolver un objeto (dict) con clave 'detalle' (lista de dicts).
    Si se itera ese dict directamente, las claves son str y falla .get en cada linea.
    """
    if not payload:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("detalle", "items", "lineas", "lines", "detalles"):
        v = payload.get(key)
        if isinstance(v, list) and all(isinstance(x, dict) for x in v):
            return list(v)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("detalle", "items", "lineas", "lines", "detalles"):
            v = data.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def obtener_detalle_documento(doc_id):
    remote = _remote_obtener_detalle_documento(doc_id)
    lines = _extract_documento_detalle_lines(remote)
    return lines if lines else []

CONFIG_FILE = "config.json"
APP_BG = "#eef3f8"
TOPBAR_BG = "#ffffff"
SIDEBAR_BG = "#0b3f75"
SIDEBAR_HOVER = "#0f5d9a"
SIDEBAR_TEXT = "#eaf6ff"
SIDEBAR_MUTED = "#bfdbfe"
CARD_BG = "#ffffff"
TEXT = "#162033"
MUTED = "#64748b"
ACCENT = "#f59e0b"
ACCENT_DARK = "#d97706"
BORDER = "#d8e2ee"
SOFT_BG = "#f8fafc"
SUCCESS = "#11a36a"
DANGER = "#ef4444"
WARNING = "#f59e0b"

NAV_MARKS = {
    "dashboard": "▦",
    "ventas": "▤",
    "clientes": "◎",
    "productos": "◈",
    "inventario": "▣",
    "compras": "+",
    "contabilidad": "▥",
    "caja": "$",
    "radio": "▶",
    "usuarios": "◉",
    "garantias": "✓",
    "auditoria": "◷",
    "erp_moderno": "▧",
    "pagina_web": "⌁",
    "ajustes": "⚙",
}

NAV_ITEMS = [
    ("Panel", "dashboard", "#0f5d9a"),
    ("Ventas", "ventas", "#11a36a"),
    ("Clientes", "clientes", "#2563eb"),
    ("Productos", "productos", "#f97316"),
    ("Inventario", "inventario", "#7c3aed"),
    ("Compras", "compras", "#0891b2"),
    ("Documentos", "contabilidad", "#ef4444"),
    ("Caja", "caja", "#f59e0b"),
    ("Radio", "radio", "#65a30d"),
    ("Usuarios", "usuarios", "#6b7280"),
    ("Garantías", "garantias", "#0f766e"),
    ("Registro", "auditoria", "#9333ea"),
    ("ERP Moderno", "erp_moderno", "#2563eb"),
    ("Página Web", "pagina_web", "#0f766e"),
    ("Configuración", "ajustes", "#334155"),
]


def apply_modern_ttk_style(root=None):
    try:
        if root is not None:
            for pattern, value in (
                ("*foreground", TEXT),
                ("*background", CARD_BG),
                ("*Entry.background", SOFT_BG),
                ("*Entry.foreground", TEXT),
                ("*Entry.insertBackground", TEXT),
                ("*Text.background", SOFT_BG),
                ("*Text.foreground", TEXT),
                ("*Listbox.background", SOFT_BG),
                ("*Listbox.foreground", TEXT),
                ("*selectBackground", ACCENT_DARK),
                ("*selectForeground", "#ffffff"),
            ):
                try:
                    root.option_add(pattern, value)
                except Exception:
                    pass
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Treeview",
                        background=CARD_BG,
                        fieldbackground=CARD_BG,
                        foreground=TEXT,
                        bordercolor=BORDER,
                        rowheight=32,
                        font=("Arial", 10))
        style.configure("Treeview.Heading",
                        background="#eff6ff",
                        foreground=TEXT,
                        bordercolor=BORDER,
                        relief="flat",
                        font=("Arial", 10, "bold"))
        style.map("Treeview",
                  background=[("selected", "#0f5d9a")],
                  foreground=[("selected", "#ffffff")])
        style.configure("TCombobox",
                        fieldbackground=SOFT_BG,
                        background=SOFT_BG,
                        foreground=TEXT,
                        bordercolor=BORDER,
                        arrowcolor=TEXT,
                        padding=5,
                        font=("Arial", 10))
        style.configure("TEntry",
                        fieldbackground=SOFT_BG,
                        foreground=TEXT,
                        bordercolor=BORDER,
                        padding=6)
        style.configure("Horizontal.TProgressbar",
                        troughcolor="#e2e8f0",
                        background=ACCENT,
                        bordercolor="#e2e8f0",
                        lightcolor=ACCENT,
                        darkcolor=ACCENT)
    except Exception:
        pass

VENTAS_NAV_KEYS = {"ventas", "clientes", "productos", "radio"}
DEFAULT_MODULE_PERMISSIONS = {
    "dashboard": True,
    "ventas": True,
    "clientes": True,
    "productos": True,
    "inventario": True,
    "compras": True,
    "contabilidad": True,
    "caja": True,
    "radio": True,
    "usuarios": True,
    "garantias": True,
    "auditoria": True,
    "erp_moderno": True,
    "pagina_web": True,
    "ajustes": True,
}

DOCUMENT_LABEL_DEFAULTS = {
    "cliente": "CLIENTE",
    "documento": "DOCUMENTO",
    "direccion": "DIRECCION",
    "fecha_emision": "FECHA EMISION",
    "fecha_vencimiento": "FECHA VENCIMIENTO",
    "moneda": "MONEDA",
    "usuario": "USUARIO",
    "condicion_pago": "CONDICION DE PAGO",
    "cuentas_bancarias": "CUENTAS BANCARIAS",
    "gravado": "GRAVADO",
    "igv": "I.G.V. 18%",
    "total": "TOTAL",
    "col_num": "Nro",
    "col_unidad": "UNIDAD",
    "col_descripcion": "DESCRIPCION",
    "col_cantidad": "CANT.",
    "col_total": "TOTAL",
    "col_unitario": "P. UNIT.",
    "mensaje": "GRACIAS POR SU COMPRA",
}

DOCUMENT_TEXT_DEFAULTS = {
    "empresa": "",
    "direccion": "",
    "contacto": "",
    "slogan": "",
    "condicion_pago_valor": "CONTADO",
    "legal_line1": "Autorizado mediante resolucion Nro 034-005-0010431/SUNAT",
    "legal_line2": "Representacion impresa del comprobante electronico",
    "legal_line3": "Emitido mediante G&G ERP",
    "resumen": "Resumen",
    "garantia_1": "UN ANO DE GARANTIA DE CADA PRODUCTO Y 6 MESES PARA PERIFERICOS",
    "garantia_2": "NO SE ACEPTAN CAMBIOS NI DEVOLUCIONES. SOLO DEFECTO DE FABRICA",
    "garantia_3": "CONSERVAR CAJAS Y ACCESORIOS DE CADA PRODUCTO",
    "garantia_4": "NO HAY GARANTIA por software, dano fisico, roto, quemado, sulfatado, presencia de oxido o presencia de sulfato",
    "garantia_5": "ENSAMBLAJE PROFESIONAL Y INSTALACION DE SISTEMA OPERATIVO WINDOWS, PAQUETE DE OFFICE GRATIS",
    "garantia_6": "POR PC COMPLETA",
}

ALMACEN_OPTIONS = ("TIENDA", "ALMACEN", "VITRINA", "TALLER", "GARANTIA")


def ensure_document_editor_defaults(cfg):
    doc = cfg.setdefault("doc_editor", {})
    doc.setdefault("template_name", "Plantilla principal")
    doc.setdefault("show_logo", True)
    doc.setdefault("show_serie", True)
    doc.setdefault("show_banks", True)
    doc.setdefault("title_font", 13)
    doc.setdefault("header_font", 11)
    doc.setdefault("body_font", 8)
    doc.setdefault("table_font", 7)
    doc.setdefault("pdf_code_width", 19)
    doc.setdefault("pdf_desc_x", 52)
    doc.setdefault("pdf_desc_chars", 48)
    doc.setdefault("pdf_desc_font", 7.0)
    doc.setdefault("pdf_desc_bold", True)
    doc.setdefault("pdf_series_font", 6.2)
    doc.setdefault("pdf_row_height", 6.5)
    doc.setdefault("pdf_code_chars", 10)
    doc.setdefault("pdf_max_rows_first_page", 12)
    doc.setdefault("pdf_desc_lines", 3)
    doc.setdefault("pdf_series_lines", 1)
    doc.setdefault("pdf_line_gap", 2.8)
    doc.setdefault("logo_x", 16)
    doc.setdefault("logo_y", 27)
    doc.setdefault("logo_w", 24)
    doc.setdefault("logo_h", 15)
    doc.setdefault("company_x", 49)
    doc.setdefault("company_y", 10.5)
    doc.setdefault("company_w", 82)
    doc.setdefault("extra_images", [])
    labels = doc.setdefault("labels", {})
    for key, value in DOCUMENT_LABEL_DEFAULTS.items():
        labels.setdefault(key, value)
    texts = doc.setdefault("texts", {})
    for key, value in DOCUMENT_TEXT_DEFAULTS.items():
        texts.setdefault(key, value)
    return cfg


def load_config():
    default = {
        "empresa": "TU EMPRESA",
        "ruc": "",
        "direccion": "",
        "telefono": "",
        "correo": "",
        "logo": app_resource_path("ARMY.png"),
        "dashboard_img": "",
        "mensaje": "GRACIAS POR SU COMPRA",
        "footer_line1": "",
        "footer_line2": "",
        "cuenta_bcp": "",
        "cuenta_interbank": "",
        "mostrar_bancos": True,
        "mostrar_igv": True,
        "caja_solo_servidor": True,
        "igv": 0.18,
        "doc_series": {"PROFORMA": "P001", "PASE": "PA001", "BOLETA": "B001", "FACTURA": "F001"},
        "doc_editor": {
            "template_name": "Plantilla principal",
            "show_logo": True,
            "show_serie": True,
            "show_banks": True,
            "title_font": 13,
            "header_font": 11,
            "body_font": 8,
            "table_font": 7,
            "pdf_code_width": 19,
            "pdf_desc_x": 52,
            "pdf_desc_chars": 48,
            "pdf_desc_font": 7.0,
            "pdf_desc_bold": True,
            "pdf_series_font": 6.2,
            "pdf_row_height": 6.5,
            "pdf_code_chars": 10,
            "labels": {
                "cliente": "Cliente:",
                "documento": "Documento:",
                "direccion": "Dirección:",
                "subtotal": "SUBTOTAL",
                "igv": "IGV",
                "total": "TOTAL",
                "mensaje": "GRACIAS POR SU COMPRA"
            }
        },
        "layout": {
            "header_left": {"x": 12, "y": 12, "w": 92, "h": 28},
            "header_right": {"x": 140, "y": 12, "w": 55, "h": 28},
            "client_box": {"x": 12, "y": 45, "w": 183, "h": 22},
            "table": {"x": 12, "y": 72, "w": 183, "h": 120},
            "totals_box": {"x": 125, "y": 195, "w": 70, "h": 22},
            "footer_box": {"x": 12, "y": 221, "w": 183, "h": 18}
        }
    }
    ensure_document_editor_defaults(default)
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4, ensure_ascii=False)
        return default
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for k, v in default.items():
        if k not in data:
            data[k] = v
        elif isinstance(v, dict):
            for k2, v2 in v.items():
                if k2 not in data[k]:
                    data[k][k2] = v2
    if not document_logo_path(data):
        data["logo"] = app_resource_path("ARMY.png")
    return ensure_document_editor_defaults(data)


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    save_shared_document_config(cfg)


def image_cache_path(src, size):
    key = hashlib.sha1(f"{src}|{size[0]}x{size[1]}".encode("utf-8", errors="ignore")).hexdigest()
    return os.path.join(IMAGE_CACHE_DIR, f"{key}.img")



def deep_merge_config(base, remote):
    if not isinstance(remote, dict):
        return base
    for k, v in remote.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge_config(base[k], v)
        else:
            base[k] = v
    return base


def load_shared_document_config(cfg):
    try:
        fn = getattr(api_client, "obtener_config_documento", None) if api_client is not None else None
        if not callable(fn):
            return cfg
        resp = fn()
        if api_response_ok(resp):
            data = api_response_get(resp, "data", {}) or {}
            if isinstance(data, dict) and data:
                deep_merge_config(cfg, data)
                ensure_document_editor_defaults(cfg)
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception:
        pass
    return ensure_document_editor_defaults(cfg)


def save_shared_document_config(cfg):
    try:
        fn = getattr(api_client, "guardar_config_documento", None) if api_client is not None else None
        if callable(fn):
            return fn(cfg)
    except Exception as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": False}


def load_sucursales_local():
    base = {
        "computer_army": {"nombre": "COMPUTER ARMY", "db": "ERP_PCFast"},
        "sky_gaming": {"nombre": "SKY GAMING", "db": "ERP_SkyGaming"},
        "crishardware": {"nombre": "CRISHARDWARE", "db": "ERP_Crishardware"},
        "aceadvance": {"nombre": "ACEADVANCE", "db": "ERP_AceAdvance"},
        "chamo": {"nombre": "CHAMO", "db": "ERP_Chamo"},
    }
    try:
        if os.path.exists("sucursales.json"):
            with open("sucursales.json", "r", encoding="utf-8") as f:
                extra = json.load(f)
            if isinstance(extra, dict):
                for k, v in extra.items():
                    if isinstance(v, dict) and v.get("nombre"):
                        base[k] = v
    except Exception:
        pass
    return base

def empresa_display_options():
    fn = getattr(api_client, "obtener_sucursales", None) if api_client is not None else None
    if callable(fn):
        try:
            data = fn()
            if isinstance(data, list) and data:
                return [str(x.get("nombre") or x.get("codigo", "")).upper() for x in data if x.get("codigo")]
        except Exception:
            pass
    return [v.get("nombre", k).upper() for k, v in load_sucursales_local().items()]

def empresa_to_key(nombre_visible):
    nombre_visible = (nombre_visible or "").strip().upper()
    fn = getattr(api_client, "obtener_sucursales", None) if api_client is not None else None
    if callable(fn):
        try:
            data = fn()
            if isinstance(data, list):
                for row in data:
                    if str(row.get("nombre", "")).strip().upper() == nombre_visible:
                        return str(row.get("codigo") or "computer_army")
        except Exception:
            pass
    for k, v in load_sucursales_local().items():
        if v.get("nombre", "").strip().upper() == nombre_visible:
            return k
    return "computer_army"


def money(x):
    return f"S/ {float(x):,.2f}"


def is_valid_cash_receipt(path):
    return bool(path and os.path.isfile(path) and os.path.getsize(path) <= 15 * 1024 * 1024)


def cash_receipt_server_payload(path):
    return _comprobante_pago_payload(path)


def calculate_sunat_totals(items, descuento=0, igv_rate=0.18, afectacion="GRAVADO - IGV 18%"):
    total = round(sum(float(x.get("total", 0) or 0) for x in (items or [])) - float(descuento or 0), 2)
    total = max(total, 0.0)
    afectacion = str(afectacion or "").upper()
    if "GRAVADO" in afectacion and igv_rate:
        subtotal = round(total / (1 + float(igv_rate)), 2)
        igv = round(total - subtotal, 2)
    else:
        subtotal = total
        igv = 0.0
    return {"subtotal": subtotal, "igv": igv, "total": total, "gravado": subtotal, "descuento": float(descuento or 0)}


def generate_sunat_ubl_xml(path, cfg, doc_type, doc_number, client_name, client_doc_type, client_doc_number, items, totals, extra=None):
    def esc(value):
        return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    extra = extra or {}
    invoice_code = "01" if str(doc_type).upper() == "FACTURA" else "03"
    issue_date = str(extra.get("fecha_emision") or today_ymd())[:10]
    lines = []
    for idx, item in enumerate(items or [], start=1):
        qty = float(item.get("cantidad", 1) or 1)
        total_item = float(item.get("total", 0) or 0)
        price = float(item.get("precio", item.get("precio_unitario", total_item / qty if qty else 0)) or 0)
        lines.append(
            f"<cac:InvoiceLine><cbc:ID>{idx}</cbc:ID><cbc:InvoicedQuantity>{qty:g}</cbc:InvoicedQuantity>"
            f"<cbc:LineExtensionAmount currencyID=\"PEN\">{total_item:.2f}</cbc:LineExtensionAmount>"
            f"<cac:Item><cbc:Description>{esc(item.get('nombre') or item.get('descripcion'))}</cbc:Description></cac:Item>"
            f"<cac:Price><cbc:PriceAmount currencyID=\"PEN\">{price:.2f}</cbc:PriceAmount></cac:Price></cac:InvoiceLine>"
        )
    xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<Invoice xmlns=\"urn:oasis:names:specification:ubl:schema:xsd:Invoice-2\" "
        "xmlns:cac=\"urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2\" "
        "xmlns:cbc=\"urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2\">"
        f"<cbc:ID>{esc(doc_number)}</cbc:ID><cbc:IssueDate>{esc(issue_date)}</cbc:IssueDate>"
        f"<cbc:InvoiceTypeCode>{invoice_code}</cbc:InvoiceTypeCode><cbc:DocumentCurrencyCode>{esc(extra.get('moneda') or 'PEN')}</cbc:DocumentCurrencyCode>"
        f"<cac:AccountingSupplierParty><cac:Party><cac:PartyIdentification><cbc:ID>{esc(cfg.get('sunat_ruc') or cfg.get('ruc'))}</cbc:ID></cac:PartyIdentification>"
        f"<cac:PartyName><cbc:Name>{esc(cfg.get('empresa'))}</cbc:Name></cac:PartyName></cac:Party></cac:AccountingSupplierParty>"
        f"<cac:AccountingCustomerParty><cac:Party><cac:PartyIdentification><cbc:ID>{esc(client_doc_number)}</cbc:ID></cac:PartyIdentification>"
        f"<cac:PartyName><cbc:Name>{esc(client_name)}</cbc:Name></cac:PartyName></cac:Party></cac:AccountingCustomerParty>"
        f"<cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID=\"PEN\">{float(totals.get('subtotal', 0)):.2f}</cbc:LineExtensionAmount>"
        f"<cbc:TaxInclusiveAmount currencyID=\"PEN\">{float(totals.get('total', 0)):.2f}</cbc:TaxInclusiveAmount>"
        f"<cbc:PayableAmount currencyID=\"PEN\">{float(totals.get('total', 0)):.2f}</cbc:PayableAmount></cac:LegalMonetaryTotal>"
        + "".join(lines) +
        "</Invoice>"
    )
    with open(path, "wb") as f:
        f.write(xml.encode("utf-8"))
    digest = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    return {"ok": True, "path": path, "hash": digest}


def build_doc_number(doc_type, backend_number, cfg):
    raw = backend_number or ""
    if "-" in raw:
        _, corr = raw.split("-", 1)
        return f'{cfg.get("doc_series", {}).get(doc_type, "X001")}-{corr}'
    return raw


def offset_doc_number(doc_number, offset=0):
    try:
        offset = int(offset or 0)
    except Exception:
        offset = 0
    if offset <= 0 or "-" not in str(doc_number or ""):
        return doc_number
    prefix, corr = str(doc_number).rsplit("-", 1)
    if not corr.isdigit():
        return doc_number
    return f"{prefix}-{str(int(corr) + offset).zfill(len(corr))}"


def mm_to_pt(v):
    return v * mm


def draw_text(c, x, y, txt, size=8, bold=False):
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, str(txt))


def wrap_text_by_chars(text, max_chars):
    """Rompe por palabras; palabras muy largas se cortan (sin canvas)."""
    text = str(text or "").replace("\n", " ").strip()
    if not text or max_chars < 4:
        return [""]
    words = text.split()
    lines, current = [], ""
    for word in words:
        chunks = [word[i : i + max_chars] for i in range(0, len(word), max_chars)] if len(word) > max_chars else [word]
        for chunk in chunks:
            trial = (current + " " + chunk).strip() if current else chunk
            if len(trial) <= max_chars:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = chunk
    if current:
        lines.append(current)
    return lines or [""]


def wrap_text_mm_canvas(c, text, max_mm, font_name, size, fudge=0.96):
    """
    Rompe descripcion / texto largo por ancho real en puntos (evita que se meta en columnas de cantidad/precio).
    fudge: margen por kern/glyphs que miden un poco mas que stringWidth.
    """
    max_pt = max(1.0, float(max_mm)) * mm * fudge
    text = str(text or "").replace("\n", " ").strip()
    if not text:
        return [""]
    words = text.split()
    lines, current = [], ""
    for word in words:
        pieces = []
        if c.stringWidth(word, font_name, size) <= max_pt:
            pieces = [word]
        else:
            part = ""
            for ch in word:
                cand = part + ch
                if part and c.stringWidth(cand, font_name, size) > max_pt:
                    pieces.append(part)
                    part = ch
                else:
                    part = cand
            if part:
                pieces.append(part)
        for piece in pieces:
            trial = (current + " " + piece).strip() if current else piece
            if not current or c.stringWidth(trial, font_name, size) <= max_pt:
                current = trial
            else:
                lines.append(current)
                current = piece
    if current:
        lines.append(current)
    return lines or [""]


def format_series_for_print(series_text):
    cleaned = str(series_text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^(s\s*/?\s*n|serie)\s*[:\-]?\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return f"S/N: {cleaned}" if cleaned else ""


def data_url_logo_path(value):
    text = str(value or "").strip()
    if not text.startswith("data:image/") or "," not in text:
        return ""
    header, payload = text.split(",", 1)
    ext = "png"
    if "jpeg" in header or "jpg" in header:
        ext = "jpg"
    elif "webp" in header:
        ext = "webp"
    path = os.path.join(tempfile.gettempdir(), f"gg_erp_document_logo.{ext}")
    try:
        with open(path, "wb") as f:
            f.write(base64.b64decode(payload))
        return path
    except Exception:
        return ""


def document_logo_path(cfg):
    configured = str((cfg or {}).get("logo", "") or "").strip()
    decoded = data_url_logo_path(configured)
    for candidate in (decoded, configured, app_resource_path("ARMY.png")):
        if candidate and os.path.exists(candidate):
            return candidate
    return ""


def generate_pdf(filepath, cfg, doc_type, doc_number, client_name, client_doc, client_addr, items, subtotal, igv, total, vendedor="", extra=None):
    c = canvas.Canvas(filepath, pagesize=A4)
    page_w, page_h = A4

    def x(mm_value):
        return mm_value * mm

    def y(mm_value):
        return page_h - (mm_value * mm)

    def font(name="Helvetica", size=8):
        c.setFont(name, size)

    def txt(px, py, value, size=8, bold=False):
        font("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x(px), y(py), str(value or ""))

    def txt_right(px, py, value, size=8, bold=False):
        font("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawRightString(x(px), y(py), str(value or ""))

    def txt_right_fit(px, py, value, size=8, bold=False, max_mm=16, min_size=5):
        text = str(value or "")
        font_name = "Helvetica-Bold" if bold else "Helvetica"
        use_size = float(size)
        while use_size > min_size and c.stringWidth(text, font_name, use_size) > x(max_mm):
            use_size -= 0.5
        while len(text) > 4 and c.stringWidth(text, font_name, use_size) > x(max_mm):
            text = "..." + text[-(len(text) - 4):]
        font(font_name, use_size)
        c.drawRightString(x(px), y(py), text)

    def txt_center(px, py, value, size=8, bold=False):
        font("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawCentredString(x(px), y(py), str(value or ""))

    def txt_fit(px, py, value, size=8, bold=False, max_mm=40, min_size=4):
        text = str(value or "")
        font_name = "Helvetica-Bold" if bold else "Helvetica"
        use_size = float(size)
        while use_size > min_size and c.stringWidth(text, font_name, use_size) > x(max_mm):
            use_size -= 0.5
        while len(text) > 4 and c.stringWidth(text, font_name, use_size) > x(max_mm):
            text = text[:-4] + "..."
        font(font_name, use_size)
        c.drawString(x(px), y(py), text)

    def txt_center_fit(px, py, value, size=8, bold=False, max_mm=40, min_size=4):
        text = str(value or "")
        font_name = "Helvetica-Bold" if bold else "Helvetica"
        use_size = float(size)
        while use_size > min_size and c.stringWidth(text, font_name, use_size) > x(max_mm):
            use_size -= 0.5
        while len(text) > 4 and c.stringWidth(text, font_name, use_size) > x(max_mm):
            text = text[:-4] + "..."
        font(font_name, use_size)
        c.drawCentredString(x(px), y(py), text)

    def rect(px, py, pw, ph, fill=0):
        c.rect(x(px), y(py + ph), x(pw), x(ph), fill=fill, stroke=1)

    def line(px1, py1, px2, py2):
        c.line(x(px1), y(py1), x(px2), y(py2))

    def money_pdf(value):
        try:
            num = float(value)
            return f"{num:.2f}"
        except Exception:
            return "0.00"

    def numero_a_letras(num):
        unidades = ["", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE"]
        especiales = {
            10: "DIEZ", 11: "ONCE", 12: "DOCE", 13: "TRECE", 14: "CATORCE", 15: "QUINCE",
            20: "VEINTE", 30: "TREINTA", 40: "CUARENTA", 50: "CINCUENTA", 60: "SESENTA",
            70: "SETENTA", 80: "OCHENTA", 90: "NOVENTA"
        }
        centenas = {
            100: "CIEN", 200: "DOSCIENTOS", 300: "TRESCIENTOS", 400: "CUATROCIENTOS",
            500: "QUINIENTOS", 600: "SEISCIENTOS", 700: "SETECIENTOS", 800: "OCHOCIENTOS",
            900: "NOVECIENTOS"
        }

        def hasta_99(n):
            if n < 10:
                return unidades[n]
            if n in especiales:
                return especiales[n]
            if n < 20:
                return "DIECI" + unidades[n - 10]
            if n < 30:
                return "VEINTI" + unidades[n - 20]
            dec = (n // 10) * 10
            uni = n % 10
            return especiales[dec] if uni == 0 else especiales[dec] + " Y " + unidades[uni]

        def hasta_999(n):
            if n < 100:
                return hasta_99(n)
            if n in centenas:
                return centenas[n]
            cen = (n // 100) * 100
            return ("CIENTO" if cen == 100 else centenas[cen]) + " " + hasta_99(n % 100)

        entero = int(float(num or 0))
        centimos = int(round((float(num or 0) - entero) * 100))
        if entero == 0:
            letras = "CERO"
        elif entero < 1000:
            letras = hasta_999(entero)
        elif entero < 1000000:
            miles = entero // 1000
            resto = entero % 1000
            letras = ("MIL" if miles == 1 else hasta_999(miles) + " MIL")
            if resto:
                letras += " " + hasta_999(resto)
        else:
            letras = str(entero)
        return f"SON {letras} Y {centimos:02d}/100 SOLES"

    extra = extra or {}
    doc_type = str(doc_type or "").upper()
    doc_cfg = cfg.get("doc_editor", {}) if isinstance(cfg.get("doc_editor", {}), dict) else {}
    keyfacil_exact = bool(doc_cfg.get("keyfacil_exact")) or str(doc_cfg.get("template_name", "")).lower().startswith("army referencia")
    labels = dict(DOCUMENT_LABEL_DEFAULTS)
    if isinstance(doc_cfg.get("labels"), dict):
        labels.update({k: v for k, v in doc_cfg.get("labels", {}).items() if v not in (None, "")})
    texts = dict(DOCUMENT_TEXT_DEFAULTS)
    if isinstance(doc_cfg.get("texts"), dict):
        texts.update({k: v for k, v in doc_cfg.get("texts", {}).items() if v not in (None, "")})

    def lbl(key, default=""):
        return str(labels.get(key, default) or default)

    def custom_text(key, default=""):
        return str(texts.get(key, "") or default)

    def cfg_num(key, default):
        try:
            return float(doc_cfg.get(key, default))
        except Exception:
            return default

    def cfg_int(key, default):
        try:
            return int(float(doc_cfg.get(key, default)))
        except Exception:
            return default

    layout = cfg.get("layout", {}) if isinstance(cfg.get("layout", {}), dict) else {}

    def box(name, defaults):
        value = layout.get(name, {}) if isinstance(layout.get(name, {}), dict) else {}
        merged = dict(defaults)
        merged.update({k: value.get(k, merged[k]) for k in merged})
        return merged

    doc_title = {
        "BOLETA": "BOLETA DE VENTA\nELECTRONICA",
        "FACTURA": "FACTURA\nELECTRONICA",
        "NOTA DE VENTA": "NOTA DE VENTA",
        "PASE": "PASE",
        "PROFORMA": "PROFORMA",
    }.get(doc_type, doc_type)

    total = float(total or 0)
    if total <= 0:
        total = sum(float(i.get("total", 0) or 0) for i in items)
    gravado = round(total / 1.18, 2) if total else 0
    igv_calc = round(total - gravado, 2)
    if float(igv or 0) > 0:
        igv_calc = float(igv)
        gravado = round(total - igv_calc, 2)

    left = 4
    right = 206
    top = 7

    header_left = box("header_left", {"x": 12, "y": 12, "w": 92, "h": 28})
    header_right = box("header_right", {"x": 130, "y": 4, "w": 74, "h": 39})
    client_box = box("client_box", {"x": 4, "y": 51, "w": 200, "h": 18})

    # Logo y empresa
    logo = document_logo_path(cfg)
    if doc_cfg.get("show_logo", True) and logo and os.path.exists(logo):
        try:
            logo_x = cfg_num("logo_x", float(header_left.get("x", 7)))
            logo_y = cfg_num("logo_y", float(header_left.get("y", 12)) + 5)
            logo_w = cfg_num("logo_w", min(36, float(header_left.get("w", 92)) * 0.38))
            logo_h = cfg_num("logo_h", min(22, float(header_left.get("h", 28)) * 0.7))
            c.drawImage(logo, x(logo_x), y(logo_y + logo_h), width=x(logo_w), height=x(logo_h), preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    for img_cfg in doc_cfg.get("extra_images", []) if isinstance(doc_cfg.get("extra_images", []), list) else []:
        try:
            if not img_cfg.get("visible", True):
                continue
            src = str(img_cfg.get("src", "") or "").strip()
            if not src:
                continue
            px = float(img_cfg.get("x", 10))
            py = float(img_cfg.get("y", 10))
            pw = float(img_cfg.get("w", 25))
            ph = float(img_cfg.get("h", 25))
            if src.startswith("data:image"):
                raw = src.split(",", 1)[1] if "," in src else ""
                img_bytes = io.BytesIO(base64.b64decode(raw))
                c.drawImage(ImageReader(img_bytes), x(px), y(py + ph), width=x(pw), height=x(ph), preserveAspectRatio=True, mask="auto")
            elif os.path.exists(src) or src.startswith(("http://", "https://")):
                c.drawImage(src, x(px), y(py + ph), width=x(pw), height=x(ph), preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    empresa = (custom_text("empresa", cfg.get("empresa") or "CORPORACION COMPUTER ARMY EIRL")).upper()
    ruc = cfg.get("ruc") or "20611068701"
    direccion = custom_text("direccion", cfg.get("direccion") or "AV. INCA GARCILASO DE LA VEGA NRO. 1348 INT2B 130-131 - CERCADO DE LIMA - LIMA - PERU")
    telefono = cfg.get("telefono") or ""
    correo = cfg.get("correo") or ""
    contacto = custom_text("contacto", f"{telefono} {correo}".strip())
    slogan = custom_text("slogan", cfg.get("mensaje") or "MEJORES PRECIOS EN TARJETAS DE VIDEOS")
    company_x = cfg_num("company_x", float(header_left.get("x", 12)) + 30)
    company_y = cfg_num("company_y", float(header_left.get("y", 12)) + 1)
    company_w = cfg_num("company_w", max(50, float(header_left.get("w", 92)) - (company_x - float(header_left.get("x", 12))) - 2))

    for i, line_text in enumerate(wrap_text_mm_canvas(c, empresa, company_w, "Helvetica-Bold", cfg_num("header_font", 12))[:2]):
        txt_fit(company_x, company_y + (i * 5), line_text, cfg_num("header_font", 12), True, max_mm=company_w, min_size=6)
    for i, line_text in enumerate(wrap_text_mm_canvas(c, direccion.upper(), company_w + 16, "Helvetica", 7)[:4]):
        txt_fit(company_x, company_y + 13 + (i * 4), line_text, 7, max_mm=company_w + 16, min_size=5)
    if contacto:
        txt_fit(company_x, company_y + 26, contacto, 7, max_mm=company_w + 16, min_size=5)
    txt_fit(company_x, company_y + 33, slogan.upper(), 7, max_mm=company_w + 16, min_size=5)

    # Cuadro comprobante
    doc_x = max(120, min(150, float(header_right.get("x", 130))))
    doc_y = max(3, min(18, float(header_right.get("y", 4))))
    doc_w = max(52, min(82, float(header_right.get("w", 74))))
    doc_h = max(28, min(45, float(header_right.get("h", 39))))
    rect(doc_x, doc_y, doc_w, doc_h)
    txt_center(doc_x + doc_w / 2, doc_y + 9, f"RUC {ruc}", 10)
    title_lines = doc_title.split("\n")
    for i, line_text in enumerate(title_lines):
        txt_center_fit(doc_x + doc_w / 2, doc_y + 20 + (i * 6), line_text, cfg_num("title_font", 13), True, max_mm=doc_w - 8, min_size=7)
    txt_center_fit(doc_x + doc_w / 2, doc_y + doc_h - 4, doc_number, 11, max_mm=doc_w - 8, min_size=6)

    # Datos cliente y emision
    is_proforma = doc_type == "PROFORMA"
    client_x = max(3, min(20, float(client_box.get("x", 4))))
    client_y = max(46, min(65, float(client_box.get("y", 51))))
    value_x = client_x + 28
    right_label_x = min(client_x + 132, 142)
    right_value_x = min(client_x + 170, 178)
    if not (is_proforma and not str(client_doc or "").strip()):
        txt_fit(client_x, client_y + 4, lbl("documento", "DOCUMENTO"), 7, True, max_mm=25, min_size=5)
        txt_fit(value_x, client_y + 4, client_doc, 7, max_mm=92, min_size=5)
    txt_fit(client_x, client_y + 10, lbl("cliente", "CLIENTE"), 7, True, max_mm=25, min_size=5)
    for i, line_text in enumerate(wrap_text_mm_canvas(c, str(client_name or "USUARIO X").upper(), 92, "Helvetica", 7)[:2]):
        txt_fit(value_x, client_y + 10 + (i * 4), line_text, 7, max_mm=92, min_size=5)
    if not (is_proforma and not str(client_addr or "").strip()):
        txt_fit(client_x, client_y + 16, lbl("direccion", "DIRECCION"), 7, True, max_mm=25, min_size=5)
        for i, line_text in enumerate(wrap_text_mm_canvas(c, (client_addr or "SIN DIRECCION").upper(), 100, "Helvetica", 7)[:2]):
            txt_fit(value_x, client_y + 16 + (i * 3.6), line_text, 7, max_mm=96, min_size=5)

    fecha = pdf_date_from_value(extra.get("fecha_emision"))
    fecha_vencimiento = pdf_date_from_value(extra.get("fecha_vencimiento")) if extra.get("fecha_vencimiento") else "-"
    txt_fit(right_label_x, client_y + 4, lbl("fecha_emision", "FECHA EMISION"), 7, True, max_mm=36, min_size=5)
    txt_fit(right_value_x, client_y + 4, fecha, 7, max_mm=25, min_size=5)
    txt_fit(right_label_x, client_y + 10, lbl("fecha_vencimiento", "FECHA VENCIMIENTO"), 7, True, max_mm=36, min_size=5)
    txt_fit(right_value_x, client_y + 10, fecha_vencimiento, 7, max_mm=25, min_size=5)
    txt_fit(right_label_x, client_y + 16, lbl("moneda", "MONEDA"), 7, True, max_mm=36, min_size=5)
    txt_fit(right_value_x, client_y + 16, "SOLES", 7, max_mm=25, min_size=5)

    # Tabla de items
    table_box = box("table", {"x": 4, "y": 77, "w": 200, "h": 82})
    totals_box = box("totals_box", {"x": 125, "y": 164, "w": 79, "h": 19})
    table_x = max(3, min(20, float(table_box["x"])))
    table_y = max(68, min(95, float(table_box["y"])))
    table_w = max(160, min(202, float(table_box["w"])))
    table_h = max(58, min(132, float(table_box["h"])))
    desc_x = table_x + 29
    desc_chars = max(35, min(85, cfg_int("pdf_desc_chars", 62)))
    desc_font = max(5, min(11, cfg_num("pdf_desc_font", 7.5)))
    serie_font = max(5, min(9, cfg_num("pdf_series_font", 6)))
    row_h_cfg = max(6, min(18, cfg_num("pdf_row_height", 10)))
    usable_table_h = max(16, table_h - 7)
    max_first_rows = max(1, min(24, cfg_int("pdf_max_rows_first_page", 12)))
    desc_line_limit = max(3, min(7, cfg_int("pdf_desc_lines", 3)))
    series_line_limit = max(0, min(3, cfg_int("pdf_series_lines", 1)))
    line_gap = max(2.2, min(4.0, cfg_num("pdf_line_gap", 2.8)))
    item_count = len(items or [])
    single_page_target = 0 < item_count <= max_first_rows
    if single_page_target:
        if keyfacil_exact:
            table_h = max(table_h, 92 if item_count >= 10 else 98)
        else:
            table_h = max(table_h, 128 if is_proforma else 122)
    bottom_limit = table_y + table_h - 2
    row_slot_h = min(row_h_cfg, max(4.6, (bottom_limit - (table_y + 9)) / max(max_first_rows, 1)))
    table_font = cfg_num("table_font", 7)
    desc_bold = bool(doc_cfg.get("pdf_desc_bold", True))
    if single_page_target:
        if keyfacil_exact:
            desc_font = min(desc_font, 6.0 if item_count >= 10 else 6.4)
            serie_font = min(serie_font, 5.0)
            line_gap = min(line_gap, 2.15 if item_count >= 10 else 2.35)
            desc_line_limit = min(desc_line_limit, 1 if item_count >= 11 else 2)
            series_line_limit = 0 if item_count >= 9 else min(series_line_limit, 1)
            row_slot_h = min(row_slot_h, 6.4 if item_count >= 10 else 7.1)
        else:
            desc_font = min(desc_font, 6.6 if item_count >= 9 else 7.0)
            serie_font = min(serie_font, 5.4)
            line_gap = min(line_gap, 2.35 if item_count >= 9 else 2.55)
            desc_line_limit = min(desc_line_limit, 2 if item_count >= 10 else 3)
            series_line_limit = 0 if item_count >= 10 else min(series_line_limit, 1)
            row_slot_h = min(row_slot_h, 7.0 if item_count >= 10 else 8.0)
    elif is_proforma:
        # Proformas son documentos comerciales: priorizamos que la descripcion se lea completa.
        desc_line_limit = max(desc_line_limit, 6)
        series_line_limit = max(series_line_limit, 2)
        row_slot_h = max(row_h_cfg, row_slot_h, 9.0)
    rect(table_x, table_y, table_w, table_h)
    c.setFillGray(0)
    c.rect(x(table_x), y(table_y + 6), x(table_w), x(6), fill=1, stroke=0)
    c.setFillGray(1)
    txt_center(table_x + 4, table_y + 4, lbl("col_num", "Nro"), 7, True)
    txt_center(table_x + 16, table_y + 4, lbl("col_unidad", "UNIDAD"), table_font, True)
    txt_fit(desc_x, table_y + 4, lbl("col_descripcion", "DESCRIPCION"), table_font, True, max_mm=104, min_size=5)
    qty_x = table_x + table_w - 64
    total_x = table_x + table_w - 42
    unit_div_x = table_x + table_w - 21
    unit_x = table_x + table_w - 9
    desc_available_mm = max(24, qty_x - desc_x - 4)
    desc_safe_mm = max(20, desc_available_mm - 2)
    desc_chars = min(desc_chars, max(24, int(desc_available_mm * 1.55)))
    txt_center(qty_x + 4, table_y + 4, lbl("col_cantidad", "CANT."), table_font, True)
    txt_center(total_x + 10, table_y + 4, lbl("col_total", "TOTAL"), table_font, True)
    txt_center(unit_x - 1, table_y + 4, lbl("col_unitario", "P.UNIT."), table_font, True)
    c.setFillGray(0)

    for px in [table_x + 8, table_x + 27, qty_x, total_x, unit_div_x]:
        line(px, table_y, px, table_y + table_h)

    def build_pdf_print_rows(source_items, width_mm, line_cap):
        rows = []
        desc_font_name = "Helvetica-Bold" if desc_bold else "Helvetica"
        for item_index, item in enumerate(source_items, start=1):
            desc = str(item.get("nombre") or item.get("descripcion") or "").strip().upper()
            desc_lines_all = wrap_text_mm_canvas(c, desc, width_mm, desc_font_name, desc_font)
            if not desc_lines_all:
                desc_lines_all = [""]
            if is_proforma and not single_page_target:
                chunks = [desc_lines_all[i:i + line_cap] for i in range(0, len(desc_lines_all), line_cap)]
            else:
                chunks = [desc_lines_all[:line_cap]]
            serie = item.get("serie") or item.get("series_texto") or ""
            serie_lines = []
            if serie and doc_cfg.get("show_serie", True):
                serie_lines = wrap_text_mm_canvas(c, format_series_for_print(serie), width_mm, "Helvetica", serie_font)[:series_line_limit]
            for chunk_index, chunk in enumerate(chunks):
                rows.append({
                    "item": item,
                    "idx": item_index,
                    "first": chunk_index == 0,
                    "continued": chunk_index > 0,
                    "desc_lines": chunk,
                    "serie_lines": serie_lines if chunk_index == len(chunks) - 1 else [],
                })
        return rows

    print_rows = build_pdf_print_rows(items, desc_safe_mm, desc_line_limit)

    def pdf_row_height_for(row):
        n_lines = len(row.get("desc_lines") or []) + len(row.get("serie_lines") or [])
        return max(row_slot_h, 3.2 + max(1, n_lines) * line_gap)

    def draw_pdf_item_row(row, row_y_value, compact=False):
        item = row["item"]
        cantidad = float(item.get("cantidad", 0) or 0)
        precio = float(item.get("precio", 0) or 0)
        item_total = float(item.get("total", 0) or (cantidad * precio))
        desc_lines = row.get("desc_lines") or [""]
        serie_lines = row.get("serie_lines") or []
        if row.get("first"):
            txt_center(table_x + 4, row_y_value, row["idx"], 7)
            txt_center(table_x + 17, row_y_value, "UNIDADES", 6)
            txt_right_fit(total_x - 2, row_y_value, f"{cantidad:.2f}", 7, max_mm=13, min_size=4)
            txt_right_fit(unit_div_x - 2, row_y_value, money_pdf(item_total), 7, max_mm=18, min_size=3.5)
            txt_right_fit(table_x + table_w - 1, row_y_value, money_pdf(precio), 7, max_mm=18, min_size=3.5)
        else:
            txt_center(table_x + 4, row_y_value, "...", 7)
        for j, line_text in enumerate(desc_lines):
            txt_fit(desc_x, row_y_value + (j * line_gap), line_text, desc_font, desc_bold, max_mm=desc_safe_mm, min_size=4.5)
        for j, line_text in enumerate(serie_lines):
            txt_fit(desc_x, row_y_value + (len(desc_lines) * line_gap) + (j * line_gap), line_text, serie_font, max_mm=desc_safe_mm, min_size=4.2)

    row_y = table_y + 11
    row_cursor = 0
    first_items_printed = 0
    while row_cursor < len(print_rows):
        row = print_rows[row_cursor]
        if row.get("first") and first_items_printed >= max_first_rows:
            break
        this_row_h = pdf_row_height_for(row)
        if row_y + this_row_h > bottom_limit + 0.01:
            break
        draw_pdf_item_row(row, row_y)
        row_y += this_row_h
        if row.get("first"):
            first_items_printed += 1
        row_cursor += 1
    extra_rows = print_rows[row_cursor:]
    if extra_rows and row_cursor == 0:
        txt(desc_x, table_y + 11, "ITEMS NO CABEN: revisa tabla en Ajustes / editor PDF.", 6, True)
    elif extra_rows:
        remaining_items = len({r.get("idx") for r in extra_rows})
        txt_fit(table_x + 2, table_y + table_h + 3, f"Continua pag. 2: {remaining_items} item(s)", 5, True, max_mm=55, min_size=4)

    amount_words_y = table_y + table_h + 5
    line(table_x, table_y + table_h, table_x + table_w, table_y + table_h)
    line(table_x, table_y + table_h + 8, table_x + table_w, table_y + table_h + 8)
    txt_center_fit(table_x + (table_w / 2), amount_words_y, numero_a_letras(total), 7, max_mm=table_w - 4, min_size=4)

    # Totales
    totals_x = max(table_x + table_w - 70, min(132, float(totals_box.get("x", 132))))
    total_y = max(table_y + table_h + 14, min(210, float(totals_box.get("y", table_y + table_h + 14))))
    totals_w = min(72, table_x + table_w - totals_x)
    totals_h = 22
    rect(totals_x, total_y - 5, totals_w, totals_h)
    line(totals_x, total_y + 2, totals_x + totals_w, total_y + 2)
    line(totals_x, total_y + 8, totals_x + totals_w, total_y + 8)
    txt_fit(totals_x + 3, total_y, lbl("gravado", "GRAVADO"), 8, True, max_mm=31, min_size=5)
    txt(totals_x + 36, total_y, "S/", 8)
    txt_right_fit(totals_x + totals_w - 3, total_y, money_pdf(gravado), 8, max_mm=30, min_size=4)
    txt_fit(totals_x + 3, total_y + 6, lbl("igv", "I.G.V. 18%"), 8, True, max_mm=31, min_size=5)
    txt(totals_x + 36, total_y + 6, "S/", 8)
    txt_right_fit(totals_x + totals_w - 3, total_y + 6, money_pdf(igv_calc), 8, max_mm=30, min_size=4)
    txt_fit(totals_x + 3, total_y + 12, lbl("total", "TOTAL"), 8, True, max_mm=31, min_size=5)
    txt(totals_x + 36, total_y + 12, "S/", 8)
    txt_right_fit(totals_x + totals_w - 3, total_y + 12, money_pdf(total), 9, True, max_mm=30, min_size=4)
    totals_bottom = total_y - 5 + totals_h

    # Usuario y cuentas
    usuario = vendedor or cfg.get("usuario_actual", "COMPUTER ARMY")
    info_y = 178.9 if keyfacil_exact else max(table_y + table_h + 16, totals_bottom + 8)
    info_label_x = 5.6 if keyfacil_exact else 4
    info_value_x = 58.6 if keyfacil_exact else 57
    condition_y = info_y + (4.6 if keyfacil_exact else 6)
    bank_label_y = info_y + (9.1 if keyfacil_exact else 12)
    txt_fit(info_label_x, info_y, lbl("usuario", "USUARIO"), 7, True, max_mm=50, min_size=5)
    txt(info_value_x, info_y, f"{usuario} - {fecha}", 7)
    txt_fit(info_label_x, condition_y, lbl("condicion_pago", "CONDICION DE PAGO"), 7, True, max_mm=50, min_size=5)
    txt_fit(info_value_x, condition_y, custom_text("condicion_pago_valor", "CONTADO"), 7, max_mm=45, min_size=5)
    txt_fit(info_label_x, bank_label_y, lbl("cuentas_bancarias", "CUENTAS BANCARIAS"), 7, True, max_mm=50, min_size=5)
    bank_y = info_y + (9.8 if keyfacil_exact else 12)
    bank_lines = []
    if cfg.get("cuenta_bcp", "").strip():
        bank_lines.append(f"Bcp soles : {cfg.get('cuenta_bcp')}")
    if cfg.get("cuenta_interbank", "").strip():
        bank_lines.append(f"Interbank soles cuenta corriente : {cfg.get('cuenta_interbank')}")
    if keyfacil_exact and not bank_lines:
        bank_lines = [
            "Bcp soles :1941066028058",
            "Titular:Computer Army Eirl",
            "Interbank soles cuenta corriente : 2003005323345",
            "Titular: Computer Army eirl",
        ]
    for idx, bank_line in enumerate(bank_lines):
        if keyfacil_exact and idx == 2:
            bank_y += 4.2
        txt_fit(info_value_x, bank_y, bank_line, 7, max_mm=118, min_size=4.5)
        bank_y += 4.2 if keyfacil_exact else 6

    # QR
    try:
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderPDF
        qr_data = f"{ruc}|{doc_type}|{doc_number}|{fecha}|{money_pdf(total)}"
        qr = QrCodeWidget(qr_data)
        bounds = qr.getBounds()
        qr_w = bounds[2] - bounds[0]
        qr_h = bounds[3] - bounds[1]
        qr_size = 24.7 if keyfacil_exact else 22
        qr_x = 179.6 if keyfacil_exact else 181
        qr_y = 211.0 if keyfacil_exact else max(info_y + (20 if single_page_target else 28), 232)
        d = Drawing(x(qr_size), x(qr_size), transform=[x(qr_size) / qr_w, 0, 0, x(qr_size) / qr_h, 0, 0])
        d.add(qr)
        renderPDF.draw(d, c, x(qr_x), y(qr_y + qr_size))
    except Exception:
        rect(179.6 if keyfacil_exact else 181, 211.0 if keyfacil_exact else max(info_y + (20 if single_page_target else 5), 209), 24.7 if keyfacil_exact else 22, 24.7 if keyfacil_exact else 22)

    legal_y = 217.3 if keyfacil_exact else max(info_y + (18 if single_page_target else 28), 229)
    legal_x = 5.6 if keyfacil_exact else 4
    txt_fit(legal_x, legal_y, custom_text("legal_line1", "Autorizado mediante resolucion Nro 034-005-0010431/SUNAT"), 6, max_mm=160, min_size=4.5)
    legal_line2 = custom_text("legal_line2", f"Representacion impresa de la {doc_title.replace(chr(10), ' ')}")
    if doc_type != "BOLETA" and "BOLETA" in legal_line2.upper():
        legal_line2 = f"Representacion impresa de la {doc_title.replace(chr(10), ' ')}"
    txt_fit(legal_x, legal_y + 6, legal_line2, 6, max_mm=160, min_size=4.5)
    legal_line3 = custom_text("legal_line3", "")
    if legal_line3:
        txt_fit(legal_x, legal_y + 12, legal_line3, 6, max_mm=160, min_size=4.5)
    txt_fit(legal_x, legal_y + 18, custom_text("resumen", "Resumen"), 6, max_mm=60, min_size=4.5)

    # Garantia / pie
    warranty = [custom_text(f"garantia_{i}", DOCUMENT_TEXT_DEFAULTS.get(f"garantia_{i}", "")) for i in range(1, 7)]
    wy = 245.2 if keyfacil_exact else max(legal_y + (24 if single_page_target else 30), 257)
    if wy > 269:
        wy = 269
    for para in warranty:
        for sub in wrap_text_mm_canvas(c, para, 175, "Helvetica", 6.5)[:3]:
            txt_center(105, wy, sub, 6.5)
            wy += 3.6
            if wy > 288:
                break
        if wy > 288:
            break

    if keyfacil_exact and doc_cfg.get("show_reference_footer", False):
        c.setFillColorRGB(0.92, 0.92, 0.92)
        c.rect(x(0), y(297), x(210), x(21.1), fill=1, stroke=0)
        c.setFillGray(0)
        txt(92.8, 282.6, "G&G ERP", 12, True)
        txt(66.3, 286.8, "Comprobante emitido a traves de", 8)
        txt(124.0, 286.8, "G&G ERP", 8, True)

    if extra_rows:
        extra_page_rows = 14 if is_proforma else 22
        item_cursor = 0
        page_index = 0
        extra_desc_w = 128
        while item_cursor < len(extra_rows):
            c.showPage()
            page_no = 2 + page_index
            font("Helvetica-Bold", 12)
            c.drawString(x(10), y(14), f"{empresa[:46]} - DETALLE DE PRODUCTOS")
            font("Helvetica", 9)
            c.drawString(x(10), y(21), f"{doc_type} {doc_number} | Cliente: {str(client_name or 'USUARIO X')[:70]}")
            c.drawRightString(x(200), y(21), f"Pagina {page_no}")

            extra_x, extra_y, extra_w, extra_h = 8, 31, 194, 214
            rect(extra_x, extra_y, extra_w, extra_h)
            c.setFillGray(0)
            c.rect(x(extra_x), y(extra_y + 7), x(extra_w), x(7), fill=1, stroke=0)
            c.setFillGray(1)
            txt_center(extra_x + 5, extra_y + 5, "Nro", 7, True)
            txt_center(extra_x + 20, extra_y + 5, "UNIDAD", 7, True)
            txt(extra_x + 37, extra_y + 5, "DESCRIPCION", 7, True)
            txt_center(extra_x + extra_w - 45, extra_y + 5, "CANT.", 7, True)
            txt_center(extra_x + extra_w - 25, extra_y + 5, "TOTAL", 7, True)
            txt_center(extra_x + extra_w - 7, extra_y + 5, "P.UNIT.", 7, True)
            c.setFillGray(0)
            for px in [extra_x + 10, extra_x + 30, extra_x + extra_w - 52, extra_x + extra_w - 32, extra_x + extra_w - 15]:
                line(px, extra_y, px, extra_y + extra_h)

            detail_y = extra_y + 13
            printed_on_page = 0
            while item_cursor < len(extra_rows) and printed_on_page < extra_page_rows:
                row = extra_rows[item_cursor]
                item = row["item"]
                cantidad = float(item.get("cantidad", 0) or 0)
                precio = float(item.get("precio", 0) or 0)
                item_total = float(item.get("total", 0) or (cantidad * precio))
                desc_ex = row.get("desc_lines") or [""]
                serie_ex = row.get("serie_lines") or []
                row_h_extra = max(9.0, 4.8 + len(desc_ex) * 3.5 + len(serie_ex) * 3.2)
                if printed_on_page and detail_y + row_h_extra > extra_y + extra_h - 4:
                    break
                if row.get("first"):
                    txt_center(extra_x + 5, detail_y, row.get("idx", ""), 7)
                    txt_center(extra_x + 20, detail_y, "UNIDADES", 6)
                else:
                    txt_center(extra_x + 5, detail_y, "...", 7)
                for j, line_text in enumerate(desc_ex):
                    txt_fit(extra_x + 37, detail_y + (j * 3.5), line_text, desc_font, desc_bold, max_mm=extra_desc_w, min_size=4.5)
                for j, line_text in enumerate(serie_ex):
                    txt_fit(extra_x + 37, detail_y + (len(desc_ex) * 3.5) + (j * 3.2), line_text, serie_font, max_mm=extra_desc_w, min_size=4.2)
                if row.get("first"):
                    txt_right_fit(extra_x + extra_w - 54, detail_y, f"{cantidad:.2f}", 7, max_mm=10)
                    txt_right_fit(extra_x + extra_w - 17, detail_y, money_pdf(item_total), 7, max_mm=15)
                    txt_right_fit(extra_x + extra_w - 1, detail_y, money_pdf(precio), 7, max_mm=13)
                detail_y += row_h_extra
                item_cursor += 1
                printed_on_page += 1

            if printed_on_page == 0:
                item_cursor += 1

            if item_cursor >= len(extra_rows):
                line(8, 252, 202, 252)
                txt_center(93, 257, numero_a_letras(total), 7)
                txt(137, 265, "GRAVADO", 8, True)
                txt(171, 265, "S/", 8)
                txt_right_fit(197, 265, money_pdf(gravado), 8, max_mm=25)
                txt(137, 271, "I.G.V. 18%", 8, True)
                txt(171, 271, "S/", 8)
                txt_right_fit(197, 271, money_pdf(igv_calc), 8, max_mm=25)
                txt(137, 277, "TOTAL", 8, True)
                txt(171, 277, "S/", 8)
                txt_right_fit(197, 277, money_pdf(total), 9, True, max_mm=25)
            page_index += 1

    c.save()


def open_pdf_file(path):
    try:
        os.startfile(path)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "msg": str(e), "no_association": getattr(e, "winerror", None) == 1155}


def copy_pdf_to_downloads(path, suggested_name="documento.pdf"):
    if not path or not os.path.exists(path):
        return {"ok": False, "msg": "PDF no encontrado."}
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(downloads, exist_ok=True)
    safe_name = _safe_file_name(suggested_name or os.path.basename(path) or "documento.pdf")
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    base, ext = os.path.splitext(safe_name)
    dest = os.path.join(downloads, safe_name)
    idx = 1
    while os.path.exists(dest):
        dest = os.path.join(downloads, f"{base}_{idx}{ext}")
        idx += 1
    shutil.copy2(path, dest)
    return {"ok": True, "path": dest}


def print_pdf_file(path):
    try:
        os.startfile(path, "print")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "msg": str(e), "no_association": getattr(e, "winerror", None) == 1155}


def open_pdf_internal_window(parent, title, path, suggested_name="documento.pdf"):
    image_store = []
    root = parent.winfo_toplevel() if parent is not None else None
    win = tk.Toplevel(root)
    win.title(title or "Visor PDF")
    screen_w = max(1024, win.winfo_screenwidth())
    screen_h = max(700, win.winfo_screenheight())
    win_w = min(1120, max(940, screen_w - 90))
    win_h = min(760, max(640, screen_h - 110))
    win.geometry(f"{win_w}x{win_h}+30+30")
    win.minsize(900, 580)
    win.configure(bg=APP_BG)

    def download_pdf():
        result = copy_pdf_to_downloads(path, suggested_name or os.path.basename(path) or "documento.pdf")
        if api_response_ok(result):
            messagebox.showinfo("Descargar PDF", f"PDF guardado en Descargas:\n{result.get('path')}")
        else:
            messagebox.showerror("Descargar PDF", api_response_error(result, "No se pudo guardar el PDF."))

    def print_pdf():
        result = print_pdf_file(path)
        if api_response_ok(result):
            play_document_sound("print")
        elif result.get("no_association"):
            messagebox.showwarning("PDF", "Windows no tiene un lector PDF asociado para imprimir directo. El PDF sigue abierto en el visor interno del ERP.")
        else:
            messagebox.showerror("PDF", api_response_error(result, "No se pudo enviar a imprimir."))

    top = tk.Frame(win, bg=TOPBAR_BG, highlightthickness=1, highlightbackground=BORDER)
    top.pack(fill="x")
    tk.Label(top, text=title or "Visor PDF", bg=TOPBAR_BG, fg=TEXT, font=("Arial", 17, "bold")).pack(side="left", padx=16, pady=12)
    actions = tk.Frame(top, bg=TOPBAR_BG)
    actions.pack(side="right", padx=12, pady=8)
    tk.Button(actions, text="Imprimir", command=print_pdf, bg="#16a34a", fg="white", relief="flat", padx=12, pady=7).pack(side="left", padx=4)
    tk.Button(actions, text="Descargar", command=download_pdf, bg="#2563eb", fg="white", relief="flat", padx=12, pady=7).pack(side="left", padx=4)
    tk.Button(actions, text="Cerrar", command=win.destroy, bg="#64748b", fg="white", relief="flat", padx=12, pady=7).pack(side="left", padx=4)

    body = tk.Frame(win, bg=CARD_BG)
    body.pack(fill="both", expand=True, padx=14, pady=14)
    tk.Label(
        body,
        text="Vista interna del PDF real generado por el ERP.",
        bg="#eff6ff",
        fg="#1d4ed8",
        font=("Arial", 10, "bold"),
        padx=12,
        pady=8,
    ).pack(fill="x", padx=14, pady=(14, 0))
    render_pdf_inside(body, path, image_store)
    win._pdf_images = image_store
    play_document_sound("open")
    return win


def render_pdf_inside(parent, path, image_store=None, max_page_width=980):
    if image_store is None:
        image_store = []
    holder = tk.Frame(parent, bg="#e5e7eb", highlightthickness=1, highlightbackground=BORDER)
    holder.pack(fill="both", expand=True, padx=14, pady=14)

    canvas_widget = tk.Canvas(holder, bg="#e5e7eb", highlightthickness=0)
    scrollbar = ttk.Scrollbar(holder, orient="vertical", command=canvas_widget.yview)
    canvas_widget.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas_widget.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(canvas_widget, bg="#e5e7eb")
    window_id = canvas_widget.create_window((0, 0), window=inner, anchor="n")

    def refresh_scrollregion(_event=None):
        canvas_widget.configure(scrollregion=canvas_widget.bbox("all"))
        canvas_width = max(canvas_widget.winfo_width(), 1)
        canvas_widget.itemconfigure(window_id, width=canvas_width)

    inner.bind("<Configure>", refresh_scrollregion)
    canvas_widget.bind("<Configure>", refresh_scrollregion)

    def on_mousewheel(event):
        canvas_widget.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas_widget.bind("<MouseWheel>", on_mousewheel)
    inner.bind("<MouseWheel>", on_mousewheel)

    if not path or not os.path.exists(path):
        tk.Label(inner, text="No se encontro el PDF para visualizar.", bg="#e5e7eb", fg=DANGER, font=("Arial", 12, "bold")).pack(padx=20, pady=20)
        return holder
    if fitz is None:
        tk.Label(
            inner,
            text="El visor interno de PDF no esta disponible en esta instalacion.",
            bg="#e5e7eb",
            fg=DANGER,
            font=("Arial", 12, "bold"),
        ).pack(padx=20, pady=20)
        return holder

    try:
        doc = fitz.open(path)
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            page_width = max(float(page.rect.width), 1.0)
            zoom = min(2.2, max(1.0, max_page_width / page_width))
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            photo = ImageTk.PhotoImage(img)
            image_store.append(photo)

            page_frame = tk.Frame(inner, bg="#e5e7eb")
            page_frame.pack(anchor="center", pady=(14, 8))
            tk.Label(page_frame, text=f"Pagina {page_index + 1}", bg="#e5e7eb", fg=MUTED, font=("Arial", 9, "bold")).pack(anchor="w")
            tk.Label(page_frame, image=photo, bg="white", bd=0, highlightthickness=1, highlightbackground="#cbd5e1").pack()
        doc.close()
    except Exception as e:
        tk.Label(inner, text=f"No se pudo renderizar el PDF dentro del ERP.\n{e}", bg="#e5e7eb", fg=DANGER, font=("Arial", 11, "bold")).pack(padx=20, pady=20)
    return holder


class LayoutEditor(tk.Toplevel):
    SCALE = 2.7
    COLORS = {
        "header_left": "#bfdbfe",
        "header_right": "#fecaca",
        "client_box": "#d9f99d",
        "table": "#fde68a",
        "totals_box": "#e9d5ff",
        "footer_box": "#c7d2fe",
        "extra_image": "#bae6fd",
    }
    FRIENDLY = {
        "header_left": "Encabezado empresa / logo",
        "header_right": "Cuadro documento",
        "client_box": "Datos del cliente",
        "table": "Tabla de productos",
        "totals_box": "Totales",
        "footer_box": "Pie de documento",
        "extra_image": "Imagen extra",
    }

    def __init__(self, master, cfg, on_save):
        super().__init__(master)
        self.title("Editor de plantilla de impresión")
        self.geometry("1280x860")
        self.cfg = cfg
        ensure_document_editor_defaults(self.cfg)
        self.on_save = on_save
        self.selected = None
        self.drag_prev = None
        self.resize_mode = None
        self.resize_start = None
        self.canvas_images = []

        self.cfg.setdefault("doc_editor", {})
        self.cfg["doc_editor"].setdefault("show_logo", True)
        self.cfg["doc_editor"].setdefault("show_serie", True)
        self.cfg["doc_editor"].setdefault("show_banks", True)
        self.cfg["doc_editor"].setdefault("title_font", 13)
        self.cfg["doc_editor"].setdefault("header_font", 11)
        self.cfg["doc_editor"].setdefault("body_font", 8)
        self.cfg["doc_editor"].setdefault("table_font", 7)
        self.cfg["doc_editor"].setdefault("pdf_code_width", 19)
        self.cfg["doc_editor"].setdefault("pdf_desc_x", 52)
        self.cfg["doc_editor"].setdefault("pdf_desc_chars", 62)
        self.cfg["doc_editor"].setdefault("pdf_desc_font", 7.5)
        self.cfg["doc_editor"].setdefault("pdf_desc_bold", True)
        self.cfg["doc_editor"].setdefault("pdf_series_font", 6)
        self.cfg["doc_editor"].setdefault("pdf_row_height", 10)
        self.cfg["doc_editor"].setdefault("pdf_code_chars", 10)
        self.cfg["doc_editor"].setdefault("pdf_max_rows_first_page", 12)
        self.cfg["doc_editor"].setdefault("pdf_desc_lines", 3)
        self.cfg["doc_editor"].setdefault("pdf_series_lines", 1)
        self.cfg["doc_editor"].setdefault("pdf_line_gap", 2.8)
        self.cfg["doc_editor"].setdefault("extra_images", [])
        self.cfg["doc_editor"].setdefault("labels", {
            "cliente": "Cliente:",
            "documento": "Documento:",
            "direccion": "Dirección:",
            "subtotal": "SUBTOTAL",
            "igv": "IGV",
            "total": "TOTAL",
            "mensaje": self.cfg.get("mensaje", "GRACIAS POR SU COMPRA")
        })

        wrap = tk.Frame(self, bg="#f1f5f9")
        wrap.pack(fill="both", expand=True)

        left = tk.Frame(wrap, bg="#f1f5f9")
        left.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(left, width=int(210*self.SCALE), height=int(297*self.SCALE), bg="white", highlightbackground="#94a3b8")
        self.canvas.pack(side="left", padx=10, pady=10)

        side = tk.Frame(wrap, bg="#e2e8f0", width=500)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)

        tk.Label(side, text="Plantilla de documentos", bg="#e2e8f0", fg="#0f172a", font=("Arial", 15, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(side, text="Mueve las zonas de la hoja y ajusta columnas. Al guardar se sincroniza solo para esta sucursal.", bg="#e2e8f0", fg="#475569", justify="left", wraplength=420).pack(anchor="w", padx=12, pady=(0, 8))

        self.lbl = tk.Label(side, text="Selecciona un bloque", bg="#e2e8f0", fg="#0f172a", justify="left", font=("Arial", 10, "bold"))
        self.lbl.pack(anchor="w", padx=12, pady=4)

        pos = tk.LabelFrame(side, text="Posición y tamaño en mm", bg="#e2e8f0", padx=8, pady=6)
        pos.pack(fill="x", padx=10, pady=6)
        grid = tk.Frame(pos, bg="#e2e8f0")
        grid.pack(fill="x")
        for i, t in enumerate(["x", "y", "w", "h"]):
            tk.Label(grid, text=t.upper(), bg="#e2e8f0").grid(row=0, column=i, padx=4)
            ent = tk.Entry(grid, width=8)
            ent.grid(row=1, column=i, padx=4)
            setattr(self, f"ent_{t}", ent)

        tk.Button(pos, text="Aplicar posición", command=self.apply_values, bg="#2563eb", fg="white", relief="flat").pack(fill="x", pady=(8, 0))
        quick = tk.Frame(pos, bg="#e2e8f0")
        quick.pack(fill="x", pady=(6, 0))
        tk.Button(quick, text="A- letra", command=lambda: self.adjust_selected_font(-1), bg="#475569", fg="white", relief="flat").pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(quick, text="A+ letra", command=lambda: self.adjust_selected_font(1), bg="#0f766e", fg="white", relief="flat").pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(quick, text="Mas alto", command=lambda: self.adjust_selected_size("h", 5), bg="#0891b2", fg="white", relief="flat").pack(side="left", expand=True, fill="x", padx=2)

        presets = tk.LabelFrame(side, text="Ejemplos de plantilla", bg="#e2e8f0", padx=8, pady=6)
        presets.pack(fill="x", padx=10, pady=6)
        tk.Button(presets, text="Ver galeria de plantillas", command=self.open_template_gallery, bg="#7c3aed", fg="white", relief="flat").pack(fill="x", pady=(0, 5))
        tk.Button(presets, text="ARMY PDF exacta", command=lambda: self.apply_template_preset("army"), bg="#b91c1c", fg="white", relief="flat").pack(fill="x", pady=(0, 5))
        tk.Button(presets, text="SUNAT A4 ordenada", command=lambda: self.apply_template_preset("sunat"), bg="#111827", fg="white", relief="flat").pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(presets, text="PC + garantia", command=lambda: self.apply_template_preset("pc"), bg="#0f766e", fg="white", relief="flat").pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(presets, text="Proforma limpia", command=lambda: self.apply_template_preset("simple"), bg="#2563eb", fg="white", relief="flat").pack(side="left", expand=True, fill="x", padx=2)

        opts = tk.LabelFrame(side, text="Mostrar / ocultar", bg="#e2e8f0", padx=8, pady=6)
        opts.pack(fill="x", padx=10, pady=6)

        doc = self.cfg["doc_editor"]
        self.var_logo = tk.BooleanVar(value=doc.get("show_logo", True))
        self.var_serie = tk.BooleanVar(value=doc.get("show_serie", True))
        self.var_banks = tk.BooleanVar(value=doc.get("show_banks", True))

        tk.Checkbutton(opts, text="Mostrar logo", variable=self.var_logo, bg="#e2e8f0").pack(anchor="w")
        tk.Checkbutton(opts, text="Mostrar columna serie", variable=self.var_serie, bg="#e2e8f0").pack(anchor="w")
        tk.Checkbutton(opts, text="Mostrar cuentas bancarias", variable=self.var_banks, bg="#e2e8f0").pack(anchor="w")

        fonts = tk.LabelFrame(side, text="Tamaños de letra", bg="#e2e8f0", padx=8, pady=6)
        fonts.pack(fill="x", padx=10, pady=6)

        self.ent_title_font = self._entry_row(fonts, "Título documento", doc.get("title_font", 13), 0)
        self.ent_header_font = self._entry_row(fonts, "Empresa", doc.get("header_font", 11), 1)
        self.ent_body_font = self._entry_row(fonts, "Texto general", doc.get("body_font", 8), 2)
        self.ent_table_font = self._entry_row(fonts, "Tabla", doc.get("table_font", 7), 3)

        table_opts = tk.LabelFrame(side, text="Tabla PDF / productos", bg="#e2e8f0", padx=8, pady=6)
        table_opts.pack(fill="x", padx=10, pady=6)
        self.ent_pdf_code_width = self._entry_row(table_opts, "Ancho codigo mm", doc.get("pdf_code_width", 19), 0)
        self.ent_pdf_code_chars = self._entry_row(table_opts, "Letras codigo", doc.get("pdf_code_chars", 10), 1)
        self.ent_pdf_desc_x = self._entry_row(table_opts, "Inicio descripcion mm", doc.get("pdf_desc_x", 52), 2)
        self.ent_pdf_desc_chars = self._entry_row(table_opts, "Letras descripcion", doc.get("pdf_desc_chars", 62), 3)
        self.ent_pdf_desc_font = self._entry_row(table_opts, "Tam. descripcion", doc.get("pdf_desc_font", 7.5), 4)
        self.ent_pdf_series_font = self._entry_row(table_opts, "Tam. serie SN", doc.get("pdf_series_font", 6), 5)
        self.ent_pdf_row_height = self._entry_row(table_opts, "Alto fila mm", doc.get("pdf_row_height", 10), 6)
        self.ent_pdf_max_rows = self._entry_row(table_opts, "Productos 1ra hoja", doc.get("pdf_max_rows_first_page", 12), 7)
        self.ent_pdf_desc_lines = self._entry_row(table_opts, "Lineas descripcion", doc.get("pdf_desc_lines", 3), 8)
        self.ent_pdf_series_lines = self._entry_row(table_opts, "Lineas serie", doc.get("pdf_series_lines", 1), 9)
        self.ent_pdf_line_gap = self._entry_row(table_opts, "Espacio lineas", doc.get("pdf_line_gap", 2.8), 10)
        self.var_desc_bold = tk.BooleanVar(value=doc.get("pdf_desc_bold", True))
        tk.Checkbutton(table_opts, text="Descripcion en negrita", variable=self.var_desc_bold, bg="#e2e8f0").grid(row=11, column=0, columnspan=2, sticky="w", padx=4, pady=3)
        tk.Label(
            table_opts,
            text="Tip: ARMY usa 12 productos en la primera hoja. Si un texto es largo se achica para no invadir columnas.",
            bg="#e2e8f0",
            fg="#475569",
            wraplength=360,
            justify="left"
        ).grid(row=12, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 0))

        labels_box = tk.LabelFrame(side, text="Textos editables del documento", bg="#e2e8f0", padx=8, pady=6)
        labels_box.pack(fill="x", padx=10, pady=6)

        labels = doc.setdefault("labels", {})
        self.ent_lbl_cliente = self._entry_row(labels_box, "Cliente", labels.get("cliente", "Cliente:"), 0, width=25)
        self.ent_lbl_doc = self._entry_row(labels_box, "Documento", labels.get("documento", "Documento:"), 1, width=25)
        self.ent_lbl_dir = self._entry_row(labels_box, "Dirección", labels.get("direccion", "Dirección:"), 2, width=25)
        self.ent_lbl_total = self._entry_row(labels_box, "Total", labels.get("total", "TOTAL"), 3, width=25)
        self.ent_lbl_msg = self._entry_row(labels_box, "Mensaje final", labels.get("mensaje", self.cfg.get("mensaje", "")), 4, width=25)
        tk.Button(labels_box, text="Editar todos los textos letra por letra", command=self.open_precise_text_editor, bg="#334155", fg="white", relief="flat").grid(row=5, column=0, columnspan=2, sticky="ew", padx=4, pady=(6, 2))

        actions = tk.Frame(side, bg="#e2e8f0")
        actions.pack(fill="x", padx=10, pady=8)

        tk.Button(actions, text="+ Agregar imagen extra", command=self.add_extra_image, bg="#0284c7", fg="white", relief="flat").pack(fill="x", pady=3)
        tk.Button(actions, text="Eliminar seleccionado", command=self.delete_selected_element, bg="#be123c", fg="white", relief="flat").pack(fill="x", pady=3)
        tk.Button(actions, text="Vista previa PDF", command=self.preview_pdf, bg="#d97706", fg="white", relief="flat").pack(fill="x", pady=3)
        tk.Button(actions, text="Guardar PDF", command=self.save_editor_pdf, bg="#2563eb", fg="white", relief="flat").pack(fill="x", pady=3)
        tk.Button(actions, text="Guardar plantilla", command=self.save, bg="#059669", fg="white", relief="flat").pack(fill="x", pady=3)
        tk.Button(actions, text="Reset plantilla", command=self.reset, bg="#dc2626", fg="white", relief="flat").pack(fill="x", pady=3)

        help_txt = (
            "Como usar:\n"
            "• Arrastra una zona para moverla.\n"
            "• Arrastra el cuadrito rojo de la esquina para agrandar.\n"
            "• Agrega imagenes extra como sellos, banners o logos.\n"
            "• Vista previa genera PDF real."
        )
        tk.Label(side, text=help_txt, bg="#e2e8f0", fg="#334155", justify="left").pack(anchor="w", padx=12, pady=6)

        self.redraw()

    def _entry_row(self, parent, label, value, row, width=10):
        tk.Label(parent, text=label, bg="#e2e8f0").grid(row=row, column=0, sticky="e", padx=4, pady=3)
        ent = tk.Entry(parent, width=width)
        ent.grid(row=row, column=1, sticky="w", padx=4, pady=3)
        ent.insert(0, str(value))
        return ent

    def redraw(self):
        self.canvas.delete("all")
        self.canvas_images = []
        self.draw_mock_document()
        self.canvas.create_text(8, 8, text="A4 - vista de ejemplo editable", anchor="nw", fill="#94a3b8", font=("Arial", 9, "bold"))
        for name, box in self.cfg["layout"].items():
            self.draw_editor_box(name, box, self.FRIENDLY.get(name, name))
        for idx, img_cfg in enumerate(self.cfg["doc_editor"].get("extra_images", [])):
            self.draw_extra_image(idx, img_cfg)

    def selected_kind_key(self):
        if not self.selected:
            return None, None
        if str(self.selected).startswith("extra_image:"):
            return "image", int(str(self.selected).split(":", 1)[1])
        return "layout", self.selected

    def selected_box(self):
        kind, key = self.selected_kind_key()
        if kind == "image":
            images = self.cfg["doc_editor"].setdefault("extra_images", [])
            if 0 <= key < len(images):
                return images[key]
        if kind == "layout":
            return self.cfg["layout"].get(key)
        return None

    def draw_editor_box(self, name, box, label):
        x = box["x"] * self.SCALE
        y = box["y"] * self.SCALE
        w = box["w"] * self.SCALE
        h = box["h"] * self.SCALE
        tag = name
        outline = "#dc2626" if self.selected == name else "#334155"
        self.canvas.create_rectangle(x, y, x+w, y+h, fill="", outline=outline, width=3 if self.selected == name else 2, tags=(tag,))
        self.canvas.create_rectangle(x+w-10, y+h-10, x+w, y+h, fill=outline, outline=outline, tags=(tag, f"{tag}:resize"))
        self.canvas.create_text(x+5, y+5, text=label, anchor="nw", fill=outline, font=("Arial", 8, "bold"), tags=(tag,))
        self.canvas.tag_bind(tag, "<Button-1>", lambda e, n=name: self.select(n, e))
        self.canvas.tag_bind(tag, "<B1-Motion>", lambda e, n=name: self.drag(n, e))
        self.canvas.tag_bind(tag, "<ButtonRelease-1>", lambda e: self.release())

    def draw_extra_image(self, idx, img_cfg):
        name = f"extra_image:{idx}"
        if not img_cfg.get("visible", True):
            return
        box = {
            "x": float(img_cfg.get("x", 20)),
            "y": float(img_cfg.get("y", 20)),
            "w": float(img_cfg.get("w", 30)),
            "h": float(img_cfg.get("h", 20)),
        }
        x = box["x"] * self.SCALE
        y = box["y"] * self.SCALE
        w = box["w"] * self.SCALE
        h = box["h"] * self.SCALE
        src = str(img_cfg.get("src", "") or "")
        try:
            pil = None
            if src.startswith("data:image"):
                raw = src.split(",", 1)[1] if "," in src else ""
                pil = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
            elif src and os.path.exists(src):
                pil = Image.open(src).convert("RGB")
            if pil is not None:
                pil.thumbnail((int(w), int(h)))
                photo = ImageTk.PhotoImage(pil)
                self.canvas_images.append(photo)
                self.canvas.create_image(x + w / 2, y + h / 2, image=photo, tags=(name,))
        except Exception:
            pass
        self.draw_editor_box(name, box, img_cfg.get("name", "Imagen extra"))

    def mm(self, value):
        return value * self.SCALE

    def draw_mock_text(self, px, py, text, size=7, bold=False, anchor="nw", fill="#111827", width_mm=None):
        font_size = max(5, int(size * 1.25))
        kwargs = {}
        if width_mm:
            kwargs["width"] = self.mm(width_mm)
        self.canvas.create_text(self.mm(px), self.mm(py), text=text, anchor=anchor, fill=fill, font=("Arial", font_size, "bold" if bold else "normal"), **kwargs)

    def draw_mock_wrapped_text(self, px, py, text, width_mm, size=7, bold=False, fill="#111827", max_lines=2):
        chars = max(8, int(width_mm * 1.35))
        words = str(text or "").split()
        lines = []
        current = ""
        for word in words:
            parts = [word[i:i + chars] for i in range(0, len(word), chars)] if len(word) > chars else [word]
            for part in parts:
                test = (current + " " + part).strip()
                if len(test) <= chars:
                    current = test
                else:
                    if current:
                        lines.append(current)
                    current = part
        if current:
            lines.append(current)
        for i, line_text in enumerate(lines[:max_lines]):
            self.draw_mock_text(px, py + (i * 4), line_text, size, bold, fill=fill, width_mm=width_mm)

    def draw_mock_document(self):
        doc = self.cfg.get("doc_editor", {})
        layout = self.cfg.get("layout", {})
        self.canvas.create_rectangle(0, 0, self.mm(210), self.mm(297), fill="white", outline="#cbd5e1")
        self.draw_mock_wrapped_text(42, 13, (self.cfg.get("empresa") or "COMPUTERARMY").upper(), 66, doc.get("header_font", 11), True, max_lines=2)
        self.draw_mock_text(42, 26, "AV. INCA GARCILASO DE LA VEGA 1348", 6, width_mm=66)
        self.draw_mock_text(42, 39, "903039171 computerarmy.eirl@gmail.com", 6, width_mm=66)
        self.canvas.create_rectangle(self.mm(130), self.mm(4), self.mm(204), self.mm(43), outline="#111827")
        self.draw_mock_text(167, 13, "RUC 20611068701", 7, anchor="n")
        self.draw_mock_text(167, 24, "PROFORMA", min(12, doc.get("title_font", 13)), True, anchor="n", width_mm=62)
        self.draw_mock_text(167, 39, "P001-000008", 8, anchor="n")
        self.draw_mock_text(4, 61, "CLIENTE", 7, True)
        self.draw_mock_text(32, 61, "USUARIO X", 7)
        self.draw_mock_text(137, 55, "FECHA EMISION", 7, True)
        self.draw_mock_text(176, 55, "09/05/2026", 7, width_mm=24)
        table = layout.get("table", {"x": 12, "y": 72, "w": 183, "h": 120})
        tx, ty, tw, th = table.get("x", 12), table.get("y", 72), table.get("w", 183), table.get("h", 120)
        self.canvas.create_rectangle(self.mm(tx), self.mm(ty), self.mm(tx+tw), self.mm(ty+th), outline="#111827")
        self.canvas.create_rectangle(self.mm(tx), self.mm(ty), self.mm(tx+tw), self.mm(ty+6), fill="#111827", outline="#111827")
        col_lines = [tx+8, tx+27, tx+tw-64, tx+tw-42, tx+tw-21]
        for lx in col_lines:
            self.canvas.create_line(self.mm(lx), self.mm(ty), self.mm(lx), self.mm(ty+th), fill="#111827")
        for label, lx in [("N°", tx+4), ("UNIDAD", tx+17), ("DESCRIPCION", tx+40), ("CANT.", tx+tw-58), ("TOTAL", tx+tw-31), ("P.UNIT.", tx+tw-9)]:
            self.draw_mock_text(lx, ty+2, label, 6, True, fill="white", anchor="n")
        sample = "PRODUCTO CON NOMBRE LARGO QUE SE PARTE EN LINEAS SIN INVADIR TOTALES"
        desc_width = max(70, (tx + tw - 64) - (tx + 31) - 3)
        self.draw_mock_wrapped_text(tx+31, ty+13, sample, desc_width, doc.get("pdf_desc_font", 7.5), doc.get("pdf_desc_bold", True), max_lines=4)
        self.draw_mock_text(tx+tw-23, ty+13, "100000.00", 5, anchor="ne", width_mm=18)
        self.draw_mock_text(tx+tw-2, ty+13, "100000.00", 5, anchor="ne", width_mm=18)
        totals = layout.get("totals_box", {"x": 125, "y": 195, "w": 70, "h": 22})
        bx, by = totals.get("x", 125), totals.get("y", 195)
        self.draw_mock_text(bx+8, by+4, "GRAVADO", 7, True)
        self.draw_mock_text(bx+62, by+4, "84745.76", 7, anchor="ne")
        self.draw_mock_text(bx+8, by+16, "TOTAL", 8, True)
        self.draw_mock_text(bx+62, by+16, "100000.00", 8, True, anchor="ne")
        self.draw_mock_text(105, 257, "UN AÑO DE GARANTIA DE CADA PRODUCTO", 6, anchor="n")

    def select(self, name, event=None):
        self.selected = name
        if event:
            self.drag_prev = (event.x, event.y)
            b = self.selected_box()
            if b:
                x = float(b.get("x", 0)) * self.SCALE
                y = float(b.get("y", 0)) * self.SCALE
                w = float(b.get("w", 0)) * self.SCALE
                h = float(b.get("h", 0)) * self.SCALE
                self.resize_mode = "se" if event.x >= x + w - 14 and event.y >= y + h - 14 else None
                self.resize_start = dict(b)
        b = self.selected_box()
        if not b:
            return
        kind, key = self.selected_kind_key()
        label = self.FRIENDLY.get(name, name) if kind == "layout" else self.cfg["doc_editor"]["extra_images"][key].get("name", "Imagen extra")
        self.lbl.config(text=f"Seleccionado:\n{label}\n{'Redimensionando' if self.resize_mode else 'Arrastrando'}")
        for k in ["x", "y", "w", "h"]:
            ent = getattr(self, f"ent_{k}")
            ent.delete(0, tk.END)
            ent.insert(0, str(b[k]))

    def drag(self, name, event):
        if self.selected != name or self.drag_prev is None:
            return
        dx = (event.x - self.drag_prev[0]) / self.SCALE
        dy = (event.y - self.drag_prev[1]) / self.SCALE
        b = self.selected_box()
        if not b:
            return
        if self.resize_mode == "se":
            b["w"] = max(5, round(float(b.get("w", 0)) + dx, 1))
            b["h"] = max(5, round(float(b.get("h", 0)) + dy, 1))
        else:
            b["x"] = max(0, round(float(b.get("x", 0)) + dx, 1))
            b["y"] = max(0, round(float(b.get("y", 0)) + dy, 1))
        self.drag_prev = (event.x, event.y)
        self.redraw()
        self.select(name)

    def release(self):
        self.drag_prev = None
        self.resize_mode = None
        self.resize_start = None

    def adjust_selected_size(self, key, delta):
        if not self.selected:
            messagebox.showwarning("Aviso", "Selecciona una zona del documento primero.")
            return
        b = self.selected_box()
        if not b:
            return
        b[key] = max(5, round(float(b.get(key, 0)) + delta, 1))
        self.select(self.selected)
        self.redraw()

    def adjust_selected_font(self, delta):
        if not self.selected:
            messagebox.showwarning("Aviso", "Selecciona una zona del documento primero.")
            return
        doc = self.cfg.setdefault("doc_editor", {})
        mapping = {
            "header_left": ["header_font", self.ent_header_font],
            "header_right": ["title_font", self.ent_title_font],
            "client_box": ["body_font", self.ent_body_font],
            "table": ["pdf_desc_font", self.ent_pdf_desc_font],
            "totals_box": ["table_font", self.ent_table_font],
            "footer_box": ["body_font", self.ent_body_font],
        }
        key, entry = mapping.get(self.selected, ["body_font", self.ent_body_font])
        current = float(doc.get(key, 8) or 8)
        value = max(5, min(18, current + delta))
        doc[key] = value
        entry.delete(0, tk.END)
        entry.insert(0, str(value))
        self.redraw()

    def apply_values(self):
        if not self.selected:
            messagebox.showwarning("Aviso", "Selecciona un bloque primero.")
            return
        b = self.selected_box()
        if not b:
            return
        try:
            b["x"] = float(self.ent_x.get())
            b["y"] = float(self.ent_y.get())
            b["w"] = float(self.ent_w.get())
            b["h"] = float(self.ent_h.get())
        except Exception:
            messagebox.showerror("Error", "Valores inválidos.")
            return
        self.redraw()

    def add_extra_image(self):
        path = filedialog.askopenfilename(
            title="Seleccionar imagen extra",
            filetypes=[("Imagenes", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("Todos los archivos", "*.*")]
        )
        if not path:
            return
        try:
            data_url = self.image_path_to_data_url(path)
        except Exception as e:
            messagebox.showerror("Imagen", f"No se pudo cargar la imagen.\n{e}")
            return
        images = self.cfg["doc_editor"].setdefault("extra_images", [])
        images.append({
            "name": os.path.basename(path),
            "src": data_url,
            "x": 150,
            "y": 210,
            "w": 28,
            "h": 22,
            "visible": True,
        })
        self.selected = f"extra_image:{len(images)-1}"
        self.redraw()
        self.select(self.selected)

    def image_path_to_data_url(self, path, max_size=(900, 900)):
        img = Image.open(path).convert("RGBA")
        img.thumbnail(max_size)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    def delete_selected_element(self):
        kind, key = self.selected_kind_key()
        if kind != "image":
            messagebox.showinfo("Eliminar", "Solo puedes eliminar imagenes extra. Las zonas base se pueden mover o resetear.")
            return
        images = self.cfg["doc_editor"].setdefault("extra_images", [])
        if 0 <= key < len(images) and messagebox.askyesno("Eliminar imagen", "¿Eliminar esta imagen extra de la plantilla?"):
            images.pop(key)
            self.selected = None
            self.redraw()

    def open_precise_text_editor(self):
        self._apply_doc_options()
        doc = self.cfg.setdefault("doc_editor", {})
        labels = doc.setdefault("labels", {})
        texts = doc.setdefault("texts", {})
        win = tk.Toplevel(self)
        win.title("Editor fino de textos ARMY")
        win.geometry("760x720")
        win.configure(bg="#f8fafc")
        tk.Label(
            win,
            text="Editor fino: cambia cada texto tal como saldra en el PDF",
            bg="#f8fafc",
            fg="#0f172a",
            font=("Arial", 14, "bold"),
        ).pack(anchor="w", padx=14, pady=(12, 4))
        tk.Label(
            win,
            text="Los cambios se aplican a la plantilla de esta sucursal cuando guardes.",
            bg="#f8fafc",
            fg="#475569",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        shell = tk.Frame(win, bg="#f8fafc")
        shell.pack(fill="both", expand=True, padx=12, pady=8)
        canvas_box = tk.Canvas(shell, bg="#f8fafc", highlightthickness=0)
        scroll = ttk.Scrollbar(shell, orient="vertical", command=canvas_box.yview)
        body = tk.Frame(canvas_box, bg="#f8fafc")
        body_id = canvas_box.create_window((0, 0), window=body, anchor="nw")
        canvas_box.configure(yscrollcommand=scroll.set)
        canvas_box.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        body.bind("<Configure>", lambda e: canvas_box.configure(scrollregion=canvas_box.bbox("all")))
        canvas_box.bind("<Configure>", lambda e: canvas_box.itemconfigure(body_id, width=e.width))

        entries = {}
        row = 0

        def section(title):
            nonlocal row
            tk.Label(body, text=title, bg="#e2e8f0", fg="#0f172a", font=("Arial", 10, "bold")).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 3), padx=2)
            row += 1

        def add_entry(group, key, title, value, width=62):
            nonlocal row
            tk.Label(body, text=title, bg="#f8fafc", fg="#334155").grid(row=row, column=0, sticky="e", padx=6, pady=3)
            ent = tk.Entry(body, width=width)
            ent.grid(row=row, column=1, sticky="ew", padx=6, pady=3)
            ent.insert(0, str(value or ""))
            entries[(group, key)] = ent
            row += 1

        body.grid_columnconfigure(1, weight=1)
        section("Medidas logo y nombre")
        for key, title in [
            ("logo_x", "Logo X mm"), ("logo_y", "Logo Y mm"), ("logo_w", "Logo ancho mm"), ("logo_h", "Logo alto mm"),
            ("company_x", "Empresa X mm"), ("company_y", "Empresa Y mm"), ("company_w", "Empresa ancho mm"),
        ]:
            add_entry("doc_num", key, title, doc.get(key, ""), width=18)

        section("Etiquetas del documento")
        label_titles = {
            "documento": "Etiqueta documento",
            "cliente": "Etiqueta cliente",
            "direccion": "Etiqueta direccion",
            "fecha_emision": "Etiqueta fecha emision",
            "fecha_vencimiento": "Etiqueta fecha vencimiento",
            "moneda": "Etiqueta moneda",
            "usuario": "Etiqueta usuario/vendedor",
            "condicion_pago": "Etiqueta condicion pago",
            "cuentas_bancarias": "Etiqueta cuentas bancarias",
            "gravado": "Etiqueta gravado",
            "igv": "Etiqueta IGV",
            "total": "Etiqueta total",
            "col_num": "Columna numero",
            "col_unidad": "Columna unidad",
            "col_descripcion": "Columna descripcion",
            "col_cantidad": "Columna cantidad",
            "col_total": "Columna total",
            "col_unitario": "Columna precio unitario",
            "mensaje": "Mensaje final",
        }
        for key, title in label_titles.items():
            add_entry("labels", key, title, labels.get(key, DOCUMENT_LABEL_DEFAULTS.get(key, "")))

        section("Textos fijos y garantia")
        text_titles = {
            "empresa": "Nombre empresa impreso",
            "direccion": "Direccion impresa",
            "contacto": "Telefono / correo",
            "slogan": "Slogan encabezado",
            "condicion_pago_valor": "Valor condicion pago",
            "legal_line1": "Linea legal 1",
            "legal_line2": "Linea legal 2",
            "legal_line3": "Linea legal 3",
            "resumen": "Titulo resumen",
            "garantia_1": "Garantia linea 1",
            "garantia_2": "Garantia linea 2",
            "garantia_3": "Garantia linea 3",
            "garantia_4": "Garantia linea 4",
            "garantia_5": "Garantia linea 5",
            "garantia_6": "Garantia linea 6",
        }
        for key, title in text_titles.items():
            default = DOCUMENT_TEXT_DEFAULTS.get(key, "")
            if key == "empresa":
                default = self.cfg.get("empresa", default)
            elif key == "direccion":
                default = self.cfg.get("direccion", default)
            elif key == "contacto":
                default = f"{self.cfg.get('telefono', '')} {self.cfg.get('correo', '')}".strip()
            elif key == "slogan":
                default = self.cfg.get("mensaje", default)
            add_entry("texts", key, title, texts.get(key, default))

        def save_precise_texts():
            for (group, key), ent in entries.items():
                value = ent.get().strip()
                if group == "labels":
                    labels[key] = value or DOCUMENT_LABEL_DEFAULTS.get(key, "")
                elif group == "texts":
                    texts[key] = value
                elif group == "doc_num":
                    try:
                        doc[key] = float(value)
                    except Exception:
                        pass
            self.ent_lbl_cliente.delete(0, tk.END)
            self.ent_lbl_cliente.insert(0, labels.get("cliente", "CLIENTE"))
            self.ent_lbl_doc.delete(0, tk.END)
            self.ent_lbl_doc.insert(0, labels.get("documento", "DOCUMENTO"))
            self.ent_lbl_dir.delete(0, tk.END)
            self.ent_lbl_dir.insert(0, labels.get("direccion", "DIRECCION"))
            self.ent_lbl_total.delete(0, tk.END)
            self.ent_lbl_total.insert(0, labels.get("total", "TOTAL"))
            self.ent_lbl_msg.delete(0, tk.END)
            self.ent_lbl_msg.insert(0, labels.get("mensaje", self.cfg.get("mensaje", "")))
            self.redraw()
            win.destroy()

        footer = tk.Frame(win, bg="#f8fafc")
        footer.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(footer, text="Aplicar textos al editor", command=save_precise_texts, bg="#059669", fg="white", relief="flat").pack(side="right", padx=4)
        tk.Button(footer, text="Cerrar", command=win.destroy, bg="#64748b", fg="white", relief="flat").pack(side="right", padx=4)

    def template_preset_data(self, name):
        if name == "army":
            return {
                "title": "ARMY referencia exacta",
                "desc": "Replica la plantilla PDF enviada: logo, RUC, tabla y pie ajustados para ARMY.",
                "config": {
                    "logo": os.path.abspath(os.path.join("muestras_plantillas", "reference_assets", "Im9.jpg")).replace("\\", "/")
                },
                "layout": {
                    "header_left": {"x": 5.6, "y": 5.6, "w": 116, "h": 39},
                    "header_right": {"x": 130.2, "y": 5.6, "w": 74.1, "h": 38.8},
                    "client_box": {"x": 5.6, "y": 50.6, "w": 198.6, "h": 16},
                    "table": {"x": 5.6, "y": 69.5, "w": 198.6, "h": 75.1},
                    "totals_box": {"x": 136, "y": 157, "w": 68, "h": 22},
                    "footer_box": {"x": 5.6, "y": 216, "w": 198.6, "h": 52},
                },
                "doc": {
                    "template_name": "ARMY referencia exacta",
                    "title_font": 14,
                    "header_font": 14,
                    "body_font": 7,
                    "table_font": 7,
                    "pdf_code_width": 27.8,
                    "pdf_desc_x": 62.1,
                    "pdf_desc_chars": 58,
                    "pdf_desc_font": 7.0,
                    "pdf_desc_bold": True,
                    "pdf_series_font": 6.2,
                    "pdf_row_height": 6.5,
                    "pdf_code_chars": 14,
                    "pdf_max_rows_first_page": 12,
                    "pdf_desc_lines": 3,
                    "pdf_series_lines": 1,
                    "pdf_line_gap": 2.8,
                    "logo_x": 16,
                    "logo_y": 27,
                    "logo_w": 24,
                    "logo_h": 15,
                    "company_x": 49,
                    "company_y": 10.5,
                    "company_w": 82,
                    "show_logo": True,
                    "show_serie": True,
                    "show_banks": True,
                    "keyfacil_exact": True,
                    "show_reference_footer": True,
                    "labels": {
                        "documento": "DOCUMENTO",
                        "cliente": "CLIENTE",
                        "direccion": "DIRECCION",
                        "fecha_emision": "FECHA EMISION",
                        "fecha_vencimiento": "FECHA VENCIMIENTO",
                        "moneda": "MONEDA",
                        "usuario": "USUARIO",
                        "condicion_pago": "CONDICION DE PAGO",
                        "cuentas_bancarias": "CUENTAS BANCARIAS",
                        "gravado": "GRAVADO",
                        "igv": "I.G.V. 18%",
                        "total": "TOTAL",
                    },
                    "texts": {
                        **DOCUMENT_TEXT_DEFAULTS,
                        "empresa": "CORPORACION COMPUTER ARMY EIRL",
                        "direccion": "PRINCIPAL >> AV. INCA GARCILASO DE LA VEGA NRO. 1348 INT2B 130-131 - CERCADO DE LIMA - LIMA - PERU",
                        "slogan": "MEJORES PRECIOS EN TARJETAS DE VIDEOS",
                        "legal_line1": "Autorizado mediante resolucion Nro 034-005-0010431/SUNAT",
                        "legal_line2": "",
                        "legal_line3": "Emitido mediante G&G ERP",
                    },
                }
            }
        if name == "keyfacil":
            return {
            "title": "Proforma ARMY exacta",
            "desc": "Plantilla replicada de la muestra, con encabezado, tabla, totales y garantias.",
            "layout": {
                "header_left": {"x": 8, "y": 8, "w": 105, "h": 32},
                "header_right": {"x": 130, "y": 6, "w": 72, "h": 36},
                "client_box": {"x": 8, "y": 48, "w": 194, "h": 20},
                "table": {"x": 8, "y": 70, "w": 194, "h": 88},
                "totals_box": {"x": 132, "y": 162, "w": 68, "h": 22},
                "footer_box": {"x": 8, "y": 212, "w": 194, "h": 60},
            },
            "doc": {
                "title_font": 13,
                "header_font": 11,
                "body_font": 7,
                "table_font": 6,
                "pdf_code_width": 22,
                "pdf_desc_x": 56,
                "pdf_desc_chars": 60,
                "pdf_desc_font": 7,
                "pdf_desc_bold": True,
                "pdf_row_height": 10,
                "pdf_code_chars": 10,
                "show_logo": True,
                "show_serie": True,
                "show_banks": True
            }
        }
        presets = {
            "sunat": {
                "title": "SUNAT A4 ordenada",
                "desc": "Formato limpio para boleta, factura y proforma electronica.",
                "layout": {
                    "header_left": {"x": 12, "y": 12, "w": 92, "h": 28},
                    "header_right": {"x": 140, "y": 12, "w": 55, "h": 28},
                    "client_box": {"x": 12, "y": 45, "w": 183, "h": 22},
                    "table": {"x": 12, "y": 72, "w": 183, "h": 100},
                    "totals_box": {"x": 125, "y": 185, "w": 70, "h": 22},
                    "footer_box": {"x": 12, "y": 221, "w": 183, "h": 18},
                },
                "doc": {"template_name": "SUNAT A4 ordenada", "title_font": 13, "header_font": 11, "body_font": 8, "table_font": 7, "pdf_row_height": 8, "pdf_max_rows_first_page": 12},
            },
            "pc": {
                "title": "PC + garantia",
                "desc": "Mas espacio para series, garantias y cuentas bancarias.",
                "layout": {
                    "header_left": {"x": 8, "y": 8, "w": 110, "h": 36},
                    "header_right": {"x": 130, "y": 6, "w": 72, "h": 38},
                    "client_box": {"x": 8, "y": 48, "w": 194, "h": 20},
                    "table": {"x": 8, "y": 72, "w": 194, "h": 90},
                    "totals_box": {"x": 132, "y": 174, "w": 68, "h": 22},
                    "footer_box": {"x": 8, "y": 216, "w": 194, "h": 56},
                },
                "doc": {"template_name": "PC + garantia", "title_font": 13, "header_font": 12, "body_font": 7, "table_font": 6.5, "pdf_row_height": 7, "pdf_max_rows_first_page": 12, "pdf_desc_lines": 3, "pdf_series_lines": 1},
            },
            "ticket": {
                "title": "Ticket estrecho",
                "desc": "Estilo compacto para ventas rapidas, sin quitar opciones de A4.",
                "layout": {
                    "header_left": {"x": 10, "y": 10, "w": 115, "h": 30},
                    "header_right": {"x": 132, "y": 8, "w": 65, "h": 35},
                    "client_box": {"x": 10, "y": 48, "w": 187, "h": 18},
                    "table": {"x": 10, "y": 72, "w": 187, "h": 96},
                    "totals_box": {"x": 127, "y": 180, "w": 70, "h": 22},
                    "footer_box": {"x": 10, "y": 218, "w": 187, "h": 44},
                },
                "doc": {"template_name": "Ticket estrecho", "title_font": 12, "header_font": 10, "body_font": 7, "table_font": 6.2, "pdf_row_height": 7, "pdf_max_rows_first_page": 12},
            },
            "simple": {
                "title": "Proforma limpia",
                "desc": "Documento claro con mas aire visual para cotizaciones.",
                "layout": {
                    "header_left": {"x": 14, "y": 14, "w": 100, "h": 28},
                    "header_right": {"x": 138, "y": 14, "w": 58, "h": 30},
                    "client_box": {"x": 14, "y": 52, "w": 182, "h": 20},
                    "table": {"x": 14, "y": 78, "w": 182, "h": 94},
                    "totals_box": {"x": 126, "y": 186, "w": 70, "h": 22},
                    "footer_box": {"x": 14, "y": 224, "w": 182, "h": 30},
                },
                "doc": {"template_name": "Proforma limpia", "title_font": 13, "header_font": 11, "body_font": 8, "table_font": 7, "pdf_row_height": 8, "pdf_max_rows_first_page": 12},
            },
        }
        return presets.get(name, presets["sunat"])

    def open_template_gallery(self):
        win = tk.Toplevel(self)
        win.title("Galeria de plantillas")
        win.geometry("1180x760")
        win.configure(bg="#f1f5f9")
        tk.Label(win, text="Escoge una plantilla de impresión", bg="#f1f5f9", fg="#0f172a", font=("Arial", 18, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
        tk.Label(win, text="Estas vistas son ejemplos. Al elegir una puedes seguir moviendo zonas y guardar para la sucursal.", bg="#f1f5f9", fg="#475569").pack(anchor="w", padx=18, pady=(0, 10))
        grid = tk.Frame(win, bg="#f1f5f9")
        grid.pack(fill="both", expand=True, padx=14, pady=8)
        names = ["army", "sunat", "pc", "ticket", "simple"]
        for idx, name in enumerate(names):
            data = self.template_preset_data(name)
            card = tk.Frame(grid, bg="white", highlightthickness=1, highlightbackground="#cbd5e1")
            card.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=8, pady=8)
            grid.grid_columnconfigure(idx % 2, weight=1)
            grid.grid_rowconfigure(idx // 2, weight=1)
            tk.Label(card, text=data["title"], bg="white", fg="#0f172a", font=("Arial", 13, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
            tk.Label(card, text=data["desc"], bg="white", fg="#64748b", wraplength=430, justify="left").pack(anchor="w", padx=10, pady=(0, 6))
            preview = tk.Canvas(card, width=255, height=360, bg="white", highlightthickness=1, highlightbackground="#94a3b8")
            preview.pack(padx=10, pady=6)
            self.draw_template_thumbnail(preview, data)
            tk.Button(card, text="Usar esta plantilla", command=lambda n=name, w=win: (self.apply_template_preset(n, ask=False), w.destroy()), bg="#0891b2", fg="white", relief="flat").pack(fill="x", padx=10, pady=(2, 10))

    def draw_template_thumbnail(self, canvas_widget, data):
        scale = 1.2
        def mmv(v): return v * scale
        canvas_widget.create_rectangle(0, 0, mmv(210), mmv(297), fill="white", outline="#cbd5e1")
        layout = data["layout"]
        for key, label in [("header_left", "EMPRESA"), ("header_right", "DOCUMENTO"), ("client_box", "CLIENTE / FECHA"), ("table", "TABLA PRODUCTOS"), ("totals_box", "TOTALES"), ("footer_box", "PIE / GARANTIA")]:
            b = layout[key]
            canvas_widget.create_rectangle(mmv(b["x"]), mmv(b["y"]), mmv(b["x"] + b["w"]), mmv(b["y"] + b["h"]), outline="#0f172a", width=1)
            canvas_widget.create_text(mmv(b["x"] + 2), mmv(b["y"] + 2), text=label, anchor="nw", fill="#0f172a", font=("Arial", 6, "bold"))
            if key == "table":
                canvas_widget.create_rectangle(mmv(b["x"]), mmv(b["y"]), mmv(b["x"] + b["w"]), mmv(b["y"] + 5), fill="#111827", outline="#111827")
                for line_x in [b["x"] + 8, b["x"] + 27, b["x"] + 50, b["x"] + b["w"] - 64, b["x"] + b["w"] - 42, b["x"] + b["w"] - 21]:
                    canvas_widget.create_line(mmv(line_x), mmv(b["y"]), mmv(line_x), mmv(b["y"] + b["h"]), fill="#334155")
                for r in range(4):
                    y = b["y"] + 12 + (r * 8)
                    if y < b["y"] + b["h"] - 4:
                        canvas_widget.create_line(mmv(b["x"] + 2), mmv(y), mmv(b["x"] + b["w"] - 2), mmv(y), fill="#e2e8f0")

    def apply_template_preset(self, name, ask=True):
        if ask and not messagebox.askyesno("Aplicar plantilla", "Esto reemplazara posiciones y formato actual del editor. ¿Continuar?"):
            return
        doc = self.cfg.setdefault("doc_editor", {})
        data = self.template_preset_data(name)
        self.cfg["layout"] = json.loads(json.dumps(data["layout"]))
        if isinstance(data.get("config"), dict):
            self.cfg.update(data["config"])
        doc.update(data["doc"])
        ensure_document_editor_defaults(self.cfg)
        self.var_logo.set(doc.get("show_logo", True))
        self.var_serie.set(doc.get("show_serie", True))
        self.var_banks.set(doc.get("show_banks", True))
        self.selected = None
        self.sync_entries_from_doc()
        self.redraw()

    def sync_entries_from_doc(self):
        doc = self.cfg.setdefault("doc_editor", {})
        mapping = [
            (self.ent_title_font, doc.get("title_font", 13)),
            (self.ent_header_font, doc.get("header_font", 11)),
            (self.ent_body_font, doc.get("body_font", 7)),
            (self.ent_table_font, doc.get("table_font", 6)),
            (self.ent_pdf_code_width, doc.get("pdf_code_width", 19)),
            (self.ent_pdf_code_chars, doc.get("pdf_code_chars", 10)),
            (self.ent_pdf_desc_x, doc.get("pdf_desc_x", 52)),
            (self.ent_pdf_desc_chars, doc.get("pdf_desc_chars", 62)),
            (self.ent_pdf_desc_font, doc.get("pdf_desc_font", 7.5)),
            (self.ent_pdf_series_font, doc.get("pdf_series_font", 6)),
            (self.ent_pdf_row_height, doc.get("pdf_row_height", 10)),
            (self.ent_pdf_max_rows, doc.get("pdf_max_rows_first_page", 12)),
            (self.ent_pdf_desc_lines, doc.get("pdf_desc_lines", 3)),
            (self.ent_pdf_series_lines, doc.get("pdf_series_lines", 1)),
            (self.ent_pdf_line_gap, doc.get("pdf_line_gap", 2.8)),
        ]
        for ent, value in mapping:
            ent.delete(0, tk.END)
            ent.insert(0, str(value))

    def _apply_doc_options(self):
        doc = self.cfg.setdefault("doc_editor", {})
        labels = doc.setdefault("labels", {})
        doc["show_logo"] = self.var_logo.get()
        doc["show_serie"] = self.var_serie.get()
        doc["show_banks"] = self.var_banks.get()

        def num(entry, default):
            try:
                return int(entry.get())
            except Exception:
                return default

        def dec(entry, default):
            try:
                return float(str(entry.get()).replace(",", "."))
            except Exception:
                return default

        doc["title_font"] = num(self.ent_title_font, 13)
        doc["header_font"] = num(self.ent_header_font, 11)
        doc["body_font"] = num(self.ent_body_font, 8)
        doc["table_font"] = num(self.ent_table_font, 7)
        doc["pdf_code_width"] = dec(self.ent_pdf_code_width, 19)
        doc["pdf_code_chars"] = num(self.ent_pdf_code_chars, 10)
        doc["pdf_desc_x"] = dec(self.ent_pdf_desc_x, 52)
        doc["pdf_desc_chars"] = num(self.ent_pdf_desc_chars, 62)
        doc["pdf_desc_font"] = dec(self.ent_pdf_desc_font, 7.5)
        doc["pdf_series_font"] = dec(self.ent_pdf_series_font, 6)
        doc["pdf_row_height"] = dec(self.ent_pdf_row_height, 10)
        doc["pdf_max_rows_first_page"] = num(self.ent_pdf_max_rows, 12)
        doc["pdf_desc_lines"] = num(self.ent_pdf_desc_lines, 3)
        doc["pdf_series_lines"] = num(self.ent_pdf_series_lines, 1)
        doc["pdf_line_gap"] = dec(self.ent_pdf_line_gap, 2.8)
        doc["pdf_desc_bold"] = self.var_desc_bold.get()

        labels["cliente"] = self.ent_lbl_cliente.get().strip() or "CLIENTE"
        labels["documento"] = self.ent_lbl_doc.get().strip() or "DOCUMENTO"
        labels["direccion"] = self.ent_lbl_dir.get().strip() or "DIRECCION"
        labels["total"] = self.ent_lbl_total.get().strip() or "TOTAL"
        labels["mensaje"] = self.ent_lbl_msg.get().strip() or self.cfg.get("mensaje", "GRACIAS POR SU COMPRA")
        self.cfg["mensaje"] = labels["mensaje"]

    def build_editor_sample_pdf(self, out):
        sample_items = [
            {"nombre": "PROCESADOR INTEL CORE I5", "marca": "INTEL", "modelo": "12400F", "serie": "SN123456", "cantidad": 1, "precio": 450, "total": 450},
            {"nombre": "PLACA MADRE B760", "marca": "ASUS", "modelo": "TUF", "serie": "MB98765", "cantidad": 1, "precio": 520, "total": 520},
            {"nombre": "MEMORIA RAM KINGSTON FURY BEAST 16GB DDR4", "marca": "KINGSTON", "modelo": "3200MHZ", "serie": "", "cantidad": 1, "precio": 180, "total": 180},
            {"nombre": "DISCO SSD M.2 NVME ADATA XPG S20", "marca": "ADATA", "modelo": "512GB", "serie": "", "cantidad": 1, "precio": 285, "total": 285},
            {"nombre": "TARJETA DE VIDEO GEFORCE RTX 5060", "marca": "MSI", "modelo": "SHADOW 2X", "serie": "", "cantidad": 1, "precio": 1600, "total": 1600},
            {"nombre": "FUENTE DE PODER MSI MAG A650BN", "marca": "MSI", "modelo": "650W", "serie": "", "cantidad": 1, "precio": 235, "total": 235},
            {"nombre": "CASE ANTEC CX800 RGB BLACK", "marca": "ANTEC", "modelo": "VIDRIO", "serie": "", "cantidad": 1, "precio": 295, "total": 295},
        ]
        generate_pdf(
            out,
            self.cfg,
            "PROFORMA",
            "P001-000001",
            "CLIENTE DE PRUEBA",
            "DNI: 00000000",
            "LIMA - PERÚ",
            sample_items,
            3022.03,
            543.96,
            3565.99,
            "ID 2 - Giomar",
        )
        return out

    def preview_pdf(self):
        self._apply_doc_options()
        out = os.path.join(tempfile.gettempdir(), "vista_previa_editor_a4.pdf")
        self.build_editor_sample_pdf(out)
        open_pdf_internal_window(self, "Vista previa PDF plantilla", out, "plantilla_documento_ggerp.pdf")

    def save_editor_pdf(self):
        self._apply_doc_options()
        out = filedialog.asksaveasfilename(
            title="Guardar PDF de plantilla",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile="plantilla_documento_ggerp.pdf",
        )
        if not out:
            return
        try:
            self.build_editor_sample_pdf(out)
            play_document_sound("success")
            messagebox.showinfo("Guardar PDF", f"PDF guardado:\n{out}")
        except Exception as e:
            messagebox.showerror("Guardar PDF", f"No se pudo guardar el PDF.\n{e}")

    def reset(self):
        if not messagebox.askyesno("Confirmar", "¿Restablecer plantilla A4?"):
            return
        self.cfg.setdefault("doc_editor", {})["extra_images"] = []
        self.apply_template_preset("sunat", ask=False)

    def save(self):
        self._apply_doc_options()
        save_config(self.cfg)
        self.on_save()
        messagebox.showinfo("Éxito", "Plantilla guardada en la nube para esta sucursal.")


class LoginWindow:
    def __init__(self, root):
        self.root = root
        self.root.title(f"ERP V20 MENÚ LATERAL - Login ({APP_VERSION})")
        apply_modern_ttk_style(root)
        self.root.title(f"G&G ERP - Login ({APP_VERSION})")
        self.root.geometry("580x680")
        self.root.resizable(False, False)
        self.root.configure(bg=APP_BG)
        self.remember_file = "login_user.json"
        self.login_avatar_photo = None
        self.login_avatar_after_id = None

        bg_band = tk.Frame(root, bg=SIDEBAR_BG, height=185)
        bg_band.pack(fill="x", side="top")
        tk.Label(root, text="G&G ERP", bg=SIDEBAR_BG, fg="#ffffff", font=("Arial", 25, "bold")).place(relx=0.5, y=38, anchor="center")
        tk.Label(root, text="Sistema administrativo sincronizado", bg=SIDEBAR_BG, fg=SIDEBAR_MUTED, font=("Arial", 10, "bold")).place(relx=0.5, y=70, anchor="center")
        frame = tk.Frame(root, bg=CARD_BG, highlightthickness=1, highlightbackground=BORDER)
        frame.place(relx=0.5, rely=0.55, anchor="center", width=430, height=535)

        tk.Label(frame, text="Acceso seguro", bg=CARD_BG, fg=TEXT, font=("Arial", 19, "bold")).pack(pady=(22, 2))
        self.login_avatar = tk.Label(frame, text="👤", font=("Arial", 34), bg=CARD_BG, fg=ACCENT, width=4, height=1)
        self.login_avatar.pack(pady=(2, 2))
        self.login_user_name = tk.Label(frame, text="INICIAR SESIÓN", bg=CARD_BG, fg=ACCENT, font=("Arial", 16, "bold"))
        self.login_user_name.pack(pady=(0, 3))
        self.login_avatar.config(text="US", font=("Arial", 22, "bold"), bg=ACCENT, fg="#ffffff", width=4, height=2)
        self.login_user_name.config(text="INICIAR SESION")
        tk.Label(frame, text=f"Versión {APP_VERSION}", bg=CARD_BG, fg=MUTED, font=("Arial", 9)).pack(pady=(0, 5))

        tk.Label(frame, text="Empresa", bg=CARD_BG, fg=MUTED, font=("Arial", 10, "bold")).pack(anchor="w", padx=58, pady=(10, 0))
        self.empresa = ttk.Combobox(
            frame,
            values=empresa_display_options(),
            state="readonly",
            width=26
        )
        self.empresa.pack(pady=5, ipady=2)
        self.empresa.set("COMPUTER ARMY")

        tk.Label(frame, text="Usuario", bg=CARD_BG, fg=MUTED, font=("Arial", 10, "bold")).pack(anchor="w", padx=58, pady=(8, 0))
        self.user = tk.Entry(frame, width=28, bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, font=("Arial", 11), fg=TEXT, bg=SOFT_BG, insertbackground=TEXT)
        self.user.pack(pady=6, ipady=9)
        self.user.bind("<KeyRelease>", self.schedule_login_avatar_update)
        self.user.bind("<FocusOut>", self.update_login_avatar)

        tk.Label(frame, text="Contraseña", bg=CARD_BG, fg=TEXT).pack()
        self.passw = tk.Entry(frame, width=28, show="*", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, font=("Arial", 11), fg=TEXT, bg=SOFT_BG, insertbackground=TEXT)
        self.passw.pack(pady=6, ipady=9)

        self.show_pass_var = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="Mostrar contraseña", variable=self.show_pass_var, command=self.toggle_password, bg=CARD_BG, fg=TEXT, activebackground=CARD_BG).pack()

        self.remember_var = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Recordar usuario", variable=self.remember_var, bg=CARD_BG, fg=TEXT, activebackground=CARD_BG).pack()

        btn = tk.Button(frame, text="Ingresar", command=self.login, bg=ACCENT, fg="white", relief="flat", width=26, cursor="hand2", font=("Arial", 12, "bold"), pady=10, bd=0)
        btn.pack(pady=16)
        btn.bind("<Enter>", lambda e: btn.config(bg=ACCENT_DARK))
        btn.bind("<Leave>", lambda e: btn.config(bg=ACCENT))

        self.user.bind("<Return>", self.focus_pass)
        self.passw.bind("<Return>", lambda e: self.login())

        self.load_user()
        self.root.after(500, self.check_update_ui)

    def login_photo_value_to_image(self, value, size=(74, 74)):
        src = str(value or "").strip()
        if not src:
            return None
        try:
            if src.startswith(("http://", "https://")):
                with urllib.request.urlopen(src, timeout=8) as r:
                    img = Image.open(r).convert("RGB")
            elif src.startswith("data:image"):
                raw = src.split(",", 1)[1] if "," in src else ""
                img = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
            elif os.path.exists(src):
                img = Image.open(src).convert("RGB")
            else:
                return None
            img.thumbnail(size)
            canvas_img = Image.new("RGB", size, CARD_BG)
            canvas_img.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
            return ImageTk.PhotoImage(canvas_img)
        except Exception:
            return None

    def schedule_login_avatar_update(self, event=None):
        if self.login_avatar_after_id:
            try:
                self.root.after_cancel(self.login_avatar_after_id)
            except Exception:
                pass
        self.login_avatar_after_id = self.root.after(250, self.update_login_avatar)

    def update_login_avatar(self, event=None):
        self.login_avatar_after_id = None
        usuario = self.user.get().strip()
        if not usuario:
            self.login_avatar_photo = None
            self.login_avatar.config(image="", text="👤", font=("Arial", 42), bg=CARD_BG, width=4, height=2)
            self.login_user_name.config(text="INICIAR SESIÓN")
            return
        data = {}
        try:
            fn = getattr(api_client, "perfil_usuario", None) if api_client is not None else None
            data = fn(usuario) if callable(fn) else _api_json("get", f"/usuarios/perfil?usuario={urllib.parse.quote(usuario)}", {})
        except Exception:
            data = {}
        if api_response_ok(data) and data.get("found"):
            photo = self.login_photo_value_to_image(data.get("foto_url", ""))
            self.login_user_name.config(text=str(data.get("usuario", usuario)))
            if photo:
                self.login_avatar_photo = photo
                self.login_avatar.config(image=photo, text="", bg=CARD_BG, width=74, height=74)
            else:
                self.login_avatar_photo = None
                initials = str(data.get("usuario", usuario))[:2].upper()
                self.login_avatar.config(image="", text=initials, font=("Arial", 24, "bold"), bg=ACCENT, fg="white", width=4, height=2)
        else:
            self.login_avatar_photo = None
            self.login_user_name.config(text=usuario)
            self.login_avatar.config(image="", text="👤", font=("Arial", 42), bg=CARD_BG, fg=ACCENT, width=4, height=2)

    def toggle_password(self):
        self.passw.config(show="" if self.show_pass_var.get() else "*")

    def focus_pass(self, event=None):
        self.passw.focus_set()

    def load_user(self):
        try:
            if os.path.exists(self.remember_file):
                with open(self.remember_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                username = data.get("usuario", "").strip()
                if username:
                    self.user.insert(0, username)
                    self.update_login_avatar()
                    self.passw.focus_set()
                    return
        except Exception:
            pass
        self.user.focus_set()

    def save_user(self):
        try:
            if self.remember_var.get():
                with open(self.remember_file, "w", encoding="utf-8") as f:
                    json.dump({"usuario": self.user.get().strip()}, f, ensure_ascii=False, indent=4)
            elif os.path.exists(self.remember_file):
                os.remove(self.remember_file)
        except Exception:
            pass

    def check_update_ui(self):
        info = check_update()
        if not api_response_ok(info):
            return
        if info.get("update_available"):
            resp = messagebox.askyesno("Actualización disponible", f"Hay una nueva versión disponible: {info['remote_version']}\n\nTu versión actual es: {APP_VERSION}\n\n¿Deseas actualizar ahora?")
            if resp:
                result = update_exe_and_restart(info["download_url"], info["exe_name"])
                if api_response_ok(result):
                    messagebox.showinfo("Actualizando", "Se descargó la actualización.\nEl sistema se cerrará para reemplazar el ejecutable.")
                    self.root.destroy()
                else:
                    messagebox.showerror("Error de actualización", result.get("msg", "No se pudo actualizar."))

    def login(self):
        empresa_ui = self.empresa.get().strip()
        empresa_key = empresa_to_key(empresa_ui)
        if api_client is not None and hasattr(api_client, "set_empresa"):
            api_client.set_empresa(empresa_key)
        data = validar_usuario(self.user.get().strip(), self.passw.get().strip())
        if not data or "usuario" not in data:
            msg = "Credenciales incorrectas o API sin respuesta"
            if isinstance(data, dict):
                msg = data.get("msg") or data.get("error") or msg
            messagebox.showerror("Error", msg)
            return
        self.save_user()
        self.root.destroy()
        root = tk.Tk()
        App(root, data)
        root.mainloop()


class App:
    def __init__(self, root, user):
        self.root = root
        apply_modern_ttk_style(root)
        self.user = user
        try:
            if api_client is not None and hasattr(api_client, "set_empresa"):
                api_client.set_empresa(user.get("sucursal") or user.get("empresa") or "computer_army")
        except Exception:
            pass
        self.cfg = load_shared_document_config(load_config())
        self.dashboard_img_tk = None
        self.logo_tk = None
        self.items_venta = []
        self.items_compra = []
        self.productos_encontrados = []
        self.sales_product_cache = []
        self.sales_product_cache_loaded = False
        self.sale_search_after_id = None
        self.product_img_cache = {}
        self.product_img_bytes_cache = {}
        self.product_img_loading = set()
        self.sale_card_images = []
        self.user_avatar_photo = None
        self.selected_sale_product_index = None
        self.cash_comprobante_pago_path = ""
        self.cash_comprobante_pago_paths = []
        self.sale_drafts = []
        self.active_sale_draft_id = None
        self._loading_sale_draft = False
        self.editing_proforma_id = None
        self.editing_proforma_numero = ""
        self._cash_alert_key = ""
        self._cash_alert_ready = False
        self._radio_ready = True
        self._radio_last_id = 0
        self._radio_poll_running = False
        self._radio_played_ids = set()
        self._radio_recording = False
        self._radio_selected_user = tk.StringVar(value="")
        self._radio_status_var = tk.StringVar(value="Radio listo")
        self._radio_users = []
        self.sucursal_permisos = self.load_branch_permissions()

        self.root.title(f'ERP V20 - {user["usuario"]} - {user.get("empresa", "computer_army")}')
        screen_w = max(1024, self.root.winfo_screenwidth())
        screen_h = max(700, self.root.winfo_screenheight())
        self.compact_layout = screen_w < 1360 or screen_h < 820
        self.sidebar_width = 218 if self.compact_layout else 260
        self.sale_panel_width = 360 if self.compact_layout else 410
        win_w = min(1520, max(1024, screen_w - 70))
        win_h = min(930, max(680, screen_h - 95))
        self.root.geometry(f"{win_w}x{win_h}+20+20")
        self.root.minsize(1024, 650)
        self.root.configure(bg=APP_BG)

        self.build_shell()
        self.root.bind_all("<ButtonRelease-1>", self.play_click_for_button, add="+")
        self.refresh_all()
        self.start_cash_document_alert_monitor()
        self.start_boquitoqui_audio_monitor()

    def play_click_for_button(self, event=None):
        try:
            widget = event.widget
            if isinstance(widget, tk.Button) or widget.winfo_class() in ("TButton", "Button"):
                play_click_sound()
        except Exception:
            pass

    def start_cash_document_alert_monitor(self):
        self.root.after(9000, self.check_cash_document_alert)

    def start_boquitoqui_audio_monitor(self):
        self.root.after(1200, self.check_boquitoqui_audio)

    def check_boquitoqui_audio(self):
        if self._radio_poll_running:
            try:
                self.root.after(330, self.check_boquitoqui_audio)
            except Exception:
                pass
            return
        self._radio_poll_running = True
        usuario = str(self.user.get("usuario", "")).strip()
        since_id = int(self._radio_last_id or 0)

        def worker():
            rows = []
            try:
                resp = obtener_boquitoqui_live(usuario, since_id, 20)
                rows = api_response_get(resp, "data", resp if isinstance(resp, list) else []) or []
            except Exception:
                rows = []
            try:
                self.root.after(0, lambda: self.process_boquitoqui_audio_rows(rows))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def process_boquitoqui_audio_rows(self, rows):
        self._radio_poll_running = False
        try:
            rows = rows if isinstance(rows, list) else []
            newest_id = int(self._radio_last_id or 0)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    msg_id = int(row.get("id") or 0)
                except Exception:
                    msg_id = 0
                if msg_id > newest_id:
                    newest_id = msg_id
                if not self._radio_ready:
                    continue
                if not msg_id or msg_id in self._radio_played_ids:
                    continue
                sender = str(row.get("usuario_emisor", "")).strip().lower()
                usuario = str(self.user.get("usuario", "")).strip().lower()
                if sender == usuario:
                    continue
                if play_boquitoqui_audio(row.get("audio_base64", ""), row.get("audio_mime", "audio/wav")):
                    self._radio_played_ids.add(msg_id)
            self._radio_last_id = max(int(self._radio_last_id or 0), newest_id)
            self._radio_ready = True
            if len(self._radio_played_ids) > 200:
                self._radio_played_ids = set(list(self._radio_played_ids)[-80:])
        except Exception:
            pass
        try:
            self.root.after(330, self.check_boquitoqui_audio)
        except Exception:
            pass

    def check_cash_document_alert(self):
        try:
            resp = obtener_ultimo_documento_caja()
            doc = api_response_get(resp, "data", None) if isinstance(resp, dict) else None
            if isinstance(doc, dict) and doc:
                key = str(doc.get("key") or f"{doc.get('id')}-{doc.get('numero')}-{doc.get('total')}")
                if not self._cash_alert_ready:
                    self._cash_alert_key = key
                    self._cash_alert_ready = True
                elif key and key != self._cash_alert_key:
                    self._cash_alert_key = key
                    play_cash_approved_sound()
                    try:
                        if getattr(self, "current_key", "") == "caja":
                            self.refresh_cash()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            self.root.after(20000, self.check_cash_document_alert)
        except Exception:
            pass

    def build_shell(self):
        self.current_key = None
        self.current_color = SIDEBAR_BG

        body = tk.Frame(self.root, bg=APP_BG)
        body.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(body, bg=SIDEBAR_BG, width=getattr(self, "sidebar_width", 260))
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        brand.pack(fill="x", padx=18, pady=(24, 18))
        self.logo_lbl = tk.Label(brand, bg=SIDEBAR_BG)
        self.logo_lbl.pack(side="left")
        self.update_logo_ui()
        tk.Label(brand, text="G&G", bg=SIDEBAR_BG, fg="white", font=("Arial", 16, "bold")).pack(side="left", padx=(10, 0))
        tk.Label(brand, text="ERP", bg=SIDEBAR_BG, fg="#bfdbfe", font=("Arial", 16, "bold")).pack(side="left", padx=(3, 0))

        self.content = tk.Frame(body, bg=APP_BG)
        self.content.pack(side="right", fill="both", expand=True)

        self.topbar = tk.Frame(self.content, bg=TOPBAR_BG, height=76, highlightthickness=1, highlightbackground=BORDER)
        self.topbar.pack(fill="x", side="top")
        self.topbar.pack_propagate(False)

        tk.Label(self.topbar, text="MENU", bg=TOPBAR_BG, fg=MUTED, font=("Arial", 10, "bold")).pack(side="left", padx=(28, 18))
        search_wrap = tk.Frame(self.topbar, bg=SOFT_BG, highlightthickness=1, highlightbackground=BORDER)
        search_wrap.pack(side="left", fill="x", expand=True, padx=(0, 32), pady=16)
        self.global_search = tk.Entry(search_wrap, bd=0, bg=SOFT_BG, fg=TEXT, insertbackground=TEXT, font=("Arial", 11))
        self.global_search.pack(side="left", fill="x", expand=True, padx=14, pady=8)
        self.global_search.insert(0, "Buscar")
        self.global_search.bind("<FocusIn>", self.global_search_focus_in)
        self.global_search.bind("<FocusOut>", self.global_search_focus_out)
        self.global_search.bind("<Return>", self.run_global_search)

        branch_name = str(self.user.get("sucursal") or self.user.get("empresa") or "computer_army").replace("_", " ").title()
        self.branch_lbl = tk.Label(self.topbar, text=branch_name, bg=SOFT_BG, fg=TEXT, font=("Arial", 10, "bold"), padx=12, pady=6)
        self.branch_lbl.pack(side="left", padx=18)
        avatar_text = str(self.user.get("usuario", "AD"))[:2].upper() or "AD"
        self.avatar_lbl = tk.Label(self.topbar, text=avatar_text, bg="#0f5d9a", fg="white", font=("Arial", 11, "bold"), width=3)
        self.avatar_lbl.pack(side="left", padx=(18, 8))
        self.update_user_avatar_ui()
        self.user_lbl = tk.Label(self.topbar, text=f'{self.user.get("usuario", "")}  |  {self.user.get("rol", "")}', bg=TOPBAR_BG, fg=TEXT, font=("Arial", 10, "bold"))
        self.user_lbl.pack(side="left", padx=(0, 22))

        self.frames = {}
        self.nav_buttons = {}
        self.nav_items = self.allowed_nav_items()

        for text, key, color in self.nav_items:
            b = tk.Button(
                self.sidebar,
                text=f"  {NAV_MARKS.get(key, '•')}   {text}",
                anchor="w",
                bg=SIDEBAR_BG,
                fg=SIDEBAR_TEXT,
                relief="flat",
                activebackground=ACCENT_DARK if key == "caja" else color,
                activeforeground="white",
                padx=14,
                pady=13,
                font=("Segoe UI Symbol", 11, "bold"),
                bd=0,
                command=lambda k=key, c=color: self.show_frame(k, c),
            )
            b.pack(fill="x", padx=12, pady=4)
            b.bind("<Enter>", lambda e, btn=b, c=color: btn.config(bg=SIDEBAR_HOVER if c == "#334155" else c, fg="white"))
            b.bind("<Leave>", lambda e, btn=b, k=key: btn.config(bg=SIDEBAR_BG if self.current_key != k else self.current_color, fg=SIDEBAR_TEXT if self.current_key != k else "white"))
            self.nav_buttons[key] = b

        bottom = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        bottom.pack(side="bottom", fill="x", padx=12, pady=18)
        for label in ("Ayuda", "Cerrar sesion"):
            tk.Label(bottom, text=f"   {label}", bg=SIDEBAR_BG, fg=SIDEBAR_MUTED, font=("Arial", 10)).pack(fill="x", pady=8, anchor="w")

        for key in [x[1] for x in NAV_ITEMS]:
            f = tk.Frame(self.content, bg=APP_BG)
            self.frames[key] = f

        self.build_dashboard()
        self.build_ventas()
        self.build_clientes()
        self.build_productos()
        self.build_inventario()
        self.build_compras()
        self.build_contabilidad()
        self.build_caja()
        self.build_radio()
        self.build_usuarios()
        self.build_garantias()
        self.build_auditoria()
        self.build_erp_moderno()
        self.build_pagina_web()
        self.build_ajustes()
        self.apply_dark_widget_theme(self.content)

        self.current_key = None
        self.current_color = SIDEBAR_BG
        self.show_frame(self.nav_items[0][1], self.nav_items[0][2])

    def allowed_nav_items(self):
        usuario = str(self.user.get("usuario", "")).strip().lower()
        rol = str(self.user.get("rol", "")).strip().upper()
        branch = str(self.user.get("sucursal") or self.user.get("empresa") or "computer_army").strip().lower()
        permisos = getattr(self, "sucursal_permisos", {}) or {}
        def branch_items(items):
            out = []
            for item in items:
                key = item[1]
                if usuario == "giomar":
                    out.append(item)
                    continue
                if permisos.get(key, True):
                    out.append(item)
            return out
        if usuario == "giomar":
            return branch_items(NAV_ITEMS)
        if rol == "VENTAS":
            return branch_items([item for item in NAV_ITEMS if item[1] in VENTAS_NAV_KEYS])
        return branch_items(NAV_ITEMS)

    def load_branch_permissions(self, branch=None):
        branch = branch or str(self.user.get("sucursal") or self.user.get("empresa") or "computer_army")
        permisos = dict(DEFAULT_MODULE_PERMISSIONS)
        permisos["pagina_web"] = False
        try:
            fn = getattr(api_client, "obtener_permisos_sucursal", None) if api_client is not None else None
            if callable(fn):
                resp = fn(branch)
                data = api_response_get(resp, "permisos", {}) if api_response_ok(resp) else {}
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k in permisos:
                            permisos[k] = bool(v)
        except Exception:
            pass
        return permisos

    def can_access_frame(self, key):
        return key in {item[1] for item in getattr(self, "nav_items", NAV_ITEMS)}

    def global_search_focus_in(self, event=None):
        if self.global_search.get().strip() == "Buscar":
            self.global_search.delete(0, tk.END)

    def global_search_focus_out(self, event=None):
        if not self.global_search.get().strip():
            self.global_search.insert(0, "Buscar")

    def run_global_search(self, event=None):
        q = self.global_search.get().strip()
        if not q or q == "Buscar":
            return
        ql = q.lower()
        module_map = {
            "venta": ("ventas", "#059669"),
            "caja": ("caja", "#ca8a04"),
            "cliente": ("clientes", "#2563eb"),
            "producto": ("productos", "#ea580c"),
            "inventario": ("inventario", "#7c3aed"),
            "documento": ("contabilidad", "#b91c1c"),
            "usuario": ("usuarios", "#6b7280"),
            "registro": ("auditoria", "#9333ea"),
            "ajuste": ("ajustes", "#111827"),
        }
        for token, target in module_map.items():
            if token in ql and self.can_access_frame(target[0]):
                self.show_frame(*target)
                return
            if token in ql:
                messagebox.showwarning("Acceso denegado", "Tu cargo no tiene acceso a ese módulo.")
                return
        if not self.can_access_frame("productos"):
            messagebox.showwarning("Acceso denegado", "Tu cargo no tiene acceso a ese módulo.")
            return
        self.show_frame("productos", "#ea580c")
        try:
            self.product_search.delete(0, tk.END)
            self.product_search.insert(0, q)
            self.refresh_products()
        except Exception:
            pass

    def set_card(self, parent, padx=24, pady=18):
        card = tk.Frame(parent, bg=CARD_BG, bd=0, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="both", expand=True, padx=padx, pady=pady)
        return card

    def apply_dark_widget_theme(self, parent):
        light_bgs = {"#ffffff", "white", "#f8fafc", "#f6f8fb", "#f1f5f9", "#e2e8f0", "#e5e7eb"}
        dark_classes = {"Frame", "Labelframe", "LabelFrame", "Canvas"}
        text_classes = {"Label", "Checkbutton", "Radiobutton", "Labelframe", "LabelFrame"}
        for widget in parent.winfo_children():
            cls = widget.winfo_class()
            try:
                bg = str(widget.cget("background")).lower()
            except Exception:
                bg = ""
            if bg in light_bgs:
                try:
                    if cls in ("Entry", "Text", "Listbox", "Canvas"):
                        widget.configure(background=SOFT_BG)
                    elif cls == "Button":
                        widget.configure(background=SOFT_BG, activebackground=ACCENT_DARK)
                    elif cls in dark_classes or cls in text_classes:
                        widget.configure(background=CARD_BG)
                    else:
                        widget.configure(background=CARD_BG)
                except Exception:
                    pass
            if cls in text_classes:
                try:
                    fg = str(widget.cget("foreground")).lower()
                    if fg in ("", "black", "#000000", "systembuttontext") or bg in light_bgs:
                        widget.configure(foreground=TEXT)
                except Exception:
                    pass
            if cls in ("Entry", "Text", "Listbox"):
                try:
                    widget.configure(foreground=TEXT, insertbackground=TEXT)
                except Exception:
                    pass
            self.apply_dark_widget_theme(widget)

    def show_frame(self, key, color):
        play_click_sound()
        if not self.can_access_frame(key):
            messagebox.showwarning("Acceso denegado", "Tu cargo no tiene acceso a este módulo.")
            fallback = getattr(self, "nav_items", NAV_ITEMS)[0]
            key, color = fallback[1], fallback[2]
        if self.current_key:
            if self.current_key in self.nav_buttons:
                self.nav_buttons[self.current_key].config(bg=SIDEBAR_BG, fg=SIDEBAR_TEXT)
            self.frames[self.current_key].pack_forget()
        self.current_key = key
        self.current_color = color
        if key in self.nav_buttons:
            self.nav_buttons[key].config(bg=color, fg="white")
        self.frames[key].pack(fill="both", expand=True)
        if key == "dashboard":
            try:
                self.refresh_dashboard()
            except Exception:
                pass
        if key == "ventas":
            self.refresh_sale_products_cache()
        if key == "caja":
            try:
                self.refresh_cash()
            except Exception:
                pass

    def photo_value_to_image(self, value, size=(42, 42)):
        src = str(value or "").strip()
        if not src:
            return None
        try:
            if src.startswith(("http://", "https://")):
                with urllib.request.urlopen(src, timeout=8) as r:
                    img = Image.open(r).convert("RGB")
            elif src.startswith("data:image"):
                raw = src.split(",", 1)[1] if "," in src else ""
                img = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
            elif os.path.exists(src):
                img = Image.open(src).convert("RGB")
            else:
                return None
            img.thumbnail(size)
            canvas_img = Image.new("RGB", size, "#ffffff")
            canvas_img.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
            return ImageTk.PhotoImage(canvas_img)
        except Exception:
            return None

    def update_user_avatar_ui(self):
        if not hasattr(self, "avatar_lbl"):
            return
        photo = self.photo_value_to_image(self.user.get("foto_url", ""), size=(42, 42))
        if photo:
            self.user_avatar_photo = photo
            self.avatar_lbl.config(image=photo, text="", bg=TOPBAR_BG, width=42, height=42)
        else:
            self.user_avatar_photo = None
            avatar_text = str(self.user.get("usuario", "AD"))[:2].upper() or "AD"
            self.avatar_lbl.config(image="", text=avatar_text, bg="#0891b2", fg="white", width=3, height=1)

    def update_logo_ui(self):
        path = document_logo_path(self.cfg)
        if path and os.path.exists(path):
            try:
                img = Image.open(path)
                img.thumbnail((42, 42))
                self.logo_tk = ImageTk.PhotoImage(img)
                self.logo_lbl.config(image=self.logo_tk, text="", bg=SIDEBAR_BG)
                return
            except Exception:
                pass
        self.logo_lbl.config(image="", text="▣", fg="#14b8a6", font=("Arial", 22, "bold"), bg=SIDEBAR_BG)

    # DASHBOARD
    def build_dashboard(self):
        frame = self.frames["dashboard"]
        self.dashboard_canvas = tk.Canvas(frame, bg=APP_BG, highlightthickness=0)
        self.dashboard_canvas.pack(fill="both", expand=True)
        self.dashboard_canvas.bind("<Configure>", lambda e: self.draw_dashboard_static())
        self.dashboard_values = {}
        self.draw_dashboard_static()

    def dash_round(self, x1, y1, x2, y2, r=12, fill="#ffffff", outline="#e2e8f0", width=1):
        c = self.dashboard_canvas
        c.create_arc(x1, y1, x1 + r*2, y1 + r*2, start=90, extent=90, fill=fill, outline=outline, width=width)
        c.create_arc(x2 - r*2, y1, x2, y1 + r*2, start=0, extent=90, fill=fill, outline=outline, width=width)
        c.create_arc(x2 - r*2, y2 - r*2, x2, y2, start=270, extent=90, fill=fill, outline=outline, width=width)
        c.create_arc(x1, y2 - r*2, x1 + r*2, y2, start=180, extent=90, fill=fill, outline=outline, width=width)
        c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=outline, width=width)
        c.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=outline, width=width)

    def dash_text(self, x, y, text, size=10, fill=TEXT, bold=False, anchor="nw", tag=None):
        font = ("Arial", size, "bold") if bold else ("Arial", size)
        return self.dashboard_canvas.create_text(x, y, text=str(text), fill=fill, font=font, anchor=anchor, tags=tag)

    def draw_dashboard_static(self):
        c = self.dashboard_canvas
        c.delete("all")
        w = max(c.winfo_width(), 1180)
        x0, y0 = 28, 24

        branch_label = str(getattr(api_client, "EMPRESA", "") or self.user.get("sucursal") or "computer_army").replace("_", " ").title()
        self.dash_text(x0, y0, "Panel de Caja", 24, TEXT, True)
        self.dash_text(x0, y0 + 38, f"Sucursal activa: {branch_label} | Datos en vivo", 11, MUTED)
        self.dash_round(w - 250, y0 - 4, w - 28, y0 + 42, 10, CARD_BG, BORDER)
        try:
            from datetime import datetime
            today_label = datetime.now().strftime("%d/%m/%Y")
        except Exception:
            today_label = ""
        self.dash_text(w - 230, y0 + 11, today_label, 11, TEXT, True)

        stat_defs = [
            ("Ventas hoy", "Ventas", "#f59e0b", "$"),
            ("Docs venta", "Documentos", "#22d3ee", "D"),
            ("Productos", "Productos", "#10b981", "P"),
            ("Clientes", "Clientes", "#60a5fa", "C"),
            ("Caja cobrada", "Caja", "#fbbf24", "$"),
        ]
        gap = 14
        card_w = (w - 56 - gap * 4) / 5
        y = 98
        self.dashboard_values = {}
        for i, (title, key, color, icon) in enumerate(stat_defs):
            x = x0 + i * (card_w + gap)
            self.dash_round(x, y, x + card_w, y + 118, 12, CARD_BG, BORDER)
            c.create_oval(x + 18, y + 24, x + 62, y + 68, fill=color, outline=color)
            self.dash_text(x + 40, y + 36, icon, 15, "#ffffff", True, anchor="center")
            self.dash_text(x + 78, y + 24, title, 10, MUTED)
            self.dashboard_values[key] = self.dash_text(x + 78, y + 48, "0", 17, TEXT, True)
            self.dash_text(x + 18, y + 88, "Datos sincronizados con servidor", 9, SUCCESS, True)

        # Chart area
        y2 = 238
        left_w = int((w - 70) * 0.42)
        mid_w = int((w - 70) * 0.28)
        right_w = w - 56 - left_w - mid_w - 28
        self.dash_round(x0, y2, x0 + left_w, y2 + 350, 12, CARD_BG, BORDER)
        self.dash_text(x0 + 18, y2 + 18, "Ventas del mes", 14, TEXT, True)
        self.dashboard_values["chart_area"] = (x0 + 28, y2 + 64, left_w - 56, 210)
        self.draw_dashboard_chart_area(x0 + 28, y2 + 64, left_w - 56, 210, 0)
        self.dashboard_values["chart_total"] = self.dash_text(x0 + 18, y2 + 300, "Ventas del mes  S/ 0.00", 12, TEXT, True)

        # Critical products
        mx = x0 + left_w + 14
        self.dash_round(mx, y2, mx + mid_w, y2 + 350, 12, CARD_BG, BORDER)
        self.dash_text(mx + 16, y2 + 18, "Productos criticos", 14, TEXT, True)
        self.dashboard_values["critical_start"] = (mx + 16, y2 + 62)

        # Tasks
        rx = mx + mid_w + 14
        self.dash_round(rx, y2, rx + right_w, y2 + 350, 12, CARD_BG, BORDER)
        self.dash_text(rx + 16, y2 + 18, "Tareas pendientes", 14, TEXT, True)
        tasks = [
            ("Ordenes por confirmar", "0", "#dc2626"),
            ("Compras por recibir", "0", "#f97316"),
            ("Productos con stock bajo", "0", "#f97316"),
            ("Nuevos clientes", "0", "#2563eb"),
            ("Facturas por cobrar", "0", "#16a34a"),
        ]
        self.dashboard_task_tags = {}
        ty = y2 + 64
        for label, value, color in tasks:
            self.dash_round(rx + 16, ty - 8, rx + right_w - 16, ty + 42, 8, SOFT_BG, BORDER)
            self.dash_text(rx + 34, ty + 4, label, 10, TEXT, True)
            tag = f"task_{label}"
            self.dashboard_task_tags[label] = self.dash_text(rx + right_w - 38, ty + 5, value, 13, color, True, anchor="ne")
            ty += 58

        # Bottom tables
        by = y2 + 370
        self.dashboard_values["recent_area"] = (x0, by, left_w + mid_w + 14, 220)
        self.dash_round(x0, by, x0 + left_w + mid_w + 14, by + 220, 12, CARD_BG, BORDER)
        self.dash_text(x0 + 16, by + 18, "Transacciones recientes", 14, TEXT, True)
        headers = ["Tipo", "Folio", "Cliente", "Total", "Estado"]
        hx = [x0 + 18, x0 + 112, x0 + 225, x0 + 470, x0 + 590]
        for xx, h in zip(hx, headers):
            self.dash_text(xx, by + 56, h, 9, MUTED, True)
        sample = []
        sy = by + 86
        for row in sample:
            self.dashboard_canvas.create_line(x0 + 16, sy - 12, x0 + left_w + mid_w - 8, sy - 12, fill=BORDER)
            self.dash_text(hx[0], sy, row[0], 9, row[5], True)
            self.dash_text(hx[1], sy, row[1], 9, TEXT)
            self.dash_text(hx[2], sy, row[2], 9, TEXT)
            self.dash_text(hx[3], sy, row[3], 9, "#dc2626" if row[3].startswith("-") else TEXT, True)
            self.dash_text(hx[4], sy, row[4], 9, row[5], True)
            sy += 34

        self.dash_round(rx, by, rx + right_w, by + 220, 12, CARD_BG, BORDER)
        self.dashboard_values["payment_area"] = (rx, by, right_w, 220)
        self.dash_text(rx + 16, by + 18, "Resumen de metodos de pago", 14, TEXT, True)
        methods = []
        my = by + 62
        for name, pct, color in methods:
            self.dash_text(rx + 18, my, name, 10, TEXT, True)
            self.dashboard_canvas.create_rectangle(rx + 140, my + 5, rx + right_w - 82, my + 11, fill="#e5e7eb", outline="#e5e7eb")
            self.dashboard_canvas.create_rectangle(rx + 140, my + 5, rx + 140 + int((right_w - 222) * pct / 100), my + 11, fill=color, outline=color)
            self.dash_text(rx + right_w - 22, my, f"{pct}%", 10, TEXT, True, anchor="ne")
            my += 36

    def draw_dashboard_chart_area(self, x, y, w, h, total_ventas):
        c = self.dashboard_canvas
        for i in range(5):
            yy = y + i * (h / 4)
            c.create_line(x, yy, x + w, yy, fill=BORDER)
        base = float(total_ventas or 1000)
        vals = [base * f for f in [0.18, 0.35, 0.31, 0.42, 0.61, 0.45, 0.56, 0.78, 0.52, 0.69, 0.81, 0.64, 0.88]]
        maxv = max(vals) or 1
        pts = []
        for i, v in enumerate(vals):
            xx = x + w * (i / max(1, len(vals) - 1))
            yy = y + h - (h * (v / maxv))
            pts.append((xx, yy))
        flat = []
        for p in pts:
            flat.extend(p)
        if len(flat) >= 4:
            c.create_line(*flat, fill=ACCENT, width=3, smooth=True)
        for xx, yy in pts:
            c.create_oval(xx - 3, yy - 3, xx + 3, yy + 3, fill=ACCENT, outline="white", width=2)

    def draw_product_thumbnail(self, x, y, product):
        c = self.dashboard_canvas
        name = f'{product.get("nombre", "")} {product.get("categoria", "")} {product.get("marca", "")} {product.get("modelo", "")}'.upper()
        c.create_rectangle(x, y, x + 54, y + 38, fill=SOFT_BG, outline=BORDER, width=1, tags="critical_item")
        if "RAM" in name or "MEMORIA" in name:
            c.create_rectangle(x + 7, y + 14, x + 47, y + 24, fill="#1f2937", outline="#111827", tags="critical_item")
            for i in range(5):
                c.create_rectangle(x + 10 + i * 7, y + 16, x + 14 + i * 7, y + 22, fill="#22c55e", outline="#16a34a", tags="critical_item")
        elif "SSD" in name or "DISCO" in name or "NVME" in name:
            c.create_rectangle(x + 12, y + 9, x + 42, y + 29, fill="#111827", outline="#0f172a", tags="critical_item")
            c.create_text(x + 27, y + 19, text="SSD", fill="#e5e7eb", font=("Arial", 7, "bold"), tags="critical_item")
        elif "MONITOR" in name or "LED" in name:
            c.create_rectangle(x + 8, y + 6, x + 46, y + 26, fill="#0f172a", outline="#334155", tags="critical_item")
            c.create_rectangle(x + 23, y + 27, x + 31, y + 32, fill="#334155", outline="#334155", tags="critical_item")
            c.create_rectangle(x + 16, y + 33, x + 38, y + 35, fill="#334155", outline="#334155", tags="critical_item")
        elif "TECLADO" in name:
            c.create_rectangle(x + 6, y + 12, x + 48, y + 28, fill="#111827", outline="#0f172a", tags="critical_item")
            for row in range(2):
                for col in range(8):
                    c.create_rectangle(x + 9 + col * 5, y + 15 + row * 5, x + 11 + col * 5, y + 17 + row * 5, fill="#ef4444" if (row + col) % 3 == 0 else "#64748b", outline="", tags="critical_item")
        elif "MOUSE" in name:
            c.create_oval(x + 18, y + 6, x + 38, y + 32, fill="#111827", outline="#0f172a", tags="critical_item")
            c.create_line(x + 28, y + 8, x + 28, y + 17, fill="#64748b", tags="critical_item")
        else:
            c.create_rectangle(x + 10, y + 8, x + 44, y + 30, fill="#0f969c", outline="#0f766e", tags="critical_item")
            c.create_text(x + 27, y + 19, text="PC", fill="white", font=("Arial", 8, "bold"), tags="critical_item")

    def refresh_dashboard(self):
        d = dashboard() or {}
        if not isinstance(d, dict) or d.get("ok") is False:
            self.dashboard_canvas.delete("dashboard_live")
            self.dashboard_canvas.create_text(
                28, 72,
                text="Panel sin conexion al servidor. Se reintentara al actualizar.",
                fill=WARNING,
                font=("Arial", 11, "bold"),
                anchor="nw",
                tags="dashboard_live"
            )
            return
        total_ventas = float(d.get("total_ventas_hoy", d.get("total_ventas", 0)) or 0)
        total_ventas_mes = float(d.get("total_ventas_mes", total_ventas) or 0)
        self.dashboard_canvas.delete("dashboard_live")
        self.dashboard_live_images = []
        vals = {
            "Clientes": str(d.get("clientes", 0)),
            "Productos": str(d.get("productos", 0)),
            "Documentos": str(d.get("documentos", 0)),
            "Ventas": money(total_ventas),
            "Caja": money(d.get("saldo_caja", 0)),
            "chart_total": f"Ventas del mes  {money(total_ventas_mes)}",
        }
        for key, value in vals.items():
            item = self.dashboard_values.get(key)
            if item:
                self.dashboard_canvas.itemconfigure(item, text=value)

        for item in self.dashboard_canvas.find_withtag("critical_item"):
            self.dashboard_canvas.delete(item)
        start = self.dashboard_values.get("critical_start")
        bajos = []
        try:
            bajos = d.get("productos_bajos") or [p for p in obtener_productos() if int(p.get("stock", 0) or 0) <= 5][:5]
        except Exception:
            bajos = []
        if start:
            x, y = start
            if not bajos:
                try:
                    bajos = (obtener_productos() or [])[:5]
                except Exception:
                    bajos = []
            if not bajos:
                self.dashboard_canvas.create_text(x, y, text="Sin productos para mostrar", fill=MUTED, font=("Arial", 10), anchor="nw", tags="critical_item")
            for p in bajos:
                if str(p.get("imagen_url", "") or "").strip():
                    img = self.product_image_for_ui(p, size=(54, 38))
                    self.dashboard_live_images.append(img)
                    self.dashboard_canvas.create_image(x + 27, y + 13, image=img, tags="critical_item")
                else:
                    self.draw_product_thumbnail(x, y - 6, p)
                self.dashboard_canvas.create_text(x + 66, y, text=str(p.get("nombre", ""))[:30], fill=TEXT, font=("Arial", 10, "bold"), anchor="nw", tags="critical_item")
                stock = int(p.get("stock", 0) or 0)
                stock_color = "#dc2626" if stock <= 5 else "#16a34a"
                self.dashboard_canvas.create_text(x + 66, y + 18, text=f"Stock: {stock}", fill=stock_color, font=("Arial", 9, "bold"), anchor="nw", tags="critical_item")
                estado = "Critico" if int(p.get("stock", 0) or 0) <= 2 else "Bajo"
                if stock > 5:
                    estado = "Activo"
                badge_color = "#fee2e2" if estado == "Critico" else "#dcfce7" if estado == "Activo" else "#ffedd5"
                txt_color = "#dc2626" if estado == "Critico" else "#16a34a" if estado == "Activo" else "#ea580c"
                self.dashboard_canvas.create_rectangle(x + 230, y - 1, x + 292, y + 21, fill=badge_color, outline=badge_color, tags="critical_item")
                self.dashboard_canvas.create_text(x + 261, y + 10, text=estado, fill=txt_color, font=("Arial", 8, "bold"), anchor="center", tags="critical_item")
                y += 58
        tag = self.dashboard_task_tags.get("Productos con stock bajo") if hasattr(self, "dashboard_task_tags") else None
        if tag:
            self.dashboard_canvas.itemconfigure(tag, text=str(d.get("stock_bajo", len(bajos))))
        tag = self.dashboard_task_tags.get("Ordenes por confirmar") if hasattr(self, "dashboard_task_tags") else None
        if tag:
            self.dashboard_canvas.itemconfigure(tag, text=str(d.get("documentos_pendientes", d.get("documentos", 0))))
        tag = self.dashboard_task_tags.get("Compras por recibir") if hasattr(self, "dashboard_task_tags") else None
        if tag:
            self.dashboard_canvas.itemconfigure(tag, text=str(d.get("compras_pendientes", d.get("compras", 0))))
        tag = self.dashboard_task_tags.get("Nuevos clientes") if hasattr(self, "dashboard_task_tags") else None
        if tag:
            self.dashboard_canvas.itemconfigure(tag, text=str(d.get("clientes_hoy", 0)))
        tag = self.dashboard_task_tags.get("Facturas por cobrar") if hasattr(self, "dashboard_task_tags") else None
        if tag:
            self.dashboard_canvas.itemconfigure(tag, text=str(d.get("facturas_cobrar", 0)))

        self.draw_dashboard_live_chart(d.get("ventas_por_dia") or [], total_ventas)
        self.draw_dashboard_recent(d.get("recientes") or [])
        self.draw_dashboard_payments(d.get("metodos_pago") or [])

    def draw_dashboard_live_chart(self, ventas_por_dia, total_ventas):
        area = self.dashboard_values.get("chart_area")
        if not area:
            return
        x, y, w, h = area
        c = self.dashboard_canvas
        c.create_rectangle(x - 4, y - 4, x + w + 4, y + h + 8, fill=CARD_BG, outline=CARD_BG, tags="dashboard_live")
        for i in range(5):
            yy = y + i * (h / 4)
            c.create_line(x, yy, x + w, yy, fill=BORDER, tags="dashboard_live")
        vals = [float(v.get("total", 0) or 0) for v in ventas_por_dia][-13:]
        if not vals:
            vals = [float(total_ventas or 0)]
        if len(vals) == 1:
            vals = [0, vals[0]]
        maxv = max(vals) or 1
        pts = []
        for i, v in enumerate(vals):
            xx = x + w * (i / max(1, len(vals) - 1))
            yy = y + h - (h * (v / maxv))
            pts.append((xx, yy))
        flat = []
        for p in pts:
            flat.extend(p)
        c.create_line(*flat, fill="#0f969c", width=3, smooth=True, tags="dashboard_live")
        for xx, yy in pts:
            c.create_oval(xx - 3, yy - 3, xx + 3, yy + 3, fill="#0f969c", outline="white", width=2, tags="dashboard_live")

    def draw_dashboard_recent(self, recientes):
        area = self.dashboard_values.get("recent_area")
        if not area:
            return
        x, y, w, h = area
        c = self.dashboard_canvas
        c.create_rectangle(x + 8, y + 48, x + w - 8, y + h - 10, fill=CARD_BG, outline=CARD_BG, tags="dashboard_live")
        headers = ["Tipo", "Folio", "Cliente", "Total", "Estado"]
        hx = [x + 18, x + 112, x + 225, x + 470, x + 590]
        for xx, head in zip(hx, headers):
            self.dash_text(xx, y + 56, head, 9, MUTED, True, tag="dashboard_live")
        sy = y + 86
        for r in recientes[:4]:
            estado = str(r.get("estado_pago", "") or "").upper()
            color = "#16a34a" if estado == "PAGADO" else "#f97316" if estado == "CREDITO" else "#dc2626"
            c.create_line(x + 16, sy - 12, x + w - 20, sy - 12, fill=BORDER, tags="dashboard_live")
            self.dash_text(hx[0], sy, r.get("tipo", ""), 9, color, True, tag="dashboard_live")
            self.dash_text(hx[1], sy, r.get("numero", ""), 9, TEXT, tag="dashboard_live")
            self.dash_text(hx[2], sy, str(r.get("cliente", ""))[:28], 9, TEXT, tag="dashboard_live")
            self.dash_text(hx[3], sy, money(r.get("total", 0)), 9, TEXT, True, tag="dashboard_live")
            self.dash_text(hx[4], sy, estado or "EMITIDO", 9, color, True, tag="dashboard_live")
            sy += 34
        if not recientes:
            self.dash_text(x + 18, y + 96, "Sin documentos recientes en el servidor.", 10, MUTED, True, tag="dashboard_live")

    def draw_dashboard_payments(self, metodos):
        area = self.dashboard_values.get("payment_area")
        if not area:
            return
        x, y, w, h = area
        c = self.dashboard_canvas
        c.create_rectangle(x + 8, y + 48, x + w - 8, y + h - 10, fill=CARD_BG, outline=CARD_BG, tags="dashboard_live")
        total = sum(float(m.get("total", 0) or 0) for m in metodos) or 1
        colors = ["#16a34a", "#2563eb", "#0f969c", "#7c3aed", "#f97316"]
        my = y + 62
        for idx, m in enumerate(metodos[:5]):
            pct = int((float(m.get("total", 0) or 0) / total) * 100)
            color = colors[idx % len(colors)]
            self.dash_text(x + 18, my, str(m.get("metodo", ""))[:18], 10, TEXT, True, tag="dashboard_live")
            c.create_rectangle(x + 140, my + 5, x + w - 82, my + 11, fill=BORDER, outline=BORDER, tags="dashboard_live")
            c.create_rectangle(x + 140, my + 5, x + 140 + int((w - 222) * pct / 100), my + 11, fill=color, outline=color, tags="dashboard_live")
            self.dash_text(x + w - 22, my, f"{pct}%", 10, TEXT, True, anchor="ne", tag="dashboard_live")
            my += 36
        if not metodos:
            self.dash_text(x + 18, y + 96, "Sin pagos registrados en el servidor.", 10, MUTED, True, tag="dashboard_live")
    # VENTAS
    def build_ventas(self):
        frame = self.frames["ventas"]
        card = self.set_card(frame, padx=0, pady=0)
        card.configure(bg="#f6f8fb")

        header = tk.Frame(card, bg="#ffffff", highlightthickness=1, highlightbackground="#e2e8f0")
        header.pack(fill="x")
        tk.Label(header, text="🛒", bg="#ffffff", fg="#0f766e", font=("Arial", 19, "bold")).pack(side="left", padx=(22, 8))
        tk.Label(header, text="Nueva venta", bg="#ffffff", fg=TEXT, font=("Arial", 19, "bold")).pack(side="left")
        tools = tk.Frame(header, bg="#ffffff")
        tools.pack(fill="x", padx=18, pady=(2, 8))
        tk.Label(tools, text="Documento", bg="#ffffff", fg=MUTED, font=("Arial", 8)).grid(row=0, column=0, sticky="w")
        self.v_doc_tipo = ttk.Combobox(tools, values=["PROFORMA", "PASE", "NOTA DE VENTA", "BOLETA", "FACTURA"], state="readonly", width=15)
        self.v_doc_tipo.grid(row=1, column=0, padx=(0, 8))
        self.v_doc_tipo.set("PROFORMA")
        self.v_doc_tipo.bind("<<ComboboxSelected>>", self.on_sale_doc_type_changed)
        self.lbl_next = tk.Label(tools, text="", bg="#ffffff", fg=ACCENT, font=("Arial", 9, "bold"))
        self.lbl_next.grid(row=1, column=1, padx=(0, 12))
        tool_row = 2 if getattr(self, "compact_layout", False) else 1
        tool_col = 0 if getattr(self, "compact_layout", False) else 2
        tk.Button(tools, text="Vista PDF", command=self.preview_pdf_sale, bg="#f8fafc", fg=TEXT, relief="flat", padx=12, pady=8).grid(row=tool_row, column=tool_col, padx=4, pady=(4, 0))
        tk.Button(tools, text="Imprimir", command=self.print_preview_sale, bg="#f8fafc", fg=TEXT, relief="flat", padx=12, pady=8).grid(row=tool_row, column=tool_col + 1, padx=4, pady=(4, 0))
        tk.Button(tools, text="Limpiar", command=self.clear_sale_form, bg="#f8fafc", fg=TEXT, relief="flat", padx=12, pady=8).grid(row=tool_row, column=tool_col + 2, padx=4, pady=(4, 0))
        self.lbl_sale_edit_mode = tk.Label(tools, text="", bg="#ffffff", fg="#b45309", font=("Arial", 9, "bold"))
        self.lbl_sale_edit_mode.grid(row=tool_row, column=tool_col + 3, padx=(8, 0), pady=(4, 0))

        self.sale_tabs_bar = tk.Frame(card, bg="#eef2f7", height=42)
        self.sale_tabs_bar.pack(fill="x")

        body = tk.Frame(card, bg="#f6f8fb")
        body.pack(fill="both", expand=True, padx=12, pady=10)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0)
        body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(body, bg="#f6f8fb")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(3, weight=1)

        search_bar = tk.Frame(left, bg="#f6f8fb")
        search_bar.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        search_bar.grid_columnconfigure(0, weight=1)
        self.v_search = tk.Entry(search_bar, font=("Arial", 14), relief="solid", bd=1)
        self.v_search.grid(row=0, column=0, sticky="ew", ipady=7)
        self.v_search.insert(0, "")
        self.v_search.bind("<KeyRelease>", self.search_products_sale)
        self.v_search.bind("<Return>", lambda e: self.add_sale_item())
        tk.Button(search_bar, text="Recargar", command=lambda: self.refresh_sale_products_cache(force=True), bg="#ffffff", fg=TEXT, relief="solid", bd=1, padx=14, pady=7).grid(row=0, column=1, padx=(10, 0))

        self.sale_category = "Todos"
        self.sale_category_buttons = {}
        self.sale_categories_frame = tk.Frame(left, bg="#f6f8fb")
        self.sale_categories_frame.grid(row=1, column=0, sticky="ew", pady=(0, 7))

        edit_bar = tk.Frame(left, bg="#ffffff", highlightthickness=1, highlightbackground="#e2e8f0")
        edit_bar.grid(row=2, column=0, sticky="ew", pady=(0, 7))
        for col in range(6):
            edit_bar.grid_columnconfigure(col, weight=1 if col in (0, 1) else 0)
        tk.Label(edit_bar, text="Nombre en documento", bg="#ffffff", fg=MUTED).grid(row=0, column=0, padx=10, pady=(8, 2), sticky="w")
        self.v_item_name = tk.Entry(edit_bar, relief="solid", bd=1)
        self.v_item_name.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.v_item_brand = tk.Entry(edit_bar, width=14, relief="solid", bd=1)
        self.v_item_model = tk.Entry(edit_bar, width=14, relief="solid", bd=1)
        tk.Label(edit_bar, text="Serie", bg="#ffffff", fg=MUTED).grid(row=0, column=1, padx=6, pady=(8, 2), sticky="w")
        self.v_series = tk.Entry(edit_bar, relief="solid", bd=1)
        self.v_series.grid(row=1, column=1, padx=6, pady=(0, 10), sticky="ew")
        tk.Button(edit_bar, text="Series", command=self.open_sale_series_picker, bg="#eef2ff", fg="#3730a3", relief="flat", padx=10, pady=7).grid(row=1, column=5, padx=(0, 10), pady=(0, 10))
        tk.Label(edit_bar, text="Cant.", bg="#ffffff", fg=MUTED).grid(row=0, column=2, padx=6, pady=(8, 2), sticky="w")
        self.v_qty = tk.Entry(edit_bar, width=6, relief="solid", bd=1, justify="center")
        self.v_qty.grid(row=1, column=2, padx=6, pady=(0, 10))
        self.v_qty.insert(0, "1")
        self.v_qty.bind("<Return>", lambda e: self.add_sale_item())
        tk.Label(edit_bar, text="Precio", bg="#ffffff", fg=MUTED).grid(row=0, column=3, padx=6, pady=(8, 2), sticky="w")
        self.v_price = tk.Entry(edit_bar, width=10, relief="solid", bd=1, justify="right")
        self.v_price.grid(row=1, column=3, padx=6, pady=(0, 10))
        tk.Button(edit_bar, text="+ Agregar", command=self.add_sale_item, bg="#0f766e", fg="white", relief="flat", padx=14, pady=7).grid(row=1, column=4, padx=10, pady=(0, 10))

        product_shell = tk.Frame(left, bg="#ffffff", highlightthickness=1, highlightbackground="#e2e8f0")
        product_shell.grid(row=3, column=0, sticky="nsew")
        product_shell.grid_columnconfigure(0, weight=1)
        product_shell.grid_rowconfigure(0, weight=1)
        self.sale_canvas = tk.Canvas(product_shell, bg="#ffffff", highlightthickness=0)
        self.sale_canvas.grid(row=0, column=0, sticky="nsew")
        product_scroll = ttk.Scrollbar(product_shell, orient="vertical", command=self.sale_canvas.yview)
        product_scroll.grid(row=0, column=1, sticky="ns")
        self.sale_canvas.configure(yscrollcommand=product_scroll.set)
        self.sale_cards = tk.Frame(self.sale_canvas, bg="#ffffff")
        self.sale_cards_window = self.sale_canvas.create_window((0, 0), window=self.sale_cards, anchor="nw")
        self.sale_cards.bind("<Configure>", lambda e: self.sale_canvas.configure(scrollregion=self.sale_canvas.bbox("all")))
        self.sale_canvas.bind("<Configure>", lambda e: self.sale_canvas.itemconfigure(self.sale_cards_window, width=e.width))

        right = tk.Frame(body, bg="#ffffff", width=getattr(self, "sale_panel_width", 410), highlightthickness=1, highlightbackground="#e2e8f0")
        right.grid(row=0, column=1, sticky="ns")
        right.grid_propagate(False)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        cart_head = tk.Frame(right, bg="#ffffff")
        cart_head.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 5))
        tk.Label(cart_head, text="Carrito", bg="#ffffff", fg=TEXT, font=("Arial", 17, "bold")).pack(side="left")
        self.lbl_cart_count = tk.Label(cart_head, text="0", bg="#dc2626", fg="white", font=("Arial", 9, "bold"), padx=7, pady=2)
        self.lbl_cart_count.pack(side="left", padx=8)
        tk.Button(cart_head, text="Vaciar", command=self.clear_sale_form, bg="#ffffff", fg="#dc2626", relief="flat").pack(side="right")

        client = tk.LabelFrame(right, text="Cliente", bg="#ffffff", fg=TEXT, padx=10, pady=8)
        client.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        self.v_tipo_doc = ttk.Combobox(client, values=["DNI", "RUC"], state="readonly", width=7)
        self.v_tipo_doc.grid(row=0, column=0, padx=(0, 6), pady=4)
        self.v_tipo_doc.set("DNI")
        self.v_num = tk.Entry(client, width=18, relief="solid", bd=1)
        self.v_num.grid(row=0, column=1, padx=4, pady=4)
        self.v_num.bind("<KeyRelease>", self.on_sale_doc_keyrelease)
        tk.Button(client, text="Buscar", command=self.search_client_sale, bg="#0f766e", fg="white", relief="flat").grid(row=0, column=2, padx=4, pady=4)
        tk.Button(client, text="DNI", command=self.consultar_dni_venta, bg="#eef2ff", fg="#3730a3", relief="flat").grid(row=1, column=0, padx=(0, 6), pady=4)
        tk.Button(client, text="RUC", command=self.consultar_ruc_venta, bg="#f3e8ff", fg="#6d28d9", relief="flat").grid(row=1, column=1, sticky="w", padx=4, pady=4)
        tk.Button(client, text="Guardar cliente", command=self.save_sale_client_ui, bg="#0891b2", fg="white", relief="flat").grid(row=1, column=2, padx=4, pady=4)
        self.v_nom = tk.Entry(client, relief="solid", bd=1)
        self.v_nom.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        self.v_dir = tk.Entry(client, relief="solid", bd=1)
        self.v_dir.grid(row=3, column=0, columnspan=3, sticky="ew", pady=4)
        client.grid_columnconfigure(2, weight=1)

        cart_container = tk.Frame(right, bg="#ffffff")
        cart_container.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 6))
        cart_container.grid_columnconfigure(0, weight=1)
        cart_container.grid_rowconfigure(0, weight=1)
        self.cart_canvas = tk.Canvas(cart_container, bg="#ffffff", highlightthickness=0)
        self.cart_canvas.grid(row=0, column=0, sticky="nsew")
        cart_scroll = ttk.Scrollbar(cart_container, orient="vertical", command=self.cart_canvas.yview)
        cart_scroll.grid(row=0, column=1, sticky="ns")
        self.cart_canvas.configure(yscrollcommand=cart_scroll.set)
        self.cart_items_frame = tk.Frame(self.cart_canvas, bg="#ffffff")
        self.cart_window = self.cart_canvas.create_window((0, 0), window=self.cart_items_frame, anchor="nw")
        self.cart_items_frame.bind("<Configure>", lambda e: self.cart_canvas.configure(scrollregion=self.cart_canvas.bbox("all")))
        self.cart_canvas.bind("<Configure>", lambda e: self.cart_canvas.itemconfigure(self.cart_window, width=e.width))

        totals = tk.Frame(right, bg="#ffffff")
        totals.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 4))
        self.lbl_sub = tk.Label(totals, text="Subtotal: S/ 0.00", bg="#ffffff", fg=TEXT, font=("Arial", 10))
        self.lbl_sub.pack(anchor="e", pady=1)
        self.lbl_igv = tk.Label(totals, text="IGV: DESACTIVADO", bg="#ffffff", fg=MUTED, font=("Arial", 10))
        self.lbl_igv.pack(anchor="e", pady=1)
        desc_row = tk.Frame(totals, bg="#ffffff")
        desc_row.pack(fill="x", pady=2)
        tk.Label(desc_row, text="Descuento", bg="#ffffff", fg=TEXT).pack(side="left")
        self.v_desc = tk.Entry(desc_row, width=10, relief="solid", bd=1, justify="right")
        self.v_desc.pack(side="right")
        self.v_desc.insert(0, "0")
        self.v_desc.bind("<KeyRelease>", lambda e: self.refresh_sale_table())
        self.lbl_tot = tk.Label(totals, text="Total: S/ 0.00", bg="#ffffff", fg="#0f766e", font=("Arial", 18, "bold"))
        self.lbl_tot.pack(anchor="e", pady=(2, 0))

        pay = tk.Frame(right, bg="#ffffff")
        pay.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 10))
        self.v_estado_pago = tk.StringVar(value="DEUDA")
        self.v_metodo_pago = tk.StringVar(value="")
        tk.Label(
            pay,
            text="La venta se enviara a Caja como pendiente. El cobro, metodo de pago e impresion se hacen desde Caja.",
            bg="#ffffff", fg=MUTED, wraplength=330, justify="left"
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        tk.Label(pay, text="Obs.", bg="#ffffff", fg=MUTED).grid(row=1, column=0, sticky="w")
        self.v_obs = tk.Entry(pay, relief="solid", bd=1)
        self.v_obs.grid(row=1, column=1, sticky="ew", pady=2)
        for sale_field in (self.v_num, self.v_nom, self.v_dir, self.v_obs, self.v_desc):
            sale_field.bind("<KeyRelease>", lambda e: self.save_current_sale_draft(), add="+")
        pay.grid_columnconfigure(1, weight=1)
        self.btn_issue_sale = tk.Button(pay, text="Enviar a caja", command=self.issue_sale, bg="#0f766e", fg="white", relief="flat", font=("Arial", 14, "bold"), pady=9)
        self.btn_issue_sale.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 6))

        self.sale_list = tk.Listbox(card, height=1)
        self.sale_list.bind("<ButtonRelease-1>", self.pick_product_sale)
        self.sale_list.bind("<Double-Button-1>", lambda e: self.add_sale_item())
        self.sale_list.bind("<Return>", lambda e: self.add_sale_item())

        cols = ("ID", "Producto", "Serie", "Cantidad", "Precio", "Total")
        self.tree_sale = ttk.Treeview(card, columns=cols, show="headings", height=10)
        widths = [60, 420, 170, 80, 90, 95]
        for c, w in zip(cols, widths):
            self.tree_sale.heading(c, text=c)
            self.tree_sale.column(c, width=w, anchor="center")
        self.tree_sale.bind("<Double-1>", self.edit_sale_item)
        self.tree_sale.bind("<Delete>", lambda e: self.remove_sale_item())
        self.render_sale_categories()
        self.init_sale_drafts()

    def update_next_doc(self):
        raw = siguiente_numero(self.v_doc_tipo.get())
        number = build_doc_number(self.v_doc_tipo.get(), raw, self.cfg)
        try:
            active_idx = next((i for i, d in enumerate(self.sale_drafts) if d.get("id") == self.active_sale_draft_id), 0)
        except Exception:
            active_idx = 0
        self.lbl_next.config(text=offset_doc_number(number, active_idx))

    def init_sale_drafts(self):
        if self.sale_drafts:
            return
        draft = self.create_sale_draft_state()
        self.sale_drafts = [draft]
        self.active_sale_draft_id = draft["id"]
        self.render_sale_tabs()

    def create_sale_draft_state(self):
        stamp = int(time.time() * 1000)
        return {
            "id": f"venta_{stamp}_{len(getattr(self, 'sale_drafts', [])) + 1}",
            "title": f"Venta {len(getattr(self, 'sale_drafts', [])) + 1}",
            "doc_tipo": "PROFORMA",
            "items": [],
            "cliente_tipo": "DNI",
            "cliente_num": "",
            "cliente_nom": "",
            "cliente_dir": "",
            "desc": "0",
            "obs": "",
            "editing_proforma_id": None,
            "editing_proforma_numero": "",
        }

    def active_sale_draft(self):
        for draft in self.sale_drafts:
            if draft.get("id") == self.active_sale_draft_id:
                return draft
        return None

    def sale_draft_title(self, draft):
        if draft.get("editing_proforma_numero"):
            return str(draft.get("editing_proforma_numero"))[:18]
        cliente = str(draft.get("cliente_nom") or "").strip()
        if cliente:
            return cliente[:18]
        count = len(draft.get("items") or [])
        base = str(draft.get("title") or "Venta")
        return f"{base} ({count})" if count else base

    def save_current_sale_draft(self):
        if getattr(self, "_loading_sale_draft", False) or not getattr(self, "active_sale_draft_id", None):
            return
        draft = self.active_sale_draft()
        if not draft or not hasattr(self, "v_doc_tipo"):
            return
        draft.update({
            "doc_tipo": self.v_doc_tipo.get(),
            "items": [dict(x) for x in self.items_venta],
            "cliente_tipo": self.v_tipo_doc.get() if hasattr(self, "v_tipo_doc") else "DNI",
            "cliente_num": self.v_num.get().strip() if hasattr(self, "v_num") else "",
            "cliente_nom": self.v_nom.get().strip() if hasattr(self, "v_nom") else "",
            "cliente_dir": self.v_dir.get().strip() if hasattr(self, "v_dir") else "",
            "desc": self.v_desc.get().strip() if hasattr(self, "v_desc") else "0",
            "obs": self.v_obs.get().strip() if hasattr(self, "v_obs") else "",
            "editing_proforma_id": getattr(self, "editing_proforma_id", None),
            "editing_proforma_numero": getattr(self, "editing_proforma_numero", ""),
        })
        self.render_sale_tabs()

    def load_sale_draft(self, draft_id):
        if draft_id == self.active_sale_draft_id:
            return
        self.save_current_sale_draft()
        draft = next((d for d in self.sale_drafts if d.get("id") == draft_id), None)
        if not draft:
            return
        self.active_sale_draft_id = draft_id
        self.apply_sale_draft_state(draft)
        self.render_sale_tabs()

    def apply_sale_draft_state(self, draft):
        self._loading_sale_draft = True
        try:
            self.items_venta = [dict(x) for x in draft.get("items", [])]
            self.editing_proforma_id = draft.get("editing_proforma_id")
            self.editing_proforma_numero = draft.get("editing_proforma_numero", "")
            self.v_doc_tipo.set(draft.get("doc_tipo") or "PROFORMA")
            self.update_next_doc()
            self.v_tipo_doc.set(draft.get("cliente_tipo") or "DNI")
            for widget, value in (
                (self.v_num, draft.get("cliente_num", "")),
                (self.v_nom, draft.get("cliente_nom", "")),
                (self.v_dir, draft.get("cliente_dir", "")),
                (self.v_desc, draft.get("desc", "0")),
                (self.v_obs, draft.get("obs", "")),
            ):
                widget.delete(0, tk.END)
                widget.insert(0, str(value or ""))
            for widget in (self.v_search, self.v_price, self.v_item_name, self.v_item_brand, self.v_item_model, self.v_series):
                widget.delete(0, tk.END)
            self.v_qty.delete(0, tk.END)
            self.v_qty.insert(0, "1")
            self.sale_list.delete(0, tk.END)
            self.selected_sale_product_index = None
            self.refresh_sale_table()
            self.update_sale_edit_state_ui()
            self.render_sale_product_cards()
        finally:
            self._loading_sale_draft = False

    def add_sale_draft(self):
        self.save_current_sale_draft()
        draft = self.create_sale_draft_state()
        self.sale_drafts.append(draft)
        self.active_sale_draft_id = draft["id"]
        self.apply_sale_draft_state(draft)
        self.render_sale_tabs()

    def close_sale_draft(self, draft_id):
        if len(self.sale_drafts) <= 1:
            self.clear_sale_form()
            return
        idx = next((i for i, d in enumerate(self.sale_drafts) if d.get("id") == draft_id), -1)
        if idx < 0:
            return
        draft = self.sale_drafts[idx]
        if draft_id == self.active_sale_draft_id:
            self.save_current_sale_draft()
            draft = self.sale_drafts[idx]
        has_data = bool(draft.get("items") or draft.get("cliente_nom") or draft.get("cliente_num") or draft.get("obs"))
        if has_data and not messagebox.askyesno("Cerrar pestaña", "Esta venta tiene datos. ¿Cerrar esta pestaña?"):
            return
        self.sale_drafts.pop(idx)
        if draft_id == self.active_sale_draft_id:
            next_idx = min(idx, len(self.sale_drafts) - 1)
            self.active_sale_draft_id = self.sale_drafts[next_idx]["id"]
            self.apply_sale_draft_state(self.sale_drafts[next_idx])
        self.render_sale_tabs()

    def render_sale_tabs(self):
        if not hasattr(self, "sale_tabs_bar"):
            return
        for child in self.sale_tabs_bar.winfo_children():
            child.destroy()
        for draft in self.sale_drafts:
            active = draft.get("id") == self.active_sale_draft_id
            tab = tk.Frame(self.sale_tabs_bar, bg="#ffffff" if active else "#e2e8f0", highlightthickness=1, highlightbackground="#cbd5e1")
            tab.pack(side="left", padx=(8, 0), pady=6)
            tk.Button(
                tab,
                text=self.sale_draft_title(draft),
                command=lambda did=draft.get("id"): self.load_sale_draft(did),
                bg="#ffffff" if active else "#e2e8f0",
                fg=ACCENT if active else TEXT,
                relief="flat",
                padx=10,
                pady=5,
                font=("Arial", 9, "bold" if active else "normal"),
            ).pack(side="left")
            tk.Button(
                tab,
                text="x",
                command=lambda did=draft.get("id"): self.close_sale_draft(did),
                bg="#ffffff" if active else "#e2e8f0",
                fg="#dc2626",
                relief="flat",
                padx=5,
                pady=5,
            ).pack(side="left")
        tk.Button(self.sale_tabs_bar, text="+", command=self.add_sale_draft, bg=ACCENT, fg="white", relief="flat", padx=13, pady=5, font=("Arial", 11, "bold")).pack(side="left", padx=8, pady=6)

    def update_sale_edit_state_ui(self):
        editing = bool(getattr(self, "editing_proforma_id", None))
        if hasattr(self, "btn_issue_sale"):
            self.btn_issue_sale.config(text="Guardar cambios de proforma" if editing else "Enviar a caja")
        if hasattr(self, "lbl_sale_edit_mode"):
            self.lbl_sale_edit_mode.config(text=f"Editando {self.editing_proforma_numero}" if editing else "")

    def on_sale_doc_type_changed(self, event=None):
        self.update_next_doc()
        self.apply_proforma_defaults()
        self.save_current_sale_draft()

    def auto_sale_doc_type_from_customer_doc(self, numero=""):
        if not hasattr(self, "v_doc_tipo"):
            return
        if self.v_doc_tipo.get() == "PASE":
            return
        numero = self._documento_digits(numero or self.v_num.get())
        nuevo_tipo = ""
        if len(numero) == 8:
            nuevo_tipo = "BOLETA"
        elif len(numero) == 11:
            nuevo_tipo = "FACTURA"
        if nuevo_tipo and self.v_doc_tipo.get() != nuevo_tipo:
            self.v_doc_tipo.set(nuevo_tipo)
            self.update_next_doc()

    def set_sale_doc_proforma_default(self):
        if not hasattr(self, "v_doc_tipo"):
            return
        self.v_doc_tipo.set("PROFORMA")
        self.update_next_doc()
        self.apply_proforma_defaults()

    def apply_proforma_defaults(self):
        if not hasattr(self, "v_doc_tipo") or self.v_doc_tipo.get() != "PROFORMA":
            return
        if not self.v_nom.get().strip():
            self.v_nom.insert(0, "USUARIO X")
        if self.v_num.get().strip().upper() in ("", "0", "00000000"):
            self.v_num.delete(0, tk.END)
        if self.v_dir.get().strip().upper() in ("", "SIN DIRECCION"):
            self.v_dir.delete(0, tk.END)

    def sale_customer_doc_text(self):
        if self.v_doc_tipo.get() == "PROFORMA":
            return ""
        numero = self.v_num.get().strip()
        return f'{self.v_tipo_doc.get()}: {numero}' if numero else ""

    def sale_seller_label(self):
        user_id = str(self.user.get("id") or self.user.get("usuario_id") or "").strip()
        usuario = str(self.user.get("usuario", "")).strip()
        return f"ID {user_id} - {usuario}" if user_id else usuario

    def search_client_sale(self):
        numero = self._documento_digits(self.v_num.get().strip())
        if len(numero) not in (8, 11):
            messagebox.showwarning("Consulta", "Ingresa 8 dígitos para DNI o 11 para RUC.")
            return
        self.v_tipo_doc.set("RUC" if len(numero) == 11 else "DNI")
        self.auto_sale_doc_type_from_customer_doc(numero)
        data = consultar_documento_api(numero)
        if isinstance(data, dict) and (api_response_ok(data) or data.get("found")):
            self._set_cliente_fields(self.v_nom, self.v_dir, data)
        else:
            messagebox.showinfo("Consulta", "Cliente no encontrado. Puedes escribirlo manualmente.")

    def save_sale_client_ui(self, silent=False):
        if self.v_doc_tipo.get() == "PROFORMA":
            if not silent:
                messagebox.showinfo("Cliente", "La proforma no requiere registrar cliente.")
            return {"ok": True, "skipped": True}
        numero = self.v_num.get().strip()
        nombre = self.v_nom.get().strip()
        if not numero or not nombre:
            if not silent:
                messagebox.showwarning("Cliente", "Ingresa DNI/RUC y nombre para registrar.")
            return {"ok": False}
        r = guardar_cliente({
            "tipo_documento": self.v_tipo_doc.get(),
            "numero_documento": numero,
            "nombre": nombre,
            "direccion": self.v_dir.get().strip()
        })
        if api_response_ok(r):
            if not silent:
                messagebox.showinfo("Cliente", "Cliente guardado correctamente.")
            try:
                self.refresh_clients()
            except Exception:
                pass
        elif not silent:
            messagebox.showerror("Cliente", api_response_error(r, "No se pudo guardar el cliente."))
        return r

    def refresh_sale_products_cache(self, force=False):
        if self.sales_product_cache_loaded and not force:
            return
        try:
            self.sales_product_cache = obtener_productos() or []
            for p in self.sales_product_cache:
                p["_search_text"] = " ".join([
                    str(p.get("id", "")),
                    str(p.get("nombre", "")),
                    str(p.get("categoria", "")),
                    str(p.get("marca", "")),
                    str(p.get("modelo", "")),
                    str(p.get("sku_woo", "")),
                ]).lower()
            self.sales_product_cache_loaded = True
        except Exception:
            if not self.sales_product_cache:
                self.sales_product_cache = []
            self.sales_product_cache_loaded = bool(self.sales_product_cache)
        self.render_sale_categories()
        if hasattr(self, "v_search"):
            self.perform_sale_search(load_first=False)

    def render_sale_categories(self):
        if not hasattr(self, "sale_categories_frame"):
            return
        for child in self.sale_categories_frame.winfo_children():
            child.destroy()
        categorias = ["Todos"]
        try:
            extras = sorted({
                str(p.get("categoria", "") or "").strip()
                for p in (self.sales_product_cache or [])
                if str(p.get("categoria", "") or "").strip()
            })
            categorias.extend(extras[:9])
        except Exception:
            pass
        self.sale_category_buttons = {}
        for idx, cat in enumerate(categorias):
            active = cat == getattr(self, "sale_category", "Todos")
            btn = tk.Button(
                self.sale_categories_frame,
                text=cat,
                command=lambda c=cat: self.set_sale_category(c),
                bg="#0f766e" if active else "#ffffff",
                fg="#ffffff" if active else TEXT,
                relief="flat" if active else "solid",
                bd=1,
                padx=16,
                pady=9,
            )
            btn.grid(row=0, column=idx, padx=(0, 8), sticky="w")
            self.sale_category_buttons[cat] = btn

    def set_sale_category(self, category):
        self.sale_category = category or "Todos"
        self.render_sale_categories()
        self.perform_sale_search(load_first=False)

    def filter_sale_products_cached(self, texto):
        q = str(texto or "").strip().lower()
        tokens = [t for t in q.replace("|", " ").replace("-", " ").split() if t]
        base = self.sales_product_cache or []
        categoria = getattr(self, "sale_category", "Todos")
        if categoria and categoria != "Todos":
            base = [p for p in base if str(p.get("categoria", "") or "").strip().lower() == categoria.lower()]
        if not tokens:
            return base[:24]

        def score_producto(p):
            texto_busqueda = p.get("_search_text") or " ".join([
                str(p.get("id", "")),
                str(p.get("nombre", "")),
                str(p.get("categoria", "")),
                str(p.get("marca", "")),
                str(p.get("modelo", "")),
                str(p.get("almacen", "")),
                str(p.get("sku_woo", "")),
                str(p.get("observacion", "")),
            ]).lower()
            if not all(token in texto_busqueda for token in tokens):
                return -1
            score = 0
            nombre = str(p.get("nombre", "")).lower()
            marca = str(p.get("marca", "")).lower()
            modelo = str(p.get("modelo", "")).lower()
            pid = str(p.get("id", "")).lower()
            for token in tokens:
                if token == pid:
                    score += 100
                if nombre.startswith(token):
                    score += 40
                if token in nombre:
                    score += 25
                if token in marca or token in modelo:
                    score += 15
                if token in texto_busqueda:
                    score += 5
            return score

        resultados = []
        for p in base:
            score = score_producto(p)
            if score >= 0:
                resultados.append((score, p))
        resultados.sort(key=lambda item: (-item[0], str(item[1].get("nombre", ""))))
        return [p for _, p in resultados[:24]]

    def search_products_sale(self, event=None):
        if self.sale_search_after_id:
            try:
                self.root.after_cancel(self.sale_search_after_id)
            except Exception:
                pass
        keysym = getattr(event, "keysym", "") if event is not None else ""
        self.sale_search_after_id = self.root.after(90, lambda: self.perform_sale_search(keysym))

    def perform_sale_search(self, keysym="", load_first=True):
        self.sale_search_after_id = None
        if not self.sales_product_cache_loaded:
            self.refresh_sale_products_cache()
        q = self.v_search.get().strip()
        self.sale_list.delete(0, tk.END)
        self.selected_sale_product_index = None
        self.productos_encontrados = self.filter_sale_products_cached(q)
        for p in self.productos_encontrados:
            stock = int(p.get("stock", 0) or 0)
            etiqueta_stock = "SIN STOCK" if stock <= 0 else f"Stock: {stock}"
            self.sale_list.insert(
                tk.END,
                f'#{p.get("id","")} | {p.get("nombre","")} | {etiqueta_stock} | {money(p.get("precio_venta",0) or 0)}'
            )
        if self.productos_encontrados:
            self.sale_list.selection_clear(0, tk.END)
            self.sale_list.selection_set(0)
            self.sale_list.activate(0)
            self.selected_sale_product_index = 0
            if load_first and keysym not in ("BackSpace", "Delete"):
                self.load_sale_product_fields(self.productos_encontrados[0])
        self.render_sale_product_cards()

    def sale_price_from_product(self, p):
        for key in ("precio_venta", "precio", "price"):
            value = p.get(key, "")
            if value not in ("", None):
                try:
                    return float(str(value).replace(",", "."))
                except Exception:
                    pass
        return 0.0

    def product_placeholder_image(self, product, size=(92, 78)):
        name = f'{product.get("nombre","")} {product.get("categoria","")} {product.get("marca","")} {product.get("modelo","")}'.upper()
        img = Image.new("RGB", size, "#f8fafc")
        draw = ImageDraw.Draw(img)
        fill = "#0f969c"
        label = "PC"
        if "RAM" in name or "MEMORIA" in name:
            fill, label = "#111827", "RAM"
        elif "SSD" in name or "DISCO" in name or "NVME" in name:
            fill, label = "#334155", "SSD"
        elif "MONITOR" in name:
            fill, label = "#2563eb", "MON"
        elif "TECLADO" in name:
            fill, label = "#7c3aed", "KEY"
        elif "MOUSE" in name:
            fill, label = "#ea580c", "MOU"
        elif "GRAFICA" in name or "RTX" in name or "GTX" in name:
            fill, label = "#16a34a", "GPU"
        draw.rounded_rectangle((12, 10, size[0] - 12, size[1] - 10), radius=8, fill=fill)
        draw.text((size[0] / 2 - 12, size[1] / 2 - 6), label, fill="white")
        return img

    def product_image_for_ui(self, product, size=(92, 78), allow_remote=True):
        raw_key = str(product.get("imagen_url") or product.get("id") or product.get("nombre") or "")
        key = f"{raw_key}|{size[0]}x{size[1]}"
        if key in self.product_img_cache:
            return self.product_img_cache[key]
        img = None
        cache_photo = True
        src = str(product.get("imagen_url") or "").strip()
        try:
            if src.startswith(("http://", "https://")):
                if key in self.product_img_bytes_cache:
                    img = Image.open(io.BytesIO(self.product_img_bytes_cache[key])).convert("RGB")
                elif os.path.exists(image_cache_path(src, size)):
                    with open(image_cache_path(src, size), "rb") as f:
                        data = f.read()
                    self.product_img_bytes_cache[key] = data
                    img = Image.open(io.BytesIO(data)).convert("RGB")
                elif allow_remote:
                    with urllib.request.urlopen(src, timeout=1.2) as r:
                        data = r.read()
                    self.product_img_bytes_cache[key] = data
                    try:
                        os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
                        with open(image_cache_path(src, size), "wb") as f:
                            f.write(data)
                    except Exception:
                        pass
                    img = Image.open(io.BytesIO(data)).convert("RGB")
                else:
                    img = self.product_placeholder_image(product, size)
                    cache_photo = False
            elif src.startswith("data:image"):
                raw = src.split(",", 1)[1] if "," in src else ""
                img = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
            elif src and os.path.exists(src):
                img = Image.open(src).convert("RGB")
        except Exception:
            img = None
        if img is None:
            img = self.product_placeholder_image(product, size)
        img.thumbnail(size)
        canvas = Image.new("RGB", size, "#ffffff")
        canvas.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
        photo = ImageTk.PhotoImage(canvas)
        if cache_photo:
            self.product_img_cache[key] = photo
        return photo

    def queue_sale_image_load(self, product, size=(116, 96)):
        src = str(product.get("imagen_url") or "").strip()
        if not src.startswith(("http://", "https://")):
            return
        raw_key = str(product.get("imagen_url") or product.get("id") or product.get("nombre") or "")
        key = f"{raw_key}|{size[0]}x{size[1]}"
        if key in self.product_img_bytes_cache or key in self.product_img_loading:
            return
        disk_path = image_cache_path(src, size)
        if os.path.exists(disk_path):
            try:
                with open(disk_path, "rb") as f:
                    self.product_img_bytes_cache[key] = f.read()
                self.product_img_cache.pop(key, None)
                if getattr(self, "current_key", "") == "ventas":
                    self.root.after(0, self.render_sale_product_cards)
                return
            except Exception:
                pass
        self.product_img_loading.add(key)

        def worker():
            data = None
            try:
                with urllib.request.urlopen(src, timeout=3) as r:
                    data = r.read()
            except Exception:
                data = None

            def finish():
                self.product_img_loading.discard(key)
                if data:
                    self.product_img_bytes_cache[key] = data
                    try:
                        os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
                        with open(disk_path, "wb") as f:
                            f.write(data)
                    except Exception:
                        pass
                    self.product_img_cache.pop(key, None)
                    if getattr(self, "current_key", "") == "ventas":
                        self.render_sale_product_cards()
            try:
                self.root.after(0, finish)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def render_sale_product_cards(self):
        if not hasattr(self, "sale_cards"):
            return
        for child in self.sale_cards.winfo_children():
            child.destroy()
        self.sale_card_images = []
        if not self.productos_encontrados:
            tk.Label(self.sale_cards, text="Busca un producto o presiona Recargar para ver el catalogo.", bg="#ffffff", fg=MUTED, font=("Arial", 12)).grid(row=0, column=0, padx=24, pady=24, sticky="w")
            self.apply_dark_widget_theme(self.sale_cards)
            return
        visibles = self.productos_encontrados[:12]
        for idx, p in enumerate(visibles):
            card = tk.Frame(self.sale_cards, bg="#ffffff", highlightthickness=1, highlightbackground="#e2e8f0", width=158, height=226)
            card.grid(row=idx // 4, column=idx % 4, padx=7, pady=7, sticky="n")
            card.grid_propagate(False)
            img = self.product_image_for_ui(p, size=(116, 96), allow_remote=False)
            self.queue_sale_image_load(p, size=(116, 96))
            self.sale_card_images.append(img)
            tk.Button(card, image=img, bg="#ffffff", relief="flat", command=lambda i=idx: self.pick_sale_product_index(i)).pack(pady=(12, 4))
            tk.Label(card, text=str(p.get("nombre", ""))[:38], bg="#ffffff", fg=TEXT, font=("Arial", 8, "bold"), wraplength=140, justify="center").pack(padx=5)
            tk.Label(card, text=money(self.sale_price_from_product(p)), bg="#ffffff", fg=TEXT, font=("Arial", 13, "bold")).pack(pady=(8, 0))
            stock = int(p.get("stock", 0) or 0)
            stock_color = "#dc2626" if stock <= 3 else "#16a34a"
            tk.Label(card, text=f"Stock: {stock}", bg="#ffffff", fg=stock_color, font=("Arial", 9, "bold")).pack()
        if len(self.productos_encontrados) > len(visibles):
            tk.Label(
                self.sale_cards,
                text=f"Mostrando {len(visibles)} de {len(self.productos_encontrados)}. Escribe mas para filtrar.",
                bg="#ffffff",
                fg=MUTED,
                font=("Arial", 10, "bold")
            ).grid(row=3, column=0, columnspan=4, padx=10, pady=8, sticky="w")
        self.apply_dark_widget_theme(self.sale_cards)

    def pick_sale_product_index(self, idx):
        if idx < 0 or idx >= len(self.productos_encontrados):
            return
        self.selected_sale_product_index = idx
        self.sale_list.selection_clear(0, tk.END)
        self.sale_list.selection_set(idx)
        p = self.productos_encontrados[idx]
        self.v_search.delete(0, tk.END)
        self.v_search.insert(0, str(p.get("nombre", "") or ""))
        self.load_sale_product_fields(p)
        self.v_qty.focus_set()
        self.v_qty.selection_range(0, tk.END)

    def load_sale_product_fields(self, p):
        precio = self.sale_price_from_product(p)
        self.v_item_name.delete(0, tk.END)
        self.v_item_name.insert(0, str(p.get("nombre", "") or ""))
        self.v_item_brand.delete(0, tk.END)
        self.v_item_model.delete(0, tk.END)
        self.v_price.delete(0, tk.END)
        self.v_price.insert(0, f"{precio:.2f}")

    def pick_product_sale(self, event=None):
        sel = self.sale_list.curselection()
        if not sel and self.productos_encontrados:
            idx = self.selected_sale_product_index if self.selected_sale_product_index is not None else 0
            p = self.productos_encontrados[idx]
        elif sel:
            idx = sel[0]
            p = self.productos_encontrados[idx]
        else:
            return
        self.selected_sale_product_index = idx
        self.v_search.delete(0, tk.END)
        self.v_search.insert(0, str(p.get("nombre", "") or ""))
        self.load_sale_product_fields(p)
        self.v_qty.focus_set()
        self.v_qty.selection_range(0, tk.END)

    def current_sale_selected_product(self):
        try:
            if self.selected_sale_product_index is not None and self.productos_encontrados:
                return self.productos_encontrados[self.selected_sale_product_index]
            sel = self.sale_list.curselection()
            if sel and self.productos_encontrados:
                return self.productos_encontrados[sel[0]]
            if self.productos_encontrados:
                return self.productos_encontrados[0]
        except Exception:
            return None
        return None

    def open_sale_series_picker(self):
        p = self.current_sale_selected_product()
        if not p:
            messagebox.showwarning("Series", "Selecciona un producto primero.")
            return
        producto_id = p.get("id")
        try:
            rows = obtener_series_producto(producto_id) or []
        except Exception:
            rows = []
        disponibles = [
            s for s in rows
            if str(s.get("estado") or "DISPONIBLE").upper() in ("DISPONIBLE", "RESERVADO")
        ]

        win = tk.Toplevel(self.root)
        win.title("Escoger series")
        win.geometry("560x430")
        tk.Label(win, text=str(p.get("nombre", "")), font=("Arial", 12, "bold"), wraplength=520).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(win, text="Selecciona una o varias series. Tambien puedes escribir una nueva abajo.", fg=MUTED, wraplength=520, justify="left").pack(anchor="w", padx=12, pady=(0, 8))

        tree = ttk.Treeview(win, columns=("Serie", "Estado", "Proveedor"), show="headings", height=10, selectmode="extended")
        for col, width in zip(("Serie", "Estado", "Proveedor"), (210, 110, 190)):
            tree.heading(col, text=col)
            tree.column(col, width=width, anchor="center")
        tree.pack(fill="both", expand=True, padx=12, pady=6)
        for s in disponibles:
            tree.insert("", "end", values=(s.get("serie", ""), s.get("estado", "DISPONIBLE"), s.get("proveedor", "")))
        if not disponibles:
            tree.insert("", "end", values=("Sin series disponibles registradas", "", ""))

        bottom = tk.Frame(win)
        bottom.pack(fill="x", padx=12, pady=10)
        tk.Label(bottom, text="Serie nueva").grid(row=0, column=0, sticky="w")
        ent_new = tk.Entry(bottom)
        ent_new.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        bottom.grid_columnconfigure(0, weight=1)

        def apply_series():
            selected = []
            current = [
                s.strip()
                for s in re.split(r"[,;\n\r|]+", self.v_series.get().strip())
                if s.strip()
            ]
            selected.extend(current)
            for iid in tree.selection():
                value = str(tree.item(iid, "values")[0] or "").strip()
                if value and not value.lower().startswith("sin series"):
                    selected.append(value)
            manual = ent_new.get().strip()
            if manual:
                selected.extend([s.strip() for s in re.split(r"[,;\n\r|]+", manual) if s.strip()])
            if not selected:
                messagebox.showwarning("Series", "Selecciona o escribe una serie.")
                return
            normalized = []
            seen = set()
            for serie in selected:
                key = serie.upper()
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(serie)
            self.v_series.delete(0, tk.END)
            self.v_series.insert(0, ", ".join(normalized))
            win.destroy()

        tree.bind("<Double-1>", lambda e: apply_series())
        tk.Button(bottom, text="Usar series", command=apply_series, bg="#0f766e", fg="white", relief="flat", padx=14, pady=7).grid(row=1, column=1, padx=(8, 0), pady=(2, 0))

    def add_sale_item(self):
        if self.sale_search_after_id:
            try:
                self.root.after_cancel(self.sale_search_after_id)
            except Exception:
                pass
            self.sale_search_after_id = None
            self.perform_sale_search(load_first=False)
        sel = self.sale_list.curselection()
        if self.selected_sale_product_index is not None and self.productos_encontrados:
            p = self.productos_encontrados[self.selected_sale_product_index]
        elif not sel:
            if not self.productos_encontrados:
                messagebox.showwarning("Aviso", "Busca y selecciona un producto.")
                return
            p = self.productos_encontrados[0]
        else:
            p = self.productos_encontrados[sel[0]]

        try:
            qty = int(self.v_qty.get() or 0)
            price = float(str(self.v_price.get() or 0).replace(",", "."))
        except Exception:
            messagebox.showerror("Error", "Cantidad o precio inválidos.")
            return
        if qty <= 0:
            messagebox.showwarning("Aviso", "La cantidad debe ser mayor a 0.")
            return
        if price <= 0:
            messagebox.showwarning("Aviso", "El precio debe ser mayor a 0.")
            return

        nombre_doc = self.v_item_name.get().strip() or str(p.get("nombre", "") or "")
        marca_doc = ""
        modelo_doc = ""

        item = {
            "producto_id": p["id"], "id": p["id"], "nombre": nombre_doc, "marca": marca_doc,
            "modelo": modelo_doc, "serie": self.v_series.get().strip(), "cantidad": qty,
            "precio": price, "total": qty * price, "series_texto": self.v_series.get().strip(),
            "imagen_url": p.get("imagen_url", "")
        }
        self.items_venta.append(item)
        self.refresh_sale_table()
        self.v_search.delete(0, tk.END)
        self.v_price.delete(0, tk.END)
        self.v_item_name.delete(0, tk.END)
        self.v_item_brand.delete(0, tk.END)
        self.v_item_model.delete(0, tk.END)
        self.v_series.delete(0, tk.END)
        self.v_qty.delete(0, tk.END)
        self.v_qty.insert(0, "1")
        self.sale_list.delete(0, tk.END)
        self.selected_sale_product_index = None
        self.render_sale_product_cards()
        self.save_current_sale_draft()
        self.v_search.focus_set()

    def set_sale_payment_method(self, metodo):
        if hasattr(self, "v_metodo_pago"):
            self.v_metodo_pago.set(metodo)
        if hasattr(self, "v_estado_pago"):
            self.v_estado_pago.set("PAGADO")

    def change_sale_item_qty(self, idx, delta):
        if idx < 0 or idx >= len(self.items_venta):
            return
        item = self.items_venta[idx]
        nueva = int(item.get("cantidad", 1) or 1) + delta
        if nueva <= 0:
            del self.items_venta[idx]
        else:
            item["cantidad"] = nueva
            item["total"] = float(item.get("precio", 0) or 0) * nueva
        self.refresh_sale_table()

    def remove_sale_item_at(self, idx):
        if idx < 0 or idx >= len(self.items_venta):
            return
        del self.items_venta[idx]
        self.refresh_sale_table()

    def render_sale_cart(self):
        if not hasattr(self, "cart_items_frame"):
            return
        for child in self.cart_items_frame.winfo_children():
            child.destroy()
        if hasattr(self, "lbl_cart_count"):
            self.lbl_cart_count.config(text=str(len(self.items_venta)))
        if not self.items_venta:
            tk.Label(self.cart_items_frame, text="Aun no hay productos en el carrito.", bg="#ffffff", fg=MUTED, font=("Arial", 11)).pack(anchor="w", padx=10, pady=18)
            self.apply_dark_widget_theme(self.cart_items_frame)
            return
        for idx, item in enumerate(self.items_venta):
            row = tk.Frame(self.cart_items_frame, bg="#ffffff", highlightthickness=1, highlightbackground="#e5e7eb")
            row.pack(fill="x", padx=4, pady=5)
            prod_ref = {"imagen_url": item.get("imagen_url", ""), "nombre": item.get("nombre", ""), "marca": item.get("marca", ""), "modelo": item.get("modelo", "")}
            img = self.product_image_for_ui(prod_ref, size=(54, 50))
            self.sale_card_images.append(img)
            tk.Label(row, image=img, bg="#ffffff").grid(row=0, column=0, rowspan=3, padx=8, pady=8)
            tk.Label(row, text=str(item.get("nombre", ""))[:34], bg="#ffffff", fg=TEXT, font=("Arial", 9, "bold"), anchor="w").grid(row=0, column=1, columnspan=4, sticky="ew", padx=(0, 4), pady=(7, 0))
            tk.Label(row, text=money(item.get("precio", 0)), bg="#ffffff", fg=MUTED, font=("Arial", 9)).grid(row=1, column=1, sticky="w")
            tk.Button(row, text="-", command=lambda i=idx: self.change_sale_item_qty(i, -1), bg="#f8fafc", fg=TEXT, relief="solid", bd=1, width=3).grid(row=2, column=1, sticky="w", pady=(4, 8))
            tk.Label(row, text=str(item.get("cantidad", 0)), bg="#ffffff", fg=TEXT, width=4, font=("Arial", 10, "bold")).grid(row=2, column=2, pady=(4, 8))
            tk.Button(row, text="+", command=lambda i=idx: self.change_sale_item_qty(i, 1), bg="#f8fafc", fg=TEXT, relief="solid", bd=1, width=3).grid(row=2, column=3, sticky="w", pady=(4, 8))
            tk.Label(row, text=money(item.get("total", 0)), bg="#ffffff", fg=TEXT, font=("Arial", 10, "bold")).grid(row=1, column=4, sticky="e", padx=8)
            tk.Button(row, text="Editar", command=lambda i=idx: self.edit_sale_item_at(i), bg="#eef2ff", fg="#3730a3", relief="flat").grid(row=2, column=4, sticky="e", padx=8, pady=(4, 8))
            tk.Button(row, text="x", command=lambda i=idx: self.remove_sale_item_at(i), bg="#ffffff", fg="#dc2626", relief="flat").grid(row=0, column=4, sticky="e", padx=8)
            row.grid_columnconfigure(1, weight=1)
        self.apply_dark_widget_theme(self.cart_items_frame)

    def remove_sale_item(self):
        sel = self.tree_sale.selection()
        if not sel:
            return
        idx = self.tree_sale.index(sel[0])
        del self.items_venta[idx]
        self.refresh_sale_table()

    def duplicate_sale_item(self):
        sel = self.tree_sale.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona un ítem para duplicar.")
            return
        idx = self.tree_sale.index(sel[0])
        item = self.items_venta[idx].copy()
        self.items_venta.append(item)
        self.refresh_sale_table()

    def edit_sale_item(self, event=None):
        sel = self.tree_sale.selection()
        if not sel:
            return
        idx = self.tree_sale.index(sel[0])
        item = self.items_venta[idx]

        win = tk.Toplevel(self.root)
        win.title("Editar ítem")
        win.geometry("420x390")
        tk.Label(win, text="Nombre en documento").pack(pady=5)
        ent_name = tk.Entry(win, width=48)
        ent_name.pack()
        ent_name.insert(0, item.get("nombre", ""))
        tk.Label(win, text="Marca").pack(pady=5)
        ent_brand = tk.Entry(win, width=32)
        ent_brand.pack()
        ent_brand.insert(0, item.get("marca", ""))
        tk.Label(win, text="Modelo").pack(pady=5)
        ent_model = tk.Entry(win, width=32)
        ent_model.pack()
        ent_model.insert(0, item.get("modelo", ""))
        tk.Label(win, text="Cantidad").pack(pady=5)
        ent_qty = tk.Entry(win)
        ent_qty.pack()
        ent_qty.insert(0, str(item["cantidad"]))
        tk.Label(win, text="Precio").pack(pady=5)
        ent_price = tk.Entry(win)
        ent_price.pack()
        ent_price.insert(0, str(item["precio"]))
        tk.Label(win, text="Serie").pack(pady=5)
        ent_series = tk.Entry(win)
        ent_series.pack()
        ent_series.insert(0, item.get("serie", ""))

        def save_edit():
            try:
                item["nombre"] = ent_name.get().strip()
                item["marca"] = ent_brand.get().strip()
                item["modelo"] = ent_model.get().strip()
                item["cantidad"] = int(ent_qty.get())
                item["precio"] = float(str(ent_price.get()).replace(",", "."))
                item["serie"] = ent_series.get().strip()
                item["series_texto"] = ent_series.get().strip()
                item["total"] = item["cantidad"] * item["precio"]
                self.refresh_sale_table()
                win.destroy()
            except Exception:
                messagebox.showerror("Error", "Datos inválidos.")

        tk.Button(win, text="Guardar", command=save_edit, bg=ACCENT, fg="white", relief="flat").pack(pady=14)

    def edit_sale_item(self, event=None):
        sel = self.tree_sale.selection()
        if not sel:
            return
        self.edit_sale_item_at(self.tree_sale.index(sel[0]))

    def edit_sale_item_at(self, idx):
        if idx < 0 or idx >= len(self.items_venta):
            return
        item = self.items_venta[idx]
        win = tk.Toplevel(self.root)
        win.title("Editar producto agregado")
        win.geometry("460x330")
        tk.Label(win, text="Nombre en documento").pack(pady=5)
        ent_name = tk.Entry(win, width=52)
        ent_name.pack()
        ent_name.insert(0, item.get("nombre", ""))
        tk.Label(win, text="Cantidad").pack(pady=5)
        ent_qty = tk.Entry(win)
        ent_qty.pack()
        ent_qty.insert(0, str(item.get("cantidad", 1)))
        tk.Label(win, text="Precio").pack(pady=5)
        ent_price = tk.Entry(win)
        ent_price.pack()
        ent_price.insert(0, str(item.get("precio", 0)))
        tk.Label(win, text="Serie").pack(pady=5)
        ent_series = tk.Entry(win, width=52)
        ent_series.pack()
        ent_series.insert(0, item.get("serie", item.get("series_texto", "")))

        def save_edit():
            try:
                item["nombre"] = ent_name.get().strip()
                item["marca"] = ""
                item["modelo"] = ""
                item["cantidad"] = int(ent_qty.get())
                item["precio"] = float(str(ent_price.get()).replace(",", "."))
                item["serie"] = ent_series.get().strip()
                item["series_texto"] = ent_series.get().strip()
                item["total"] = item["cantidad"] * item["precio"]
                self.refresh_sale_table()
                self.save_current_sale_draft()
                win.destroy()
            except Exception:
                messagebox.showerror("Error", "Datos invalidos.")

        tk.Button(win, text="Guardar cambios", command=save_edit, bg=ACCENT, fg="white", relief="flat").pack(pady=14)

    def clear_sale_form(self, reset_edit=True):
        if reset_edit:
            self.editing_proforma_id = None
            self.editing_proforma_numero = ""
            self.update_sale_edit_state_ui()
        self.items_venta = []
        self.refresh_sale_table()
        self.v_search.delete(0, tk.END)
        self.v_qty.delete(0, tk.END)
        self.v_qty.insert(0, "1")
        self.v_price.delete(0, tk.END)
        self.v_item_name.delete(0, tk.END)
        self.v_item_brand.delete(0, tk.END)
        self.v_item_model.delete(0, tk.END)
        self.v_series.delete(0, tk.END)
        self.v_obs.delete(0, tk.END)
        if hasattr(self, "v_estado_pago"): self.v_estado_pago.set("DEUDA")
        if hasattr(self, "v_metodo_pago"): self.v_metodo_pago.set("")
        if hasattr(self, "v_num"): self.v_num.delete(0, tk.END)
        if hasattr(self, "v_nom"): self.v_nom.delete(0, tk.END)
        if hasattr(self, "v_dir"): self.v_dir.delete(0, tk.END)
        if hasattr(self, "_last_sale_doc_lookup"): self._last_sale_doc_lookup = ""
        self.set_sale_doc_proforma_default()
        self.v_desc.delete(0, tk.END)
        self.v_desc.insert(0, "0")
        self.sale_list.delete(0, tk.END)
        self.selected_sale_product_index = None
        self.render_sale_product_cards()

    def refresh_sale_table(self):
        if hasattr(self, "sale_card_images"):
            self.sale_card_images = []
        for i in self.tree_sale.get_children():
            self.tree_sale.delete(i)
        for x in self.items_venta:
            self.tree_sale.insert("", "end", values=(x["id"], x["nombre"], x["serie"], x["cantidad"], f'{x["precio"]:.2f}', f'{x["total"]:.2f}'))
        total = sum(x["total"] for x in self.items_venta)
        try:
            desc = float(self.v_desc.get() or 0)
        except Exception:
            desc = 0
        total = max(0, total - desc)
        subtotal = total
        igv = 0
        self.lbl_sub.config(text=f"Subtotal: {money(subtotal)}")
        self.lbl_igv.config(text="IGV: DESACTIVADO")
        self.lbl_tot.config(text=f"Total: {money(total)}")
        self.render_sale_cart()
        self.save_current_sale_draft()

    def build_pdf_data(self):
        total = sum(x["total"] for x in self.items_venta)
        try:
            desc = float(self.v_desc.get() or 0)
        except Exception:
            desc = 0
        total = max(0, round(total - desc, 2))
        subtotal = total
        igv = 0
        return subtotal, igv, total

    def preview_pdf_sale(self):
        if not self.items_venta:
            messagebox.showwarning("Aviso", "No hay items en la venta.")
            return
        self.apply_proforma_defaults()
        subtotal, igv, total = self.build_pdf_data()
        path = os.path.join(tempfile.gettempdir(), "preview_v20.pdf")
        generate_pdf(path, self.cfg, self.v_doc_tipo.get(), self.lbl_next.cget("text"), self.v_nom.get().strip(),
                     self.sale_customer_doc_text(), self.v_dir.get().strip(),
                     self.items_venta, subtotal, igv, total, self.sale_seller_label(),
                     {"fecha_emision": now_local_api_timestamp(), "fecha_vencimiento": today_ymd() if self.v_doc_tipo.get() == "PROFORMA" else ""})
        doc_meta = {
            "tipo": self.v_doc_tipo.get(),
            "numero": self.lbl_next.cget("text"),
            "cliente_nombre": self.v_nom.get().strip(),
            "documento_cliente": self.sale_customer_doc_text(),
            "fecha_emision": now_local_api_timestamp(),
            "subtotal": subtotal,
            "igv": igv,
            "total": total,
        }
        self.open_internal_document_viewer(f"PDF {self.lbl_next.cget('text')}", doc_meta, self.items_venta, pdf_path=path)

    def print_preview_sale(self):
        if not self.items_venta:
            messagebox.showwarning("Aviso", "No hay items en la venta.")
            return
        self.apply_proforma_defaults()
        subtotal, igv, total = self.build_pdf_data()
        path = os.path.join(tempfile.gettempdir(), "preview_v20_print.pdf")
        generate_pdf(path, self.cfg, self.v_doc_tipo.get(), self.lbl_next.cget("text"), self.v_nom.get().strip(),
                     self.sale_customer_doc_text(), self.v_dir.get().strip(),
                     self.items_venta, subtotal, igv, total, self.sale_seller_label(),
                     {"fecha_emision": now_local_api_timestamp(), "fecha_vencimiento": today_ymd() if self.v_doc_tipo.get() == "PROFORMA" else ""})
        r = print_pdf_file(path)
        if not api_response_ok(r):
            if r.get("no_association"):
                messagebox.showwarning("PDF", "Esta PC no tiene lector PDF asociado para imprimir directo. Abrire el visor interno del ERP.")
                doc_meta = {
                    "tipo": self.v_doc_tipo.get(),
                    "numero": self.lbl_next.cget("text"),
                    "cliente_nombre": self.v_nom.get().strip(),
                    "documento_cliente": self.sale_customer_doc_text(),
                    "fecha_emision": now_local_api_timestamp(),
                    "subtotal": subtotal,
                    "igv": igv,
                    "total": total,
                }
                self.open_internal_document_viewer(f"PDF {self.lbl_next.cget('text')}", doc_meta, self.items_venta, pdf_path=path)
            else:
                messagebox.showerror("Error", api_response_error(r, "No se pudo enviar a imprimir."))

    def set_entry_value(self, widget, value):
        widget.delete(0, tk.END)
        widget.insert(0, str(value or ""))

    def current_sale_payload(self):
        doc_tipo = self.v_doc_tipo.get()
        numero_cliente = "" if doc_tipo in ("PROFORMA", "PASE") else self.v_num.get().strip()
        tipo_cliente = "" if doc_tipo in ("PROFORMA", "PASE") else self.v_tipo_doc.get()
        subtotal, igv, total = self.build_pdf_data()
        return {
            "tipo": doc_tipo,
            "tipo_documento_cliente": tipo_cliente,
            "numero_documento_cliente": numero_cliente,
            "cliente_nombre": self.v_nom.get().strip(),
            "direccion_cliente": self.v_dir.get().strip(),
            "usuario_emisor": self.user["usuario"],
            "fecha_emision": now_local_api_timestamp(),
            "observacion": self.v_obs.get().strip(),
            "fecha_vencimiento": today_ymd() if doc_tipo == "PROFORMA" else "",
            "estado_pago": "DEUDA",
            "metodo_pago": "",
            "subtotal": subtotal,
            "igv": igv,
            "total": total,
            "items": self.items_venta,
        }

    def update_current_proforma(self):
        doc_tipo = self.v_doc_tipo.get()
        if doc_tipo != "PROFORMA":
            messagebox.showwarning("Proforma", "Solo se puede guardar edicion sobre documentos tipo PROFORMA.")
            return
        self.apply_proforma_defaults()
        if not self.items_venta:
            messagebox.showwarning("Aviso", "Agrega al menos un producto.")
            return
        payload = self.current_sale_payload()
        payload["id"] = self.editing_proforma_id
        payload["numero"] = self.editing_proforma_numero
        try:
            resp = actualizar_documento(self.editing_proforma_id, payload)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo conectar con la API.\n{e}")
            return
        if not api_response_ok(resp):
            messagebox.showerror("Proforma", api_response_error(resp, "No se pudo actualizar la proforma."))
            return
        _, _, total = self.build_pdf_data()
        play_document_sound("success")
        messagebox.showinfo("Proforma", f"Proforma actualizada.\nNumero: {self.editing_proforma_numero}\nTotal: {money(total)}")
        self.registrar_accion("PROFORMA EDITADA", f"{self.editing_proforma_numero} - {self.v_nom.get().strip()} - {money(total)}")
        self.clear_sale_form()
        self.refresh_contabilidad()
        self.refresh_dashboard()
        self.save_current_sale_draft()

    
    def issue_sale(self, print_after=False):
        if getattr(self, "editing_proforma_id", None):
            self.update_current_proforma()
            return
        doc_tipo = self.v_doc_tipo.get()
        if doc_tipo == "PROFORMA":
            self.apply_proforma_defaults()
        if doc_tipo == "PASE" and not self.v_nom.get().strip():
            messagebox.showwarning("Aviso", "Escribe el nombre del pase o tienda.")
            return
        if doc_tipo not in ("PROFORMA", "PASE") and (not self.v_num.get().strip() or not self.v_nom.get().strip()):
            messagebox.showwarning("Aviso", "Completa los datos del cliente.")
            return
        if doc_tipo == "PROFORMA" and not self.v_nom.get().strip():
            self.v_nom.insert(0, "USUARIO X")
        if not self.items_venta:
            messagebox.showwarning("Aviso", "Agrega al menos un producto.")
            return
        if doc_tipo not in ("PROFORMA", "PASE") and self.v_num.get().strip() and self.v_nom.get().strip():
            self.save_sale_client_ui(silent=True)

        payload = self.current_sale_payload()

        try:
            resp = emitir_documento(payload)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo conectar con la API.\n{e}")
            return

        if not api_response_ok(resp):
            detalle = api_response_error(resp, "No se pudo emitir el documento.")
            messagebox.showerror("Error", f"No se pudo emitir el documento.\n{detalle}")
            return

        doc_number = build_doc_number(self.v_doc_tipo.get(), api_response_get(resp, "numero", self.lbl_next.cget("text")), self.cfg)
        subtotal = float(api_response_get(resp, "subtotal", 0) or 0)
        igv = float(api_response_get(resp, "igv", 0) or 0)
        total = float(api_response_get(resp, "total", 0) or 0)
        local_subtotal, local_igv, local_total = self.build_pdf_data()
        if total <= 0:
            subtotal, igv, total = local_subtotal, local_igv, local_total
        elif subtotal <= 0:
            subtotal = total if local_subtotal <= 0 else local_subtotal
            igv = local_igv

        play_document_sound("success")
        messagebox.showinfo("Éxito", f"Venta enviada a Caja como pendiente.\nNúmero: {doc_number}\nTotal: {money(total)}")
        self.registrar_accion("VENTA ENVIADA A CAJA", f"{self.v_doc_tipo.get()} {doc_number} - {self.v_nom.get().strip()} - {money(total)}")
        self.clear_sale_form()
        self.refresh_products()
        self.refresh_contabilidad()
        self.refresh_dashboard()
        self.save_current_sale_draft()

    # CLIENTES
    def build_clientes(self):
        frame = self.frames["clientes"]
        card = self.set_card(frame)
        tk.Label(card, text="Clientes", bg=CARD_BG, fg=TEXT, font=("Arial", 20, "bold")).pack(anchor="w", padx=12, pady=10)
        form = tk.Frame(card, bg=CARD_BG); form.pack(padx=12, pady=8)
        tk.Label(form, text="Tipo", bg=CARD_BG).grid(row=0, column=0, padx=6, pady=6)
        self.cli_tipo = ttk.Combobox(form, values=["DNI", "RUC"], state="readonly", width=12); self.cli_tipo.grid(row=0, column=1, padx=6, pady=6); self.cli_tipo.set("DNI")
        tk.Label(form, text="Número", bg=CARD_BG).grid(row=0, column=2, padx=6, pady=6)
        self.cli_num = tk.Entry(form, width=18); self.cli_num.grid(row=0, column=3, padx=6, pady=6)
        self.cli_num.bind("<KeyRelease>", self.on_client_doc_keyrelease)
        tk.Label(form, text="Nombre", bg=CARD_BG).grid(row=1, column=0, padx=6, pady=6)
        self.cli_nom = tk.Entry(form, width=35); self.cli_nom.grid(row=1, column=1, columnspan=2, padx=6, pady=6)
        tk.Label(form, text="Dirección", bg=CARD_BG).grid(row=1, column=3, padx=6, pady=6)
        self.cli_dir = tk.Entry(form, width=35); self.cli_dir.grid(row=1, column=4, padx=6, pady=6)
        tk.Button(form, text="Guardar Cliente", command=self.save_client_ui, bg=ACCENT, fg="white", relief="flat").grid(row=0, column=4, padx=6, pady=6)
        tk.Button(form, text="Consultar RUC", command=self.consultar_ruc_cliente, bg="#7c3aed", fg="white", relief="flat").grid(row=0, column=5, padx=6, pady=6)
        tk.Button(form, text="Consultar DNI", command=self.consultar_dni_cliente, bg="#0f766e", fg="white", relief="flat").grid(row=0, column=6, padx=6, pady=6)
        tk.Button(form, text="Ver compras", command=self.ver_historial_cliente_ui, bg="#334155", fg="white", relief="flat").grid(row=2, column=4, padx=6, pady=6)
        cols = ("ID", "Tipo", "Documento", "Nombre", "Dirección")
        self.tree_clients = ttk.Treeview(card, columns=cols, show="headings", height=16)
        for c, w in zip(cols, [60, 80, 120, 260, 300]):
            self.tree_clients.heading(c, text=c); self.tree_clients.column(c, width=w, anchor="center")
        self.tree_clients.pack(fill="both", expand=True, padx=12, pady=8)
        self.tree_clients.bind("<Double-1>", self.ver_historial_cliente_ui)

    def save_client_ui(self):
        r = guardar_cliente({
            "tipo_documento": self.cli_tipo.get(), "numero_documento": self.cli_num.get().strip(),
            "nombre": self.cli_nom.get().strip(), "direccion": self.cli_dir.get().strip()
        })
        if api_response_ok(r):
            messagebox.showinfo("Éxito", "Cliente guardado.")
            self.refresh_clients()

    def refresh_clients(self):
        for i in self.tree_clients.get_children():
            self.tree_clients.delete(i)
        for c in obtener_clientes():
            self.tree_clients.insert("", "end", values=(c["id"], c["tipo_documento"], c["numero_documento"], c["nombre"], c["direccion"]))

    def ver_historial_cliente_ui(self, event=None):
        documento = self.cli_num.get().strip() if hasattr(self, "cli_num") else ""
        nombre = self.cli_nom.get().strip() if hasattr(self, "cli_nom") else ""
        sel = self.tree_clients.selection() if hasattr(self, "tree_clients") else []
        if sel:
            vals = self.tree_clients.item(sel[0], "values")
            if len(vals) >= 4:
                documento = str(vals[2])
                nombre = str(vals[3])
        documento_digits = self._documento_digits(documento)
        if not documento_digits:
            messagebox.showwarning("Cliente", "Selecciona un cliente o ingresa su DNI/RUC.")
            return

        docs = []
        for d in obtener_documentos():
            doc_cliente = str(d.get("documento_cliente", ""))
            if documento_digits in self._documento_digits(doc_cliente):
                docs.append(d)

        win = tk.Toplevel(self.root)
        win.title(f"Compras del cliente {documento_digits}")
        win.geometry("1050x560")
        tk.Label(win, text=f"{nombre or 'Cliente'} - {documento_digits}", font=("Arial", 15, "bold")).pack(anchor="w", padx=12, pady=(10, 4))

        cols = ("ID", "Tipo", "Número", "Fecha", "Total", "Estado pago", "Método", "Usuario")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=14)
        for c, w in zip(cols, [70, 120, 150, 160, 110, 120, 120, 160]):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="center")
        tree.pack(fill="both", expand=True, padx=12, pady=8)

        total = 0
        for d in docs:
            monto = float(d.get("total", 0) or 0)
            total += monto
            tree.insert("", "end", values=(
                d.get("id", ""),
                d.get("tipo", ""),
                d.get("numero", ""),
                d.get("fecha_emision", ""),
                money(monto),
                d.get("estado_pago", ""),
                d.get("metodo_pago", ""),
                d.get("usuario_emisor", ""),
            ))

        tk.Label(win, text=f"Documentos: {len(docs)} | Total comprado: {money(total)}", font=("Arial", 11, "bold")).pack(anchor="e", padx=12, pady=4)

        def ver_detalle():
            selected = tree.selection()
            if not selected:
                return
            vals = tree.item(selected[0], "values")
            detalle = obtener_detalle_documento(vals[0])
            texto = "\n".join(
                f'- {x.get("descripcion","")} {x.get("marca","")} {x.get("modelo","")} | Cant: {x.get("cantidad","")} | {money(x.get("total",0) or 0)}'
                for x in detalle
            ) or "Sin detalle."
            messagebox.showinfo(f"Detalle {vals[2]}", texto)

        actions = tk.Frame(win)
        actions.pack(fill="x", padx=12, pady=8)
        tk.Button(actions, text="Ver detalle", command=ver_detalle, bg="#0891b2", fg="white", relief="flat").pack(side="left")
        tk.Button(actions, text="Cerrar", command=win.destroy, bg="#334155", fg="white", relief="flat").pack(side="right")

    # PRODUCTOS
    def build_productos(self):
        frame = self.frames["productos"]
        card = self.set_card(frame)
        tk.Label(card, text="Productos", bg=CARD_BG, fg=TEXT, font=("Arial", 20, "bold")).pack(anchor="w", padx=12, pady=10)

        form = tk.Frame(card, bg=CARD_BG)
        form.pack(padx=12, pady=8, fill="x")

        categorias = product_category_options()

        labels = ["Nombre", "Categoría", "Marca", "Modelo", "P.Compra", "P.Venta", "Stock", "Almacén", "Imagen / foto", "Observación"]
        entries = []

        for idx, lab in enumerate(labels):
            tk.Label(form, text=lab, bg=CARD_BG).grid(
                row=0 if idx < 4 else (1 if idx < 8 else 2),
                column=(idx % 4) * 2,
                padx=6,
                pady=6,
                sticky="e"
            )

            if lab == "Categoría":
                e = ttk.Combobox(form, width=18, state="readonly", values=categorias)
                e.set(default_product_category())
            elif lab == "Almacén":
                e = ttk.Combobox(form, width=18, state="readonly", values=ALMACEN_OPTIONS)
                e.set("TIENDA")
            else:
                e = tk.Entry(form, width=18)

            e.grid(
                row=0 if idx < 4 else (1 if idx < 8 else 2),
                column=(idx % 4) * 2 + 1,
                padx=6,
                pady=6,
                sticky="w"
            )
            entries.append(e)

        self.pro_nom, self.pro_cat, self.pro_mar, self.pro_mod, self.pro_pc, self.pro_pv, self.pro_st, self.pro_alm, self.pro_img, self.pro_obs = entries[:10]

        tk.Button(
            form,
            text="Subir / actualizar foto",
            command=lambda: self.pick_product_image(self.pro_img),
            bg="#0f766e",
            fg="white",
            relief="flat"
        ).grid(row=3, column=0, columnspan=2, padx=6, pady=6)

        tk.Button(
            form,
            text="Guardar Producto Nuevo",
            command=self.save_product_ui,
            bg=ACCENT,
            fg="white",
            relief="flat"
        ).grid(row=2, column=0, columnspan=2, padx=6, pady=6)

        tk.Button(
            form,
            text="Editar seleccionado",
            command=self.edit_product_ui,
            bg="#059669",
            fg="white",
            relief="flat"
        ).grid(row=2, column=2, columnspan=2, padx=6, pady=6)

        tk.Button(
            form,
            text="Series producto",
            command=self.product_series_manager_ui,
            bg="#7c3aed",
            fg="white",
            relief="flat"
        ).grid(row=3, column=2, columnspan=2, padx=6, pady=6)

        tk.Button(
            form,
            text="Eliminar seleccionado",
            command=self.delete_product_ui,
            bg="#dc2626",
            fg="white",
            relief="flat"
        ).grid(row=2, column=4, columnspan=2, padx=6, pady=6)

        tk.Button(
            form,
            text="Sincronizar Woo",
            command=self.sync_selected_product_woo,
            bg="#7c3aed",
            fg="white",
            relief="flat"
        ).grid(row=2, column=6, columnspan=2, padx=6, pady=6)

        info = tk.Label(
            card,
            text="Tip: doble clic sobre un producto para editar nombre, categoría, marca, modelo, precios y stock.",
            bg=CARD_BG,
            fg=MUTED,
            font=("Arial", 10)
        )
        info.pack(anchor="w", padx=12, pady=(0, 5))

        search_bar = tk.Frame(card, bg=CARD_BG)
        search_bar.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(search_bar, text="Buscar producto", bg=CARD_BG, fg=TEXT).pack(side="left")
        self.product_search = tk.Entry(search_bar, width=45)
        self.product_search.pack(side="left", padx=8)
        self.product_search.bind("<KeyRelease>", lambda e: self.refresh_products())
        tk.Button(
            search_bar,
            text="Limpiar búsqueda",
            command=lambda: (self.product_search.delete(0, tk.END), self.refresh_products()),
            bg="#334155",
            fg="white",
            relief="flat"
        ).pack(side="left", padx=6)

        cols = ("ID", "Nombre", "Categoría", "Marca", "Modelo", "P.Compra", "P.Venta", "Stock", "Almacén", "Obs.")
        self.tree_products = ttk.Treeview(card, columns=cols, show="headings", height=16)

        widths = [60, 240, 130, 100, 100, 80, 80, 65, 90, 160]
        for c, w in zip(cols, widths):
            self.tree_products.heading(c, text=c)
            self.tree_products.column(c, width=w, anchor="center")

        self.tree_products.pack(fill="both", expand=True, padx=12, pady=8)
        self.tree_products.tag_configure("ok", background="#dcfce7", foreground="#0f172a")
        self.tree_products.tag_configure("low", background="#fef9c3", foreground="#0f172a")
        self.tree_products.tag_configure("out", background="#fee2e2", foreground="#0f172a")
        self.tree_products.bind("<Double-1>", self.edit_product_ui)

    def save_product_ui(self):
        try:
            payload = {
                "nombre": self.pro_nom.get().strip(),
                "categoria": self.pro_cat.get().strip(),
                "marca": self.pro_mar.get().strip(),
                "modelo": self.pro_mod.get().strip(),
                "precio_compra": float(self.pro_pc.get() or 0),
                "precio_venta": float(self.pro_pv.get() or 0),
                "stock": int(self.pro_st.get() or 0),
                "almacen": self.pro_alm.get().strip() or "TIENDA",
                "imagen_url": self.pro_img.get().strip(),
                "observacion": self.pro_obs.get().strip()
            }
        except Exception:
            messagebox.showerror("Error", "Revisa precio compra, precio venta y stock.")
            return

        if not payload["nombre"]:
            messagebox.showwarning("Aviso", "El nombre del producto es obligatorio.")
            return

        r = guardar_producto(payload)
        if api_response_ok(r):
            messagebox.showinfo("Éxito", "Producto guardado.")
            self.registrar_accion("PRODUCTO AGREGADO", payload.get("nombre", ""))
            self.auto_sync_product_after_save(api_response_get(r, "id", None))
            self.pro_nom.delete(0, tk.END)
            self.pro_mar.delete(0, tk.END)
            self.pro_mod.delete(0, tk.END)
            self.pro_pc.delete(0, tk.END)
            self.pro_pv.delete(0, tk.END)
            self.pro_st.delete(0, tk.END)
            self.pro_img.delete(0, tk.END)
            self.pro_obs.delete(0, tk.END)
            self.refresh_products()
        else:
            messagebox.showerror("Error", "No se pudo guardar el producto.")

    def image_file_to_data_url(self, path, max_size=(520, 520)):
        img = Image.open(path).convert("RGB")
        img.thumbnail(max_size)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def pick_product_image(self, entry_widget):
        path = filedialog.askopenfilename(
            title="Seleccionar imagen del producto",
            filetypes=[
                ("Imagenes", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if not path:
            return
        try:
            data_url = self.image_file_to_data_url(path)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar la imagen.\n{e}")
            return
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, data_url)
        messagebox.showinfo("Imagen lista", "La imagen quedo cargada para guardarse en la API y verse en las demas PCs.")

    def normalize_photo_value_for_api(self, value, max_size=(520, 520)):
        foto_url = str(value or "").strip()
        if foto_url and os.path.isfile(foto_url):
            return self.image_file_to_data_url(foto_url, max_size=max_size)
        return foto_url

    def refresh_products(self):
        self.productos_cache = {}
        q = ""
        try:
            q = self.product_search.get().strip().lower()
        except Exception:
            q = ""

        for i in self.tree_products.get_children():
            self.tree_products.delete(i)

        productos = obtener_productos()
        for p in productos:
            p["_search_text"] = " ".join([
                str(p.get("id", "")),
                str(p.get("nombre", "")),
                str(p.get("categoria", "")),
                str(p.get("marca", "")),
                str(p.get("modelo", "")),
                str(p.get("sku_woo", "")),
            ]).lower()
        self.sales_product_cache = productos
        self.sales_product_cache_loaded = True

        for p in productos:
            texto = p.get("_search_text") or f'{p.get("nombre","")} {p.get("categoria","")} {p.get("marca","")} {p.get("modelo","")}'.lower()
            if q and q not in texto:
                continue

            self.productos_cache[int(p["id"])] = p
            stock = int(p.get("stock", 0) or 0)

            if stock == 0:
                tag = "out"
            elif stock <= 5:
                tag = "low"
            else:
                tag = "ok"

            self.tree_products.insert(
                "",
                "end",
                values=(
                    p["id"],
                    p.get("nombre", ""),
                    p.get("categoria", ""),
                    p.get("marca", ""),
                    p.get("modelo", ""),
                    f'{float(p.get("precio_compra", 0) or 0):.2f}',
                    f'{float(p.get("precio_venta", 0) or 0):.2f}',
                    stock,
                    p.get("almacen", "TIENDA") or "TIENDA",
                    p.get("observacion", "")
                ),
                tags=(tag,)
            )

    def product_series_manager_ui(self):
        sel = self.tree_products.selection()
        if not sel:
            messagebox.showwarning("Series", "Selecciona un producto.")
            return
        vals = self.tree_products.item(sel[0], "values")
        producto_id = int(vals[0])
        producto_nombre = str(vals[1])

        win = tk.Toplevel(self.root)
        win.title("Agregar series masivas")
        win.geometry("780x600")
        win.configure(bg=CARD_BG)
        tk.Label(win, text=producto_nombre, bg=CARD_BG, fg=TEXT, font=("Arial", 14, "bold"), wraplength=720).pack(anchor="w", padx=12, pady=(10, 4))

        form = tk.Frame(win, bg=CARD_BG)
        form.pack(fill="x", padx=12, pady=6)
        tk.Label(form, text="Series masivas\n(una por linea)", bg=CARD_BG, justify="right").grid(row=0, column=0, padx=4, pady=4)
        ent_serie = tk.Text(form, width=34, height=7)
        ent_serie.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        tk.Label(form, text="Proveedor", bg=CARD_BG).grid(row=0, column=2, padx=4, pady=4)
        ent_prov = tk.Entry(form, width=28)
        ent_prov.grid(row=0, column=3, padx=4, pady=4)
        ent_prov.insert(0, getattr(self, "last_series_provider", ""))
        tk.Label(form, text="Almacén", bg=CARD_BG).grid(row=1, column=0, padx=4, pady=4)
        combo_almacen = ttk.Combobox(form, values=ALMACEN_OPTIONS, state="readonly", width=18)
        combo_almacen.set(getattr(self, "last_series_almacen", "TIENDA") or "TIENDA")
        combo_almacen.grid(row=1, column=1, padx=4, pady=4)
        tk.Label(form, text="Estado", bg=CARD_BG).grid(row=1, column=2, padx=4, pady=4)
        combo_estado = ttk.Combobox(form, values=["DISPONIBLE", "VENDIDO", "GARANTIA", "RESERVADO", "AGOTADO"], state="readonly", width=14)
        combo_estado.set("DISPONIBLE")
        combo_estado.grid(row=1, column=3, padx=4, pady=4)
        selected_serie_id = {"id": ""}

        def serie_text():
            return ent_serie.get("1.0", tk.END).strip()

        def set_serie_text(value=""):
            ent_serie.delete("1.0", tk.END)
            if value:
                ent_serie.insert("1.0", str(value))

        quick_actions = tk.Frame(win, bg=CARD_BG)
        quick_actions.pack(fill="x", padx=12, pady=(0, 4))

        def add_another_line():
            current = serie_text()
            set_serie_text((current + "\n") if current else "")
            ent_serie.focus_set()
            ent_serie.mark_set(tk.INSERT, tk.END)

        def selected_series_text():
            selected = []
            for iid in tree.selection():
                vals_row = tree.item(iid, "values")
                if len(vals_row) > 1 and vals_row[1]:
                    selected.append(str(vals_row[1]))
            return "\n".join(selected) or serie_text()

        def salida_manual_ui():
            series_prefill = selected_series_text()
            popup = tk.Toplevel(win)
            popup.title("Salida manual por series")
            popup.geometry("540x460")
            popup.configure(bg=CARD_BG)
            popup.transient(win)
            popup.grab_set()

            box = tk.Frame(popup, bg=CARD_BG)
            box.pack(fill="both", expand=True, padx=14, pady=14)
            tk.Label(box, text=f"Producto: {producto_nombre}", bg=CARD_BG, fg=TEXT, font=("Arial", 11, "bold"), wraplength=500).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
            tk.Label(box, text="Tipo salida", bg=CARD_BG, fg=TEXT).grid(row=1, column=0, sticky="w", pady=4)
            tipo_salida = ttk.Combobox(box, values=["PASE", "BOLETA", "FACTURA"], state="readonly", width=14)
            tipo_salida.set("PASE")
            tipo_salida.grid(row=1, column=1, sticky="w", pady=4)
            tk.Label(box, text="Doc. externo", bg=CARD_BG, fg=TEXT).grid(row=2, column=0, sticky="w", pady=4)
            doc_ext = tk.Entry(box, width=34)
            doc_ext.grid(row=2, column=1, sticky="ew", pady=4)
            tk.Label(box, text="Nombre / tienda", bg=CARD_BG, fg=TEXT).grid(row=3, column=0, sticky="w", pady=4)
            cliente_ext = tk.Entry(box, width=34)
            cliente_ext.insert(0, "SALIDA MANUAL")
            cliente_ext.grid(row=3, column=1, sticky="ew", pady=4)
            tk.Label(box, text="Series", bg=CARD_BG, fg=TEXT).grid(row=4, column=0, sticky="nw", pady=4)
            series_txt = tk.Text(box, width=42, height=8)
            series_txt.insert("1.0", series_prefill)
            series_txt.grid(row=4, column=1, sticky="nsew", pady=4)
            tk.Label(box, text="Observación", bg=CARD_BG, fg=TEXT).grid(row=5, column=0, sticky="w", pady=4)
            obs_ext = tk.Entry(box, width=34)
            obs_ext.insert(0, "Venta registrada en otro sistema")
            obs_ext.grid(row=5, column=1, sticky="ew", pady=4)
            box.grid_columnconfigure(1, weight=1)
            box.grid_rowconfigure(4, weight=1)

            def guardar_salida():
                payload = {
                    "tipo": tipo_salida.get() or "PASE",
                    "numero": doc_ext.get().strip(),
                    "cliente_nombre": cliente_ext.get().strip() or "SALIDA MANUAL",
                    "fecha_emision": today_ymd(),
                    "series_texto": series_txt.get("1.0", tk.END).strip(),
                    "usuario_emisor": self.user.get("usuario", ""),
                    "observacion": obs_ext.get().strip() or "Salida manual por series",
                }
                if not payload["series_texto"]:
                    messagebox.showwarning("Salida", "Ingresa una o mas series.")
                    return
                r = crear_documento_manual_series(payload)
                if api_response_ok(r):
                    play_document_sound("success")
                    messagebox.showinfo("Salida", f"Salida registrada: {r.get('tipo')} {r.get('numero')}")
                    popup.destroy()
                    load_rows()
                    self.refresh_products()
                else:
                    messagebox.showerror("Salida", api_response_error(r, "No se pudo registrar la salida manual."))

            buttons = tk.Frame(popup, bg=CARD_BG)
            buttons.pack(fill="x", padx=14, pady=(0, 14))
            tk.Button(buttons, text="Cancelar", command=popup.destroy, bg="#64748b", fg="white", relief="flat", padx=12, pady=7).pack(side="right", padx=4)
            tk.Button(buttons, text="Dar salida como venta", command=guardar_salida, bg="#dc2626", fg="white", relief="flat", padx=12, pady=7).pack(side="right", padx=4)

        tk.Button(quick_actions, text="+ Otra serie", command=add_another_line, bg="#e2e8f0", fg=TEXT, relief="flat", padx=12, pady=6).pack(side="left", padx=4)
        tk.Button(quick_actions, text="Salida manual", command=salida_manual_ui, bg="#2563eb", fg="white", relief="flat", padx=12, pady=6).pack(side="left", padx=4)

        cols = ("ID", "Serie", "Estado", "Proveedor", "Almacén", "Ingreso", "Usuario", "Salida")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=14)
        for col, width in zip(cols, (60, 180, 95, 145, 85, 82, 95, 82)):
            tree.heading(col, text=col)
            tree.column(col, width=width, anchor="center")
        tree.pack(fill="both", expand=True, padx=12, pady=8)

        def load_rows():
            for iid in tree.get_children():
                tree.delete(iid)
            for s in obtener_series_producto(producto_id) or []:
                tree.insert("", "end", values=(s.get("id", ""), s.get("serie", ""), s.get("estado", ""), s.get("proveedor", ""), s.get("almacen", "TIENDA"), s.get("fecha_ingreso", ""), s.get("usuario_ingreso", ""), s.get("fecha_salida", "")))

        def clear_form():
            selected_serie_id["id"] = ""
            set_serie_text("")
            ent_prov.delete(0, tk.END)
            ent_prov.insert(0, getattr(self, "last_series_provider", ""))
            combo_almacen.set(getattr(self, "last_series_almacen", "TIENDA") or "TIENDA")
            combo_estado.set("DISPONIBLE")

        def clear_after_save():
            selected_serie_id["id"] = ""
            set_serie_text("")
            ent_serie.focus_set()

        def pick_row(event=None):
            row_sel = tree.selection()
            if not row_sel:
                return
            row_vals = tree.item(row_sel[0], "values")
            selected_serie_id["id"] = row_vals[0]
            set_serie_text(row_vals[1])
            ent_prov.delete(0, tk.END); ent_prov.insert(0, row_vals[3])
            combo_almacen.set(row_vals[4] or "TIENDA")
            combo_estado.set(row_vals[2] or "DISPONIBLE")

        def save_row():
            serie_txt = serie_text()
            if not serie_txt:
                messagebox.showwarning("Series", "Ingresa la serie.")
                return
            payload = {
                "producto_id": producto_id,
                "serie": serie_txt,
                "proveedor": ent_prov.get().strip(),
                "estado": combo_estado.get() or "DISPONIBLE",
                "almacen": combo_almacen.get().strip() or "TIENDA",
                "fecha_ingreso": today_ymd(),
                "usuario_ingreso": self.user.get("usuario", ""),
            }
            if selected_serie_id["id"]:
                r = actualizar_serie(selected_serie_id["id"], payload)
            else:
                r = guardar_serie(payload)
            if api_response_ok(r):
                self.last_series_provider = ent_prov.get().strip()
                self.last_series_almacen = combo_almacen.get().strip() or "TIENDA"
                clear_after_save()
                load_rows()
                self.refresh_products()
            else:
                messagebox.showerror("Series", api_response_error(r, "No se pudo guardar la serie."))

        def delete_row():
            if not selected_serie_id["id"]:
                messagebox.showwarning("Series", "Selecciona una serie.")
                return
            if not messagebox.askyesno("Series", f"Eliminar serie {serie_text()}?"):
                return
            r = eliminar_serie(selected_serie_id["id"])
            if api_response_ok(r):
                clear_form()
                load_rows()
                self.refresh_products()
            else:
                messagebox.showerror("Series", api_response_error(r, "No se pudo eliminar la serie."))

        actions = tk.Frame(win, bg=CARD_BG)
        actions.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(actions, text="Guardar serie(s)", command=save_row, bg="#7c3aed", fg="white", relief="flat", padx=14, pady=7).pack(side="left", padx=4)
        tk.Button(actions, text="Limpiar", command=clear_form, bg="#e2e8f0", fg=TEXT, relief="flat", padx=14, pady=7).pack(side="left", padx=4)
        tk.Button(actions, text="Eliminar", command=delete_row, bg="#dc2626", fg="white", relief="flat", padx=14, pady=7).pack(side="left", padx=4)
        tree.bind("<<TreeviewSelect>>", pick_row)
        ent_serie.focus_set()
        load_rows()

    def edit_product_ui(self, event=None):
        sel = self.tree_products.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona un producto para editar.")
            return

        vals = self.tree_products.item(sel[0], "values")
        producto_id = int(vals[0])
        p = self.productos_cache.get(producto_id)

        if not p:
            messagebox.showerror("Error", "No se encontró el producto seleccionado.")
            return

        categorias = product_category_options()

        win = tk.Toplevel(self.root)
        win.title("Editar producto")
        win.geometry("640x600")
        win.configure(bg=CARD_BG)

        form = tk.Frame(win, bg=CARD_BG)
        form.pack(fill="both", expand=True, padx=15, pady=15)

        fields = {}

        def add_entry(row, label, value="", combo=False, options=None):
            tk.Label(form, text=label, bg=CARD_BG, fg=TEXT).grid(row=row, column=0, padx=6, pady=6, sticky="e")
            if combo:
                values = options or categorias
                ent = ttk.Combobox(form, values=values, state="readonly", width=32)
                ent.set(value if value in values else values[0])
            else:
                ent = tk.Entry(form, width=35)
                ent.insert(0, str(value or ""))
            ent.grid(row=row, column=1, padx=6, pady=6, sticky="w")
            fields[label] = ent

        add_entry(0, "Nombre", p.get("nombre", ""))
        add_entry(1, "Categoría", p.get("categoria", ""), combo=True)
        add_entry(2, "Marca", p.get("marca", ""))
        add_entry(3, "Modelo", p.get("modelo", ""))
        add_entry(4, "P.Compra", p.get("precio_compra", 0))
        add_entry(5, "P.Venta", p.get("precio_venta", 0))
        add_entry(6, "Stock", p.get("stock", 0))
        add_entry(7, "Almacén", p.get("almacen", "TIENDA") or "TIENDA", combo=True, options=ALMACEN_OPTIONS)
        add_entry(8, "Imagen / foto", p.get("imagen_url", ""))
        tk.Label(form, text="Observación", bg=CARD_BG, fg=TEXT).grid(row=9, column=0, padx=6, pady=6, sticky="ne")
        obs_txt = tk.Text(form, width=35, height=4)
        obs_txt.grid(row=9, column=1, padx=6, pady=6, sticky="w")
        obs_txt.insert("1.0", str(p.get("observacion", "") or ""))

        tk.Button(
            form,
            text="Subir/cambiar imagen",
            command=lambda: self.pick_product_image(fields["Imagen / foto"]),
            bg="#0f766e",
            fg="white",
            relief="flat"
        ).grid(row=10, column=1, padx=6, pady=6, sticky="w")

        def guardar_edicion():
            try:
                payload = {
                    "nombre": fields["Nombre"].get().strip(),
                    "categoria": fields["Categoría"].get().strip(),
                    "marca": fields["Marca"].get().strip(),
                    "modelo": fields["Modelo"].get().strip(),
                    "precio_compra": float(fields["P.Compra"].get() or 0),
                    "precio_venta": float(fields["P.Venta"].get() or 0),
                    "stock": int(fields["Stock"].get() or 0),
                    "almacen": fields["Almacén"].get().strip() or "TIENDA",
                    "imagen_url": fields["Imagen / foto"].get().strip(),
                    "observacion": obs_txt.get("1.0", "end").strip()
                }
            except Exception:
                messagebox.showerror("Error", "Revisa precios y stock.")
                return

            if not payload["nombre"]:
                messagebox.showwarning("Aviso", "El nombre no puede estar vacío.")
                return

            r = actualizar_producto(producto_id, payload)
            if api_response_ok(r):
                messagebox.showinfo("Éxito", "Producto actualizado.")
                self.auto_sync_product_after_save(producto_id)
                win.destroy()
                self.refresh_products()
                try:
                    self.comp_prod["values"] = [f'{x["id"]} - {x["nombre"]}' for x in obtener_productos()]
                except Exception:
                    pass
            else:
                messagebox.showerror("Error", api_response_error(r, "No se pudo actualizar el producto."))

        tk.Button(
            form,
            text="Guardar cambios",
            command=guardar_edicion,
            bg="#059669",
            fg="white",
            relief="flat",
            width=20
        ).grid(row=10, column=1, pady=18, sticky="w")



    def delete_product_ui(self):
        sel = self.tree_products.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona un producto para eliminar.")
            return

        vals = self.tree_products.item(sel[0], "values")
        producto_id = int(vals[0])
        nombre = vals[1]

        confirmar = messagebox.askyesno(
            "Eliminar producto",
            f"¿Seguro que deseas eliminar este producto?\n\n{nombre}\n\nTambién se eliminarán sus series registradas."
        )
        if not confirmar:
            return

        r = eliminar_producto(producto_id)
        if api_response_ok(r):
            messagebox.showinfo("Éxito", "Producto eliminado.")
            self.registrar_accion("PRODUCTO ELIMINADO", str(nombre))
            self.refresh_products()
            self.refresh_inventory_product_combo()
            self.cargar_inventario_categoria()
            try:
                self.comp_prod["values"] = [f'{x["id"]} - {x["nombre"]}' for x in obtener_productos()]
            except Exception:
                pass
        else:
            messagebox.showerror("Error", api_response_error(r, "No se pudo eliminar el producto."))

    def sync_selected_product_woo(self):
        sel = self.tree_products.selection()
        if not sel:
            messagebox.showwarning("WooCommerce", "Selecciona un producto para sincronizar.")
            return
        vals = self.tree_products.item(sel[0], "values")
        producto_id = int(vals[0])
        try:
            fn = getattr(api_client, "woo_sincronizar_producto_erp", None) if api_client is not None else None
            if callable(fn):
                r = fn(producto_id)
            else:
                r = _api_json("post", f"/web/woocommerce/sync-product/{producto_id}", {"ok": False})
        except Exception as e:
            messagebox.showerror("WooCommerce", f"No se pudo conectar.\n{e}")
            return
        if api_response_ok(r):
            data = api_response_get(r, "data", {}) or {}
            messagebox.showinfo("WooCommerce", f'{r.get("msg", "Producto sincronizado.")}\nID Woo: {data.get("id", "")}\nSKU: {data.get("sku", "")}')
        else:
            messagebox.showerror("WooCommerce", api_response_error(r, "No se pudo sincronizar con WooCommerce."))

    def woo_auto_sync_enabled(self):
        try:
            return bool(self.cfg.get("woo_auto_sync", False))
        except Exception:
            return False

    def auto_sync_product_after_save(self, producto_id):
        if not producto_id or not self.woo_auto_sync_enabled():
            return
        try:
            fn = getattr(api_client, "woo_sincronizar_producto_erp", None) if api_client is not None else None
            if callable(fn):
                fn(int(producto_id))
        except Exception:
            pass



    # INVENTARIO
    def build_inventario(self):
        frame = self.frames["inventario"]
        card = self.set_card(frame)

        tk.Label(
            card,
            text="Inventario / Control por categoría",
            bg=CARD_BG,
            fg=TEXT,
            font=("Arial", 20, "bold")
        ).pack(anchor="w", padx=12, pady=10)

        tk.Label(
            card,
            text="Elige categoría para conteo. Doble clic sobre un producto para ver ingreso, venta/salida, proveedor y series.",
            bg=CARD_BG,
            fg=MUTED,
            font=("Arial", 10)
        ).pack(anchor="w", padx=12, pady=(0, 6))

        categorias = product_category_options()

        # =========================
        # BLOQUE 1: FILTRO / CONTEO
        # =========================
        filtro = tk.LabelFrame(card, text="Conteo por categoría", bg=CARD_BG, fg=TEXT)
        filtro.pack(fill="x", padx=12, pady=6)

        tk.Label(filtro, text="Categoría", bg=CARD_BG).pack(side="left", padx=(8, 4))

        self.inv_categoria = ttk.Combobox(
            filtro,
            width=30,
            state="readonly",
            values=categorias
        )
        self.inv_categoria.pack(side="left", padx=6, pady=8)
        self.inv_categoria.set(default_product_category())

        tk.Label(filtro, text="Buscar", bg=CARD_BG).pack(side="left", padx=(12, 4))
        self.inv_buscar = tk.Entry(filtro, width=30)
        self.inv_buscar.pack(side="left", padx=6)
        self.inv_buscar.bind("<KeyRelease>", lambda e: self.cargar_inventario_categoria())

        tk.Button(
            filtro,
            text="Cargar categoría",
            command=self.cargar_inventario_categoria,
            bg="#2563eb",
            fg="white",
            relief="flat"
        ).pack(side="left", padx=6)

        tk.Button(
            filtro,
            text="Registrar conteo",
            command=self.editar_conteo_inventario,
            bg="#7c3aed",
            fg="white",
            relief="flat"
        ).pack(side="left", padx=6)

        tk.Button(
            filtro,
            text="Aplicar ajuste",
            command=self.aplicar_ajuste_inventario,
            bg="#059669",
            fg="white",
            relief="flat"
        ).pack(side="left", padx=6)

        tk.Button(
            filtro,
            text="Transferir sucursal",
            command=self.transferir_stock_inventario_ui,
            bg="#d97706",
            fg="white",
            relief="flat"
        ).pack(side="left", padx=6)

        conteo_scan = tk.LabelFrame(card, text="Inventariado por pistola de series", bg=CARD_BG, fg=TEXT)
        conteo_scan.pack(fill="x", padx=12, pady=6)
        self.inv_conteo_id = ""
        tk.Button(conteo_scan, text="Comenzar inventario", command=self.comenzar_inventario_categoria_ui, bg="#0f766e", fg="white", relief="flat").pack(side="left", padx=6, pady=8)
        tk.Label(conteo_scan, text="Serie", bg=CARD_BG, fg=TEXT).pack(side="left", padx=(10, 4))
        self.inv_scan_entry = tk.Entry(conteo_scan, width=34)
        self.inv_scan_entry.pack(side="left", padx=4)
        self.inv_scan_entry.bind("<Return>", lambda e: self.escanear_inventario_categoria_ui())
        tk.Button(conteo_scan, text="Contar serie", command=self.escanear_inventario_categoria_ui, bg="#2563eb", fg="white", relief="flat").pack(side="left", padx=6)
        tk.Button(conteo_scan, text="Refrescar conteo", command=self.refrescar_inventario_conteo_ui, bg="#334155", fg="white", relief="flat").pack(side="left", padx=6)
        tk.Button(conteo_scan, text="Cerrar inventario", command=self.cerrar_inventario_conteo_ui, bg="#dc2626", fg="white", relief="flat").pack(side="left", padx=6)
        self.inv_scan_status = tk.Label(conteo_scan, text="Sin inventario iniciado", bg=CARD_BG, fg=MUTED, font=("Arial", 10, "bold"))
        self.inv_scan_status.pack(side="left", padx=10)

        self.inv_resumen_conteo = tk.Label(
            card,
            text="Conteo físico: sin datos",
            bg=CARD_BG,
            fg=TEXT,
            font=("Arial", 11, "bold")
        )
        self.inv_resumen_conteo.pack(anchor="w", padx=14, pady=(2, 4))

        # =========================
        # BLOQUE 2: AGREGAR SERIES
        # =========================
        serie_box = tk.LabelFrame(card, text="Agregar serie / ingreso de producto", bg=CARD_BG, fg=TEXT)
        serie_box.pack(fill="x", padx=12, pady=6)

        tk.Label(serie_box, text="Buscar producto", bg=CARD_BG).grid(row=0, column=0, padx=6, pady=6, sticky="e")
        self.inv_buscar_producto = tk.Entry(serie_box, width=45)
        self.inv_buscar_producto.grid(row=0, column=1, padx=6, pady=6, sticky="w")
        self.inv_buscar_producto.bind("<KeyRelease>", lambda e: self.filter_inventory_product_combo())
        tk.Button(
            serie_box,
            text="Seleccionar",
            command=self.select_inventory_product_from_tree,
            bg="#2563eb",
            fg="white",
            relief="flat"
        ).grid(row=0, column=3, padx=6, pady=6, sticky="w")

        tk.Label(serie_box, text="Producto", bg=CARD_BG).grid(row=1, column=0, padx=6, pady=6, sticky="e")
        self.inv_producto_combo = ttk.Combobox(serie_box, width=45, state="readonly", height=15)
        self.inv_producto_combo.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        tk.Label(serie_box, text="Serie", bg=CARD_BG).grid(row=1, column=2, padx=6, pady=6, sticky="e")
        self.inv_serie_entry = tk.Entry(serie_box, width=24)
        self.inv_serie_entry.grid(row=1, column=3, padx=6, pady=6, sticky="w")
        self.inv_serie_entry.bind("<Return>", lambda e: self.guardar_serie_inventario_ui())

        tk.Label(serie_box, text="Proveedor", bg=CARD_BG).grid(row=2, column=0, padx=6, pady=6, sticky="e")
        self.inv_proveedor_entry = tk.Entry(serie_box, width=45)
        self.inv_proveedor_entry.grid(row=2, column=1, padx=6, pady=6, sticky="w")
        self.inv_proveedor_entry.insert(0, getattr(self, "last_series_provider", ""))

        tk.Label(serie_box, text="Fecha ingreso", bg=CARD_BG).grid(row=2, column=2, padx=6, pady=6, sticky="e")
        if DateEntry:
            self.inv_fecha_ingreso = DateEntry(serie_box, width=18, date_pattern="yyyy-mm-dd")
        else:
            self.inv_fecha_ingreso = tk.Entry(serie_box, width=20)
            self.inv_fecha_ingreso.insert(0, "YYYY-MM-DD")
        self.inv_fecha_ingreso.grid(row=2, column=3, padx=6, pady=6, sticky="w")

        tk.Label(serie_box, text="Estado", bg=CARD_BG).grid(row=3, column=0, padx=6, pady=6, sticky="e")
        self.inv_estado_combo = ttk.Combobox(
            serie_box,
            width=20,
            state="readonly",
            values=["DISPONIBLE", "RESERVADO", "VENDIDO", "GARANTIA"]
        )
        self.inv_estado_combo.grid(row=3, column=1, padx=6, pady=6, sticky="w")
        self.inv_estado_combo.set("DISPONIBLE")

        tk.Label(serie_box, text="Almacén", bg=CARD_BG).grid(row=3, column=2, padx=6, pady=6, sticky="e")
        self.inv_almacen_combo = ttk.Combobox(serie_box, width=18, state="readonly", values=ALMACEN_OPTIONS)
        self.inv_almacen_combo.set(getattr(self, "last_series_almacen", "TIENDA") or "TIENDA")
        self.inv_almacen_combo.grid(row=3, column=3, padx=6, pady=6, sticky="w")

        tk.Button(
            serie_box,
            text="Guardar serie",
            command=self.guardar_serie_inventario_ui,
            bg="#0f766e",
            fg="white",
            relief="flat"
        ).grid(row=3, column=4, padx=6, pady=6, sticky="w")
        tk.Button(
            serie_box,
            text="Cambiar serie",
            command=self.actualizar_serie_inventario_ui,
            bg="#f59e0b",
            fg="white",
            relief="flat"
        ).grid(row=3, column=5, padx=6, pady=6, sticky="w")

        tk.Button(
            serie_box,
            text="Ver series del producto",
            command=self.abrir_detalle_producto_combo,
            bg="#334155",
            fg="white",
            relief="flat"
        ).grid(row=3, column=6, padx=6, pady=6, sticky="w")

        tk.Label(serie_box, text="Buscar serie", bg=CARD_BG).grid(row=4, column=0, padx=6, pady=6, sticky="e")
        self.inv_buscar_serie = tk.Entry(serie_box, width=45)
        self.inv_buscar_serie.grid(row=4, column=1, padx=6, pady=6, sticky="w")
        self.inv_buscar_serie.bind("<Return>", lambda e: self.buscar_series_inventario_ui())
        tk.Button(
            serie_box,
            text="Buscar series",
            command=self.buscar_series_inventario_ui,
            bg="#0891b2",
            fg="white",
            relief="flat"
        ).grid(row=4, column=3, padx=6, pady=6, sticky="w")
        tk.Button(
            serie_box,
            text="Eliminar serie",
            command=self.eliminar_serie_inventario_ui,
            bg="#dc2626",
            fg="white",
            relief="flat"
        ).grid(row=4, column=4, padx=6, pady=6, sticky="w")

        # =========================
        # TABLA PRINCIPAL
        # =========================
        cols = ("ID", "Producto", "Categoría", "Marca", "Modelo", "Stock sistema", "Conteo físico", "Diferencia")
        self.tree_series = ttk.Treeview(card, columns=cols, show="headings", height=14)

        widths = [60, 280, 150, 120, 120, 110, 110, 100]
        for c, w in zip(cols, widths):
            self.tree_series.heading(c, text=c)
            self.tree_series.column(c, anchor="center", width=w)

        self.tree_series.pack(fill="both", expand=True, padx=12, pady=8)

        # Doble clic = ver historial/detalle del producto y sus series
        self.tree_series.bind("<Double-1>", self.abrir_detalle_inventario_producto)
        self.tree_series.bind("<<TreeviewSelect>>", lambda e: self.select_inventory_product_from_tree(silent=True))

        self.tree_series.tag_configure("ok", background="#dcfce7", foreground="#0f172a")
        self.tree_series.tag_configure("low", background="#fef9c3", foreground="#0f172a")
        self.tree_series.tag_configure("out", background="#fee2e2", foreground="#0f172a")
        self.tree_series.tag_configure("sobran", background="#dbeafe", foreground="#0f172a")
        self.tree_series.tag_configure("faltan", background="#fee2e2", foreground="#0f172a")
        self.tree_series.tag_configure("cuadrado", background="#dcfce7", foreground="#0f172a")

        scan_cols = ("Serie", "Producto", "Estado")
        self.tree_inv_scans = ttk.Treeview(card, columns=scan_cols, show="headings", height=5)
        for c, w in zip(scan_cols, [180, 430, 160]):
            self.tree_inv_scans.heading(c, text=c)
            self.tree_inv_scans.column(c, anchor="center", width=w)
        self.tree_inv_scans.tag_configure("OK", background="#dcfce7", foreground="#0f172a")
        self.tree_inv_scans.tag_configure("ERROR", background="#fee2e2", foreground="#0f172a")
        self.tree_inv_scans.pack(fill="x", padx=12, pady=(0, 8))

        self.refresh_inventory_product_combo()

    def refresh_inventory_product_combo(self):
        try:
            productos = obtener_productos()
            self.inv_productos_cache = productos
            valores = [
                f'{p["id"]} - {p.get("nombre","")} | {p.get("marca","")} | {p.get("modelo","")}'
                for p in productos
            ]
            self.inv_producto_combo["values"] = valores
            if valores and not self.inv_producto_combo.get():
                self.inv_producto_combo.set(valores[0])
        except Exception:
            self.inv_producto_combo["values"] = []
            self.inv_productos_cache = []

    def filter_inventory_product_combo(self):
        productos = getattr(self, "inv_productos_cache", None)
        if productos is None:
            try:
                productos = obtener_productos()
                self.inv_productos_cache = productos
            except Exception:
                productos = []
        q = self.inv_buscar_producto.get().strip().lower() if hasattr(self, "inv_buscar_producto") else ""
        tokens = [t for t in q.split() if t]
        filtrados = []
        for p in productos:
            texto = " ".join([
                str(p.get("id", "")),
                str(p.get("nombre", "")),
                str(p.get("categoria", "")),
                str(p.get("marca", "")),
                str(p.get("modelo", "")),
                str(p.get("sku_woo", "")),
            ]).lower()
            if not tokens or all(t in texto for t in tokens):
                filtrados.append(p)
        valores = [
            f'{p["id"]} - {p.get("nombre","")} | {p.get("marca","")} | {p.get("modelo","")}'
            for p in filtrados[:60]
        ]
        self.inv_producto_combo["values"] = valores
        if valores:
            self.inv_producto_combo.set(valores[0])

    def set_inventory_product_combo_by_id(self, producto_id):
        producto_id = str(producto_id or "").strip()
        productos = getattr(self, "inv_productos_cache", None) or []
        if not productos:
            try:
                productos = obtener_productos()
                self.inv_productos_cache = productos
            except Exception:
                productos = []
        for p in productos:
            if str(p.get("id", "")) == producto_id:
                self.inv_producto_combo.set(f'{p["id"]} - {p.get("nombre","")} | {p.get("marca","")} | {p.get("modelo","")}')
                return True
        return False

    def select_inventory_product_from_tree(self, silent=False):
        if not hasattr(self, "tree_series") or not self.tree_series.selection():
            if not silent:
                messagebox.showwarning("Inventario", "Selecciona un producto de la tabla.")
            return None
        vals = list(self.tree_series.item(self.tree_series.selection()[0], "values"))
        producto_id = vals[0] if vals else ""
        self.set_inventory_product_combo_by_id(producto_id)
        if hasattr(self, "inv_buscar_producto"):
            self.inv_buscar_producto.delete(0, tk.END)
            self.inv_buscar_producto.insert(0, str(vals[1] if len(vals) > 1 else ""))
        return producto_id

    def selected_inventory_producto_id(self):
        producto_txt = self.inv_producto_combo.get().strip()
        if not producto_txt or " - " not in producto_txt:
            return None
        try:
            return int(producto_txt.split(" - ")[0])
        except Exception:
            return None

    def current_inventory_serie_payload(self):
        producto_id = self.selected_inventory_producto_id()
        if producto_id is None:
            return None, "Selecciona un producto."
        serie = self.inv_serie_entry.get().strip()
        if not serie:
            return None, "Ingresa la serie."
        if DateEntry and hasattr(self.inv_fecha_ingreso, "get_date"):
            fecha_ingreso = str(self.inv_fecha_ingreso.get_date())
        else:
            fecha_ingreso = self.inv_fecha_ingreso.get().strip()
            if fecha_ingreso == "YYYY-MM-DD":
                fecha_ingreso = ""
        return {
            "producto_id": producto_id,
            "serie": serie,
            "proveedor": self.inv_proveedor_entry.get().strip(),
            "estado": self.inv_estado_combo.get().strip() or "DISPONIBLE",
            "almacen": self.inv_almacen_combo.get().strip() if hasattr(self, "inv_almacen_combo") else "TIENDA",
            "fecha_ingreso": fecha_ingreso,
            "fecha_salida": None,
            "usuario_ingreso": self.user.get("usuario", ""),
        }, ""

    def cargar_inventario_categoria(self):
        categoria = self.inv_categoria.get().strip()
        q = ""
        try:
            q = self.inv_buscar.get().strip().lower()
        except Exception:
            q = ""

        for i in self.tree_series.get_children():
            self.tree_series.delete(i)

        for p in obtener_productos():
            if categoria and categoria.lower() != (p.get("categoria") or "").lower():
                continue

            texto = f'{p.get("nombre","")} {p.get("categoria","")} {p.get("marca","")} {p.get("modelo","")}'.lower()
            if q and q not in texto:
                continue

            stock = int(p.get("stock", 0) or 0)
            if stock == 0:
                tag = "out"
            elif stock <= 5:
                tag = "low"
            else:
                tag = "ok"

            self.tree_series.insert(
                "",
                "end",
                values=(
                    p["id"],
                    p.get("nombre", ""),
                    p.get("categoria", ""),
                    p.get("marca", ""),
                    p.get("modelo", ""),
                    stock,
                    "",
                    ""
                ),
                tags=(tag,)
            )
        self.actualizar_resumen_conteo_inventario()

    def actualizar_resumen_conteo_inventario(self):
        total_sistema = 0
        total_fisico = 0
        filas_contadas = 0
        faltan = 0
        sobran = 0

        if not hasattr(self, "tree_series"):
            return

        for row in self.tree_series.get_children():
            vals = list(self.tree_series.item(row, "values"))
            try:
                stock = int(vals[5])
                total_sistema += stock
            except Exception:
                stock = 0

            conteo = vals[6] if len(vals) > 6 else ""
            if conteo in ("", None):
                continue

            try:
                fisico = int(conteo)
            except Exception:
                continue

            filas_contadas += 1
            total_fisico += fisico
            diff = fisico - stock
            if diff < 0:
                faltan += abs(diff)
                self.tree_series.item(row, tags=("faltan",))
            elif diff > 0:
                sobran += diff
                self.tree_series.item(row, tags=("sobran",))
            else:
                self.tree_series.item(row, tags=("cuadrado",))

        if hasattr(self, "inv_resumen_conteo"):
            if filas_contadas == 0:
                self.inv_resumen_conteo.config(text=f"Stock sistema cargado: {total_sistema} | Conteo físico: sin datos", fg=TEXT)
            else:
                balance = total_fisico - total_sistema
                estado = "CUADRADO" if balance == 0 else ("SOBRAN" if balance > 0 else "FALTAN")
                color = "#166534" if balance == 0 else ("#1d4ed8" if balance > 0 else "#b91c1c")
                self.inv_resumen_conteo.config(
                    text=f"Conteo físico: {total_fisico} | Sistema: {total_sistema} | Diferencia: {balance} ({estado}) | Faltan: {faltan} | Sobran: {sobran}",
                    fg=color
                )

    def _apply_inventario_conteo_result(self, result):
        if not api_response_ok(result):
            if hasattr(self, "inv_scan_status"):
                self.inv_scan_status.config(text=api_response_error(result, "No se pudo actualizar conteo."), fg="#b91c1c")
            return False
        conteo = result.get("conteo") or {}
        if conteo.get("id"):
            self.inv_conteo_id = str(conteo.get("id"))
        resumen = result.get("resumen") or {}
        if hasattr(self, "inv_scan_status"):
            self.inv_scan_status.config(
                text=f"Conteo #{self.inv_conteo_id} | Fisico {resumen.get('fisico', 0)} / Sistema {resumen.get('sistema', 0)} | Faltan {resumen.get('faltantes', 0)} | Alertas {resumen.get('errores', 0)}",
                fg="#166534" if int(resumen.get("errores", 0) or 0) == 0 else "#b91c1c"
            )
        productos = {str(p.get("producto_id")): p for p in result.get("productos", []) if p.get("producto_id") is not None}
        if hasattr(self, "tree_series"):
            for row in self.tree_series.get_children():
                vals = list(self.tree_series.item(row, "values"))
                info = productos.get(str(vals[0] if vals else ""))
                if not info:
                    continue
                vals[6] = int(info.get("fisico") or 0)
                vals[7] = int(info.get("diferencia") or 0)
                tag = "cuadrado" if vals[7] == 0 else ("sobran" if vals[7] > 0 else "faltan")
                self.tree_series.item(row, values=vals, tags=(tag,))
        if hasattr(self, "tree_inv_scans"):
            for row in self.tree_inv_scans.get_children():
                self.tree_inv_scans.delete(row)
            for scan in (result.get("scans") or [])[:80]:
                estado = str(scan.get("estado") or "")
                self.tree_inv_scans.insert("", "end", values=(scan.get("serie", ""), scan.get("producto_nombre", ""), estado), tags=("OK" if estado == "OK" else "ERROR",))
        self.actualizar_resumen_conteo_inventario()
        return True

    def comenzar_inventario_categoria_ui(self):
        categoria = self.inv_categoria.get().strip() if hasattr(self, "inv_categoria") else ""
        if not categoria:
            messagebox.showwarning("Inventario", "Selecciona una categoria.")
            return
        self.cargar_inventario_categoria()
        try:
            usuario = self.user.get("usuario", "")
        except Exception:
            usuario = ""
        result = iniciar_inventario_conteo_api(categoria, usuario)
        if self._apply_inventario_conteo_result(result):
            play_document_sound("success")
            if hasattr(self, "inv_scan_entry"):
                self.inv_scan_entry.focus_set()
        else:
            messagebox.showerror("Inventario", api_response_error(result, "No se pudo comenzar inventario."))

    def refrescar_inventario_conteo_ui(self):
        if not getattr(self, "inv_conteo_id", ""):
            messagebox.showwarning("Inventario", "Primero comienza un inventario.")
            return
        result = obtener_inventario_conteo_api(self.inv_conteo_id)
        if not self._apply_inventario_conteo_result(result):
            messagebox.showerror("Inventario", api_response_error(result, "No se pudo refrescar conteo."))

    def escanear_inventario_categoria_ui(self):
        if not getattr(self, "inv_conteo_id", ""):
            messagebox.showwarning("Inventario", "Primero pulsa Comenzar inventario.")
            return
        serie = self.inv_scan_entry.get().strip() if hasattr(self, "inv_scan_entry") else ""
        if not serie:
            return
        try:
            usuario = self.user.get("usuario", "")
        except Exception:
            usuario = ""
        result = escanear_inventario_conteo_api(self.inv_conteo_id, serie, usuario)
        ok = self._apply_inventario_conteo_result(result)
        scan = result.get("scan") if isinstance(result, dict) else None
        estado = str((scan or {}).get("estado") or result.get("estado") or "")
        if ok and estado == "OK":
            play_document_sound("success")
        else:
            play_document_sound("warning")
            if isinstance(result, dict) and result.get("msg"):
                messagebox.showwarning("Inventario", result.get("msg"))
        if hasattr(self, "inv_scan_entry"):
            self.inv_scan_entry.delete(0, tk.END)
            self.inv_scan_entry.focus_set()

    def cerrar_inventario_conteo_ui(self):
        if not getattr(self, "inv_conteo_id", ""):
            messagebox.showwarning("Inventario", "No hay inventario abierto.")
            return
        if not messagebox.askyesno("Inventario", "Cerrar este inventario? Podras consultar el resumen, pero no seguir contando en esta sesion."):
            return
        result = cerrar_inventario_conteo_api(self.inv_conteo_id)
        if self._apply_inventario_conteo_result(result):
            play_document_sound("success")
            messagebox.showinfo("Inventario", "Inventario cerrado.")
        else:
            messagebox.showerror("Inventario", api_response_error(result, "No se pudo cerrar inventario."))

    def guardar_serie_inventario_ui(self):
        payload, error = self.current_inventory_serie_payload()
        if error:
            messagebox.showwarning("Aviso", error)
            return
        r = guardar_serie(payload)
        if api_response_ok(r):
            play_document_sound("success")
            self.last_series_provider = payload.get("proveedor", "")
            self.last_series_almacen = payload.get("almacen", "TIENDA") or "TIENDA"
            self.inv_selected_serie_id = ""
            self.inv_serie_entry.delete(0, tk.END)
            self.inv_serie_entry.focus_set()
            if hasattr(self, "inv_scan_status"):
                self.inv_scan_status.config(text=f"Serie guardada: {payload.get('serie')} | Proveedor: {payload.get('proveedor') or 'sin proveedor'} | Almacén: {payload.get('almacen') or 'TIENDA'}", fg="#166534")
            self.refresh_products()
            self.refresh_inventory_product_combo()
            self.cargar_inventario_categoria()
        else:
            messagebox.showerror("Error", f"No se pudo guardar la serie.\n\nDetalle:\n{r}")
        return

        producto_txt = self.inv_producto_combo.get().strip()
        if not producto_txt or " - " not in producto_txt:
            messagebox.showwarning("Aviso", "Selecciona un producto.")
            return

        try:
            producto_id = int(producto_txt.split(" - ")[0])
        except Exception:
            messagebox.showerror("Error", "Producto inválido.")
            return

        serie = self.inv_serie_entry.get().strip()
        if not serie:
            messagebox.showwarning("Aviso", "Ingresa la serie.")
            return

        if DateEntry and hasattr(self.inv_fecha_ingreso, "get_date"):
            fecha_ingreso = str(self.inv_fecha_ingreso.get_date())
        else:
            fecha_ingreso = self.inv_fecha_ingreso.get().strip()

        payload = {
            "producto_id": producto_id,
            "serie": serie,
            "proveedor": self.inv_proveedor_entry.get().strip(),
            "estado": self.inv_estado_combo.get().strip() or "DISPONIBLE",
            "fecha_ingreso": fecha_ingreso,
            "fecha_salida": None
        }

        r = guardar_serie(payload)
        if api_response_ok(r):
            messagebox.showinfo("Éxito", "Serie guardada correctamente.")
            self.inv_serie_entry.delete(0, tk.END)
            self.inv_proveedor_entry.delete(0, tk.END)
            self.refresh_products()
            self.refresh_inventory_product_combo()
            self.cargar_inventario_categoria()
        else:
            messagebox.showerror("Error", f"No se pudo guardar la serie.\n\nDetalle:\n{r}")

    def cargar_serie_en_formulario_inventario(self, serie_row):
        if not isinstance(serie_row, dict):
            return
        self.inv_selected_serie_id = str(serie_row.get("id") or "")
        self.set_inventory_product_combo_by_id(serie_row.get("producto_id"))
        self.inv_serie_entry.delete(0, tk.END)
        self.inv_serie_entry.insert(0, str(serie_row.get("serie") or ""))
        self.inv_proveedor_entry.delete(0, tk.END)
        self.inv_proveedor_entry.insert(0, str(serie_row.get("proveedor") or ""))
        if hasattr(self, "inv_almacen_combo"):
            self.inv_almacen_combo.set(str(serie_row.get("almacen") or "TIENDA"))
        estado = str(serie_row.get("estado") or "DISPONIBLE").upper()
        if estado in ("DISPONIBLE", "RESERVADO", "VENDIDO", "GARANTIA"):
            self.inv_estado_combo.set(estado)
        fecha = str(serie_row.get("fecha_ingreso") or "")
        if fecha:
            try:
                if DateEntry and hasattr(self.inv_fecha_ingreso, "set_date"):
                    self.inv_fecha_ingreso.set_date(fecha[:10])
                else:
                    self.inv_fecha_ingreso.delete(0, tk.END)
                    self.inv_fecha_ingreso.insert(0, fecha[:10])
            except Exception:
                pass

    def actualizar_serie_inventario_ui(self):
        serie_id = getattr(self, "inv_selected_serie_id", "")
        if not serie_id:
            messagebox.showwarning("Series", "Busca y selecciona una serie para cambiarla.")
            return
        payload, error = self.current_inventory_serie_payload()
        if error:
            messagebox.showwarning("Aviso", error)
            return
        r = actualizar_serie(serie_id, payload)
        if api_response_ok(r):
            play_document_sound("edit")
            messagebox.showinfo("Series", "Serie actualizada correctamente.")
            self.refresh_products()
            self.refresh_inventory_product_combo()
            self.cargar_inventario_categoria()
        else:
            messagebox.showerror("Series", api_response_error(r, "No se pudo actualizar la serie."))

    def eliminar_serie_inventario_ui(self):
        serie_id = getattr(self, "inv_selected_serie_id", "")
        serie_txt = self.inv_serie_entry.get().strip()
        if not serie_id:
            messagebox.showwarning("Series", "Busca y selecciona una serie para eliminarla.")
            return
        if not messagebox.askyesno("Series", f"Se eliminara la serie {serie_txt}. ¿Continuar?"):
            return
        r = eliminar_serie(serie_id)
        if api_response_ok(r):
            play_document_sound("delete")
            messagebox.showinfo("Series", "Serie eliminada correctamente.")
            self.inv_selected_serie_id = ""
            self.inv_serie_entry.delete(0, tk.END)
            self.inv_proveedor_entry.delete(0, tk.END)
            self.refresh_products()
            self.refresh_inventory_product_combo()
            self.cargar_inventario_categoria()
        else:
            messagebox.showerror("Series", api_response_error(r, "No se pudo eliminar la serie."))

    def abrir_detalle_producto_combo(self):
        producto_txt = self.inv_producto_combo.get().strip()
        if not producto_txt or " - " not in producto_txt:
            messagebox.showwarning("Aviso", "Selecciona un producto.")
            return
        try:
            producto_id = int(producto_txt.split(" - ")[0])
        except Exception:
            messagebox.showerror("Error", "Producto inválido.")
            return

        producto = None
        for p in obtener_productos():
            try:
                if int(p.get("id", 0)) == producto_id:
                    producto = p
                    break
            except Exception:
                pass

        if producto and producto.get("categoria"):
            self.inv_categoria.set(producto.get("categoria"))
            self.cargar_inventario_categoria()
            for row in self.tree_series.get_children():
                vals = list(self.tree_series.item(row, "values"))
                try:
                    if int(vals[0]) == producto_id:
                        self.tree_series.selection_set(row)
                        self.tree_series.focus(row)
                        self.tree_series.see(row)
                        break
                except Exception:
                    pass

        self.abrir_detalle_inventario_por_id(producto_id)

    def buscar_series_inventario_ui(self):
        q = self.inv_buscar_serie.get().strip() if hasattr(self, "inv_buscar_serie") else ""
        data = obtener_series(q)
        win = tk.Toplevel(self.root)
        win.title("Buscar series")
        win.geometry("1050x520")

        top = tk.Frame(win)
        top.pack(fill="x", padx=12, pady=10)
        tk.Label(top, text="Buscar serie / producto / proveedor").pack(side="left")
        ent = tk.Entry(top, width=45)
        ent.pack(side="left", padx=8)
        ent.insert(0, q)

        cols = ("Serie ID", "Producto ID", "Producto", "Marca", "Modelo", "Serie", "Proveedor", "Estado", "Ingreso", "Salida")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=17)
        for c, w in zip(cols, [70, 80, 220, 100, 100, 180, 160, 100, 100, 100]):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="center")
        tree.pack(fill="both", expand=True, padx=12, pady=8)
        serie_rows = {}

        def cargar():
            serie_rows.clear()
            for row in tree.get_children():
                tree.delete(row)
            for s in obtener_series(ent.get().strip()):
                iid = tree.insert("", "end", values=(
                    s.get("id", ""),
                    s.get("producto_id", ""),
                    s.get("producto_nombre", ""),
                    s.get("marca", ""),
                    s.get("modelo", ""),
                    s.get("serie", ""),
                    s.get("proveedor", ""),
                    s.get("estado", ""),
                    s.get("fecha_ingreso", ""),
                    s.get("fecha_salida", ""),
                ))
                serie_rows[iid] = s

        def usar_seleccion():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Series", "Selecciona una serie.")
                return
            self.cargar_serie_en_formulario_inventario(serie_rows.get(sel[0], {}))
            win.destroy()

        ent.bind("<Return>", lambda e: cargar())
        tree.bind("<Double-1>", lambda e: usar_seleccion())
        tk.Button(top, text="Buscar", command=cargar, bg="#0891b2", fg="white", relief="flat").pack(side="left", padx=6)
        tk.Button(top, text="Usar / editar", command=usar_seleccion, bg="#f59e0b", fg="white", relief="flat").pack(side="left", padx=6)
        tk.Button(top, text="Cerrar", command=win.destroy, bg="#334155", fg="white", relief="flat").pack(side="right", padx=6)
        cargar()

    def editar_conteo_inventario(self, event=None):
        sel = self.tree_series.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona un producto para registrar conteo.")
            return

        item = self.tree_series.item(sel[0])
        vals = list(item["values"])

        win = tk.Toplevel(self.root)
        win.title("Conteo físico")
        win.geometry("300x170")

        tk.Label(win, text=f"Producto: {vals[1]}", wraplength=260).pack(pady=(10, 2))
        tk.Label(win, text="Cantidad física").pack(pady=5)
        ent = tk.Entry(win)
        ent.pack()
        ent.focus()

        def guardar():
            try:
                conteo = int(ent.get())
                stock = int(vals[5])
                diff = conteo - stock
                vals[6] = conteo
                vals[7] = diff
                self.tree_series.item(sel[0], values=vals)
                self.actualizar_resumen_conteo_inventario()
                win.destroy()
            except Exception:
                messagebox.showerror("Error", "Valor inválido")

        tk.Button(win, text="Guardar conteo", command=guardar, bg="#2563eb", fg="white", relief="flat").pack(pady=10)

    def abrir_detalle_inventario_producto(self, event=None):
        sel = self.tree_series.selection()
        if not sel:
            return
        vals = list(self.tree_series.item(sel[0], "values"))
        producto_id = int(vals[0])
        self.abrir_detalle_inventario_por_id(producto_id)

    def abrir_detalle_inventario_por_id(self, producto_id):
        producto = None
        for p in obtener_productos():
            try:
                if int(p.get("id", 0)) == int(producto_id):
                    producto = p
                    break
            except Exception:
                pass

        win = tk.Toplevel(self.root)
        win.title("Detalle de inventario")
        win.geometry("1050x600")

        header = tk.Frame(win)
        header.pack(fill="x", padx=12, pady=10)

        nombre = producto.get("nombre", "Producto") if producto else "Producto"
        categoria = producto.get("categoria", "") if producto else ""
        marca = producto.get("marca", "") if producto else ""
        modelo = producto.get("modelo", "") if producto else ""
        stock = producto.get("stock", "") if producto else ""

        tk.Label(header, text=nombre, font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        tk.Label(header, text=f"Categoría: {categoria}").grid(row=1, column=0, sticky="w", padx=5)
        tk.Label(header, text=f"Marca: {marca}").grid(row=1, column=1, sticky="w", padx=5)
        tk.Label(header, text=f"Modelo: {modelo}").grid(row=1, column=2, sticky="w", padx=5)
        tk.Label(header, text=f"Stock actual: {stock}").grid(row=1, column=3, sticky="w", padx=5)

        tk.Label(win, text="Series registradas / historial", font=("Arial", 11, "bold")).pack(anchor="w", padx=12, pady=(8, 4))

        cols = ("Serie", "Proveedor", "Estado", "Fecha ingreso", "Fecha venta/salida")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=16)
        for c, w in zip(cols, [260, 240, 130, 170, 170]):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="center")
        tree.pack(fill="both", expand=True, padx=12, pady=8)

        series = []
        for s in obtener_series(""):
            try:
                if int(s.get("producto_id", 0)) == int(producto_id):
                    series.append(s)
            except Exception:
                pass

        if not series:
            tree.insert("", "end", values=("SIN SERIES REGISTRADAS", "", "", "", ""))
        else:
            for s in series:
                tree.insert(
                    "",
                    "end",
                    values=(
                        s.get("serie", ""),
                        s.get("proveedor", ""),
                        s.get("estado", ""),
                        s.get("fecha_ingreso", ""),
                        s.get("fecha_salida", "")
                    )
                )

        tk.Button(win, text="Cerrar", command=win.destroy, bg="#334155", fg="white", relief="flat").pack(pady=8)

    def aplicar_ajuste_inventario(self):
        items = self.tree_series.get_children()
        if not items:
            messagebox.showwarning("Aviso", "No hay productos cargados.")
            return

        if not messagebox.askyesno("Confirmar ajuste", "¿Deseas actualizar el stock real con el conteo físico ingresado?"):
            return

        cambios = 0

        for row in items:
            vals = list(self.tree_series.item(row, "values"))
            producto_id = vals[0]
            stock_actual = vals[5]
            conteo = vals[6]

            if conteo in ("", None):
                continue

            try:
                nuevo_stock = int(conteo)
            except Exception:
                continue

            if int(stock_actual) != nuevo_stock:
                r = ajustar_stock_producto(producto_id, nuevo_stock)
                if api_response_ok(r):
                    cambios += 1

        messagebox.showinfo("Ajuste", f"Se actualizaron {cambios} producto(s).")
        self.cargar_inventario_categoria()
        self.refresh_products()
        self.actualizar_resumen_conteo_inventario()

    def transferir_stock_inventario_ui(self):
        sel = self.tree_series.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona un producto para transferir stock.")
            return
        vals = list(self.tree_series.item(sel[0], "values"))
        producto_id, nombre, stock_actual = vals[0], vals[1], vals[5]

        win = tk.Toplevel(self.root)
        win.title("Transferir stock a sucursal")
        win.geometry("430x285")
        win.resizable(False, False)
        tk.Label(win, text=str(nombre), font=("Arial", 12, "bold"), wraplength=390).pack(pady=(12, 4))
        tk.Label(win, text=f"Stock disponible en esta sucursal: {stock_actual}").pack(pady=(0, 8))

        form = tk.Frame(win)
        form.pack(fill="x", padx=18, pady=4)
        tk.Label(form, text="Sucursal destino").grid(row=0, column=0, sticky="e", padx=6, pady=6)
        cb_destino = ttk.Combobox(form, values=empresa_display_options(), state="readonly", width=28)
        cb_destino.grid(row=0, column=1, sticky="w", padx=6, pady=6)
        opciones = [x for x in empresa_display_options() if empresa_to_key(x) != str(self.user.get("sucursal") or self.user.get("empresa") or "computer_army")]
        cb_destino["values"] = opciones or empresa_display_options()
        if cb_destino["values"]:
            cb_destino.set(cb_destino["values"][0])
        tk.Label(form, text="Cantidad").grid(row=1, column=0, sticky="e", padx=6, pady=6)
        ent_qty = tk.Entry(form, width=12)
        ent_qty.grid(row=1, column=1, sticky="w", padx=6, pady=6)
        ent_qty.insert(0, "1")
        tk.Label(form, text="Nota").grid(row=2, column=0, sticky="e", padx=6, pady=6)
        ent_nota = tk.Entry(form, width=30)
        ent_nota.grid(row=2, column=1, sticky="w", padx=6, pady=6)

        def guardar():
            try:
                cantidad = int(ent_qty.get() or 0)
            except Exception:
                messagebox.showerror("Error", "Cantidad invalida.")
                return
            destino = empresa_to_key(cb_destino.get())
            if cantidad <= 0:
                messagebox.showwarning("Aviso", "La cantidad debe ser mayor a 0.")
                return
            if cantidad > int(stock_actual):
                messagebox.showwarning("Aviso", "No puedes transferir mas del stock disponible.")
                return
            r = transferir_stock_api(producto_id, cantidad, destino, self.user.get("usuario", ""), ent_nota.get().strip())
            if api_response_ok(r):
                self.registrar_accion("TRANSFERENCIA STOCK", f"{cantidad} x {nombre} hacia {destino}")
                messagebox.showinfo("Exito", "Stock transferido correctamente.")
                win.destroy()
                self.refresh_products()
                self.refresh_inventory_product_combo()
                self.cargar_inventario_categoria()
                self.refresh_dashboard()
            else:
                messagebox.showerror("Error", api_response_error(r, "No se pudo transferir el stock."))

        tk.Button(win, text="Transferir", command=guardar, bg="#d97706", fg="white", relief="flat", width=18).pack(pady=12)

    def refresh_series(self):
        try:
            self.refresh_inventory_product_combo()
            self.cargar_inventario_categoria()
        except Exception:
            pass


    # COMPRAS
    def build_compras(self):
        frame = self.frames["compras"]
        card = self.set_card(frame)
        tk.Label(card, text="Compras", bg=CARD_BG, fg=TEXT, font=("Arial", 20, "bold")).pack(anchor="w", padx=12, pady=10)

        form = tk.Frame(card, bg=CARD_BG); form.pack(fill="x", padx=12, pady=8)
        tk.Label(form, text="Proveedor", bg=CARD_BG).grid(row=0, column=0, padx=6, pady=6)
        self.comp_prov = ttk.Combobox(form, values=[], width=35); self.comp_prov.grid(row=0, column=1, padx=6, pady=6)
        tk.Label(form, text="Comprobante", bg=CARD_BG).grid(row=0, column=2, padx=6, pady=6)
        self.comp_doc = tk.Entry(form, width=18); self.comp_doc.grid(row=0, column=3, padx=6, pady=6)
        tk.Label(form, text="Producto", bg=CARD_BG).grid(row=1, column=0, padx=6, pady=6)
        self.comp_prod = ttk.Combobox(form, values=[], width=35); self.comp_prod.grid(row=1, column=1, padx=6, pady=6)
        tk.Label(form, text="Cantidad", bg=CARD_BG).grid(row=1, column=2, padx=6, pady=6)
        self.comp_qty = tk.Entry(form, width=10); self.comp_qty.grid(row=1, column=3, padx=6, pady=6)
        tk.Label(form, text="Costo", bg=CARD_BG).grid(row=1, column=4, padx=6, pady=6)
        self.comp_cost = tk.Entry(form, width=12); self.comp_cost.grid(row=1, column=5, padx=6, pady=6)
        tk.Button(form, text="Agregar item", command=self.add_purchase_item, bg=ACCENT, fg="white", relief="flat").grid(row=1, column=6, padx=6, pady=6)
        tk.Button(form, text="Guardar compra", command=self.save_purchase_ui, bg="#059669", fg="white", relief="flat").grid(row=0, column=6, padx=6, pady=6)

        cols = ("Producto ID", "Descripción", "Cantidad", "Costo", "Total")
        self.tree_purchase = ttk.Treeview(card, columns=cols, show="headings", height=7)
        for c, w in zip(cols, [90, 360, 90, 100, 100]):
            self.tree_purchase.heading(c, text=c); self.tree_purchase.column(c, width=w, anchor="center")
        self.tree_purchase.pack(fill="x", padx=12, pady=8)

        self.tree_purchases = ttk.Treeview(card, columns=("ID", "Fecha", "Proveedor", "Comprobante", "Total", "Usuario"), show="headings", height=8)
        for c, w in zip(("ID", "Fecha", "Proveedor", "Comprobante", "Total", "Usuario"), [60, 150, 240, 120, 100, 100]):
            self.tree_purchases.heading(c, text=c); self.tree_purchases.column(c, width=w, anchor="center")
        self.tree_purchases.pack(fill="both", expand=True, padx=12, pady=8)

    def add_purchase_item(self):
        try:
            pid = int(self.comp_prod.get().split(" - ")[0])
            desc = self.comp_prod.get().split(" - ", 1)[1]
            qty = int(self.comp_qty.get() or 0)
            cost = float(self.comp_cost.get() or 0)
        except Exception:
            messagebox.showerror("Error", "Producto, cantidad o costo inválido.")
            return
        self.items_compra.append({"producto_id": pid, "descripcion": desc, "cantidad": qty, "costo_unitario": cost, "total": qty * cost})
        self.refresh_purchase_items()

    def refresh_purchase_items(self):
        for i in self.tree_purchase.get_children():
            self.tree_purchase.delete(i)
        for x in self.items_compra:
            self.tree_purchase.insert("", "end", values=(x["producto_id"], x["descripcion"], x["cantidad"], f'{x["costo_unitario"]:.2f}', f'{x["total"]:.2f}'))

    def save_purchase_ui(self):
        try:
            prov_id = int(self.comp_prov.get().split(" - ")[0])
            prov_name = self.comp_prov.get().split(" - ", 1)[1]
        except Exception:
            messagebox.showwarning("Aviso", "Selecciona proveedor.")
            return
        if not self.items_compra:
            messagebox.showwarning("Aviso", "Agrega items a la compra.")
            return
        r = guardar_compra({
            "proveedor_id": prov_id,
            "proveedor_nombre": prov_name,
            "comprobante": self.comp_doc.get().strip(),
            "usuario_registro": self.user["usuario"],
            "items": self.items_compra
        })
        if api_response_ok(r):
            messagebox.showinfo("Éxito", "Compra guardada.")
            self.items_compra = []
            self.refresh_purchase_items()
            self.refresh_purchases()
            self.refresh_products()
            self.refresh_dashboard()
            self.refresh_cash()

    def refresh_purchases(self):
        for i in self.tree_purchases.get_children():
            self.tree_purchases.delete(i)
        for c in obtener_compras():
            self.tree_purchases.insert("", "end", values=(c["id"], c["fecha"], c["proveedor_nombre"], c["comprobante"], f'{c["total"]:.2f}', c["usuario_registro"]))

    def abrir_boleta_manual_series_ui(self):
        win = tk.Toplevel(self.root)
        win.title("Boleta manual por series")
        win.geometry("560x520")
        win.configure(bg=CARD_BG)
        win.transient(self.root)
        win.grab_set()

        form = tk.Frame(win, bg=CARD_BG)
        form.pack(fill="both", expand=True, padx=14, pady=14)

        tk.Label(form, text="Tipo", bg=CARD_BG, fg=TEXT).grid(row=0, column=0, sticky="w", pady=5)
        tipo = ttk.Combobox(form, values=["BOLETA", "FACTURA", "PASE"], state="readonly", width=16)
        tipo.set("BOLETA")
        tipo.grid(row=0, column=1, sticky="w", pady=5)

        tk.Label(form, text="Numero", bg=CARD_BG, fg=TEXT).grid(row=1, column=0, sticky="w", pady=5)
        numero = tk.Entry(form, width=32)
        numero.grid(row=1, column=1, sticky="ew", pady=5)

        tk.Label(form, text="Cliente / pase", bg=CARD_BG, fg=TEXT).grid(row=2, column=0, sticky="w", pady=5)
        cliente = tk.Entry(form, width=32)
        cliente.grid(row=2, column=1, sticky="ew", pady=5)

        tk.Label(form, text="Fecha", bg=CARD_BG, fg=TEXT).grid(row=3, column=0, sticky="w", pady=5)
        fecha = tk.Entry(form, width=16)
        fecha.insert(0, today_ymd())
        fecha.grid(row=3, column=1, sticky="w", pady=5)

        tk.Label(form, text="Series", bg=CARD_BG, fg=TEXT).grid(row=4, column=0, sticky="nw", pady=5)
        series = tk.Text(form, height=9, width=48)
        series.grid(row=4, column=1, sticky="nsew", pady=5)

        tk.Label(form, text="Observacion", bg=CARD_BG, fg=TEXT).grid(row=5, column=0, sticky="w", pady=5)
        obs = tk.Entry(form, width=48)
        obs.grid(row=5, column=1, sticky="ew", pady=5)

        form.grid_columnconfigure(1, weight=1)
        form.grid_rowconfigure(4, weight=1)

        def guardar():
            payload = {
                "tipo": tipo.get(),
                "numero": numero.get().strip(),
                "cliente_nombre": cliente.get().strip() or "CLIENTE MANUAL",
                "fecha_emision": fecha.get().strip(),
                "series_texto": series.get("1.0", tk.END).strip(),
                "usuario_emisor": self.user.get("usuario", ""),
                "observacion": obs.get().strip(),
            }
            if not payload["series_texto"]:
                messagebox.showwarning("Series", "Ingresa una o mas series.")
                return
            r = crear_documento_manual_series(payload)
            if api_response_ok(r):
                play_document_sound("success")
                messagebox.showinfo("Documento", f"Registrado: {r.get('tipo')} {r.get('numero')}")
                win.destroy()
                try:
                    self.refresh_contabilidad()
                except Exception:
                    pass
                try:
                    self.refresh_products()
                except Exception:
                    pass
            else:
                messagebox.showerror("Documento", api_response_error(r, "No se pudo registrar el documento manual."))

        actions = tk.Frame(win, bg=CARD_BG)
        actions.pack(fill="x", padx=14, pady=(0, 14))
        tk.Button(actions, text="Cancelar", command=win.destroy, bg="#64748b", fg="white", relief="flat", padx=14, pady=8).pack(side="right", padx=5)
        tk.Button(actions, text="Registrar y descontar", command=guardar, bg=ACCENT, fg="white", relief="flat", padx=14, pady=8).pack(side="right", padx=5)

    # CONTABILIDAD
    def build_contabilidad(self):
        frame = self.frames["contabilidad"]
        card = self.set_card(frame)
        tk.Label(card, text="Contabilidad / Documentos", bg=CARD_BG, fg=TEXT, font=("Arial", 20, "bold")).pack(anchor="w", padx=12, pady=10)

        filtros = tk.LabelFrame(card, text="Buscar documentos", bg=CARD_BG, fg=TEXT)
        filtros.pack(fill="x", padx=12, pady=(0, 8))

        tk.Label(filtros, text="Tipo", bg=CARD_BG).grid(row=0, column=0, padx=6, pady=6)
        self.doc_filtro_tipo = ttk.Combobox(filtros, values=["TODOS", "PROFORMA", "PASE", "NOTA DE VENTA", "BOLETA", "FACTURA"], state="readonly", width=14)
        self.doc_filtro_tipo.grid(row=0, column=1, padx=6, pady=6)
        self.doc_filtro_tipo.set("TODOS")

        tk.Label(filtros, text="Fecha", bg=CARD_BG).grid(row=0, column=2, padx=6, pady=6)
        self.doc_filtro_fecha = tk.Entry(filtros, width=14)
        self.doc_filtro_fecha.grid(row=0, column=3, padx=6, pady=6)
        self.doc_filtro_fecha.insert(0, "YYYY-MM-DD")

        tk.Label(filtros, text="Buscar", bg=CARD_BG).grid(row=0, column=4, padx=6, pady=6)
        self.doc_filtro_texto = tk.Entry(filtros, width=28)
        self.doc_filtro_texto.grid(row=0, column=5, padx=6, pady=6)

        tk.Button(filtros, text="Buscar", command=self.refresh_contabilidad, bg=ACCENT, fg="white", relief="flat").grid(row=0, column=6, padx=6, pady=6)
        tk.Button(filtros, text="Limpiar", command=self.clear_doc_filters, bg="#334155", fg="white", relief="flat").grid(row=0, column=7, padx=6, pady=6)
        tk.Button(filtros, text="Vista previa PDF", command=self.preview_selected_document_pdf, bg="#059669", fg="white", relief="flat").grid(row=0, column=8, padx=6, pady=6)
        tk.Button(filtros, text="Imprimir", command=self.print_selected_document_pdf, bg="#16a34a", fg="white", relief="flat").grid(row=0, column=9, padx=6, pady=6)
        tk.Button(filtros, text="Boleta manual por series", command=self.abrir_boleta_manual_series_ui, bg="#2563eb", fg="white", relief="flat").grid(row=1, column=0, columnspan=3, padx=6, pady=6, sticky="w")

        cols = ("ID", "Tipo", "Número", "Cliente", "Documento", "Fecha", "SUNAT", "Subtotal", "IGV", "Total", "Usuario")
        self.tree_docs = ttk.Treeview(card, columns=cols, show="headings", height=18)
        widths = [60, 90, 140, 220, 120, 150, 115, 100, 100, 100, 100]
        for c, w in zip(cols, widths):
            self.tree_docs.heading(c, text=c)
            self.tree_docs.column(c, width=w, anchor="center")
        self.tree_docs.pack(fill="both", expand=True, padx=12, pady=8)
        self.tree_docs.bind("<Double-Button-1>", self.show_doc_detail)

        acciones = tk.Frame(card, bg=CARD_BG)
        acciones.pack(fill="x", padx=12, pady=(0, 10))
        tk.Button(acciones, text="Ver detalle", command=self.show_doc_detail, bg="#0284c7", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(acciones, text="Editar proforma", command=self.edit_selected_proforma_ui, bg="#f59e0b", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(acciones, text="Asignar series", command=self.assign_series_document_ui, bg="#0f766e", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(acciones, text="Reimprimir / Ver PDF", command=self.preview_selected_document_pdf, bg="#7c3aed", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(acciones, text="Reimprimir directo", command=self.print_selected_document_pdf, bg="#16a34a", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(acciones, text="Enviar SUNAT", command=self.enviar_sunat_documento_ui, bg="#2563eb", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(acciones, text="Estado SUNAT", command=self.consultar_sunat_documento_ui, bg="#334155", fg="white", relief="flat").pack(side="left", padx=4)

    def clear_doc_filters(self):
        self.doc_filtro_tipo.set("TODOS")
        self.doc_filtro_fecha.delete(0, tk.END)
        self.doc_filtro_fecha.insert(0, "YYYY-MM-DD")
        self.doc_filtro_texto.delete(0, tk.END)
        self.refresh_contabilidad()

    def refresh_contabilidad(self):
        for i in self.tree_docs.get_children():
            self.tree_docs.delete(i)

        tipo = self.doc_filtro_tipo.get().strip() if hasattr(self, "doc_filtro_tipo") else "TODOS"
        fecha = self.doc_filtro_fecha.get().strip() if hasattr(self, "doc_filtro_fecha") else ""
        texto = self.doc_filtro_texto.get().strip().lower() if hasattr(self, "doc_filtro_texto") else ""
        if fecha == "YYYY-MM-DD":
            fecha = ""

        for d in obtener_documentos():
            if tipo and tipo != "TODOS" and d.get("tipo") != tipo:
                continue
            fecha_doc = str(d.get("fecha_emision", ""))
            if fecha and not fecha_doc.startswith(fecha):
                continue
            cadena = f'{d.get("numero","")} {d.get("cliente_nombre","")} {d.get("documento_cliente","")} {d.get("usuario_emisor","")}'.lower()
            if texto and texto not in cadena:
                continue
            self.tree_docs.insert(
                "", "end",
                values=(
                    d["id"], d["tipo"], d["numero"], d["cliente_nombre"], d["documento_cliente"],
                    d["fecha_emision"], self.sunat_estado_label(d.get("sunat_estado")),
                    f'{d["subtotal"]:.2f}', f'{d["igv"]:.2f}', f'{d["total"]:.2f}', d["usuario_emisor"]
                )
            )

    def get_selected_document_values(self):
        sel = self.tree_docs.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona un documento.")
            return None
        return self.tree_docs.item(sel[0], "values")

    def enviar_sunat_documento_ui(self):
        vals = self.get_selected_document_values()
        if not vals:
            return
        documento_id = vals[0]
        tipo = str(vals[1]).upper()
        numero = vals[2]
        if tipo not in ("BOLETA", "FACTURA"):
            messagebox.showwarning("SUNAT", "SUNAT solo aplica para boletas o facturas.")
            return
        if not messagebox.askyesno("SUNAT", f"Enviar {tipo} {numero} a SUNAT?"):
            return
        r = enviar_documento_sunat_api(documento_id, True, False)
        self.refresh_contabilidad()
        if hasattr(self, "tree_cash"):
            self.refresh_cash()
        if api_response_ok(r):
            messagebox.showinfo("SUNAT", f"{tipo} {numero}\nEstado: {r.get('sunat_estado', 'PROCESO')}")
        else:
            messagebox.showerror("SUNAT", api_response_error(r, "No se pudo enviar a SUNAT."))

    def consultar_sunat_documento_ui(self):
        vals = self.get_selected_document_values()
        if not vals:
            return
        r = obtener_estado_documento_sunat_api(vals[0])
        if not api_response_ok(r):
            messagebox.showerror("SUNAT", api_response_error(r, "No se pudo consultar SUNAT."))
            return
        respuesta = r.get("respuesta") or {}
        msg = str(respuesta.get("msg") or respuesta.get("response") or respuesta.get("raw") or "")
        if len(msg) > 1200:
            msg = msg[:1200] + "\n..."
        messagebox.showinfo(
            "Estado SUNAT",
            f'{r.get("tipo","")} {r.get("numero","")}\n'
            f'Estado: {r.get("sunat_estado","")}\n'
            f'Modo: {r.get("sunat_modo","")}\n'
            f'Fecha: {r.get("sunat_fecha","")}\n'
            f'XML: {r.get("xml_nombre","")}\n'
            f'ZIP: {r.get("zip_nombre","")}\n\n{msg}'
        )

    def render_receipt_preview(self, parent, receipt):
        for child in parent.winfo_children():
            child.destroy()
        if isinstance(receipt, list):
            receipts = [r for r in receipt if r]
            if not receipts:
                receipt = None
            else:
                selector = tk.Frame(parent, bg=CARD_BG)
                selector.pack(fill="x", padx=18, pady=(12, 0))
                tk.Label(selector, text=f"{len(receipts)} comprobante(s) adjunto(s)", bg=CARD_BG, fg=TEXT, font=("Arial", 12, "bold")).pack(side="left", padx=(0, 8))
                for idx, item in enumerate(receipts, start=1):
                    tk.Button(selector, text=str(idx), command=lambda r=item: self.render_receipt_preview(parent, r), bg="#7c3aed", fg="white", relief="flat", width=3).pack(side="left", padx=2)
                receipt = receipts[0]
        if not receipt:
            tk.Label(parent, text="Sin comprobante adjunto.", bg=CARD_BG, fg=MUTED, font=("Arial", 12, "bold")).pack(padx=18, pady=18)
            return
        path = _receipt_to_openable_path(receipt)
        name = str(receipt.get("nombre") or receipt.get("comprobante_pago_nombre") or os.path.basename(path or "") or "Comprobante")
        tk.Label(parent, text=name, bg=CARD_BG, fg=TEXT, font=("Arial", 13, "bold")).pack(anchor="w", padx=18, pady=(14, 6))
        if not path or not os.path.exists(path):
            tk.Label(parent, text="Comprobante registrado, pero no hay archivo temporal para visualizar.", bg=CARD_BG, fg=WARNING, font=("Arial", 10, "bold")).pack(anchor="w", padx=18, pady=8)
            return
        mime = mimetypes.guess_type(path)[0] or str(receipt.get("mime") or receipt.get("comprobante_pago_mime") or "")
        if mime.startswith("image/"):
            holder = tk.Frame(parent, bg="#f8fafc", highlightthickness=1, highlightbackground=BORDER)
            holder.pack(fill="both", expand=True, padx=18, pady=10)
            canvas = tk.Canvas(holder, bg="#f8fafc", highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            try:
                img = Image.open(path).convert("RGB")
                img.thumbnail((860, 560))
                photo = ImageTk.PhotoImage(img)
                if not hasattr(self, "_internal_viewer_images"):
                    self._internal_viewer_images = []
                self._internal_viewer_images.append(photo)
                canvas.create_image(20, 20, image=photo, anchor="nw")
                canvas.configure(scrollregion=(0, 0, img.width + 40, img.height + 40))
            except Exception as e:
                tk.Label(holder, text=f"No se pudo mostrar la imagen.\n{e}", bg="#f8fafc", fg=DANGER, font=("Arial", 10, "bold")).pack(padx=12, pady=12)
            return
        if path.lower().endswith(".pdf") or "pdf" in mime.lower():
            tk.Label(parent, text="Comprobante PDF adjunto.", bg=CARD_BG, fg=MUTED, wraplength=760, justify="left", font=("Arial", 11)).pack(anchor="w", padx=18, pady=8)
            render_pdf_inside(parent, path, self._internal_viewer_images, max_page_width=860)
            return
        tk.Label(parent, text=f"Archivo adjunto: {path}", bg=CARD_BG, fg=MUTED, wraplength=760, justify="left").pack(anchor="w", padx=18, pady=8)

    def open_internal_document_viewer(self, title, doc_meta=None, detail=None, pdf_path=None, receipt=None, initial_tab="document"):
        doc_meta = doc_meta or {}
        detail = detail or []
        def download_current_pdf():
            if not pdf_path:
                messagebox.showinfo("Descargar PDF", "Esta vista no tiene PDF generado para descargar.")
                return
            doc_name = f'{doc_meta.get("tipo", "documento")}_{doc_meta.get("numero", "")}'.strip("_").replace(" ", "_")
            result = copy_pdf_to_downloads(pdf_path, f"{doc_name or 'documento'}.pdf")
            if api_response_ok(result):
                messagebox.showinfo("Descargar PDF", f"PDF guardado en Descargas:\n{result.get('path')}")
            else:
                messagebox.showerror("Descargar PDF", api_response_error(result, "No se pudo guardar el PDF."))
        def money_safe(value):
            try:
                return money(str(value or 0).replace(",", ""))
            except Exception:
                return "S/ 0.00"
        self._internal_viewer_images = []
        win = tk.Toplevel(self.root)
        win.title(title or "Visor interno")
        screen_w = max(1024, win.winfo_screenwidth())
        screen_h = max(700, win.winfo_screenheight())
        win_w = min(1120, max(940, screen_w - 90))
        win_h = min(760, max(640, screen_h - 110))
        win.geometry(f"{win_w}x{win_h}+30+30")
        win.minsize(900, 580)
        win.configure(bg=APP_BG)

        top = tk.Frame(win, bg=TOPBAR_BG, highlightthickness=1, highlightbackground=BORDER)
        top.pack(fill="x")
        doc_title = f'{doc_meta.get("tipo", "")} {doc_meta.get("numero", "")}'.strip() or title or "Documento"
        tk.Label(top, text=doc_title, bg=TOPBAR_BG, fg=TEXT, font=("Arial", 18, "bold")).pack(side="left", padx=16, pady=12)
        def print_current_pdf():
            result = print_pdf_file(pdf_path)
            if api_response_ok(result):
                play_document_sound("print")
            elif result.get("no_association"):
                messagebox.showwarning("PDF", "Windows no tiene un lector PDF asociado para imprimir directo. El PDF sigue abierto en el visor interno del ERP.")
            else:
                messagebox.showerror("PDF", api_response_error(result, "No se pudo enviar a imprimir."))
        if pdf_path:
            tk.Button(top, text="Imprimir", command=print_current_pdf, bg="#16a34a", fg="white", relief="flat", padx=12, pady=7).pack(side="right", padx=6)
            tk.Button(top, text="Descargar", command=download_current_pdf, bg="#2563eb", fg="white", relief="flat", padx=12, pady=7).pack(side="right", padx=6)
        tk.Button(top, text="Cerrar", command=win.destroy, bg="#64748b", fg="white", relief="flat", padx=12, pady=7).pack(side="right", padx=14)

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=14, pady=14)
        doc_tab = tk.Frame(nb, bg=CARD_BG)
        receipt_tab = tk.Frame(nb, bg=CARD_BG)
        nb.add(doc_tab, text="Documento")
        nb.add(receipt_tab, text="Comprobante")

        if pdf_path:
            tk.Label(
                doc_tab,
                text="Vista interna del PDF real generado por el ERP.",
                bg="#eff6ff",
                fg="#1d4ed8",
                font=("Arial", 10, "bold"),
                padx=12,
                pady=8,
            ).pack(fill="x", padx=14, pady=(14, 0))
            render_pdf_inside(doc_tab, pdf_path, self._internal_viewer_images)
            self.render_receipt_preview(receipt_tab, receipt)
            if initial_tab == "receipt":
                nb.select(receipt_tab)
            play_document_sound("open")
            return win

        summary = tk.Frame(doc_tab, bg=CARD_BG)
        summary.pack(fill="x", padx=14, pady=(14, 8))
        rows = [
            ("Tipo", doc_meta.get("tipo", "")),
            ("Numero", doc_meta.get("numero", "")),
            ("Cliente", doc_meta.get("cliente_nombre", doc_meta.get("cliente", ""))),
            ("Documento", doc_meta.get("documento_cliente", doc_meta.get("client_doc", ""))),
            ("Fecha", doc_meta.get("fecha_emision", doc_meta.get("fecha", ""))),
            ("Pago", f'{doc_meta.get("estado_pago", "")} {doc_meta.get("metodo_pago", "")}'.strip()),
        ]
        for i, (label, value) in enumerate(rows):
            box = tk.Frame(summary, bg="#f8fafc", highlightthickness=1, highlightbackground=BORDER)
            box.grid(row=i // 3, column=i % 3, sticky="ew", padx=4, pady=4)
            summary.grid_columnconfigure(i % 3, weight=1)
            tk.Label(box, text=label, bg="#f8fafc", fg=MUTED, font=("Arial", 8, "bold")).pack(anchor="w", padx=10, pady=(7, 0))
            tk.Label(box, text=str(value or "-")[:70], bg="#f8fafc", fg=TEXT, font=("Arial", 11, "bold")).pack(anchor="w", padx=10, pady=(0, 7))

        cols = ("Producto", "Serie", "Cant.", "P.Unit", "Total")
        tree = ttk.Treeview(doc_tab, columns=cols, show="headings", height=15)
        widths = [520, 220, 70, 100, 100]
        for c, w in zip(cols, widths):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="center")
        tree.pack(fill="both", expand=True, padx=14, pady=8)
        for row in detail:
            desc = f'{row.get("descripcion", row.get("nombre", ""))} {row.get("marca", "")} {row.get("modelo", "")}'.strip()
            qty = float(row.get("cantidad", 0) or 0)
            price = float(row.get("precio_unitario", row.get("precio", 0)) or 0)
            total = float(row.get("total", qty * price) or 0)
            tree.insert("", "end", values=(desc[:120], row.get("series_texto", row.get("serie", "")), f"{qty:.2f}", money_safe(price), money_safe(total)))
        if not detail:
            tree.insert("", "end", values=("Sin detalle disponible", "", "", "", ""))

        totals = tk.Frame(doc_tab, bg=CARD_BG)
        totals.pack(fill="x", padx=14, pady=(0, 14))
        for label, key in (("Subtotal", "subtotal"), ("IGV", "igv"), ("Total", "total")):
            tk.Label(totals, text=f"{label}: {money_safe(doc_meta.get(key, 0))}", bg=CARD_BG, fg=TEXT if key == "total" else MUTED, font=("Arial", 12, "bold")).pack(side="right", padx=12)
        if pdf_path:
            tk.Label(totals, text=f"PDF generado internamente: {os.path.basename(pdf_path)}", bg=CARD_BG, fg=MUTED, font=("Arial", 9)).pack(side="left")

        self.render_receipt_preview(receipt_tab, receipt)
        if initial_tab == "receipt":
            nb.select(receipt_tab)
        play_document_sound("open")
        return win

    def show_doc_detail(self, event=None):
        vals = self.get_selected_document_values()
        if not vals:
            return
        detail = obtener_detalle_documento(vals[0])
        doc_meta = {
            "id": vals[0], "tipo": vals[1], "numero": vals[2], "cliente_nombre": vals[3],
            "documento_cliente": vals[4], "fecha_emision": vals[5], "subtotal": vals[7],
            "igv": vals[8], "total": vals[9],
        }
        self.open_internal_document_viewer(f"Detalle {vals[2]}", doc_meta, detail)

    def selected_document_dict(self, doc_id):
        for d in obtener_documentos() or []:
            if str(d.get("id", "")) == str(doc_id):
                return d
        return {}

    def edit_selected_proforma_ui(self):
        vals = self.get_selected_document_values()
        if not vals:
            return
        doc_id, doc_tipo, doc_numero = vals[0], str(vals[1]).upper(), vals[2]
        if doc_tipo != "PROFORMA":
            messagebox.showwarning("Proforma", "Selecciona una PROFORMA para editar.")
            return
        doc = self.selected_document_dict(doc_id)
        if not doc:
            doc = {
                "id": doc_id,
                "tipo": doc_tipo,
                "numero": doc_numero,
                "cliente_nombre": vals[3],
                "documento_cliente": vals[4],
                "fecha_emision": vals[5],
                "observacion": "",
            }
        detail = obtener_detalle_documento(doc_id)
        if not detail:
            messagebox.showwarning("Proforma", "La proforma no tiene detalle para editar.")
            return
        play_document_sound("edit")
        self.load_proforma_into_sales(doc, detail)
        self.show_frame("ventas", "#059669")
        messagebox.showinfo("Proforma", f"Editando {doc_numero}.\nCambia productos o cantidades y pulsa Guardar cambios de proforma.")

    def load_proforma_into_sales(self, doc, detail):
        self.clear_sale_form(reset_edit=False)
        self.editing_proforma_id = doc.get("id")
        self.editing_proforma_numero = str(doc.get("numero", "") or "")
        self.v_doc_tipo.set("PROFORMA")
        self.lbl_next.config(text=self.editing_proforma_numero)
        self.set_entry_value(self.v_nom, doc.get("cliente_nombre") or "USUARIO X")
        self.set_entry_value(self.v_dir, doc.get("direccion_cliente") or "")
        self.set_entry_value(self.v_obs, doc.get("observacion") or "")
        self.set_entry_value(self.v_num, "")
        self.items_venta = []
        for row in detail:
            qty = int(float(row.get("cantidad", 0) or 0))
            price = float(row.get("precio_unitario", row.get("precio", 0)) or 0)
            total = float(row.get("total", qty * price) or 0)
            producto_id = row.get("producto_id") or row.get("id")
            self.items_venta.append({
                "producto_id": producto_id,
                "id": producto_id,
                "nombre": row.get("descripcion", row.get("nombre", "")) or "",
                "marca": "",
                "modelo": "",
                "serie": row.get("series_texto", row.get("serie", "")) or "",
                "series_texto": row.get("series_texto", row.get("serie", "")) or "",
                "cantidad": qty,
                "precio": price,
                "total": total if total > 0 else qty * price,
                "imagen_url": row.get("imagen_url", "") or "",
            })
        self.refresh_sale_table()
        self.update_sale_edit_state_ui()
        self.save_current_sale_draft()

    def assign_series_document_ui(self):
        vals = self.get_selected_document_values()
        if not vals:
            return
        doc_id, doc_tipo, doc_numero = vals[0], vals[1], vals[2]
        detail = obtener_detalle_documento(doc_id)
        if not detail:
            messagebox.showwarning("Series", "El documento no tiene productos para asignar series.")
            return

        win = tk.Toplevel(self.root)
        win.title(f"Asignar series - {doc_tipo} {doc_numero}")
        win.geometry("980x560")
        win.configure(bg=CARD_BG)
        tk.Label(
            win,
            text=f"{doc_tipo} {doc_numero} - Ingresa las series por producto antes de emitir/imprimir",
            bg=CARD_BG, fg=TEXT, font=("Arial", 14, "bold")
        ).pack(anchor="w", padx=12, pady=(12, 6))

        body = tk.Frame(win, bg=CARD_BG)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        body.grid_columnconfigure(0, weight=2)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        cols = ("ID", "Producto", "Cant.", "Series")
        tree = ttk.Treeview(body, columns=cols, show="headings", height=16)
        for c, w in zip(cols, [60, 430, 70, 280]):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="center")
        tree.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        side = tk.Frame(body, bg=CARD_BG)
        side.grid(row=0, column=1, sticky="nsew")
        tk.Label(side, text="Series del producto", bg=CARD_BG, fg=TEXT, font=("Arial", 11, "bold")).pack(anchor="w")
        txt_series = tk.Text(side, height=10, font=("Consolas", 10))
        txt_series.pack(fill="both", expand=True, pady=(6, 6))
        tk.Label(side, text="Puedes separar por coma o una serie por linea.", bg=CARD_BG, fg=MUTED, wraplength=300, justify="left").pack(anchor="w")

        detail_by_item = {}
        for row in detail:
            detalle_id = str(row.get("id", ""))
            detail_by_item[detalle_id] = row
            desc = f'{row.get("descripcion","")} {row.get("marca","")} {row.get("modelo","")}'.strip()
            tree.insert("", "end", iid=detalle_id, values=(detalle_id, desc, row.get("cantidad", 0), row.get("series_texto", "")))

        def load_selected(event=None):
            sel = tree.selection()
            if not sel:
                return
            row = detail_by_item.get(str(sel[0]), {})
            txt_series.delete("1.0", tk.END)
            txt_series.insert("1.0", row.get("series_texto", "") or "")

        def save_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Series", "Selecciona un producto del documento.")
                return
            detalle_id = str(sel[0])
            series_texto = txt_series.get("1.0", tk.END).strip()
            r = actualizar_series_detalle_documento(detalle_id, series_texto, self.user.get("usuario", ""))
            if api_response_ok(r):
                play_document_sound("success")
                vals_tree = list(tree.item(detalle_id, "values"))
                vals_tree[3] = series_texto
                tree.item(detalle_id, values=vals_tree)
                detail_by_item[detalle_id]["series_texto"] = series_texto
                self.registrar_accion("SERIES DOCUMENTO", f"{doc_tipo} {doc_numero} - detalle {detalle_id}: {series_texto}")
                messagebox.showinfo("Series", "Series guardadas en el documento.")
            else:
                messagebox.showerror("Series", api_response_error(r, "No se pudieron guardar las series."))

        tree.bind("<<TreeviewSelect>>", load_selected)
        if tree.get_children():
            tree.selection_set(tree.get_children()[0])
            load_selected()

        buttons = tk.Frame(win, bg=CARD_BG)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(buttons, text="Guardar series del producto", command=save_selected, bg=ACCENT, fg="white", relief="flat", padx=14, pady=7).pack(side="left", padx=4)
        tk.Button(buttons, text="Vista PDF actualizada", command=self.preview_selected_document_pdf, bg="#7c3aed", fg="white", relief="flat", padx=14, pady=7).pack(side="left", padx=4)
        tk.Button(buttons, text="Cerrar", command=win.destroy, bg="#334155", fg="white", relief="flat", padx=14, pady=7).pack(side="right", padx=4)

    def build_selected_document_pdf_file(self):
        vals = self.get_selected_document_values()
        if not vals:
            return None
        doc_id = vals[0]
        doc_type = vals[1]
        doc_number = vals[2]
        client_name = vals[3]
        client_doc = vals[4]
        detail = obtener_detalle_documento(doc_id)
        if not detail:
            messagebox.showwarning("Aviso", "El documento no tiene detalle.")
            return None

        items = []
        for x in detail:
            items.append({
                "nombre": x.get("descripcion", ""),
                "marca": x.get("marca", ""),
                "modelo": x.get("modelo", ""),
                "serie": x.get("series_texto", ""),
                "cantidad": x.get("cantidad", 0),
                "precio": float(x.get("precio_unitario", 0)),
                "total": float(x.get("total", 0)),
            })

        subtotal = float(str(vals[7]).replace(",", ""))
        igv = float(str(vals[8]).replace(",", ""))
        total = float(str(vals[9]).replace(",", ""))
        safe_num = str(doc_number).replace("/", "_").replace("\\", "_")
        out = os.path.join(tempfile.gettempdir(), f'{safe_num}_reimpresion.pdf')
        generate_pdf(
            out, self.cfg, doc_type, doc_number, client_name, client_doc, "",
            items, subtotal, igv, total, "",
            {"fecha_emision": vals[5]},
        )
        return out

    def preview_selected_document_pdf(self):
        try:
            vals = self.get_selected_document_values()
            if not vals:
                return
            out = self.build_selected_document_pdf_file()
            if out:
                detail = obtener_detalle_documento(vals[0])
                doc_meta = {
                    "id": vals[0], "tipo": vals[1], "numero": vals[2], "cliente_nombre": vals[3],
                    "documento_cliente": vals[4], "fecha_emision": vals[5], "subtotal": vals[7],
                    "igv": vals[8], "total": vals[9],
                }
                self.open_internal_document_viewer(f"PDF {vals[2]}", doc_meta, detail, pdf_path=out)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar la vista previa PDF.\n\n{e}")

    def print_selected_document_pdf(self):
        try:
            vals = self.get_selected_document_values()
            if not vals:
                return
            out = self.build_selected_document_pdf_file()
            if out:
                r = print_pdf_file(out)
                if api_response_ok(r):
                    play_document_sound("print")
                elif r.get("no_association"):
                    messagebox.showwarning("PDF", "Esta PC no tiene lector PDF asociado para imprimir directo. Abrire el visor interno del ERP.")
                    detail = obtener_detalle_documento(vals[0])
                    doc_meta = {
                        "id": vals[0], "tipo": vals[1], "numero": vals[2], "cliente_nombre": vals[3],
                        "documento_cliente": vals[4], "fecha_emision": vals[5], "subtotal": vals[7],
                        "igv": vals[8], "total": vals[9],
                    }
                    self.open_internal_document_viewer(f"PDF {vals[2]}", doc_meta, detail, pdf_path=out)
                else:
                    messagebox.showerror("Error", api_response_error(r, "No se pudo enviar a imprimir."))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo imprimir el documento.\n\n{e}")

    def build_cash_document_pdf_file(self):
        sel = self.tree_cash.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona un documento en Caja.")
            return None
        vals = self.tree_cash.item(sel[0], "values")
        doc_id = self.resolve_cash_document_id(vals)
        if doc_id is None:
            return None
        doc_type_selected = str(vals[2] or "").upper()
        estado = str(vals[5] or "").upper()
        metodo = str(vals[6] or "").upper()
        if doc_type_selected != "PROFORMA" and estado != "PAGADO":
            messagebox.showwarning("Caja", "Primero aprueba el documento como PAGADO para emitir/imprimir desde Caja.")
            return None
        if doc_type_selected != "PROFORMA" and not metodo:
            messagebox.showwarning("Caja", "Selecciona y aplica un metodo de pago antes de imprimir.")
            return None

        doc = next((d for d in (obtener_documentos() or []) if str(d.get("id")) == str(doc_id)), None)
        if not doc:
            doc = next((d for d in _documentos_list_desde_api() if str(d.get("id")) == str(doc_id)), None)
        if not doc:
            messagebox.showwarning("Aviso", "No se encontro el documento actualizado en la API.")
            return None

        detail = obtener_detalle_documento(doc_id)
        if not detail:
            messagebox.showwarning("Aviso", "El documento no tiene detalle.")
            return None

        items = []
        for x in detail:
            items.append({
                "nombre": x.get("descripcion", ""),
                "marca": x.get("marca", ""),
                "modelo": x.get("modelo", ""),
                "serie": x.get("series_texto", ""),
                "cantidad": x.get("cantidad", 0),
                "precio": float(x.get("precio_unitario", 0) or 0),
                "total": float(x.get("total", 0) or 0),
            })

        doc_type = doc.get("tipo", vals[2])
        doc_number = doc.get("numero", vals[3])
        safe_num = str(doc_number).replace("/", "_").replace("\\", "_")
        out = os.path.join(tempfile.gettempdir(), f'{safe_num}_caja.pdf')
        generate_pdf(
            out,
            self.cfg,
            doc_type,
            doc_number,
            doc.get("cliente_nombre", vals[4]),
            doc.get("documento_cliente", ""),
            doc.get("direccion_cliente", ""),
            items,
            float(doc.get("subtotal", 0) or 0),
            float(doc.get("igv", 0) or 0),
            float(doc.get("total", vals[8]) or 0),
            doc.get("usuario_emisor", ""),
            {"fecha_emision": doc.get("fecha_emision", vals[1]), "fecha_vencimiento": doc.get("fecha_vencimiento", "")},
        )
        return out

    def preview_cash_document_ui(self):
        try:
            vals = self.selected_cash_values()
            if not vals:
                return
            out = self.build_cash_document_pdf_file()
            if out:
                doc_id, doc = self.selected_cash_document_dict(vals)
                payload = doc.get("_detalle_payload")
                detail = _extract_documento_detalle_lines(payload) if payload else obtener_detalle_documento(doc_id)
                receipt = _payment_receipts_for_document(doc, doc_id, payload, detail)
                doc_meta = {
                    "id": doc_id, "tipo": vals[2], "numero": vals[3], "cliente_nombre": vals[4],
                    "fecha_emision": vals[1], "estado_pago": vals[5], "metodo_pago": vals[6],
                    "subtotal": doc.get("subtotal", 0), "igv": doc.get("igv", 0), "total": vals[8],
                }
                self.open_internal_document_viewer(f"Caja {vals[3]}", doc_meta, detail, pdf_path=out, receipt=receipt)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar la vista previa desde Caja.\n\n{e}")

    def print_cash_document_ui(self):
        try:
            out = self.build_cash_document_pdf_file()
            if out:
                r = print_pdf_file(out)
                if api_response_ok(r):
                    play_cash_approved_sound()
                    self.registrar_accion("DOCUMENTO IMPRESO DESDE CAJA", os.path.basename(out))
                elif r.get("no_association"):
                    messagebox.showwarning("PDF", "Esta PC no tiene lector PDF asociado para imprimir directo. Abrire el visor interno del ERP.")
                    vals = self.selected_cash_values()
                    if vals:
                        doc_id, doc = self.selected_cash_document_dict(vals)
                        payload = doc.get("_detalle_payload")
                        detail = _extract_documento_detalle_lines(payload) if payload else obtener_detalle_documento(doc_id)
                        receipt = _payment_receipts_for_document(doc, doc_id, payload, detail)
                        doc_meta = {
                            "id": doc_id, "tipo": vals[2], "numero": vals[3], "cliente_nombre": vals[4],
                            "fecha_emision": vals[1], "estado_pago": vals[5], "metodo_pago": vals[6],
                            "subtotal": doc.get("subtotal", 0), "igv": doc.get("igv", 0), "total": vals[8],
                        }
                        self.open_internal_document_viewer(f"Caja {vals[3]}", doc_meta, detail, pdf_path=out, receipt=receipt)
                else:
                    messagebox.showerror("Error", api_response_error(r, "No se pudo enviar a imprimir."))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo imprimir desde Caja.\n\n{e}")

    def open_sunat_sol_ui(self):
        webbrowser.open("https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm")
        messagebox.showinfo(
            "SUNAT SOL",
            "Se abrio SUNAT Operaciones en Linea.\n"
            "Para emision legal gratis puedes emitir manualmente con RUC, usuario y Clave SOL.\n"
            "El ERP queda como control interno y Caja imprime el documento interno."
        )

    def selected_cash_values(self):
        sel = self.tree_cash.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona una boleta o factura.")
            return None
        return self.tree_cash.item(sel[0], "values")

    def resolve_cash_document_id(self, vals):
        raw_id = str(vals[0] if vals else "").strip()
        numero = str(vals[3] if len(vals) > 3 else "").strip()

        if raw_id.isdigit():
            return int(raw_id)

        remote_list = _documentos_list_desde_api()

        for d in remote_list:
            if str(d.get("id", "")).strip() == raw_id:
                did = str(d.get("id", "")).strip()
                return int(did) if did.isdigit() else did

        if numero:
            for d in remote_list:
                if str(d.get("numero", "")).strip() == numero:
                    did = str(d.get("id", "")).strip()
                    if did:
                        return int(did) if did.isdigit() else did

        messagebox.showerror(
            "Documento",
            f"No pude resolver el ID de pago para {numero or raw_id}.\n"
            "Verifica conexion, sucursal en api_client y pulsa Actualizar en Caja.\n"
            "El comprobante debe existir en el servidor (PostgreSQL / ventas)."
        )
        return None

    def clean_local_test_documents_ui(self):
        docs = _load_local_documents()
        if not docs:
            messagebox.showinfo("Limpieza", "No hay archivo antiguo documentos_emitidos_local.json con datos.\nLos documentos ya no se guardan ahi.")
            return
        if not messagebox.askyesno("Limpieza", f"Se eliminara la copia antigua ({len(docs)} registros en documentos_emitidos_local.json).\nEl ERP ya usa solo el servidor.\n\n¿Continuar?"):
            return
        try:
            backup = LOCAL_DOCS_FILE + ".bak"
            if os.path.exists(LOCAL_DOCS_FILE):
                os.replace(LOCAL_DOCS_FILE, backup)
            messagebox.showinfo("Limpieza", f"Documentos locales limpiados.\nBackup: {backup}")
            self.refresh_cash()
            self.refresh_contabilidad()
        except Exception as e:
            messagebox.showerror("Limpieza", f"No se pudo limpiar.\n{e}")

    def sunat_estado_label(self, estado):
        estado = str(estado or "PENDIENTE").upper()
        if estado == "ACEPTADO":
            return "✓ ACEPTADO"
        if estado == "RECHAZADO":
            return "X RECHAZADO"
        if estado == "PROCESO":
            return "... PROCESO"
        return "SIN ENVIAR"

    def sunat_row_tag(self, estado):
        estado = str(estado or "PENDIENTE").upper()
        if estado == "ACEPTADO":
            return "SUNAT_ACEPTADO"
        if estado == "RECHAZADO":
            return "SUNAT_RECHAZADO"
        if estado == "PROCESO":
            return "SUNAT_PROCESO"
        return "SUNAT_PENDIENTE"

    def actualizar_sunat_ui(self, estado, modo="MANUAL", abrir_sunat=False):
        vals = self.selected_cash_values()
        if not vals:
            return
        documento_id = self.resolve_cash_document_id(vals)
        if documento_id is None:
            return
        tipo, numero = str(vals[2]).upper(), vals[3]
        if tipo not in ("BOLETA", "FACTURA"):
            messagebox.showwarning("SUNAT", "SUNAT solo aplica para boletas o facturas.")
            return
        if abrir_sunat:
            ruc = str(self.cfg.get("sunat_ruc") or self.cfg.get("ruc") or "").strip()
            usuario = str(self.cfg.get("sunat_usuario") or "").strip()
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(f"RUC: {ruc}\nUSUARIO SOL: {usuario}")
            except Exception:
                pass
            webbrowser.open("https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm")
        r = actualizar_estado_sunat(documento_id, estado, modo)
        if api_response_ok(r):
            if estado in ("PROCESO", "ACEPTADO"):
                play_cash_approved_sound()
            elif estado == "RECHAZADO":
                play_document_sound("warning")
            self.registrar_accion("SUNAT MANUAL", f"{tipo} {numero} -> {estado} / {modo}")
            self.refresh_cash()
            if abrir_sunat:
                messagebox.showinfo("SUNAT", f"{tipo} {numero} quedo marcado como EN PROCESO.\nEmite manualmente en SUNAT SOL y luego marca ACEPTADO o RECHAZADO.")
        else:
            messagebox.showerror("Error", api_response_error(r, "No se pudo actualizar el estado SUNAT."))

    def enviar_sunat_api_ui(self):
        vals = self.selected_cash_values()
        if not vals:
            return
        documento_id = self.resolve_cash_document_id(vals)
        if documento_id is None:
            return
        tipo, numero = str(vals[2]).upper(), vals[3]
        if tipo not in ("BOLETA", "FACTURA"):
            messagebox.showwarning("SUNAT", "SUNAT solo aplica para boletas o facturas.")
            return
        if not messagebox.askyesno("SUNAT API", f"Enviar {tipo} {numero} a SUNAT ahora?"):
            return
        r = enviar_documento_sunat_api(documento_id, True, False)
        if api_response_ok(r):
            estado = str(r.get("sunat_estado") or "PROCESO").upper()
            self.registrar_accion("SUNAT API", f"{tipo} {numero} -> {estado}")
            self.refresh_cash()
            messagebox.showinfo(
                "SUNAT API",
                f"{tipo} {numero}\nEstado: {estado}\nHTTP: {r.get('http_status', '')}"
            )
        else:
            self.refresh_cash()
            messagebox.showerror("SUNAT API", api_response_error(r, "No se pudo enviar a SUNAT."))

    def consultar_sunat_api_ui(self):
        vals = self.selected_cash_values()
        if not vals:
            return
        documento_id = self.resolve_cash_document_id(vals)
        if documento_id is None:
            return
        r = obtener_estado_documento_sunat_api(documento_id)
        if not api_response_ok(r):
            messagebox.showerror("SUNAT", api_response_error(r, "No se pudo consultar el estado SUNAT."))
            return
        respuesta = r.get("respuesta") or {}
        msg = respuesta.get("msg") or respuesta.get("response") or respuesta.get("raw") or ""
        msg = str(msg or "")
        if len(msg) > 1200:
            msg = msg[:1200] + "\n..."
        messagebox.showinfo(
            "Estado SUNAT",
            "Documento: {tipo} {numero}\n"
            "Estado: {estado}\n"
            "Modo: {modo}\n"
            "Fecha: {fecha}\n"
            "XML: {xml}\n"
            "ZIP: {zip}\n\n"
            "{msg}".format(
                tipo=r.get("tipo", ""),
                numero=r.get("numero", ""),
                estado=r.get("sunat_estado", ""),
                modo=r.get("sunat_modo", ""),
                fecha=r.get("sunat_fecha", ""),
                xml=r.get("xml_nombre", ""),
                zip=r.get("zip_nombre", ""),
                msg=msg,
            )
        )

    def ver_sunat_config_api_ui(self):
        r = obtener_sunat_config_api()
        if not api_response_ok(r):
            messagebox.showerror("SUNAT", api_response_error(r, "No se pudo leer la configuracion SUNAT."))
            return
        data = r.get("data") or {}
        messagebox.showinfo(
            "Configuracion SUNAT API",
            "Sucursal: {sucursal}\n"
            "Ambiente: {ambiente}\n"
            "RUC: {ruc}\n"
            "Envio automatico: {auto}\n"
            "Credenciales: {listo}\n"
            "Firma/PFX: {firma}\n\n"
            "Para produccion debe estar configurado el PFX y su password en el servidor.".format(
                sucursal=r.get("sucursal", ""),
                ambiente=data.get("ambiente", ""),
                ruc=data.get("ruc", ""),
                auto="SI" if data.get("envio_automatico") else "NO",
                listo="OK" if data.get("listo_envio") else "FALTA",
                firma="OK" if data.get("firma_configurada") else "FALTA",
            )
        )

    def copy_sunat_access_ui(self):
        ruc = str(self.cfg.get("sunat_ruc") or self.cfg.get("ruc") or "").strip()
        usuario = str(self.cfg.get("sunat_usuario") or "").strip()
        clave = str(self.cfg.get("sunat_clave") or "").strip()
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(f"RUC: {ruc}\nUSUARIO SOL: {usuario}\nCLAVE SOL: {clave}")
        except Exception:
            pass
        messagebox.showinfo("SUNAT SOL", "Acceso SUNAT copiado al portapapeles.\nUsalo solo en una PC de confianza.")

    def open_sunat_config_ui(self):
        self.copy_sunat_access_ui()
        webbrowser.open(str(self.cfg.get("sunat_url") or "https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm"))

    # CAJA
    def build_caja(self):
        frame = self.frames["caja"]
        card = self.set_card(frame)
        tk.Label(card, text="Caja Pro / Boletas y facturas", bg=CARD_BG, fg=TEXT, font=("Arial", 20, "bold")).pack(anchor="w", padx=12, pady=10)

        controls = tk.Frame(card, bg=CARD_BG)
        controls.pack(fill="x", padx=12, pady=8)

        tk.Label(controls, text="Nuevo estado", bg=CARD_BG).pack(side="left", padx=(0, 6))
        self.cash_estado_pago = ttk.Combobox(controls, values=["PAGADO", "CREDITO", "DEUDA"], state="readonly", width=12)
        self.cash_estado_pago.pack(side="left", padx=6)
        self.cash_estado_pago.set("PAGADO")

        tk.Label(controls, text="Metodo pago", bg=CARD_BG).pack(side="left", padx=(14, 6))
        self.cash_metodo_pago = ttk.Combobox(
            controls,
            values=["EFECTIVO", "TRANSFERENCIA", "YAPE", "PLIN", "TARJETA"],
            state="readonly",
            width=16
        )
        self.cash_metodo_pago.pack(side="left", padx=6)
        self.cash_metodo_pago.set("EFECTIVO")
        tk.Label(controls, text="Monto", bg=CARD_BG).pack(side="left", padx=(14, 6))
        self.cash_monto_pago = tk.Entry(controls, width=12, justify="right")
        self.cash_monto_pago.pack(side="left", padx=6)
        tk.Label(controls, text="Obs.", bg=CARD_BG).pack(side="left", padx=(8, 4))
        self.cash_obs_pago = tk.Entry(controls, width=18)
        self.cash_obs_pago.pack(side="left", padx=4)
        tk.Button(controls, text="Agregar comprobante", command=self.select_cash_comprobante_ui, bg="#0891b2", fg="white", relief="flat").pack(side="left", padx=6)
        self.cash_comprobante_lbl = tk.Label(controls, text="Sin archivo", bg=CARD_BG, fg=MUTED, font=("Arial", 9))
        self.cash_comprobante_lbl.pack(side="left", padx=(0, 6))

        tk.Button(controls, text="Aprobar / aplicar", command=self.save_cash_ui, bg=ACCENT, fg="white", relief="flat").pack(side="left", padx=6)
        tk.Button(controls, text="Ver comprobante", command=self.open_payment_receipt_ui, bg="#334155", fg="white", relief="flat").pack(side="left", padx=6)
        tk.Button(controls, text="Vista PDF", command=self.preview_cash_document_ui, bg="#0f766e", fg="white", relief="flat").pack(side="left", padx=6)
        tk.Button(controls, text="Emitir / imprimir", command=self.print_cash_document_ui, bg="#16a34a", fg="white", relief="flat").pack(side="left", padx=6)
        tk.Button(controls, text="Eliminar documento", command=self.delete_cash_document_ui, bg="#dc2626", fg="white", relief="flat").pack(side="left", padx=6)
        tk.Button(controls, text="Actualizar", command=self.refresh_cash, bg="#334155", fg="white", relief="flat").pack(side="left", padx=6)
        tk.Button(controls, text="Limpiar pruebas locales", command=self.clean_local_test_documents_ui, bg="#475569", fg="white", relief="flat").pack(side="left", padx=6)

        payment_detail = tk.Frame(card, bg=CARD_BG)
        payment_detail.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(payment_detail, text="Pago parcial por metodo", bg=CARD_BG, fg=TEXT, font=("Arial", 10, "bold")).pack(side="left", padx=(0, 8))
        self.cash_payment_entries = {}
        for method in ["EFECTIVO", "TRANSFERENCIA", "YAPE", "PLIN", "TARJETA"]:
            tk.Label(payment_detail, text=method.title(), bg=CARD_BG, fg=MUTED, font=("Arial", 9)).pack(side="left", padx=(5, 2))
            ent = tk.Entry(payment_detail, width=9, justify="right")
            ent.pack(side="left", padx=(0, 5))
            ent.bind("<KeyRelease>", lambda e: self.cash_payment_details_from_entries())
            self.cash_payment_entries[method] = ent
        self.cash_payment_total_lbl = tk.Label(payment_detail, text="Total: S/ 0.00", bg=CARD_BG, fg=TEXT, font=("Arial", 10, "bold"))
        self.cash_payment_total_lbl.pack(side="left", padx=8)

        fecha_controls = tk.Frame(card, bg=CARD_BG)
        fecha_controls.pack(fill="x", padx=12, pady=(0, 8))
        self.cash_fecha_todos = False
        tk.Label(fecha_controls, text="Ver documentos del dia", bg=CARD_BG, fg=TEXT, font=("Arial", 10, "bold")).pack(side="left", padx=(0, 8))
        if DateEntry:
            self.cash_fecha_filtro = DateEntry(fecha_controls, width=12, date_pattern="yyyy-mm-dd")
        else:
            self.cash_fecha_filtro = tk.Entry(fecha_controls, width=14)
            self.cash_fecha_filtro.insert(0, today_ymd())
        self.cash_fecha_filtro.pack(side="left", padx=6)
        tk.Button(fecha_controls, text="Buscar fecha", command=self.apply_cash_date_filter, bg="#0891b2", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(fecha_controls, text="Hoy", command=self.set_cash_today_filter, bg="#0f766e", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(fecha_controls, text="Ver todos", command=self.clear_cash_date_filter, bg="#334155", fg="white", relief="flat").pack(side="left", padx=4)
        self.cash_fecha_resumen = tk.Label(fecha_controls, text="", bg=CARD_BG, fg=MUTED, font=("Arial", 9))
        self.cash_fecha_resumen.pack(side="left", padx=10)

        sunat_controls = tk.Frame(card, bg=CARD_BG)
        sunat_controls.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(sunat_controls, text="SUNAT API", bg=CARD_BG, fg=TEXT, font=("Arial", 10, "bold")).pack(side="left", padx=(0, 8))
        tk.Button(sunat_controls, text="Enviar SUNAT API", command=self.enviar_sunat_api_ui, bg="#2563eb", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(sunat_controls, text="Consultar estado", command=self.consultar_sunat_api_ui, bg="#0f766e", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(sunat_controls, text="Ver config", command=self.ver_sunat_config_api_ui, bg="#334155", fg="white", relief="flat").pack(side="left", padx=(4, 14))
        tk.Label(sunat_controls, text="Manual", bg=CARD_BG, fg=TEXT, font=("Arial", 10, "bold")).pack(side="left", padx=(0, 8))
        tk.Button(sunat_controls, text="Enviar a SUNAT manual", command=lambda: self.actualizar_sunat_ui("PROCESO", "MANUAL", True), bg="#f59e0b", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(sunat_controls, text="Aceptado", command=lambda: self.actualizar_sunat_ui("ACEPTADO", "MANUAL", False), bg="#16a34a", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(sunat_controls, text="Rechazado", command=lambda: self.actualizar_sunat_ui("RECHAZADO", "MANUAL", False), bg="#dc2626", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(sunat_controls, text="No enviar a SUNAT", command=lambda: self.actualizar_sunat_ui("PENDIENTE", "NO_ENVIAR", False), bg="#64748b", fg="white", relief="flat").pack(side="left", padx=4)

        self.cash_balance = tk.Label(card, text="", bg=CARD_BG, fg=TEXT, font=("Arial", 12, "bold"))
        self.cash_balance.pack(anchor="w", padx=12, pady=6)

        cols = ("ID", "Fecha", "Tipo", "Numero", "Cliente", "Estado Pago", "Metodo Pago", "SUNAT", "Total", "Pagado", "Saldo", "Usuario")
        self.tree_cash = ttk.Treeview(card, columns=cols, show="headings", height=18)
        widths = [60, 145, 90, 120, 210, 100, 115, 115, 85, 85, 85, 100]
        for c, w in zip(cols, widths):
            self.tree_cash.heading(c, text=c)
            self.tree_cash.column(c, width=w, anchor="center")
        self.tree_cash.tag_configure("PAGADO", background="#dcfce7", foreground="#0f172a")
        self.tree_cash.tag_configure("CREDITO", background="#fef9c3", foreground="#0f172a")
        self.tree_cash.tag_configure("DEUDA", background="#fee2e2", foreground="#0f172a")
        self.tree_cash.tag_configure("SUNAT_ACEPTADO", background="#dcfce7", foreground="#0f172a")
        self.tree_cash.tag_configure("SUNAT_PROCESO", background="#ffedd5", foreground="#0f172a")
        self.tree_cash.tag_configure("SUNAT_RECHAZADO", background="#fee2e2", foreground="#0f172a")
        self.tree_cash.tag_configure("SUNAT_PENDIENTE", background=CARD_BG, foreground=TEXT)
        self.tree_cash.pack(fill="both", expand=True, padx=12, pady=8)
        self.tree_cash.bind("<Double-1>", self.open_cash_document_options)
        self.tree_cash.bind("<<TreeviewSelect>>", self.load_selected_cash_payment)

    def select_cash_comprobante_ui(self):
        paths = list(filedialog.askopenfilenames(
            title="Agregar comprobantes de pago",
            filetypes=[("Todos los archivos", "*.*")]
        ))
        if not paths:
            return
        current = list(getattr(self, "cash_comprobante_pago_paths", []) or [])
        try:
            _comprobantes_pago_payload(paths)
        except Exception as e:
            messagebox.showerror("Comprobante", str(e))
            return
        play_document_sound("edit")
        self.cash_comprobante_pago_paths = current + paths
        self.cash_comprobante_pago_path = self.cash_comprobante_pago_paths[0] if self.cash_comprobante_pago_paths else ""
        if hasattr(self, "cash_comprobante_lbl"):
            self.cash_comprobante_lbl.config(text=f"{len(self.cash_comprobante_pago_paths)} nuevo(s)", fg=ACCENT)

    def selected_cash_document_dict(self, vals):
        doc_id = self.resolve_cash_document_id(vals)
        if doc_id is None:
            return None, {}
        docs = obtener_documentos() or []
        doc = next((d for d in docs if str(d.get("id")) == str(doc_id)), None)
        if not doc:
            doc = next((d for d in _documentos_list_desde_api() if str(d.get("id")) == str(doc_id)), {})
        payload = _documento_payload_desde_api(doc_id)
        payload_doc = _documento_record_from_payload(payload)
        merged = dict(doc or {})
        merged.update({k: v for k, v in payload_doc.items() if v not in (None, "")})
        if payload:
            merged["_detalle_payload"] = payload
        return doc_id, merged

    def open_payment_receipt_ui(self, receipt=None):
        if receipt is None:
            vals = self.selected_cash_values()
            if not vals:
                return
            doc_id, doc = self.selected_cash_document_dict(vals)
            receipt = _payment_receipts_for_document(doc, doc_id, doc.get("_detalle_payload"))
        if not receipt:
            messagebox.showinfo("Comprobante", "Este documento aun no tiene comprobante adjunto.")
            return
        self.open_internal_document_viewer("Comprobante de pago", {}, [], receipt=receipt, initial_tab="receipt")

    def open_cash_document_options(self, event=None):
        vals = self.selected_cash_values()
        if not vals:
            return
        doc_id, doc = self.selected_cash_document_dict(vals)
        if doc_id is None:
            return
        play_document_sound("open")
        payload = doc.get("_detalle_payload")
        detail = _extract_documento_detalle_lines(payload) if payload else obtener_detalle_documento(doc_id)
        receipt = _payment_receipts_for_document(doc, doc_id, payload, detail)
        win = tk.Toplevel(self.root)
        win.title(f"Caja - {vals[2]} {vals[3]}")
        win.geometry("1040x660")
        win.configure(bg=CARD_BG)
        tk.Label(win, text=f"{vals[2]} {vals[3]}", bg=CARD_BG, fg=TEXT, font=("Arial", 18, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(win, text=f"{vals[4]}  |  Total {money(vals[8])}  |  {vals[5]} {vals[6]}", bg=CARD_BG, fg=MUTED, font=("Arial", 11)).pack(anchor="w", padx=14, pady=(0, 10))

        body = tk.Frame(win, bg=CARD_BG)
        body.pack(fill="both", expand=True, padx=14, pady=8)
        body.grid_columnconfigure(0, weight=2)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        detail_box = tk.Frame(body, bg="#f8fafc", highlightthickness=1, highlightbackground="#e2e8f0")
        detail_box.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        tk.Label(detail_box, text="Detalle del documento", bg="#f8fafc", fg=TEXT, font=("Arial", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        cols = ("Producto", "Serie", "Cant.", "P.Unit", "Total")
        detail_tree = ttk.Treeview(detail_box, columns=cols, show="headings", height=12)
        for c, w in zip(cols, [330, 170, 60, 80, 80]):
            detail_tree.heading(c, text=c)
            detail_tree.column(c, width=w, anchor="center")
        detail_tree.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        for row in detail or []:
            desc = f'{row.get("descripcion", row.get("nombre", ""))} {row.get("marca", "")} {row.get("modelo", "")}'.strip()
            detail_tree.insert("", "end", values=(
                desc[:80],
                row.get("series_texto", row.get("serie", "")),
                row.get("cantidad", 0),
                f'{float(row.get("precio_unitario", row.get("precio", 0)) or 0):.2f}',
                f'{float(row.get("total", 0) or 0):.2f}',
            ))

        receipt_box = tk.Frame(body, bg="#f8fafc", highlightthickness=1, highlightbackground="#e2e8f0")
        receipt_box.grid(row=0, column=1, sticky="nsew")
        receipt_items = receipt if isinstance(receipt, list) else ([receipt] if receipt else [])
        first_receipt = receipt_items[0] if receipt_items else None
        name = (first_receipt or {}).get("nombre", "") if first_receipt else ""
        tk.Label(receipt_box, text="Comprobante de pago", bg="#f8fafc", fg=TEXT, font=("Arial", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        label_text = f"{len(receipt_items)} comprobante(s) adjunto(s)" if receipt_items else "Sin comprobante adjunto"
        tk.Label(receipt_box, text=name or label_text, bg="#f8fafc", fg=("#7c3aed" if receipt_items else MUTED), font=("Arial", 11)).pack(anchor="w", padx=12)
        path = _receipt_to_openable_path(first_receipt)
        if path and os.path.exists(path):
            try:
                mime = mimetypes.guess_type(path)[0] or ""
                if mime.startswith("image/"):
                    img = Image.open(path)
                    img.thumbnail((420, 260))
                    photo = ImageTk.PhotoImage(img)
                    lbl = tk.Label(receipt_box, image=photo, bg="#f8fafc")
                    lbl.image = photo
                    lbl.pack(pady=10)
            except Exception:
                pass

        pay_box = tk.LabelFrame(receipt_box, text="Pago parcial", bg="#f8fafc", fg=TEXT, padx=10, pady=8)
        pay_box.pack(fill="x", padx=12, pady=10)
        tk.Label(pay_box, text="Estado", bg="#f8fafc", fg=MUTED).grid(row=0, column=0, sticky="w", padx=3, pady=3)
        modal_estado = ttk.Combobox(pay_box, values=["PAGADO", "CREDITO", "DEUDA"], state="readonly", width=13)
        modal_estado.grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        modal_estado.set(str(vals[5] or "DEUDA"))
        modal_entries = {}
        parsed_pagos = doc.get("pagos_detalle") or doc.get("pagos_detalle_json") or []
        if isinstance(parsed_pagos, str):
            try:
                parsed_pagos = json.loads(parsed_pagos or "[]")
            except Exception:
                parsed_pagos = []
        for idx, method in enumerate(["EFECTIVO", "TRANSFERENCIA", "YAPE", "PLIN", "TARJETA"], start=1):
            tk.Label(pay_box, text=method.title(), bg="#f8fafc", fg=MUTED).grid(row=idx, column=0, sticky="w", padx=3, pady=2)
            ent = tk.Entry(pay_box, justify="right")
            ent.grid(row=idx, column=1, sticky="ew", padx=3, pady=2)
            modal_entries[method] = ent
        if isinstance(parsed_pagos, list) and parsed_pagos:
            for item in parsed_pagos:
                if not isinstance(item, dict):
                    continue
                method = str(item.get("metodo") or item.get("metodo_pago") or "").upper()
                if method in modal_entries:
                    modal_entries[method].insert(0, str(item.get("monto") or item.get("monto_pagado") or ""))
        else:
            method = str(vals[6] or "").upper()
            try:
                paid = float(str(vals[9] or "0").replace(",", ""))
            except Exception:
                paid = 0
            if method in modal_entries and paid > 0:
                modal_entries[method].insert(0, f"{paid:.2f}")
        tk.Label(pay_box, text="Obs.", bg="#f8fafc", fg=MUTED).grid(row=6, column=0, sticky="w", padx=3, pady=(6, 2))
        modal_obs = tk.Entry(pay_box)
        modal_obs.grid(row=6, column=1, sticky="ew", padx=3, pady=(6, 2))
        modal_obs.insert(0, str(doc.get("observacion_pago") or ""))
        modal_total_lbl = tk.Label(pay_box, text="", bg="#f8fafc", fg=TEXT, font=("Arial", 10, "bold"))
        modal_total_lbl.grid(row=7, column=0, columnspan=2, sticky="e", padx=3, pady=(6, 2))
        pay_box.grid_columnconfigure(1, weight=1)

        def modal_payment_total():
            total_paid = 0.0
            for ent in modal_entries.values():
                try:
                    total_paid += float((ent.get() or "0").replace(",", ""))
                except Exception:
                    pass
            try:
                doc_total = float(str(vals[8] or "0").replace(",", ""))
            except Exception:
                doc_total = 0.0
            saldo = max(doc_total - total_paid, 0)
            modal_total_lbl.config(text=f"Pagado {money(total_paid)} | Saldo {money(saldo)}")
            return total_paid, saldo

        def sync_modal_status(event=None):
            total_paid, saldo = modal_payment_total()
            if total_paid <= 0:
                modal_estado.set("DEUDA")
            elif saldo <= 0.009:
                modal_estado.set("PAGADO")
            else:
                modal_estado.set("CREDITO")

        for ent in modal_entries.values():
            ent.bind("<KeyRelease>", sync_modal_status)
        sync_modal_status()

        def apply_modal_payment():
            for method, ent in getattr(self, "cash_payment_entries", {}).items():
                ent.delete(0, tk.END)
                if method in modal_entries:
                    ent.insert(0, modal_entries[method].get().strip())
            self.cash_estado_pago.set(modal_estado.get() or "DEUDA")
            pagos, paid = self.cash_payment_details_from_entries()
            metodo = " + ".join(p["metodo"] for p in pagos)
            if metodo and hasattr(self, "cash_metodo_pago"):
                first_method = pagos[0]["metodo"]
                self.cash_metodo_pago.set(first_method)
            if hasattr(self, "cash_monto_pago"):
                self.cash_monto_pago.delete(0, tk.END)
                self.cash_monto_pago.insert(0, f"{paid:.2f}")
            if hasattr(self, "cash_obs_pago"):
                self.cash_obs_pago.delete(0, tk.END)
                self.cash_obs_pago.insert(0, modal_obs.get().strip())
            self.save_cash_ui()
            win.destroy()

        actions = tk.Frame(win, bg=CARD_BG)
        actions.pack(fill="x", padx=14, pady=(4, 14))
        tk.Button(actions, text="Guardar pago", command=apply_modal_payment, bg=ACCENT, fg="white", relief="flat", padx=12, pady=7).pack(side="left", padx=4)
        tk.Button(actions, text="Agregar comprobante", command=self.select_cash_comprobante_ui, bg="#7c3aed", fg="white", relief="flat", padx=12, pady=7).pack(side="left", padx=4)
        tk.Button(actions, text="Ver comprobante", command=lambda: self.open_internal_document_viewer(f"Comprobante {vals[3]}", {"tipo": vals[2], "numero": vals[3], "cliente_nombre": vals[4], "total": vals[8]}, detail, receipt=receipt, initial_tab="receipt"), bg="#334155", fg="white", relief="flat", padx=12, pady=7).pack(side="left", padx=4)
        tk.Button(actions, text="Vista documento", command=lambda: self.open_internal_document_viewer(f"{vals[2]} {vals[3]}", {"id": doc_id, "tipo": vals[2], "numero": vals[3], "cliente_nombre": vals[4], "fecha_emision": vals[1], "estado_pago": vals[5], "metodo_pago": vals[6], "total": vals[8]}, detail, receipt=receipt), bg="#0f766e", fg="white", relief="flat", padx=12, pady=7).pack(side="left", padx=4)
        tk.Button(actions, text="Emitir / imprimir", command=self.print_cash_document_ui, bg="#16a34a", fg="white", relief="flat", padx=12, pady=7).pack(side="left", padx=4)
        tk.Button(actions, text="Cerrar", command=win.destroy, bg="#64748b", fg="white", relief="flat", padx=12, pady=7).pack(side="right", padx=4)

    def cash_payment_details_from_entries(self):
        pagos = []
        for method, ent in getattr(self, "cash_payment_entries", {}).items():
            try:
                value = float((ent.get() or "0").replace(",", ""))
            except Exception:
                value = 0
            if value > 0:
                pagos.append({"metodo": method, "monto": round(value, 2)})
        total = round(sum(float(p["monto"]) for p in pagos), 2)
        if hasattr(self, "cash_payment_total_lbl"):
            self.cash_payment_total_lbl.config(text=f"Total: {money(total)}")
        return pagos, total

    def fill_cash_payment_details(self, pagos=None, fallback_method="", fallback_amount=0):
        entries = getattr(self, "cash_payment_entries", {})
        for ent in entries.values():
            ent.delete(0, tk.END)
        parsed = pagos or []
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed or "[]")
            except Exception:
                parsed = []
        if isinstance(parsed, list) and parsed:
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                method = str(item.get("metodo") or item.get("metodo_pago") or "").upper()
                if method in entries:
                    entries[method].insert(0, str(item.get("monto") or item.get("monto_pagado") or ""))
        else:
            method = str(fallback_method or "").upper()
            if method in entries and float(fallback_amount or 0) > 0:
                entries[method].insert(0, f"{float(fallback_amount or 0):.2f}")
        self.cash_payment_details_from_entries()

    def load_selected_cash_payment(self, event=None):
        sel = self.tree_cash.selection()
        if not sel or not hasattr(self, "cash_monto_pago"):
            return
        vals = self.tree_cash.item(sel[0], "values")
        try:
            total = float(str(vals[8]).replace(",", "") or 0)
            pagado = float(str(vals[9]).replace(",", "") or 0)
        except Exception:
            total = 0
            pagado = 0
        self.cash_estado_pago.set(str(vals[5] or "PAGADO"))
        metodo = str(vals[6] or "")
        if metodo:
            self.cash_metodo_pago.set(metodo)
        self.cash_monto_pago.delete(0, tk.END)
        self.cash_monto_pago.insert(0, f"{(pagado if pagado > 0 else total):.2f}")
        self.cash_comprobante_pago_path = ""
        self.cash_comprobante_pago_paths = []
        try:
            doc_id, doc = self.selected_cash_document_dict(vals)
            self.fill_cash_payment_details(doc.get("pagos_detalle") or doc.get("pagos_detalle_json"), metodo, pagado if pagado > 0 else 0)
            receipt = _payment_receipts_for_document(doc, doc_id, doc.get("_detalle_payload"))
            if hasattr(self, "cash_comprobante_lbl"):
                if receipt:
                    self.cash_comprobante_lbl.config(text=f"{len(receipt)} comprobante(s)", fg="#7c3aed")
                else:
                    self.cash_comprobante_lbl.config(text="Sin archivo", fg=MUTED)
        except Exception:
            self.fill_cash_payment_details(None, metodo, pagado if pagado > 0 else 0)
            if hasattr(self, "cash_comprobante_lbl"):
                self.cash_comprobante_lbl.config(text="Sin archivo", fg=MUTED)

    def save_cash_ui(self):
        sel = self.tree_cash.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona una boleta, factura o nota de venta.")
            return
        vals = self.tree_cash.item(sel[0], "values")
        documento_id = self.resolve_cash_document_id(vals)
        if documento_id is None:
            return
        estado = self.cash_estado_pago.get()
        metodo = self.cash_metodo_pago.get() if hasattr(self, "cash_metodo_pago") else ""
        if estado == "PAGADO" and not metodo:
            messagebox.showwarning("Caja", "Para PAGADO debes seleccionar metodo de pago.")
            return
        if estado != "PAGADO":
            metodo = ""
        pagos_detalle, pagos_total = self.cash_payment_details_from_entries()
        if pagos_detalle:
            metodo = " + ".join(p["metodo"] for p in pagos_detalle)
            monto_pagado = pagos_total
            self.cash_monto_pago.delete(0, tk.END)
            self.cash_monto_pago.insert(0, f"{monto_pagado:.2f}")
        else:
            try:
                monto_pagado = float((self.cash_monto_pago.get() or "0").replace(",", ""))
            except Exception:
                messagebox.showwarning("Caja", "El monto pagado debe ser numerico.")
                return
        obs_pago = self.cash_obs_pago.get().strip() if hasattr(self, "cash_obs_pago") else ""
        comprobante_paths = list(getattr(self, "cash_comprobante_pago_paths", []) or [])
        comprobante_pago = comprobante_paths[0] if comprobante_paths else getattr(self, "cash_comprobante_pago_path", "")
        comprobante_payload = None
        if comprobante_paths:
            try:
                comprobante_payload = _comprobantes_pago_payload(comprobante_paths)
            except Exception as e:
                messagebox.showerror("Comprobante", str(e))
                return
        elif comprobante_pago:
            try:
                comprobante_payload = _comprobante_pago_payload(comprobante_pago)
            except Exception as e:
                messagebox.showerror("Comprobante", str(e))
                return
        r = actualizar_estado_pago_documento(documento_id, estado, metodo, monto_pagado, obs_pago, comprobante_pago, comprobante_payload, pagos_detalle)
        if api_response_ok(r):
            if comprobante_paths:
                _remember_payment_receipts(documento_id, comprobante_paths)
                self.cash_comprobante_pago_paths = []
                self.cash_comprobante_pago_path = ""
                if hasattr(self, "cash_comprobante_lbl"):
                    self.cash_comprobante_lbl.config(text=f"{len(comprobante_paths)} comprobante(s)", fg="#7c3aed")
            elif comprobante_pago:
                _remember_payment_receipt(documento_id, comprobante_pago)
                self.cash_comprobante_pago_path = ""
                if hasattr(self, "cash_comprobante_lbl"):
                    self.cash_comprobante_lbl.config(text=os.path.basename(comprobante_pago)[:32], fg="#7c3aed")
            play_cash_approved_sound()
            messagebox.showinfo("Exito", f"Estado actualizado a {estado} / {metodo}.")
            self.refresh_cash()
            self.refresh_contabilidad()
            self.refresh_dashboard()
        else:
            messagebox.showerror("Error", api_response_error(r, "No se pudo actualizar el estado de pago."))

    def delete_cash_document_ui(self):
        sel = self.tree_cash.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona una boleta, factura o nota de venta.")
            return
        vals = self.tree_cash.item(sel[0], "values")
        documento_id = self.resolve_cash_document_id(vals)
        if documento_id is None:
            return
        tipo, numero, cliente = vals[2], vals[3], vals[4]
        ok = messagebox.askyesno(
            "Eliminar documento",
            f"Se eliminara {tipo} {numero} de {cliente}.\n\nTambien se quitara de Caja y se devolvera el stock de sus productos.\n\n¿Deseas continuar?"
        )
        if not ok:
            return
        r = eliminar_documento(documento_id)
        if api_response_ok(r):
            play_document_sound("delete")
            self.registrar_accion("DOCUMENTO ELIMINADO DESDE CAJA", f"{tipo} {numero} - {cliente}")
            messagebox.showinfo("Exito", "Documento eliminado correctamente.")
            self.refresh_cash()
            self.refresh_contabilidad()
            self.refresh_dashboard()
            self.refresh_products()
        else:
            messagebox.showerror("Error", api_response_error(r, "No se pudo eliminar el documento."))

    def get_cash_filter_date(self):
        if getattr(self, "cash_fecha_todos", False):
            return ""
        if not hasattr(self, "cash_fecha_filtro"):
            return today_ymd()
        try:
            if DateEntry and hasattr(self.cash_fecha_filtro, "get_date"):
                return str(self.cash_fecha_filtro.get_date())
            value = self.cash_fecha_filtro.get().strip()
            return "" if value.upper() in ("", "TODOS") else value
        except Exception:
            return today_ymd()

    def apply_cash_date_filter(self):
        self.cash_fecha_todos = False
        self.refresh_cash()

    def set_cash_today_filter(self):
        self.cash_fecha_todos = False
        if DateEntry and hasattr(self.cash_fecha_filtro, "set_date"):
            self.cash_fecha_filtro.set_date(today_ymd())
        else:
            self.cash_fecha_filtro.delete(0, tk.END)
            self.cash_fecha_filtro.insert(0, today_ymd())
        self.refresh_cash()

    def clear_cash_date_filter(self):
        self.cash_fecha_todos = True
        if DateEntry and hasattr(self.cash_fecha_filtro, "delete"):
            try:
                self.cash_fecha_filtro.delete(0, tk.END)
            except Exception:
                pass
        else:
            self.cash_fecha_filtro.delete(0, tk.END)
        self.refresh_cash()

    def refresh_cash(self):
        for i in self.tree_cash.get_children():
            self.tree_cash.delete(i)
        tipos_caja = {"BOLETA", "FACTURA", "NOTA DE VENTA", "PASE"}
        if self.cfg.get("caja_solo_servidor", True):
            docs = _documentos_list_desde_api()
        else:
            docs = obtener_documentos() or []
        docs = [d for d in docs if str(d.get("tipo", "")).upper().strip() in tipos_caja]
        fecha_filtro = self.get_cash_filter_date()
        if fecha_filtro:
            docs = [d for d in docs if str(d.get("fecha_emision", "")).startswith(fecha_filtro)]
        total_pagado = 0.0
        total_credito = 0.0
        total_deuda = 0.0
        total_saldo = 0.0
        totales_metodo = {}
        for d in docs:
            estado = str(d.get("estado_pago", "PAGADO") or "PAGADO").upper()
            metodo = str(d.get("metodo_pago", "") or "").upper()
            total = float(d.get("total", 0) or 0)
            saldo = float(d.get("saldo_pago", 0) or 0)
            total_saldo += saldo
            if estado == "PAGADO":
                total_pagado += total
                if metodo:
                    totales_metodo[metodo] = totales_metodo.get(metodo, 0.0) + total
            elif estado == "CREDITO":
                total_credito += total
            elif estado == "DEUDA":
                total_deuda += total
        metodos_txt = "   ".join(f"{k}: {money(v)}" for k, v in sorted(totales_metodo.items()))
        resumen = f"Pagado: {money(total_pagado)}   Credito: {money(total_credito)}   Deuda: {money(total_deuda)}   Saldo: {money(total_saldo)}"
        if metodos_txt:
            resumen += f"   |   {metodos_txt}"
        if fecha_filtro:
            resumen = f"[{fecha_filtro}] " + resumen
        if self.cfg.get("caja_solo_servidor", True):
            resumen = "[Solo servidor] " + resumen
            if not docs:
                resumen += " | Sin boletas/facturas desde la API. Si deberian existir, revisa GET /documentos (errores del servidor dejan la lista vacia)."
        self.cash_balance.config(text=resumen)
        if hasattr(self, "cash_fecha_resumen"):
            self.cash_fecha_resumen.config(text=f"{len(docs)} documento(s) mostrados" + (f" para {fecha_filtro}" if fecha_filtro else ""))
        for d in docs:
            estado = str(d.get("estado_pago", "PAGADO") or "PAGADO").upper()
            sunat_estado = str(d.get("sunat_estado", "PENDIENTE") or "PENDIENTE").upper()
            total = float(d.get("total", 0) or 0)
            pagado = float(d.get("monto_pagado", total if estado == "PAGADO" else 0) or 0)
            saldo = float(d.get("saldo_pago", max(total - pagado, 0)) or 0)
            self.tree_cash.insert(
                "", "end",
                values=(
                    d.get("id", ""),
                    d.get("fecha_emision", ""),
                    d.get("tipo", ""),
                    d.get("numero", ""),
                    d.get("cliente_nombre", ""),
                    estado,
                    str(d.get("metodo_pago", "") or "").upper(),
                    self.sunat_estado_label(sunat_estado),
                    f'{total:.2f}',
                    f'{pagado:.2f}',
                    f'{saldo:.2f}',
                    d.get("usuario_emisor", "")
                ),
                tags=(self.sunat_row_tag(sunat_estado),)
            )

    # USUARIOS
    def build_radio(self):
        frame = self.frames["radio"]
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = tk.Frame(frame, bg=APP_BG)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(18, 10))
        tk.Label(header, text="Radio / Boquitoqui", bg=APP_BG, fg=TEXT, font=("Arial", 22, "bold")).pack(side="left")
        tk.Button(header, text="Actualizar usuarios", bg="#eaf2ff", fg=TEXT, relief="flat", padx=14, pady=9,
                  command=self.refresh_radio_users).pack(side="right")

        left = tk.Frame(frame, bg=CARD_BG, highlightthickness=1, highlightbackground=BORDER)
        left.grid(row=1, column=0, sticky="nsew", padx=(24, 10), pady=(0, 22))
        left.grid_columnconfigure(0, weight=1)
        tk.Label(left, text="Enviar a", bg=CARD_BG, fg=MUTED, font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 6))
        self.radio_target_combo = ttk.Combobox(left, textvariable=self._radio_selected_user, state="readonly", values=[""])
        self.radio_target_combo.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))

        self.radio_talk_btn = tk.Button(left, text="MANTENER PARA HABLAR", bg="#65a30d", fg="white", relief="flat",
                                        font=("Arial", 18, "bold"), padx=20, pady=42)
        self.radio_talk_btn.grid(row=2, column=0, sticky="ew", padx=18, pady=8)
        self.radio_talk_btn.bind("<ButtonPress-1>", lambda e: self.start_radio_talk())
        self.radio_talk_btn.bind("<ButtonRelease-1>", lambda e: self.stop_radio_talk())

        tk.Button(left, text="Iniciar / detener con click", bg="#0f5d9a", fg="white", relief="flat", padx=14, pady=12,
                  command=self.toggle_radio_talk).grid(row=3, column=0, sticky="ew", padx=18, pady=(8, 12))
        tk.Label(left, textvariable=self._radio_status_var, bg="#f1f5f9", fg=TEXT, font=("Arial", 11, "bold"),
                 padx=12, pady=12).grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 18))

        right = tk.Frame(frame, bg=CARD_BG, highlightthickness=1, highlightbackground=BORDER)
        right.grid(row=1, column=1, sticky="nsew", padx=(10, 24), pady=(0, 22))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        tk.Label(right, text="Usuarios", bg=CARD_BG, fg=TEXT, font=("Arial", 18, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 10))
        cols = ("Usuario", "Estado", "Vista", "Dispositivo")
        self.tree_radio_users = ttk.Treeview(right, columns=cols, show="headings", height=16)
        for col, width in (("Usuario", 160), ("Estado", 110), ("Vista", 160), ("Dispositivo", 160)):
            self.tree_radio_users.heading(col, text=col)
            self.tree_radio_users.column(col, width=width, anchor="w")
        self.tree_radio_users.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self.tree_radio_users.bind("<<TreeviewSelect>>", self.select_radio_user_from_tree)
        self.refresh_radio_users()

    def refresh_radio_users(self):
        try:
            resp = obtener_usuarios_online()
            rows = api_response_get(resp, "data", resp if isinstance(resp, list) else []) or []
        except Exception:
            rows = []
        usuario_actual = str(self.user.get("usuario", "")).strip().lower()
        clean = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            usuario = str(row.get("usuario", "")).strip()
            if not usuario or usuario.lower() == usuario_actual:
                continue
            clean.append(row)
        self._radio_users = clean
        values = [""] + [str(row.get("usuario", "")).strip() for row in clean]
        try:
            self.radio_target_combo["values"] = values
            if self._radio_selected_user.get() not in values:
                self._radio_selected_user.set(values[1] if len(values) > 1 else "")
        except Exception:
            pass
        try:
            self.tree_radio_users.delete(*self.tree_radio_users.get_children())
            for row in clean:
                usuario = str(row.get("usuario", "")).strip()
                estado = "EN LINEA" if bool(row.get("online", False)) else "DESCONECTADO"
                self.tree_radio_users.insert("", "end", iid=usuario, values=(
                    usuario,
                    estado,
                    str(row.get("vista", "") or ""),
                    str(row.get("dispositivo", "") or ""),
                ))
        except Exception:
            pass

    def select_radio_user_from_tree(self, event=None):
        try:
            sel = self.tree_radio_users.selection()
            if sel:
                self._radio_selected_user.set(str(sel[0]))
        except Exception:
            pass

    def toggle_radio_talk(self):
        if self._radio_recording:
            self.stop_radio_talk()
        else:
            self.start_radio_talk()

    def start_radio_talk(self):
        if self._radio_recording:
            return
        self._radio_recording = True
        self._radio_status_var.set("Hablando...")
        play_boquitoqui_start_sound()
        try:
            self.radio_talk_btn.config(text="SUELTA PARA ENVIAR", bg="#dc2626")
        except Exception:
            pass
        threading.Thread(target=self.radio_record_worker, daemon=True).start()

    def stop_radio_talk(self):
        if not self._radio_recording:
            return
        self._radio_recording = False
        self._radio_status_var.set("Cerrando microfono...")
        play_boquitoqui_stop_sound()
        try:
            self.radio_talk_btn.config(text="MANTENER PARA HABLAR", bg="#65a30d")
        except Exception:
            pass

    def radio_record_worker(self):
        sent = 0
        error = ""
        while self._radio_recording:
            wav_bytes = record_microphone_wav_chunk(520)
            if not wav_bytes:
                error = "No se pudo usar el microfono de Windows."
                break
            payload = {
                "usuario_emisor": str(self.user.get("usuario", "")).strip(),
                "destinatario": self._radio_selected_user.get().strip(),
                "grupo": "GENERAL",
                "audio_mime": "audio/wav",
                "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                "duracion_ms": 520,
                "sucursal": str(self.user.get("sucursal") or self.user.get("empresa") or "computer_army"),
            }
            resp = enviar_boquitoqui_live(payload)
            if not api_response_ok(resp):
                error = api_response_error(resp, "No se pudo enviar radio.")
                break
            sent += 1
        self._radio_recording = False

        def done():
            try:
                self.radio_talk_btn.config(text="MANTENER PARA HABLAR", bg="#65a30d")
            except Exception:
                pass
            if error:
                self._radio_status_var.set(error)
            elif sent:
                target = self._radio_selected_user.get().strip() or "todos"
                self._radio_status_var.set(f"Enviado a {target}")
            else:
                self._radio_status_var.set("Radio listo")

        try:
            self.root.after(0, done)
        except Exception:
            pass

    def build_usuarios(self):
        frame = self.frames["usuarios"]
        card = self.set_card(frame)
        tk.Label(card, text="Usuarios", bg=CARD_BG, fg=TEXT, font=("Arial", 20, "bold")).pack(anchor="w", padx=12, pady=10)
        form = tk.Frame(card, bg=CARD_BG); form.pack(padx=12, pady=8)
        tk.Label(form, text="Usuario", bg=CARD_BG).grid(row=0, column=0, padx=6, pady=6)
        self.usr_name = tk.Entry(form, width=20); self.usr_name.grid(row=0, column=1, padx=6, pady=6)
        tk.Label(form, text="Clave", bg=CARD_BG).grid(row=0, column=2, padx=6, pady=6)
        self.usr_pass = tk.Entry(form, width=20); self.usr_pass.grid(row=0, column=3, padx=6, pady=6)
        tk.Label(form, text="Rol", bg=CARD_BG).grid(row=0, column=4, padx=6, pady=6)
        self.usr_role = ttk.Combobox(form, values=["ADMIN", "VENTAS"], state="readonly", width=12); self.usr_role.grid(row=0, column=5, padx=6, pady=6); self.usr_role.set("VENTAS")
        tk.Button(form, text="Guardar Usuario", command=self.save_user_ui, bg=ACCENT, fg="white", relief="flat").grid(row=0, column=6, padx=6, pady=6)
        tk.Label(form, text="Sucursal", bg=CARD_BG).grid(row=2, column=0, padx=6, pady=6)
        self.usr_branch = ttk.Combobox(form, values=empresa_display_options(), state="readonly", width=24)
        self.usr_branch.grid(row=2, column=1, columnspan=2, padx=6, pady=6, sticky="we")
        current_branch = str(self.user.get("sucursal") or self.user.get("empresa") or "computer_army").replace("_", " ").upper()
        self.usr_branch.set(current_branch if current_branch in empresa_display_options() else "COMPUTER ARMY")
        self.usr_photo = tk.Entry(form, width=36)
        self.usr_photo.grid(row=1, column=1, columnspan=3, padx=6, pady=6, sticky="we")
        tk.Label(form, text="Foto", bg=CARD_BG).grid(row=1, column=0, padx=6, pady=6)
        tk.Button(form, text="Subir foto", command=lambda: self.pick_product_image(self.usr_photo), bg="#0f766e", fg="white", relief="flat").grid(row=1, column=4, padx=6, pady=6)
        tk.Button(form, text="Guardar foto seleccionado", command=self.save_selected_user_photo, bg="#0891b2", fg="white", relief="flat").grid(row=1, column=5, columnspan=2, padx=6, pady=6)
        if self.es_giomar_admin():
            tk.Button(form, text="Cambiar rol", command=self.cambiar_rol_usuario_ui, bg="#7c3aed", fg="white", relief="flat").grid(row=0, column=7, padx=6, pady=6)
            tk.Button(form, text="Eliminar usuario", command=self.eliminar_usuario_ui, bg="#dc2626", fg="white", relief="flat").grid(row=0, column=8, padx=6, pady=6)
        tk.Button(form, text="Refrescar usuarios", command=self.refresh_users, bg="#334155", fg="white", relief="flat").grid(row=1, column=7, padx=6, pady=6)
        self.tree_users = ttk.Treeview(card, columns=("ID", "Usuario", "Rol", "Sucursal", "Foto"), show="headings", height=16)
        for c, w in zip(("ID", "Usuario", "Rol", "Sucursal", "Foto"), [60, 190, 110, 160, 130]):
            self.tree_users.heading(c, text=c); self.tree_users.column(c, width=w, anchor="center")
        self.tree_users.pack(fill="both", expand=True, padx=12, pady=8)
        self.tree_users.bind("<<TreeviewSelect>>", self.load_selected_user_to_form)

    def save_user_ui(self):
        usuario = self.usr_name.get().strip()
        clave = self.usr_pass.get().strip()
        rol = self.usr_role.get()
        if not usuario or not clave:
            messagebox.showwarning("Aviso", "Ingresa usuario y clave.")
            return
        sucursal = empresa_to_key(self.usr_branch.get()) if hasattr(self, "usr_branch") else str(self.user.get("sucursal") or self.user.get("empresa") or "computer_army")
        try:
            foto_url = self.normalize_photo_value_for_api(self.usr_photo.get(), max_size=(360, 360))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo preparar la foto del usuario.\n{e}")
            return
        r = guardar_usuario({"usuario": usuario, "clave": clave, "rol": rol, "foto_url": foto_url, "sucursal": sucursal})
        if api_response_ok(r):
            messagebox.showinfo("Exito", "Usuario guardado.")
            self.registrar_accion("USUARIO GUARDADO", f"{usuario} / {rol}")
            self.usr_photo.delete(0, tk.END)
            self.refresh_users()
        else:
            messagebox.showerror("Error", api_response_error(r, "No se pudo guardar el usuario."))

    def load_selected_user_to_form(self, event=None):
        sel = self.tree_users.selection()
        if not sel or not hasattr(self, "usr_photo"):
            return
        vals = self.tree_users.item(sel[0], "values")
        if len(vals) >= 3:
            self.usr_name.delete(0, tk.END)
            self.usr_name.insert(0, vals[1])
            self.usr_role.set(str(vals[2]).upper())
        if len(vals) >= 4 and hasattr(self, "usr_branch"):
            self.usr_branch.set(str(vals[3]).replace("_", " ").upper())
        if len(vals) >= 5:
            self.usr_photo.delete(0, tk.END)
            self.usr_photo.insert(0, vals[4])

    def save_selected_user_photo(self):
        sel = self.tree_users.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona un usuario.")
            return
        vals = self.tree_users.item(sel[0], "values")
        user_id, usuario = vals[0], vals[1]
        try:
            foto_url = self.normalize_photo_value_for_api(self.usr_photo.get(), max_size=(360, 360))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo preparar la foto del usuario.\n{e}")
            return
        try:
            fn = getattr(api_client, "actualizar_foto_usuario", None) if api_client is not None else None
            if callable(fn):
                r = fn(user_id, foto_url)
            else:
                r = _api_json("put", f"/usuarios/{user_id}/foto", {"ok": False}, json={"foto_url": foto_url})
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        if api_response_ok(r):
            messagebox.showinfo("Exito", f"Foto actualizada para {usuario}.")
            if str(usuario).strip().lower() == str(self.user.get("usuario", "")).strip().lower():
                self.user["foto_url"] = foto_url
                self.update_user_avatar_ui()
            self.registrar_accion("USUARIO FOTO ACTUALIZADA", str(usuario))
            self.refresh_users()
        else:
            messagebox.showerror("Error", api_response_error(r, "No se pudo guardar la foto."))


    def cambiar_rol_usuario_ui(self):
        if not self.es_giomar_admin():
            messagebox.showerror("Acceso denegado", "Solo Giomar puede cambiar roles.")
            return
        sel = self.tree_users.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona un usuario.")
            return
        vals = self.tree_users.item(sel[0], "values")
        user_id, usuario, rol_actual = vals[0], vals[1], vals[2]
        win = tk.Toplevel(self.root)
        win.title("Cambiar rol")
        win.geometry("300x160")
        tk.Label(win, text=f"Usuario: {usuario}").pack(pady=8)
        cb = ttk.Combobox(win, values=["ADMIN", "VENTAS"], state="readonly")
        cb.pack(pady=6); cb.set(rol_actual)
        def guardar():
            try:
                import requests
                r = requests.put(f"{api_client.BASE_URL}/usuarios/{user_id}/rol", json={"rol": cb.get(), "empresa": getattr(api_client, "EMPRESA", "")}, timeout=10)
                if r.status_code == 200:
                    messagebox.showinfo("Éxito", "Rol actualizado.")
                    self.registrar_accion("USUARIO ROL CAMBIADO", f"{usuario} -> {cb.get()}")
                    self.refresh_users(); win.destroy()
                else:
                    messagebox.showerror("Error", r.text)
            except Exception as e:
                messagebox.showerror("Error", str(e))
        tk.Button(win, text="Guardar rol", command=guardar, bg=ACCENT, fg="white", relief="flat").pack(pady=10)

    def eliminar_usuario_ui(self):
        if not self.es_giomar_admin():
            messagebox.showerror("Acceso denegado", "Solo Giomar puede eliminar usuarios.")
            return
        sel = self.tree_users.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecciona un usuario.")
            return
        vals = self.tree_users.item(sel[0], "values")
        user_id, usuario = vals[0], vals[1]
        if str(usuario).strip().lower() == "giomar":
            messagebox.showwarning("Bloqueado", "No puedes eliminar al usuario Giomar.")
            return
        if not messagebox.askyesno("Confirmar", f"¿Eliminar usuario {usuario}?"):
            return
        try:
            import requests
            r = requests.delete(f"{api_client.BASE_URL}/usuarios/{user_id}", json={"empresa": getattr(api_client, "EMPRESA", "")}, timeout=10)
            if r.status_code == 200:
                messagebox.showinfo("Éxito", "Usuario eliminado.")
                self.registrar_accion("USUARIO ELIMINADO", str(usuario))
                self.refresh_users()
            else:
                messagebox.showerror("Error", r.text)
        except Exception as e:
            messagebox.showerror("Error", str(e))


    def refresh_users(self):
        for i in self.tree_users.get_children():
            self.tree_users.delete(i)
        for u in obtener_usuarios():
            foto = str(u.get("foto_url", "") or "")
            self.tree_users.insert("", "end", values=(u["id"], u["usuario"], u["rol"], u.get("sucursal", "computer_army"), foto))



    # CONSULTA RUC / DNI
    def abrir_sunat_manual(self, ruc):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(ruc)
        except Exception:
            pass
        webbrowser.open("https://e-consultaruc.sunat.gob.pe/cl-ti-itmrconsruc/FrameCriterioBusquedaWeb.jsp")
        messagebox.showinfo("SUNAT", "Se abrió SUNAT.\nEl RUC quedó copiado para pegarlo rápido.")

    def abrir_dni_manual(self, dni):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(dni)
        except Exception:
            pass
        webbrowser.open("https://eldni.com/pe/buscar-por-dni")
        messagebox.showinfo("DNI", "Se abrió la web de consulta.\nEl DNI quedó copiado para pegarlo rápido.")

    def limpiar_texto_html(self, html):
        html = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
        html = re.sub(r"(?is)<style.*?>.*?</style>", " ", html)
        html = re.sub(r"(?is)<br\s*/?>", "\n", html)
        html = re.sub(r"(?is)</p>|</div>|</h\d>|</li>|</tr>", "\n", html)
        txt = re.sub(r"(?is)<.*?>", " ", html)
        txt = txt.replace("&nbsp;", " ").replace("&amp;", "&").replace("&Ntilde;", "Ñ").replace("&ntilde;", "ñ")
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = re.sub(r"\n\s+", "\n", txt)
        return txt.strip()

    def consultar_ruc_sunat(self, ruc):
        ruc = (ruc or "").strip()
        if not (ruc.isdigit() and len(ruc) == 11):
            return {"ok": False, "msg": "El RUC debe tener 11 dígitos."}
        try:
            import requests
            url = "https://e-consultaruc.sunat.gob.pe/cl-ti-itmrconsruc/jcrS00Alias"
            params = {"accion": "consPorRuc", "nroRuc": ruc, "contexto": "ti-it", "modo": "1", "search1": ruc, "tipdoc": "1"}
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://e-consultaruc.sunat.gob.pe/cl-ti-itmrconsruc/FrameCriterioBusquedaWeb.jsp"}
            resp = requests.get(url, params=params, headers=headers, timeout=12)
            texto = self.limpiar_texto_html(resp.text or "")
            razon = ""
            direccion = ""
            m = re.search(r"N[uú]mero de RUC\s*:?\s*" + re.escape(ruc) + r"\s*-\s*(.+)", texto, re.IGNORECASE)
            if m:
                razon = m.group(1).strip().split("\n")[0].strip()
            m2 = re.search(r"Domicilio Fiscal\s*:?\s*(.+)", texto, re.IGNORECASE)
            if m2:
                direccion = re.split(r"\n|Estado del Contribuyente|Condición", m2.group(1).strip())[0].strip()
            if razon:
                return {"ok": True, "razon_social": razon, "direccion": direccion}
            return {"ok": False, "msg": "SUNAT no devolvió datos legibles."}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def consultar_dni_eldni(self, dni):
        dni = (dni or "").strip()
        if not (dni.isdigit() and len(dni) == 8):
            return {"ok": False, "msg": "El DNI debe tener 8 dígitos."}
        try:
            import requests
            s = requests.Session()
            url = "https://eldni.com/pe/buscar-por-dni"
            headers = {"User-Agent": "Mozilla/5.0", "Referer": url, "Origin": "https://eldni.com"}
            s.get(url, headers=headers, timeout=12)
            texto = ""
            for payload in [{"dni": dni}, {"dni_numero": dni}, {"numero": dni}, {"documento": dni}, {"numdni": dni}]:
                r = s.post(url, data=payload, headers=headers, timeout=12)
                texto = r.text or ""
                if dni in texto:
                    break
            limpio = self.limpiar_texto_html(texto)
            nombres = ""
            ap_pat = ""
            ap_mat = ""
            for patron, campo in [
                (r"Nombres\s*:?\s*([A-ZÁÉÍÓÚÑ ]{2,})", "nombres"),
                (r"Apellido Paterno\s*:?\s*([A-ZÁÉÍÓÚÑ ]{2,})", "ap_pat"),
                (r"Apellido Materno\s*:?\s*([A-ZÁÉÍÓÚÑ ]{2,})", "ap_mat"),
            ]:
                m = re.search(patron, limpio, re.IGNORECASE)
                if m:
                    valor = re.split(r"\n|Apellido|Nombres|DNI", m.group(1).strip())[0].strip()
                    if campo == "nombres": nombres = valor
                    elif campo == "ap_pat": ap_pat = valor
                    else: ap_mat = valor
            nombre = " ".join([ap_pat, ap_mat, nombres]).strip()
            if nombre and len(nombre) > 5:
                return {"ok": True, "nombre": nombre.upper()}
            return {"ok": False, "msg": "La web no devolvió datos legibles o bloqueó la consulta."}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def _documento_digits(self, value):
        return re.sub(r"\D", "", str(value or ""))

    def _set_cliente_fields(self, nombre_entry, direccion_entry, data):
        nombre = (data.get("nombre") or data.get("razon_social") or data.get("razonSocial") or "").strip()
        direccion = (data.get("direccion") or data.get("domicilio_fiscal") or data.get("direccionFiscal") or "").strip()
        if nombre:
            nombre_entry.delete(0, tk.END)
            nombre_entry.insert(0, nombre)
        direccion_entry.delete(0, tk.END)
        direccion_entry.insert(0, direccion)

    def _apply_doc_lookup_result(self, data, nombre_entry, direccion_entry):
        if isinstance(data, dict) and (api_response_ok(data) or data.get("found")):
            self._set_cliente_fields(nombre_entry, direccion_entry, data)

    def _consulta_documento_async(self, numero, tipo_combo, nombre_entry, direccion_entry, cache_attr):
        numero = self._documento_digits(numero)
        if len(numero) not in (8, 11):
            return
        if getattr(self, cache_attr, "") == numero:
            return
        setattr(self, cache_attr, numero)
        tipo_combo.set("RUC" if len(numero) == 11 else "DNI")
        if tipo_combo is getattr(self, "v_tipo_doc", None):
            self.auto_sale_doc_type_from_customer_doc(numero)

        def worker():
            data = consultar_documento_api(numero)
            self.root.after(0, lambda: self._apply_doc_lookup_result(data or {}, nombre_entry, direccion_entry))

        threading.Thread(target=worker, daemon=True).start()

    def _consulta_documento_manual(self, numero, tipo, tipo_combo, nombre_entry, direccion_entry):
        numero = self._documento_digits(numero)
        tipo_combo.set(tipo)
        esperado = 11 if tipo == "RUC" else 8
        if len(numero) != esperado:
            messagebox.showwarning("Consulta", f"Ingresa {esperado} dígitos para {tipo}.")
            return
        if tipo_combo is getattr(self, "v_tipo_doc", None):
            self.auto_sale_doc_type_from_customer_doc(numero)

        data = consultar_documento_api(numero)
        if isinstance(data, dict) and (api_response_ok(data) or data.get("found")):
            self._set_cliente_fields(nombre_entry, direccion_entry, data)
            return

        if tipo == "RUC":
            data = self.consultar_ruc_sunat(numero)
            if api_response_ok(data):
                self._set_cliente_fields(nombre_entry, direccion_entry, data)
            else:
                self.abrir_sunat_manual(numero)
            return

        data = self.consultar_dni_eldni(numero)
        if api_response_ok(data):
            self._set_cliente_fields(nombre_entry, direccion_entry, data)
        else:
            self.abrir_dni_manual(numero)

    def on_sale_doc_keyrelease(self, event=None):
        if not self._documento_digits(self.v_num.get()):
            self.set_sale_doc_proforma_default()
            return
        self._consulta_documento_async(self.v_num.get(), self.v_tipo_doc, self.v_nom, self.v_dir, "_last_sale_doc_lookup")

    def on_client_doc_keyrelease(self, event=None):
        self._consulta_documento_async(self.cli_num.get(), self.cli_tipo, self.cli_nom, self.cli_dir, "_last_client_doc_lookup")

    def consultar_ruc_venta(self):
        self._consulta_documento_manual(self.v_num.get(), "RUC", self.v_tipo_doc, self.v_nom, self.v_dir)

    def consultar_ruc_cliente(self):
        self._consulta_documento_manual(self.cli_num.get(), "RUC", self.cli_tipo, self.cli_nom, self.cli_dir)

    def consultar_dni_venta(self):
        self._consulta_documento_manual(self.v_num.get(), "DNI", self.v_tipo_doc, self.v_nom, self.v_dir)

    def consultar_dni_cliente(self):
        self._consulta_documento_manual(self.cli_num.get(), "DNI", self.cli_tipo, self.cli_nom, self.cli_dir)

    # REGISTRO / AUDITORÍA
    def registrar_accion(self, accion, detalle):
        try:
            from datetime import datetime
            row = {
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "usuario": self.user.get("usuario", ""),
                "rol": self.user.get("rol", ""),
                "empresa": self.user.get("empresa", ""),
                "accion": accion,
                "detalle": detalle
            }
            fn = getattr(api_client, "registrar_auditoria", None) if api_client is not None else None
            if callable(fn):
                fn(row)

            archivo = "registro_acciones.json"
            data = []
            if os.path.exists(archivo):
                with open(archivo, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data.append(row)
            with open(archivo, "w", encoding="utf-8") as f:
                json.dump(data[-5000:], f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def build_auditoria(self):
        frame = self.frames["auditoria"]
        card = self.set_card(frame)
        tk.Label(card, text="Registro de actividad", bg=CARD_BG, fg=TEXT, font=("Arial", 20, "bold")).pack(anchor="w", padx=12, pady=10)
        top = tk.Frame(card, bg=CARD_BG); top.pack(fill="x", padx=12, pady=6)
        tk.Label(top, text="Buscar", bg=CARD_BG).pack(side="left")
        self.audit_search = tk.Entry(top, width=35); self.audit_search.pack(side="left", padx=6)
        self.audit_search.bind("<KeyRelease>", lambda e: self.refresh_auditoria())
        tk.Button(top, text="Actualizar", command=self.refresh_auditoria, bg=ACCENT, fg="white", relief="flat").pack(side="left", padx=6)
        cols = ("Fecha", "Usuario", "Rol", "Empresa", "Acción", "Detalle")
        self.tree_auditoria = ttk.Treeview(card, columns=cols, show="headings", height=20)
        for c, w in zip(cols, [150, 120, 90, 120, 160, 520]):
            self.tree_auditoria.heading(c, text=c); self.tree_auditoria.column(c, width=w, anchor="center")
        self.tree_auditoria.pack(fill="both", expand=True, padx=12, pady=8)

    def refresh_auditoria(self):
        if not hasattr(self, "tree_auditoria"): return
        for i in self.tree_auditoria.get_children(): self.tree_auditoria.delete(i)
        q = ""
        try: q = self.audit_search.get().strip().lower()
        except Exception: pass

        data = []
        try:
            fn = getattr(api_client, "obtener_auditoria", None) if api_client is not None else None
            if callable(fn):
                data = fn(q, 1000) or []
        except Exception:
            data = []

        if not data:
            try:
                if os.path.exists("registro_acciones.json"):
                    with open("registro_acciones.json", "r", encoding="utf-8") as f:
                        data = list(reversed(json.load(f)[-1000:]))
            except Exception:
                data = []

        for r in data:
            texto = f'{r.get("fecha","")} {r.get("usuario","")} {r.get("rol","")} {r.get("empresa","")} {r.get("accion","")} {r.get("detalle","")}'.lower()
            if q and q not in texto: continue
            self.tree_auditoria.insert("", "end", values=(r.get("fecha",""), r.get("usuario",""), r.get("rol",""), r.get("empresa",""), r.get("accion",""), r.get("detalle","")))

    # SUCURSALES / GIOMAR
    def es_giomar_admin(self):
        return str(self.user.get("usuario", "")).strip().lower() == "giomar"

    def crear_sucursal_ui(self):
        if not self.es_giomar_admin():
            messagebox.showerror("Acceso denegado", "Solo Giomar puede crear sucursales.")
            return
        win = tk.Toplevel(self.root)
        win.title("Crear sucursal")
        win.geometry("420x360")
        win.configure(bg=CARD_BG)
        tk.Label(win, text="Crear nueva sucursal", bg=CARD_BG, fg=TEXT, font=("Arial", 16, "bold")).pack(pady=12)
        tk.Label(win, text="Nombre visible", bg=CARD_BG).pack(anchor="w", padx=20)
        ent_nombre = tk.Entry(win, width=42); ent_nombre.pack(padx=20, pady=4)
        tk.Label(win, text="Código interno (sin espacios)", bg=CARD_BG).pack(anchor="w", padx=20)
        ent_codigo = tk.Entry(win, width=42); ent_codigo.pack(padx=20, pady=4)
        tk.Label(win, text="Base SQL", bg=CARD_BG).pack(anchor="w", padx=20)
        ent_db = tk.Entry(win, width=42); ent_db.pack(padx=20, pady=4)

        def autodb(*args):
            if ent_nombre.get().strip() and not ent_db.get().strip():
                ent_db.insert(0, "ERP_" + ent_nombre.get().strip().replace(" ", ""))
        ent_nombre.bind("<FocusOut>", autodb)

        def guardar():
            nombre = ent_nombre.get().strip().upper()
            codigo = ent_codigo.get().strip().lower().replace(" ", "_")
            db = ent_db.get().strip() or ("ERP_" + nombre.replace(" ", ""))
            if not nombre or not codigo:
                messagebox.showwarning("Aviso", "Completa nombre y código.")
                return
            fn = getattr(api_client, "guardar_sucursal", None) if api_client is not None else None
            if callable(fn):
                resp = fn(codigo, nombre, self.user.get("usuario", ""))
                if api_response_ok(resp):
                    messagebox.showinfo("Sucursal creada", f"Sucursal guardada en la API central.\n\nCódigo: {codigo}")
                    self.registrar_accion("SUCURSAL CREADA", f"{nombre} / {codigo}")
                    win.destroy()
                    return
                messagebox.showerror("Error", (resp or {}).get("msg", "No se pudo guardar la sucursal en la API."))
                return
            data = {}
            if os.path.exists("sucursales.json"):
                try:
                    with open("sucursales.json", "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data[codigo] = {"nombre": nombre, "db": db}
            with open("sucursales.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            messagebox.showinfo("Sucursal creada", f"Sucursal guardada localmente.\n\nCódigo: {codigo}\nBase: {db}\n\nRecuerda crear la base en SQL y agregarla en la API.")
            self.registrar_accion("SUCURSAL CREADA", f"{nombre} / {codigo} / {db}")
            win.destroy()

        tk.Button(win, text="Guardar sucursal", command=guardar, bg=ACCENT, fg="white", relief="flat").pack(pady=16)

    def admin_branch_permissions_ui(self):
        if not self.es_giomar_admin():
            messagebox.showerror("Acceso denegado", "Solo Giomar puede administrar permisos.")
            return
        win = tk.Toplevel(self.root)
        win.title("Permisos por sucursal")
        win.geometry("720x650")
        win.configure(bg=CARD_BG)

        tk.Label(win, text="Permisos por sucursal", bg=CARD_BG, fg=TEXT, font=("Arial", 18, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(win, text="Activa o desactiva módulos para usuarios de cada sucursal. Giomar mantiene acceso maestro.", bg=CARD_BG, fg=MUTED, wraplength=660, justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        top = tk.Frame(win, bg=CARD_BG)
        top.pack(fill="x", padx=14, pady=8)
        tk.Label(top, text="Sucursal", bg=CARD_BG).pack(side="left")
        cb = ttk.Combobox(top, values=empresa_display_options(), state="readonly", width=35)
        cb.pack(side="left", padx=8)
        opts = empresa_display_options()
        cb.set(opts[0] if opts else "COMPUTER ARMY")

        perms_frame = tk.LabelFrame(win, text="Módulos habilitados", bg=CARD_BG, fg=TEXT, padx=10, pady=10)
        perms_frame.pack(fill="both", expand=True, padx=14, pady=8)
        vars_map = {}
        info = tk.Label(win, text="", bg=CARD_BG, fg=MUTED)
        info.pack(anchor="w", padx=14, pady=(0, 4))

        def build_checks(permisos):
            for child in perms_frame.winfo_children():
                child.destroy()
            vars_map.clear()
            suc = empresa_to_key(cb.get())
            for idx, (text, key, _color) in enumerate(NAV_ITEMS):
                var = tk.BooleanVar(value=bool(permisos.get(key, True)))
                vars_map[key] = var
                chk = tk.Checkbutton(perms_frame, text=text, variable=var, bg=CARD_BG, fg=TEXT, activebackground=CARD_BG)
                chk.grid(row=idx // 2, column=idx % 2, sticky="w", padx=12, pady=5)

        def cargar():
            suc = empresa_to_key(cb.get())
            permisos = dict(DEFAULT_MODULE_PERMISSIONS)
            permisos["pagina_web"] = False
            try:
                fn = getattr(api_client, "obtener_permisos_sucursal", None) if api_client is not None else None
                resp = fn(suc) if callable(fn) else {"ok": False}
                data = api_response_get(resp, "permisos", {}) if api_response_ok(resp) else {}
                if isinstance(data, dict):
                    permisos.update({k: bool(v) for k, v in data.items() if k in permisos})
            except Exception:
                pass
            build_checks(permisos)
            info.config(text=f"Editando: {suc}. Pagina Web es la puerta para WooCommerce y futuras integraciones web/contables.")

        def guardar():
            suc = empresa_to_key(cb.get())
            permisos = {k: bool(v.get()) for k, v in vars_map.items()}
            fn = getattr(api_client, "guardar_permisos_sucursal", None) if api_client is not None else None
            resp = fn(suc, permisos, self.user.get("usuario", "Giomar")) if callable(fn) else {"ok": False, "msg": "Cliente API sin función."}
            if api_response_ok(resp):
                self.registrar_accion("PERMISOS SUCURSAL", f"{suc}: {permisos}")
                messagebox.showinfo("Permisos", "Permisos guardados. Los usuarios verán cambios al volver a iniciar sesión.")
                if suc == str(self.user.get("sucursal") or self.user.get("empresa") or "computer_army"):
                    self.sucursal_permisos = self.load_branch_permissions(suc)
            else:
                messagebox.showerror("Permisos", api_response_error(resp, "No se pudieron guardar permisos."))

        cb.bind("<<ComboboxSelected>>", lambda e: cargar())
        buttons = tk.Frame(win, bg=CARD_BG)
        buttons.pack(fill="x", padx=14, pady=12)
        tk.Button(buttons, text="Recargar", command=cargar, bg="#334155", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(buttons, text="Guardar permisos", command=guardar, bg=ACCENT, fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(buttons, text="Cerrar", command=win.destroy, bg="#64748b", fg="white", relief="flat").pack(side="right", padx=4)
        cargar()


    # GARANTIAS
    def build_garantias(self):
        frame = self.frames["garantias"]
        card = self.set_card(frame)
        tk.Label(card, text="Garantías", bg=CARD_BG, fg=TEXT, font=("Arial", 20, "bold")).pack(anchor="w", padx=12, pady=10)
        tk.Label(card, text="Control de recepción, revisión y entrega de garantías.", bg=CARD_BG, fg=MUTED, font=("Arial", 11)).pack(anchor="w", padx=12, pady=(0, 8))

        form = tk.Frame(card, bg=CARD_BG)
        form.pack(fill="x", padx=12, pady=6)
        self.gar_id = tk.StringVar(value="")
        labels = [("Cliente", "gar_cliente", 28), ("Documento", "gar_doc", 18), ("Producto", "gar_producto", 32), ("Serie", "gar_serie", 20)]
        for idx, (label, attr, width) in enumerate(labels):
            tk.Label(form, text=label, bg=CARD_BG, fg=TEXT).grid(row=idx // 2, column=(idx % 2) * 2, sticky="e", padx=6, pady=5)
            ent = tk.Entry(form, width=width)
            ent.grid(row=idx // 2, column=(idx % 2) * 2 + 1, sticky="w", padx=6, pady=5)
            setattr(self, attr, ent)
        tk.Label(form, text="Estado", bg=CARD_BG, fg=TEXT).grid(row=0, column=4, sticky="e", padx=6, pady=5)
        self.gar_estado = ttk.Combobox(form, values=["RECIBIDO", "REVISION", "APROBADO", "RECHAZADO", "ENTREGADO"], state="readonly", width=14)
        self.gar_estado.grid(row=0, column=5, sticky="w", padx=6, pady=5)
        self.gar_estado.set("RECIBIDO")
        tk.Label(form, text="Falla", bg=CARD_BG, fg=TEXT).grid(row=2, column=0, sticky="ne", padx=6, pady=5)
        self.gar_falla = tk.Text(form, height=3, width=58, wrap="word")
        self.gar_falla.grid(row=2, column=1, columnspan=3, sticky="we", padx=6, pady=5)
        tk.Label(form, text="Solución", bg=CARD_BG, fg=TEXT).grid(row=3, column=0, sticky="ne", padx=6, pady=5)
        self.gar_solucion = tk.Text(form, height=3, width=58, wrap="word")
        self.gar_solucion.grid(row=3, column=1, columnspan=3, sticky="we", padx=6, pady=5)
        self.gar_cambio_id = tk.StringVar(value="")
        tk.Label(form, text="Producto cambio", bg=CARD_BG, fg=TEXT).grid(row=4, column=0, sticky="e", padx=6, pady=5)
        self.gar_producto_cambio = tk.Entry(form, width=42)
        self.gar_producto_cambio.grid(row=4, column=1, columnspan=2, sticky="we", padx=6, pady=5)
        tk.Button(form, text="Buscar", command=self.buscar_producto_cambio_garantia, bg="#2563eb", fg="white", relief="flat").grid(row=4, column=3, sticky="w", padx=6, pady=5)
        tk.Label(form, text="Serie cambio", bg=CARD_BG, fg=TEXT).grid(row=5, column=0, sticky="e", padx=6, pady=5)
        self.gar_serie_cambio = tk.Entry(form, width=20)
        self.gar_serie_cambio.grid(row=5, column=1, sticky="w", padx=6, pady=5)
        tk.Label(form, text="Cant.", bg=CARD_BG, fg=TEXT).grid(row=5, column=2, sticky="e", padx=6, pady=5)
        self.gar_cantidad_cambio = tk.Entry(form, width=8)
        self.gar_cantidad_cambio.insert(0, "1")
        self.gar_cantidad_cambio.grid(row=5, column=3, sticky="w", padx=6, pady=5)
        tk.Label(form, text="Diferencia S/", bg=CARD_BG, fg=TEXT).grid(row=5, column=4, sticky="e", padx=6, pady=5)
        self.gar_diferencia_cambio = tk.Entry(form, width=10)
        self.gar_diferencia_cambio.insert(0, "0")
        self.gar_diferencia_cambio.grid(row=5, column=5, sticky="w", padx=6, pady=5)

        actions = tk.Frame(card, bg=CARD_BG)
        actions.pack(fill="x", padx=12, pady=4)
        tk.Button(actions, text="Guardar garantía", command=self.save_garantia_ui, bg=ACCENT, fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(actions, text="Guardar y aplicar cambio", command=lambda: self.save_garantia_ui(aplicar_cambio=True), bg="#dc2626", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(actions, text="Nuevo", command=self.clear_garantia_form, bg="#334155", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Label(actions, text="Buscar", bg=CARD_BG, fg=TEXT).pack(side="left", padx=(18, 4))
        self.gar_search = tk.Entry(actions, width=34)
        self.gar_search.pack(side="left", padx=4)
        self.gar_search.bind("<Return>", lambda e: self.refresh_garantias())
        tk.Button(actions, text="Refrescar", command=self.refresh_garantias, bg="#0f766e", fg="white", relief="flat").pack(side="left", padx=4)

        cols = ("ID", "Fecha", "Cliente", "Documento", "Producto", "Serie", "Estado", "Cambio", "Falla", "Solución", "Usuario")
        self.tree_garantias = ttk.Treeview(card, columns=cols, show="headings", height=14)
        widths = [55, 135, 180, 120, 230, 130, 95, 220, 230, 210, 100]
        for c, w in zip(cols, widths):
            self.tree_garantias.heading(c, text=c)
            self.tree_garantias.column(c, width=w, anchor="w")
        self.tree_garantias.pack(fill="both", expand=True, padx=12, pady=8)
        self.tree_garantias.bind("<<TreeviewSelect>>", self.load_selected_garantia)
        self.refresh_garantias()

    def clear_garantia_form(self):
        self.gar_id.set("")
        for ent in (self.gar_cliente, self.gar_doc, self.gar_producto, self.gar_serie):
            ent.delete(0, tk.END)
        self.gar_cambio_id.set("")
        self.gar_producto_cambio.delete(0, tk.END)
        self.gar_serie_cambio.delete(0, tk.END)
        self.gar_cantidad_cambio.delete(0, tk.END)
        self.gar_cantidad_cambio.insert(0, "1")
        self.gar_diferencia_cambio.delete(0, tk.END)
        self.gar_diferencia_cambio.insert(0, "0")
        self.gar_estado.set("RECIBIDO")
        self.gar_falla.delete("1.0", tk.END)
        self.gar_solucion.delete("1.0", tk.END)

    def save_garantia_ui(self, aplicar_cambio=False):
        try:
            cantidad_cambio = max(0, int(float(self.gar_cantidad_cambio.get().strip() or 0)))
        except Exception:
            cantidad_cambio = 0
        try:
            diferencia_precio = float((self.gar_diferencia_cambio.get().strip() or "0").replace(",", "."))
        except Exception:
            diferencia_precio = 0
        payload = {
            "id": self.gar_id.get().strip(),
            "cliente": self.gar_cliente.get().strip(),
            "documento": self.gar_doc.get().strip(),
            "producto": self.gar_producto.get().strip(),
            "serie": self.gar_serie.get().strip(),
            "falla": self.gar_falla.get("1.0", tk.END).strip(),
            "estado": self.gar_estado.get(),
            "solucion": self.gar_solucion.get("1.0", tk.END).strip(),
            "usuario": self.user.get("usuario", ""),
            "producto_cambio_id": int(self.gar_cambio_id.get() or 0) or None,
            "producto_cambio": self.gar_producto_cambio.get().strip(),
            "serie_cambio": self.gar_serie_cambio.get().strip(),
            "cantidad_cambio": cantidad_cambio,
            "diferencia_precio": diferencia_precio,
            "aplicar_cambio": bool(aplicar_cambio),
        }
        if not payload["cliente"] or not payload["producto"] or not payload["falla"]:
            messagebox.showwarning("Garantía", "Completa cliente, producto y falla.")
            return
        if aplicar_cambio:
            if not payload["producto_cambio"]:
                messagebox.showwarning("Garantía", "Selecciona el producto que se entregará como cambio.")
                return
            if not messagebox.askyesno("Aplicar cambio", "Esto descontará stock del producto de cambio y marcará la garantía como ENTREGADO.\n\n¿Continuar?"):
                return
        fn = getattr(api_client, "guardar_garantia", None) if api_client is not None else None
        r = fn(payload) if callable(fn) else _api_json("post", "/garantias", {"ok": False}, json=payload)
        if api_response_ok(r):
            messagebox.showinfo("Garantía", "Garantía guardada." + (" Stock descontado por cambio." if aplicar_cambio else ""))
            self.registrar_accion("GARANTIA GUARDADA", f'{payload["cliente"]} / {payload["producto"]} / {payload["estado"]}')
            self.clear_garantia_form()
            self.refresh_garantias()
        else:
            messagebox.showerror("Garantía", api_response_error(r, "No se pudo guardar."))

    def refresh_garantias(self):
        if not hasattr(self, "tree_garantias"):
            return
        for i in self.tree_garantias.get_children():
            self.tree_garantias.delete(i)
        q = self.gar_search.get().strip() if hasattr(self, "gar_search") else ""
        fn = getattr(api_client, "obtener_garantias", None) if api_client is not None else None
        data = fn(q) if callable(fn) else (_api_json("get", f"/garantias?q={urllib.parse.quote(q)}", []) or [])
        for g in data or []:
            cambio = g.get("producto_cambio", "") or ""
            if g.get("cambio_aplicado"):
                cambio = f"APLICADO: {cambio}"
            elif cambio:
                cambio = f"PENDIENTE: {cambio}"
            self.tree_garantias.insert("", "end", values=(
                g.get("id", ""), g.get("fecha", ""), g.get("cliente", ""), g.get("documento", ""),
                g.get("producto", ""), g.get("serie", ""), g.get("estado", ""),
                cambio, g.get("falla", ""), g.get("solucion", ""), g.get("usuario", "")
            ))

    def load_selected_garantia(self, event=None):
        sel = self.tree_garantias.selection()
        if not sel:
            return
        vals = self.tree_garantias.item(sel[0], "values")
        self.clear_garantia_form()
        self.gar_id.set(str(vals[0]))
        self.gar_cliente.insert(0, vals[2])
        self.gar_doc.insert(0, vals[3])
        self.gar_producto.insert(0, vals[4])
        self.gar_serie.insert(0, vals[5])
        self.gar_estado.set(vals[6] or "RECIBIDO")
        cambio = str(vals[7] or "")
        cambio = re.sub(r"^(APLICADO|PENDIENTE):\s*", "", cambio, flags=re.I)
        self.gar_producto_cambio.insert(0, cambio)
        self.gar_falla.insert("1.0", vals[8])
        self.gar_solucion.insert("1.0", vals[9])

    def buscar_producto_cambio_garantia(self):
        win = tk.Toplevel(self.root)
        win.title("Buscar producto para cambio")
        win.geometry("860x520")
        win.configure(bg=CARD_BG)
        top = tk.Frame(win, bg=CARD_BG)
        top.pack(fill="x", padx=12, pady=10)
        tk.Label(top, text="Buscar producto", bg=CARD_BG, fg=TEXT).pack(side="left", padx=(0, 6))
        search = tk.Entry(top, width=46)
        search.pack(side="left", padx=6)
        cols = ("ID", "Nombre", "Categoria", "Marca", "Stock", "Precio")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=16)
        widths = [70, 360, 150, 120, 70, 90]
        for c, w in zip(cols, widths):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="w")
        tree.pack(fill="both", expand=True, padx=12, pady=8)

        def cargar():
            for item in tree.get_children():
                tree.delete(item)
            q = search.get().strip().lower()
            fn = getattr(api_client, "obtener_productos", None) if api_client is not None else None
            productos = fn() if callable(fn) else (_api_json("get", "/productos", []) or [])
            count = 0
            for p in productos or []:
                texto = f'{p.get("nombre","")} {p.get("categoria","")} {p.get("marca","")} {p.get("modelo","")}'.lower()
                if q and q not in texto:
                    continue
                tree.insert("", "end", values=(
                    p.get("id", ""),
                    p.get("nombre", ""),
                    p.get("categoria", ""),
                    p.get("marca", ""),
                    p.get("stock", 0),
                    p.get("precio_venta", 0),
                ))
                count += 1
                if count >= 120:
                    break

        def seleccionar():
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0], "values")
            self.gar_cambio_id.set(str(vals[0] or ""))
            self.gar_producto_cambio.delete(0, tk.END)
            self.gar_producto_cambio.insert(0, str(vals[1] or ""))
            win.destroy()

        search.bind("<Return>", lambda e: cargar())
        tree.bind("<Double-1>", lambda e: seleccionar())
        tk.Button(top, text="Buscar", command=cargar, bg="#2563eb", fg="white", relief="flat").pack(side="left", padx=6)
        tk.Button(top, text="Seleccionar", command=seleccionar, bg="#0f766e", fg="white", relief="flat").pack(side="left", padx=6)
        cargar()


    def build_erp_moderno(self):
        frame = self.frames["erp_moderno"]
        card = self.set_card(frame)
        api_base = getattr(api_client, "BASE_URL", "https://erp-api-7x3d.onrender.com").rstrip("/") if api_client is not None else "https://erp-api-7x3d.onrender.com"
        modern_url = f"{api_base}/erp/?desktop=pc"
        tk.Label(card, text="ERP Moderno", bg=CARD_BG, fg=TEXT, font=("Arial", 24, "bold")).pack(anchor="w", padx=18, pady=(18, 4))
        tk.Label(
            card,
            text="Misma interfaz de Android/DeX para usar en PC con el mismo servidor, usuarios, productos, caja, documentos e inventario.",
            bg=CARD_BG,
            fg=MUTED,
            font=("Arial", 11),
            wraplength=760,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 14))

        panel = tk.Frame(card, bg="#f8fafc", highlightthickness=1, highlightbackground=BORDER)
        panel.pack(fill="x", padx=18, pady=8)
        tk.Label(panel, text="Interfaz moderna interna", bg="#f8fafc", fg=TEXT, font=("Arial", 13, "bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 4))
        tk.Label(panel, text="Abre el ERP con el estilo Android/DeX dentro de una ventana del sistema, sin abrir Google ni otro navegador.", bg="#f8fafc", fg=MUTED, font=("Arial", 10), wraplength=720, justify="left").grid(row=1, column=0, sticky="w", padx=14, pady=(0, 12))
        panel.grid_columnconfigure(0, weight=1)

        actions = tk.Frame(panel, bg="#f8fafc")
        actions.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 14))

        def open_modern():
            try:
                import webview
                webview.create_window("G&G ERP Moderno", modern_url, width=1360, height=820, min_size=(1100, 700))
                webview.start(gui="edgechromium")
            except Exception as e:
                try:
                    webbrowser.open(modern_url)
                except Exception:
                    pass
                messagebox.showwarning(
                    "ERP Moderno",
                    "No se pudo abrir el visor interno del ERP. Se abrio como respaldo en el navegador.\n"
                    f"{e}"
                )

        tk.Button(actions, text="Abrir ERP moderno interno", command=open_modern, bg="#2563eb", fg="white", relief="flat", padx=16, pady=9).pack(side="left", padx=4)
        tk.Button(actions, text="Abrir modo clasico", command=lambda: messagebox.showinfo("ERP clasico", "Cierra y abre el acceso directo con --classic solo si necesitas el modo anterior."), bg="#e2e8f0", fg=TEXT, relief="flat", padx=16, pady=9).pack(side="left", padx=4)

        modules = tk.LabelFrame(card, text="Distribucion como Android/DeX", bg=CARD_BG, fg=TEXT, padx=10, pady=10)
        modules.pack(fill="x", padx=18, pady=12)
        for idx, label in enumerate(["Panel", "Ventas", "Caja", "Clientes", "Productos", "Inventario", "Compras", "Documentos", "Usuarios", "Radio"]):
            tk.Label(modules, text=label, bg="#eef2ff", fg="#1e3a8a", font=("Arial", 10, "bold"), padx=14, pady=8).grid(row=idx // 5, column=idx % 5, sticky="ew", padx=5, pady=5)
        for col in range(5):
            modules.grid_columnconfigure(col, weight=1)

    # PAGINA WEB / WOOCOMMERCE
    def build_pagina_web(self):
        frame = self.frames["pagina_web"]
        card = self.set_card(frame)
        tk.Label(card, text="Pagina Web / WooCommerce", bg=CARD_BG, fg=TEXT, font=("Arial", 20, "bold")).pack(anchor="w", padx=12, pady=10)

        info = tk.LabelFrame(card, text="Conexion web de esta sucursal", bg=CARD_BG, fg=TEXT)
        info.pack(fill="x", padx=12, pady=8)
        for col in range(6):
            info.grid_columnconfigure(col, weight=1 if col in (1, 3, 5) else 0)
        tk.Label(info, text="URL tienda", bg=CARD_BG, fg=TEXT).grid(row=0, column=0, sticky="e", padx=6, pady=5)
        self.wp_store_url = tk.Entry(info, width=34)
        self.wp_store_url.grid(row=0, column=1, sticky="we", padx=6, pady=5)
        tk.Label(info, text="Consumer Key", bg=CARD_BG, fg=TEXT).grid(row=0, column=2, sticky="e", padx=6, pady=5)
        self.wp_consumer_key = tk.Entry(info, width=34)
        self.wp_consumer_key.grid(row=0, column=3, sticky="we", padx=6, pady=5)
        tk.Label(info, text="Consumer Secret", bg=CARD_BG, fg=TEXT).grid(row=1, column=0, sticky="e", padx=6, pady=5)
        self.wp_consumer_secret = tk.Entry(info, width=34, show="*")
        self.wp_consumer_secret.grid(row=1, column=1, sticky="we", padx=6, pady=5)
        self.wp_config_status = tk.Label(info, text="", bg=CARD_BG, fg=MUTED)
        self.wp_config_status.grid(row=1, column=2, columnspan=2, sticky="w", padx=6, pady=5)
        tk.Button(info, text="Guardar conexion", command=self.save_wp_connection_config, bg=ACCENT, fg="white", relief="flat").grid(row=0, column=4, padx=6, pady=5)
        tk.Button(info, text="Probar conexion", command=self.test_wp_connection, bg="#334155", fg="white", relief="flat").grid(row=1, column=4, padx=6, pady=5)

        tools = tk.Frame(card, bg=CARD_BG)
        tools.pack(fill="x", padx=12, pady=6)
        tk.Label(tools, text="Buscar producto", bg=CARD_BG).pack(side="left", padx=(0, 6))
        self.wp_search = tk.Entry(tools, width=34)
        self.wp_search.pack(side="left", padx=4)
        self.wp_search.bind("<Return>", lambda e: self.refresh_wp_items())
        tk.Button(tools, text="Cargar productos", command=self.refresh_wp_items, bg="#0f766e", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(tools, text="Nuevo producto", command=self.new_wp_item, bg="#7c3aed", fg="white", relief="flat").pack(side="left", padx=4)
        self.wp_auto_sync = tk.BooleanVar(value=bool(self.cfg.get("woo_auto_sync", False)))
        tk.Checkbutton(tools, text="Auto sync ERP", variable=self.wp_auto_sync, command=self.toggle_woo_auto_sync, bg=CARD_BG, fg=TEXT, activebackground=CARD_BG).pack(side="left", padx=8)
        self.wp_only_stock = tk.BooleanVar(value=False)
        tk.Checkbutton(tools, text="Solo stock", variable=self.wp_only_stock, bg=CARD_BG, fg=TEXT, activebackground=CARD_BG).pack(side="left", padx=4)
        tk.Button(tools, text="Sincronizar ERP -> Web", command=self.sync_all_erp_products_woo, bg="#ea580c", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(tools, text="Imagenes Web -> ERP", command=self.sync_woo_images_to_erp, bg="#2563eb", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(tools, text="Cargar Web -> Ventas", command=self.import_woo_products_to_sales, bg="#16a34a", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(tools, text="Abrir tienda", command=self.open_wp_store, bg="#334155", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(tools, text="Refrescar", command=self.refresh_wp_items, bg="#0891b2", fg="white", relief="flat").pack(side="left", padx=4)

        self.wp_cards = tk.Frame(card, bg=CARD_BG)
        self.wp_cards.pack(fill="x", padx=12, pady=(0, 6))
        self.wp_card_images = []
        self.wp_items_cache = []

        body = tk.Frame(card, bg=CARD_BG)
        body.pack(fill="both", expand=True, padx=12, pady=8)

        cols = ("ID", "Producto", "SKU", "Estado", "Precio", "Oferta", "Stock", "Stock Web")
        self.tree_wp = ttk.Treeview(body, columns=cols, show="headings", height=18)
        for c, w in zip(cols, [70, 310, 125, 85, 90, 90, 80, 95]):
            self.tree_wp.heading(c, text=c)
            self.tree_wp.column(c, width=w, anchor="w")
        self.tree_wp.pack(side="left", fill="y", padx=(0, 8))
        self.tree_wp.bind("<<TreeviewSelect>>", lambda e: self.load_selected_wp_item())

        editor = tk.Frame(body, bg=CARD_BG)
        editor.pack(side="left", fill="both", expand=True)
        self.wp_item_id = tk.StringVar(value="")

        tk.Label(editor, text="Nombre producto", bg=CARD_BG).grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.wp_name = tk.Entry(editor, width=48)
        self.wp_name.grid(row=0, column=1, columnspan=3, sticky="we", padx=4, pady=4)

        tk.Label(editor, text="SKU", bg=CARD_BG).grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.wp_sku = tk.Entry(editor, width=18)
        self.wp_sku.grid(row=1, column=1, sticky="w", padx=4, pady=4)
        tk.Label(editor, text="Estado", bg=CARD_BG).grid(row=1, column=2, sticky="e", padx=4, pady=4)
        self.wp_status = ttk.Combobox(editor, values=["publish", "draft", "pending", "private"], state="readonly", width=14)
        self.wp_status.grid(row=1, column=3, sticky="w", padx=4, pady=4)
        self.wp_status.set("publish")

        tk.Label(editor, text="Precio normal", bg=CARD_BG).grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.wp_regular_price = tk.Entry(editor, width=18)
        self.wp_regular_price.grid(row=2, column=1, sticky="w", padx=4, pady=4)
        tk.Label(editor, text="Precio oferta", bg=CARD_BG).grid(row=2, column=2, sticky="e", padx=4, pady=4)
        self.wp_sale_price = tk.Entry(editor, width=18)
        self.wp_sale_price.grid(row=2, column=3, sticky="w", padx=4, pady=4)

        tk.Label(editor, text="Stock", bg=CARD_BG).grid(row=3, column=0, sticky="w", padx=4, pady=4)
        self.wp_stock = tk.Entry(editor, width=18)
        self.wp_stock.grid(row=3, column=1, sticky="w", padx=4, pady=4)
        self.wp_manage_stock = tk.BooleanVar(value=True)
        tk.Checkbutton(editor, text="Manejar stock", variable=self.wp_manage_stock, bg=CARD_BG, fg=TEXT, activebackground=CARD_BG).grid(row=3, column=2, sticky="w", padx=4, pady=4)

        tk.Label(editor, text="Imagen URL", bg=CARD_BG).grid(row=4, column=0, sticky="w", padx=4, pady=4)
        self.wp_image_url = tk.Entry(editor, width=48)
        self.wp_image_url.grid(row=4, column=1, columnspan=3, sticky="we", padx=4, pady=4)

        tk.Label(editor, text="Descripcion corta", bg=CARD_BG).grid(row=5, column=0, sticky="nw", padx=4, pady=4)
        self.wp_short = tk.Text(editor, height=4, wrap="word")
        self.wp_short.grid(row=5, column=1, columnspan=3, sticky="nsew", padx=4, pady=4)

        tk.Label(editor, text="Descripcion", bg=CARD_BG).grid(row=6, column=0, sticky="nw", padx=4, pady=4)
        self.wp_description = tk.Text(editor, height=13, wrap="word")
        self.wp_description.grid(row=6, column=1, columnspan=3, sticky="nsew", padx=4, pady=4)
        editor.grid_columnconfigure(1, weight=1)
        editor.grid_rowconfigure(6, weight=1)

        btns = tk.Frame(editor, bg=CARD_BG)
        btns.grid(row=7, column=1, columnspan=3, sticky="w", pady=8)
        tk.Button(btns, text="Guardar producto", command=self.save_wp_item, bg=ACCENT, fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="Limpiar editor", command=self.new_wp_item, bg="#334155", fg="white", relief="flat").pack(side="left", padx=4)
        self.load_wp_connection_config()

    def load_wp_connection_config(self):
        try:
            fn = getattr(api_client, "obtener_config_web", None) if api_client is not None else None
            r = fn() if callable(fn) else {"ok": False}
            data = api_response_get(r, "data", {}) if api_response_ok(r) else {}
        except Exception:
            data = {}
        for entry in (self.wp_store_url, self.wp_consumer_key, self.wp_consumer_secret):
            entry.delete(0, tk.END)
        self.wp_store_url.insert(0, data.get("wc_store_url", ""))
        self.wp_consumer_key.insert(0, data.get("wc_consumer_key", ""))
        self.wp_consumer_secret.insert(0, data.get("wc_consumer_secret", ""))
        if hasattr(self, "wp_auto_sync"):
            self.wp_auto_sync.set(bool(data.get("woo_auto_sync", self.cfg.get("woo_auto_sync", False))))
        suc = str(self.user.get("sucursal") or self.user.get("empresa") or "computer_army")
        self.wp_config_status.config(text=f"Config local de sucursal: {suc}")

    def save_wp_connection_config(self):
        payload = {
            "wc_store_url": self.wp_store_url.get().strip(),
            "wc_consumer_key": self.wp_consumer_key.get().strip(),
            "wc_consumer_secret": self.wp_consumer_secret.get().strip(),
            "woo_auto_sync": bool(self.wp_auto_sync.get()) if hasattr(self, "wp_auto_sync") else False,
        }
        fn = getattr(api_client, "guardar_config_web", None) if api_client is not None else None
        r = fn(payload) if callable(fn) else {"ok": False, "msg": "Cliente API sin configuracion web."}
        if api_response_ok(r):
            self.wp_config_status.config(text="Conexion web guardada para esta sucursal.")
            messagebox.showinfo("Pagina Web", "Conexion guardada para esta sucursal.")
        else:
            messagebox.showerror("Pagina Web", api_response_error(r, "No se pudo guardar la conexion web."))

    def open_wp_store(self):
        url = self.wp_store_url.get().strip() if hasattr(self, "wp_store_url") else ""
        if not url:
            messagebox.showwarning("Pagina Web", "Configura la URL de la tienda para esta sucursal.")
            return
        webbrowser.open(url)

    def test_wp_connection(self):
        r = api_client.woo_test()
        if api_response_ok(r):
            messagebox.showinfo("WooCommerce", f"Conexion correcta para esta sucursal.\nSitio: {r.get('site_url', 'WooCommerce')}")
        else:
            messagebox.showerror("WooCommerce", api_response_error(r, "No se pudo conectar. Revisa URL, Consumer Key y Secret de esta sucursal."))

    def refresh_wp_items(self):
        for i in self.tree_wp.get_children():
            self.tree_wp.delete(i)
        r = api_client.woo_productos(self.wp_search.get().strip())
        if not api_response_ok(r):
            messagebox.showerror("WooCommerce", api_response_error(r, "No se pudo cargar productos."))
            return
        self.wp_items_cache = api_response_get(r, "data", []) or []
        for item in self.wp_items_cache:
            self.tree_wp.insert("", "end", values=(
                item.get("id", ""),
                item.get("name", ""),
                item.get("sku", ""),
                item.get("status", ""),
                item.get("regular_price", ""),
                item.get("sale_price", ""),
                item.get("stock_quantity", ""),
                item.get("stock_status", ""),
            ))
        self.render_wp_product_cards()

    def render_wp_product_cards(self):
        if not hasattr(self, "wp_cards"):
            return
        for child in self.wp_cards.winfo_children():
            child.destroy()
        self.wp_card_images = []
        for idx, item in enumerate((self.wp_items_cache or [])[:6]):
            images = item.get("images") or []
            src = images[0].get("src", "") if images and isinstance(images[0], dict) else ""
            p = {"id": f'woo-{item.get("id","")}', "nombre": item.get("name", ""), "imagen_url": src, "precio_venta": item.get("regular_price", 0), "stock": item.get("stock_quantity") or 0}
            card = tk.Frame(self.wp_cards, bg="#ffffff", highlightthickness=1, highlightbackground="#e2e8f0", width=160, height=150)
            card.grid(row=0, column=idx, padx=5, pady=5, sticky="n")
            card.grid_propagate(False)
            img = self.product_image_for_ui(p, size=(92, 68))
            self.wp_card_images.append(img)
            tk.Button(card, image=img, bg="#ffffff", relief="flat", command=lambda i=idx: self.pick_wp_card(i)).pack(pady=(8, 2))
            tk.Label(card, text=str(item.get("name", ""))[:34], bg="#ffffff", fg=TEXT, font=("Arial", 8, "bold"), wraplength=140, justify="center").pack(padx=4)
            tk.Label(card, text=f'S/ {item.get("regular_price", "")}', bg="#ffffff", fg="#0f766e", font=("Arial", 9, "bold")).pack()

    def pick_wp_card(self, idx):
        children = self.tree_wp.get_children()
        if idx < len(children):
            self.tree_wp.selection_set(children[idx])
            self.tree_wp.focus(children[idx])
            self.load_selected_wp_item()

    def load_selected_wp_item(self):
        sel = self.tree_wp.selection()
        if not sel:
            return
        vals = self.tree_wp.item(sel[0], "values")
        product_id = vals[0]
        r = api_client.woo_producto(product_id)
        if not api_response_ok(r):
            messagebox.showerror("WooCommerce", api_response_error(r, "No se pudo abrir el producto."))
            return
        data = api_response_get(r, "data", {}) or {}
        self.new_wp_item(clear_id=False)
        self.wp_item_id.set(str(data.get("id", "")))
        self.wp_name.insert(0, data.get("name", ""))
        self.wp_sku.insert(0, data.get("sku", ""))
        self.wp_status.set(data.get("status", "publish"))
        self.wp_regular_price.insert(0, data.get("regular_price", ""))
        self.wp_sale_price.insert(0, data.get("sale_price", ""))
        stock = data.get("stock_quantity", "")
        self.wp_stock.insert(0, "" if stock is None else str(stock))
        self.wp_manage_stock.set(bool(data.get("manage_stock", False)))
        images = data.get("images") or []
        if images and isinstance(images[0], dict):
            self.wp_image_url.insert(0, images[0].get("src", ""))
        self.wp_short.insert("1.0", data.get("short_description", ""))
        self.wp_description.insert("1.0", data.get("description", ""))

    def new_wp_item(self, clear_id=True):
        if clear_id:
            self.wp_item_id.set("")
        for entry in (self.wp_name, self.wp_sku, self.wp_regular_price, self.wp_sale_price, self.wp_stock, self.wp_image_url):
            entry.delete(0, tk.END)
        self.wp_status.set("publish")
        self.wp_manage_stock.set(True)
        self.wp_short.delete("1.0", tk.END)
        self.wp_description.delete("1.0", tk.END)

    def save_wp_item(self):
        name = self.wp_name.get().strip()
        if not name:
            messagebox.showwarning("WooCommerce", "Ingresa el nombre del producto.")
            return
        payload = {
            "name": name,
            "sku": self.wp_sku.get().strip(),
            "status": self.wp_status.get() or "publish",
            "regular_price": self.wp_regular_price.get().strip(),
            "sale_price": self.wp_sale_price.get().strip(),
            "short_description": self.wp_short.get("1.0", tk.END).strip(),
            "description": self.wp_description.get("1.0", tk.END).strip(),
            "manage_stock": bool(self.wp_manage_stock.get()),
        }
        image_url = self.wp_image_url.get().strip()
        if image_url.startswith(("http://", "https://")):
            payload["images"] = [{"src": image_url}]
        stock_text = self.wp_stock.get().strip()
        if stock_text:
            try:
                payload["stock_quantity"] = int(float(stock_text))
            except Exception:
                messagebox.showwarning("WooCommerce", "El stock debe ser numerico.")
                return
        r = api_client.woo_guardar_producto(self.wp_item_id.get().strip(), payload)
        if api_response_ok(r):
            data = api_response_get(r, "data", {}) or {}
            self.wp_item_id.set(str(data.get("id", self.wp_item_id.get())))
            messagebox.showinfo("WooCommerce", "Producto guardado correctamente.")
            self.refresh_wp_items()
        else:
            messagebox.showerror("WooCommerce", api_response_error(r, "No se pudo guardar."))

    def toggle_woo_auto_sync(self):
        self.cfg["woo_auto_sync"] = bool(self.wp_auto_sync.get())
        save_config(self.cfg)
        try:
            fn = getattr(api_client, "guardar_config_web", None) if api_client is not None else None
            if callable(fn):
                fn({
                    "wc_store_url": self.wp_store_url.get().strip() if hasattr(self, "wp_store_url") else "",
                    "wc_consumer_key": self.wp_consumer_key.get().strip() if hasattr(self, "wp_consumer_key") else "",
                    "wc_consumer_secret": self.wp_consumer_secret.get().strip() if hasattr(self, "wp_consumer_secret") else "",
                    "woo_auto_sync": bool(self.wp_auto_sync.get()),
                })
        except Exception:
            pass

    def sync_all_erp_products_woo(self):
        if not messagebox.askyesno("WooCommerce", "¿Sincronizar productos del ERP hacia la web?\n\nSe crearán/actualizarán productos y se asignará la categoría automáticamente."):
            return
        try:
            fn = getattr(api_client, "woo_sincronizar_productos_erp", None) if api_client is not None else None
            if callable(fn):
                r = fn(bool(self.wp_only_stock.get()))
            else:
                r = {"ok": False, "msg": "Cliente API sin función de sincronización masiva."}
        except Exception as e:
            messagebox.showerror("WooCommerce", f"No se pudo conectar.\n{e}")
            return
        if api_response_ok(r):
            errores = api_response_get(r, "errores", []) or []
            msg = f"Sincronización terminada.\nProductos revisados: {r.get('total', 0)}\nCorrectos: {r.get('sync_ok', 0)}"
            if errores:
                msg += f"\nErrores: {len(errores)}"
            messagebox.showinfo("WooCommerce", msg)
            self.refresh_wp_items()
        else:
            messagebox.showerror("WooCommerce", api_response_error(r, "No se pudo sincronizar productos."))

    def sync_woo_images_to_erp(self):
        if not messagebox.askyesno("WooCommerce", "¿Traer imagenes de la web hacia los productos del ERP?\n\nSe buscará por SKU ERP-ID y solo se actualizará Imagen URL. No toca stock ni precios."):
            return
        try:
            fn = getattr(api_client, "woo_sincronizar_imagenes_web", None) if api_client is not None else None
            if callable(fn):
                r = fn()
            else:
                r = {"ok": False, "msg": "Cliente API sin función de sincronización de imagenes."}
        except Exception as e:
            messagebox.showerror("WooCommerce", f"No se pudo conectar.\n{e}")
            return
        if api_response_ok(r):
            messagebox.showinfo("WooCommerce", f"Imagenes sincronizadas.\nProductos revisados: {r.get('total', 0)}\nActualizados: {r.get('updated', 0)}")
            self.refresh_products()
            self.refresh_sale_products_cache(force=True)
            self.refresh_wp_items()
        else:
            messagebox.showerror("WooCommerce", api_response_error(r, "No se pudieron sincronizar imagenes."))

    def import_woo_products_to_sales(self):
        if not messagebox.askyesno("WooCommerce", "¿Cargar productos de la pagina al ERP?\n\nAparecerán en Productos y Ventas con precio, stock, categoría e imagen de WooCommerce."):
            return
        try:
            fn = getattr(api_client, "woo_importar_productos_web", None) if api_client is not None else None
            if callable(fn):
                r = fn(self.wp_search.get().strip(), bool(self.wp_only_stock.get()))
            else:
                r = {"ok": False, "msg": "Cliente API sin función de importación Web -> ERP."}
        except Exception as e:
            messagebox.showerror("WooCommerce", f"No se pudo conectar.\n{e}")
            return
        if api_response_ok(r):
            messagebox.showinfo("WooCommerce", f"Productos cargados al ERP.\nCreados: {r.get('created', 0)}\nActualizados: {r.get('updated', 0)}")
            self.refresh_products()
            self.refresh_sale_products_cache(force=True)
            try:
                self.show_frame("ventas", "#059669")
            except Exception:
                pass
        else:
            messagebox.showerror("WooCommerce", api_response_error(r, "No se pudieron cargar productos de la web."))

    # AJUSTES
    def build_ajustes(self):
        frame = self.frames["ajustes"]
        card = self.set_card(frame)
        tk.Label(card, text="Ajustes", bg=CARD_BG, fg=TEXT, font=("Arial", 20, "bold")).pack(anchor="w", padx=12, pady=10)
        if self.es_giomar_admin():
            tk.Button(card, text="🏢 Crear nueva sucursal", command=self.crear_sucursal_ui, bg="#7c3aed", fg="white", relief="flat", padx=16, pady=8).pack(anchor="w", padx=12, pady=6)
            tk.Button(card, text="🔐 Permisos por sucursal", command=self.admin_branch_permissions_ui, bg="#0f766e", fg="white", relief="flat", padx=16, pady=8).pack(anchor="w", padx=12, pady=6)

        form = tk.Frame(card, bg=CARD_BG)
        form.pack(padx=12, pady=8, anchor="nw")

        def add_row(label, value, row, show=None):
            tk.Label(form, text=label, bg=CARD_BG).grid(row=row, column=0, sticky="e", padx=6, pady=6)
            e = tk.Entry(form, width=50, show=show)
            e.grid(row=row, column=1, padx=6, pady=6)
            e.insert(0, value)
            return e

        self.cfg_empresa = add_row("Empresa", self.cfg.get("empresa", ""), 0)
        self.cfg_ruc = add_row("RUC", self.cfg.get("ruc", ""), 1)
        self.cfg_dir = add_row("Dirección", self.cfg.get("direccion", ""), 2)
        self.cfg_tel = add_row("Teléfono", self.cfg.get("telefono", ""), 3)
        self.cfg_mail = add_row("Correo", self.cfg.get("correo", ""), 4)
        self.cfg_logo = add_row("Logo PNG", self.cfg.get("logo", ""), 5)
        self.cfg_dash = add_row("Imagen Dashboard", self.cfg.get("dashboard_img", ""), 6)
        self.cfg_msg = add_row("Mensaje", self.cfg.get("mensaje", ""), 7)
        self.cfg_f1 = add_row("Pie 1", self.cfg.get("footer_line1", ""), 8)
        self.cfg_f2 = add_row("Pie 2", self.cfg.get("footer_line2", ""), 9)
        self.cfg_bcp = add_row("Cuenta BCP", self.cfg.get("cuenta_bcp", ""), 10)
        self.cfg_int = add_row("Cuenta Interbank", self.cfg.get("cuenta_interbank", ""), 11)
        self.cfg_sp = add_row("Serie Proforma", self.cfg.get("doc_series", {}).get("PROFORMA", "P001"), 12)
        self.cfg_pase = add_row("Serie Pase", self.cfg.get("doc_series", {}).get("PASE", "PA001"), 13)
        self.cfg_sb = add_row("Serie Boleta", self.cfg.get("doc_series", {}).get("BOLETA", "B001"), 14)
        self.cfg_sf = add_row("Serie Factura", self.cfg.get("doc_series", {}).get("FACTURA", "F001"), 15)
        self.cfg_sunat_ruc = add_row("SUNAT RUC", self.cfg.get("sunat_ruc", self.cfg.get("ruc", "")), 16)
        self.cfg_sunat_usuario = add_row("SUNAT Usuario SOL", self.cfg.get("sunat_usuario", ""), 17)
        self.cfg_sunat_clave = add_row("SUNAT Clave SOL", self.cfg.get("sunat_clave", ""), 18, show="*")
        self.cfg_sunat_url = add_row("SUNAT URL SOL", self.cfg.get("sunat_url", "https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm"), 19)

        btns = tk.Frame(card, bg=CARD_BG)
        btns.pack(anchor="w", padx=12, pady=8)
        tk.Button(btns, text="Elegir logo", command=self.pick_logo, bg="#334155", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="Elegir imagen dashboard", command=self.pick_dashboard_img, bg="#334155", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="Guardar ajustes", command=self.save_settings, bg=ACCENT, fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="Editor visual documento", command=self.open_layout_editor, bg="#059669", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="Backup local", command=self.export_backup_local_ui, bg="#2563eb", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="Abrir SUNAT SOL", command=self.open_sunat_config_ui, bg="#7c3aed", fg="white", relief="flat").pack(side="left", padx=4)

    def pick_logo(self):
        path = filedialog.askopenfilename(filetypes=[("Imágenes", "*.png;*.jpg;*.jpeg;*.webp"), ("Todos", "*.*")])
        if path:
            self.cfg_logo.delete(0, tk.END); self.cfg_logo.insert(0, path)

    def pick_dashboard_img(self):
        path = filedialog.askopenfilename(filetypes=[("Imágenes", "*.png;*.jpg;*.jpeg;*.webp"), ("Todos", "*.*")])
        if path:
            self.cfg_dash.delete(0, tk.END); self.cfg_dash.insert(0, path)

    def save_settings(self):
        self.cfg.update({
            "empresa": self.cfg_empresa.get().strip(),
            "ruc": self.cfg_ruc.get().strip(),
            "direccion": self.cfg_dir.get().strip(),
            "telefono": self.cfg_tel.get().strip(),
            "correo": self.cfg_mail.get().strip(),
            "logo": self.cfg_logo.get().strip(),
            "dashboard_img": self.cfg_dash.get().strip(),
            "mensaje": self.cfg_msg.get().strip(),
            "footer_line1": self.cfg_f1.get().strip(),
            "footer_line2": self.cfg_f2.get().strip(),
            "cuenta_bcp": self.cfg_bcp.get().strip(),
            "cuenta_interbank": self.cfg_int.get().strip(),
            "sunat_ruc": self.cfg_sunat_ruc.get().strip(),
            "sunat_usuario": self.cfg_sunat_usuario.get().strip(),
            "sunat_clave": self.cfg_sunat_clave.get().strip(),
            "sunat_url": self.cfg_sunat_url.get().strip() or "https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm",
            "doc_series": {
                "PROFORMA": self.cfg_sp.get().strip() or "P001",
                "PASE": self.cfg_pase.get().strip() or "PA001",
                "BOLETA": self.cfg_sb.get().strip() or "B001",
                "FACTURA": self.cfg_sf.get().strip() or "F001"
            }
        })
        save_config(self.cfg)
        self.update_logo_ui()
        self.refresh_dashboard()
        self.update_next_doc()
        messagebox.showinfo("Éxito", "Ajustes guardados para todas las PCs.")

    def open_layout_editor(self):
        LayoutEditor(self.root, self.cfg, on_save=lambda: None)

    def export_backup_local_ui(self):
        if not messagebox.askyesno("Backup", "Se descargara un respaldo JSON completo de la sucursal actual en esta PC.\n\nUsalo solo cuando necesites respaldo para no consumir servidor de mas."):
            return
        data = _api_get_branch("/backup/export", {"ok": False})
        if not api_response_ok(data):
            messagebox.showerror("Backup", api_response_error(data, "No se pudo crear el backup."))
            return
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads, exist_ok=True)
        filename = f"gg_erp_backup_{today_ymd()}_{int(time.time())}.json"
        path = os.path.join(downloads, filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            messagebox.showinfo("Backup", f"Respaldo guardado:\n{path}")
        except Exception as e:
            messagebox.showerror("Backup", f"No se pudo guardar el archivo local.\n{e}")

    def refresh_all(self):
        self.update_next_doc()
        self.refresh_dashboard()
        self.refresh_clients()
        self.refresh_products()
        self.refresh_series()
        self.refresh_purchases()
        self.refresh_contabilidad()
        self.refresh_cash()
        self.refresh_users()
        try:
            self.comp_prov["values"] = [f'{p["id"]} - {p["nombre"]}' for p in obtener_proveedores()]
        except Exception:
            self.comp_prov["values"] = []
        self.comp_prod["values"] = [f'{p["id"]} - {p["nombre"]}' for p in obtener_productos()]


if __name__ == "__main__":
    try:
        if "--classic" not in sys.argv and os.getenv("GG_ERP_CLASSIC", "").strip() != "1":
            if run_modern_desktop_app():
                sys.exit(0)

        root = tk.Tk()
        # Captura errores en la interfaz para que no se cierre silenciosamente
        def on_error(etype, evalue, etb):
            import traceback
            err = "".join(traceback.format_exception(etype, evalue, etb))
            messagebox.showerror("Error Critico", f"Se produjo un error inesperado:\n{err}")
        root.report_callback_exception = on_error
        
        # Ajuste de DPI para Windows para que se vea nítido
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass

        app = LoginWindow(root)
        root.mainloop()
    except Exception as e:
        import tkinter as tk
        from tkinter import messagebox
        root_err = tk.Tk()
        root_err.withdraw()
        messagebox.showerror("Error de Inicio", f"El sistema no pudo iniciar:\n{str(e)}")
        root_err.destroy()
