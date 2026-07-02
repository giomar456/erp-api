from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
from decimal import Decimal
from datetime import date, datetime, timedelta
from collections import defaultdict, deque
import threading
import time
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
import base64
import binascii
import psycopg2
import os
import json
import re
import urllib.parse
import urllib.request
import urllib.error
import io
import tempfile
import html
import requests
import zipfile
import hashlib
import xml.etree.ElementTree as ET
try:
    from lxml import etree as LET
    from signxml import XMLSigner, methods
    from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
    from cryptography.hazmat.primitives import serialization
except Exception:
    LET = None
    XMLSigner = None
    methods = None
    load_key_and_certificates = None
    serialization = None

try:
    import plataform_sunat_client as plataform_sunat
except Exception:
    plataform_sunat = None

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CachedStaticFiles(StaticFiles):
    def __init__(self, *args, cache_seconds=86400, **kwargs):
        self.cache_seconds = int(cache_seconds or 0)
        super().__init__(*args, **kwargs)

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200 and self.cache_seconds > 0:
            response.headers["Cache-Control"] = f"public, max-age={self.cache_seconds}"
        return response


WEBAPP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")
if os.path.isdir(WEBAPP_DIR):
    assets_dir = os.path.join(WEBAPP_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/erp/assets", CachedStaticFiles(directory=assets_dir, cache_seconds=31536000), name="erp_assets")
        app.mount("/assets", CachedStaticFiles(directory=assets_dir, cache_seconds=31536000), name="root_assets")
    sounds_dir = os.path.join(WEBAPP_DIR, "sounds")
    if os.path.isdir(sounds_dir):
        app.mount("/erp/sounds", CachedStaticFiles(directory=sounds_dir, cache_seconds=604800), name="erp_sounds")
        app.mount("/sounds", CachedStaticFiles(directory=sounds_dir, cache_seconds=604800), name="root_sounds")


@app.get("/")
def root():
    return {
        "ok": True,
        "success": True,
        "app": "G&G ERP API",
        "web_url": "/erp/" if os.path.isdir(WEBAPP_DIR) else "",
    }


@app.get("/erp")
@app.get("/erp/")
def erp_web_index():
    index_path = os.path.join(WEBAPP_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"ok": False, "success": False, "msg": "ERP web no publicado en este deploy."}


@app.get("/favicon.svg")
def erp_favicon():
    target = os.path.join(WEBAPP_DIR, "favicon.svg")
    return FileResponse(target) if os.path.exists(target) else {"ok": False}


@app.get("/icons.svg")
def erp_icons():
    target = os.path.join(WEBAPP_DIR, "icons.svg")
    return FileResponse(target) if os.path.exists(target) else {"ok": False}


@app.get("/app-logo.png")
def erp_app_logo():
    target = os.path.join(WEBAPP_DIR, "app-logo.png")
    return FileResponse(target) if os.path.exists(target) else {"ok": False}


@app.get("/army-logo-doc.png")
def erp_army_logo():
    target = os.path.join(WEBAPP_DIR, "army-logo-doc.png")
    return FileResponse(target) if os.path.exists(target) else {"ok": False}


@app.get("/erp/{path:path}")
def erp_web_path(path: str):
    index_path = os.path.join(WEBAPP_DIR, "index.html")
    target = os.path.abspath(os.path.join(WEBAPP_DIR, path or "index.html"))
    if target.startswith(WEBAPP_DIR) and os.path.isfile(target):
        return FileResponse(target)
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"ok": False, "success": False, "msg": "ERP web no publicado en este deploy."}

try:
    LIMA_TZ = ZoneInfo("America/Lima") if ZoneInfo else None
except Exception:
    LIMA_TZ = None


def lima_now():
    if LIMA_TZ:
        return datetime.now(LIMA_TZ).replace(tzinfo=None)
    return datetime.now()


def lima_today_iso():
    return lima_now().date().isoformat()


PROFORMA_VALIDITY_HOURS = 48
PROFORMA_VALIDITY_NOTE = "Cotizacion valida solo por 48 horas desde la fecha de emision."


def proforma_fecha_vencimiento(fecha_emision=None):
    base = parse_fecha_emision(fecha_emision) if fecha_emision else lima_now()
    return (base + timedelta(hours=PROFORMA_VALIDITY_HOURS)).date().isoformat()


def proforma_observacion_valida(observacion=""):
    obs = str(observacion or "").strip()
    marker = PROFORMA_VALIDITY_NOTE.lower()
    if marker in obs.lower():
        return obs
    return f"{obs}\n{PROFORMA_VALIDITY_NOTE}".strip() if obs else PROFORMA_VALIDITY_NOTE


def documento_pdf_label(tipo):
    if str(tipo or "").upper() == "PROFORMA":
        return "COTIZACION"
    return str(tipo or "DOCUMENTO").upper()


def parse_fecha_emision(value):
    text = str(value or "").strip()
    if not text:
        return lima_now()
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            if LIMA_TZ:
                parsed = parsed.astimezone(LIMA_TZ)
            parsed = parsed.replace(tzinfo=None)
        return parsed
    except Exception:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except Exception:
        return lima_now()

# ================= CONEXION (SIMPLE Y ESTABLE) =================
DEFAULT_SUCURSAL = "computer_army"
PC_FAST_SUCURSAL = "pc_fast_store"
FERRETERIA_SUCURSAL = "ferreteria"
SHARED_STOCK_SUCURSALES = {
    PC_FAST_SUCURSAL: DEFAULT_SUCURSAL,
}
MAX_COMPROBANTE_PAGO_BYTES = 15 * 1024 * 1024
BOQUITOQUI_LIVE_TTL_SECONDS = 10
BOQUITOQUI_LIVE_MAX_QUEUE = 30
_boquitoqui_live_lock = threading.Lock()
_boquitoqui_live_next_id = 1
_boquitoqui_live_queues = defaultdict(deque)

DEFAULT_FEATURES = {
    "dashboard": True,
    "ventas": True,
    "reservas": True,
    "caja": True,
    "clientes": True,
    "productos": True,
    "inventario": True,
    "compras": True,
    "documentos": True,
    "radio": True,
    "usuarios": True,
    "sunat": True,
    "garantias": True,
    "auditoria": True,
    "web": True,
    "ajustes": True,
    "contabilidad": True,
    "pagina_web": True,
}


def norm_sucursal(value: str = ""):
    value = (value or DEFAULT_SUCURSAL).strip().lower().replace(" ", "_")
    return value or DEFAULT_SUCURSAL


DOCUMENT_EDIT_USERS = {"giomar"}
SERIES_EDIT_USERS = {"giomar", "mily"}


def norm_usuario_permiso(value=""):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def usuario_puede_editar_documento(data):
    if not isinstance(data, dict):
        return False
    for key in ("usuario", "usuario_emisor", "usuario_edicion", "editor", "user"):
        if norm_usuario_permiso(data.get(key)) in DOCUMENT_EDIT_USERS:
            return True
    return False


def usuario_puede_editar_precio_venta(data):
    if not isinstance(data, dict):
        return False
    for key in ("usuario", "usuario_emisor", "usuario_edicion", "editor", "user"):
        if norm_usuario_permiso(data.get(key)) in DOCUMENT_EDIT_USERS:
            return True
    return False


def usuario_puede_editar_series(data):
    if not isinstance(data, dict):
        return False
    for key in ("usuario", "usuario_ingreso", "usuario_emisor", "usuario_registro", "usuario_edicion", "editor", "user"):
        if norm_usuario_permiso(data.get(key)) in SERIES_EDIT_USERS:
            return True
    return False


AUDITORIA_SERIES_MAX_ITEMS = 8
AUDITORIA_SERIES_MAX_CHARS = 900


def _resumen_lista_auditoria(items, max_items=AUDITORIA_SERIES_MAX_ITEMS):
    clean = [str(x or "").strip() for x in (items or []) if str(x or "").strip()]
    if not clean:
        return "0"
    if len(clean) <= max_items:
        return ", ".join(clean)
    visibles = ", ".join(clean[:max_items])
    return f"{visibles} ... (+{len(clean) - max_items} mas, total {len(clean)})"


def _recortar_detalle_auditoria(texto, max_chars=AUDITORIA_SERIES_MAX_CHARS):
    text = str(texto or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def registrar_auditoria_mercaderia(cur, usuario="", sucursal=DEFAULT_SUCURSAL, accion="", detalle="", commit=True):
    """Un solo registro por operacion para no saturar el servidor."""
    if not accion:
        return
    try:
        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,%s,%s,%s,%s)
        """, (
            str(usuario or "SISTEMA").strip() or "SISTEMA",
            "",
            inventario_sucursal(sucursal),
            str(accion).strip(),
            _recortar_detalle_auditoria(detalle),
        ))
        if commit:
            cur.connection.commit()
    except Exception:
        pass


def _line_resumen_documento(item):
    if not isinstance(item, dict):
        return {}
    return {
        "descripcion": str(item.get("descripcion") or item.get("nombre") or "").strip().upper(),
        "cantidad": int(float(item.get("cantidad") or 0)),
        "precio": round(float(item.get("precio") or item.get("precio_unitario") or 0), 2),
        "series": str(item.get("series_texto") or item.get("serie") or "").strip().upper(),
    }


def _resumen_cambios_documento(old_items, new_items):
    parts = []
    old_rows = [_line_resumen_documento(x) for x in (old_items or [])]
    new_rows = [_line_resumen_documento(x) for x in (new_items or [])]
    max_len = max(len(old_rows), len(new_rows), 0)
    for i in range(max_len):
        old = old_rows[i] if i < len(old_rows) else None
        new = new_rows[i] if i < len(new_rows) else None
        n = i + 1
        if old is None and new:
            parts.append(f"L{n} agregado: {new['descripcion']} x{new['cantidad']} @ {new['precio']}")
            continue
        if new is None and old:
            parts.append(f"L{n} quitado: {old['descripcion']}")
            continue
        line_changes = []
        if old["descripcion"] != new["descripcion"]:
            line_changes.append(f"desc {old['descripcion']} -> {new['descripcion']}")
        if old["cantidad"] != new["cantidad"]:
            line_changes.append(f"cant {old['cantidad']} -> {new['cantidad']}")
        if old["precio"] != new["precio"]:
            line_changes.append(f"precio {old['precio']} -> {new['precio']}")
        if old["series"] != new["series"]:
            line_changes.append("series cambiadas")
        if line_changes:
            parts.append(f"L{n}: " + "; ".join(line_changes))
    return " | ".join(parts[:14])


def inventario_sucursal(value: str = ""):
    sucursal = norm_sucursal(value)
    return SHARED_STOCK_SUCURSALES.get(sucursal, sucursal)


SERIES_DOCUMENTO_INTERNO = {
    "BOLETA": "B001",
    "FACTURA": "F001",
}
SERIES_DOCUMENTO_LEGAL_SUNAT = {
    "BOLETA": "B002",
    "FACTURA": "F002",
}


def seed_branch_series(cur, sucursal):
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
    INSERT INTO series (tipo, serie, correlativo, sucursal)
    VALUES
        ('PROFORMA','P001',1,%s),
        ('NOTA DE VENTA','N001',1,%s),
        ('PASE','PA001',1,%s),
        ('BOLETA','B001',1,%s),
        ('FACTURA','F001',1,%s),
        ('GARANTIA','G001',1,%s),
        ('NOTA DE CREDITO','NC001',1,%s)
    ON CONFLICT (tipo, sucursal) DO NOTHING;
    """, (sucursal, sucursal, sucursal, sucursal, sucursal, sucursal, sucursal))
    seed_legal_sunat_series(cur, sucursal)


def seed_legal_sunat_series(cur, sucursal):
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
    INSERT INTO series (tipo, serie, correlativo, sucursal)
    VALUES
        ('BOLETA_ELECTRONICA','B002',1,%s),
        ('FACTURA_ELECTRONICA','F002',1,%s)
    ON CONFLICT (tipo, sucursal) DO NOTHING;
    """, (sucursal, sucursal))


def _resolver_fila_serie_documento(cur, doc_tipo_upper, sucursal, legal_sunat=False):
    sucursal = norm_sucursal(sucursal)
    doc_tipo_upper = str(doc_tipo_upper or "").strip().upper()
    if legal_sunat and doc_tipo_upper in SERIES_DOCUMENTO_LEGAL_SUNAT:
        seed_legal_sunat_series(cur, sucursal)
        serie_codigo = SERIES_DOCUMENTO_LEGAL_SUNAT[doc_tipo_upper]
        cur.execute("""
        SELECT id, serie, correlativo
        FROM series
        WHERE UPPER(serie)=%s AND COALESCE(sucursal,%s)=%s
        """, (serie_codigo, DEFAULT_SUCURSAL, sucursal))
        row = cur.fetchone()
        if row:
            return row, ""
        return None, f"No existe serie legal {serie_codigo} para {doc_tipo_upper}."
    cur.execute("""
    SELECT id, serie, correlativo
    FROM series
    WHERE UPPER(tipo)=%s AND COALESCE(sucursal,%s)=%s
    """, (doc_tipo_upper, DEFAULT_SUCURSAL, sucursal))
    row = cur.fetchone()
    if row:
        return row, ""
    return None, f"No existe serie para {doc_tipo_upper}"


def ensure_usuario_permisos_table(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS usuario_permisos (
        usuario_id INTEGER PRIMARY KEY,
        permisos TEXT,
        actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)


def normalize_feature_permissions(value=None):
    permisos = dict(DEFAULT_FEATURES)
    if isinstance(value, str) and value.strip():
        try:
            value = json.loads(value)
        except Exception:
            value = {}
    if isinstance(value, dict):
        for k, v in value.items():
            if k in permisos:
                permisos[k] = bool(v)
    return permisos


def permisos_usuario(cur, usuario_id, usuario_nombre="", rol=""):
    permisos = dict(DEFAULT_FEATURES)
    if str(usuario_nombre or "").strip().lower() == "giomar":
        return permisos
    if str(rol or "").strip().upper() == "ADMIN":
        return permisos
    try:
        ensure_usuario_permisos_table(cur)
        cur.execute("SELECT permisos FROM usuario_permisos WHERE usuario_id=%s", (usuario_id,))
        row = cur.fetchone()
        return normalize_feature_permissions(row[0] if row else None)
    except Exception:
        return permisos


def norm_theme_color(value: str = ""):
    clean = str(value or "").strip()
    if re.match(r"^#[0-9a-fA-F]{6}$", clean):
        return clean.lower()
    return "#304fb8"


def get_conn():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL no configurado")
    if "sslmode=" in database_url.lower():
        return psycopg2.connect(database_url)
    return psycopg2.connect(database_url, sslmode=os.getenv("DB_SSLMODE", "require"))


def dict_fetchall(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def dict_fetchone(cur):
    row = cur.fetchone()
    if not row:
        return None
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


def _jsonable_row(row: dict) -> dict:
    """Convierte Decimal/datetime a tipos JSON-serializables (evita 500 en respuestas FastAPI)."""
    out = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, datetime):
            out[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def only_digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def first_value(data, *keys):
    if not isinstance(data, dict):
        return ""
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def normalizar_comprobante_pago(data):
    def get_value(key, default=""):
        if isinstance(data, dict):
            return data.get(key, default)
        return getattr(data, key, default)
    nombre = str(get_value("comprobante_pago_nombre") or "").strip()
    referencia = str(get_value("comprobante_pago") or "").strip()
    mime = str(get_value("comprobante_pago_mime") or "").strip() or "application/octet-stream"
    tamano = get_value("comprobante_pago_tamano", None)
    raw_b64 = str(get_value("comprobante_pago_base64") or "").strip()
    data_url = str(get_value("comprobante_pago_data_url") or "").strip()

    if data_url.startswith("data:") and "," in data_url:
        header, encoded = data_url.split(",", 1)
        raw_b64 = raw_b64 or encoded.strip()
        if ";base64" in header:
            mime_from_url = header[5:].split(";", 1)[0].strip()
            if mime_from_url:
                mime = mime_from_url

    if not raw_b64:
        return {
            "comprobante_pago": referencia or None,
            "comprobante_pago_nombre": nombre or None,
            "comprobante_pago_mime": None,
            "comprobante_pago_tamano": None,
            "comprobante_pago_base64": None,
            "comprobante_pago_data_url": None,
        }

    try:
        decoded = base64.b64decode(raw_b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Comprobante de pago invalido o corrupto.")

    if len(decoded) > MAX_COMPROBANTE_PAGO_BYTES:
        raise ValueError("Comprobante de pago mayor a 15 MB.")

    if not nombre and referencia:
        nombre = os.path.basename(referencia.replace("\\", "/"))
    if not nombre:
        nombre = "comprobante_pago"
    tamano = int(tamano or len(decoded))
    data_url = f"data:{mime};base64,{raw_b64}"

    return {
        "comprobante_pago": referencia or nombre,
        "comprobante_pago_nombre": nombre,
        "comprobante_pago_mime": mime,
        "comprobante_pago_tamano": tamano,
        "comprobante_pago_base64": raw_b64,
        "comprobante_pago_data_url": data_url,
    }


def comprobante_payload_vacio():
    return {
        "comprobante_pago": None,
        "comprobante_pago_nombre": None,
        "comprobante_pago_mime": None,
        "comprobante_pago_tamano": None,
        "comprobante_pago_base64": None,
        "comprobante_pago_data_url": None,
    }


def normalizar_un_comprobante(item):
    if not isinstance(item, dict):
        return None
    nombre = str(item.get("comprobante_pago_nombre") or item.get("nombre") or item.get("name") or "").strip()
    referencia = str(item.get("comprobante_pago") or item.get("path") or item.get("referencia") or nombre).strip()
    mime = str(item.get("comprobante_pago_mime") or item.get("mime") or "application/octet-stream").strip()
    tamano = item.get("comprobante_pago_tamano", item.get("tamano", item.get("size")))
    raw_b64 = str(item.get("comprobante_pago_base64") or item.get("base64") or "").strip()
    data_url = str(item.get("comprobante_pago_data_url") or item.get("data_url") or "").strip()
    if data_url.startswith("data:") and "," in data_url:
        header, encoded = data_url.split(",", 1)
        raw_b64 = raw_b64 or encoded.strip()
        if ";base64" in header:
            mime = header[5:].split(";", 1)[0].strip() or mime
    if not raw_b64:
        return None
    decoded = base64.b64decode(raw_b64, validate=True)
    if len(decoded) > MAX_COMPROBANTE_PAGO_BYTES:
        raise ValueError("Cada comprobante de pago debe pesar maximo 15 MB.")
    if not nombre:
        nombre = os.path.basename(referencia.replace("\\", "/")) or "comprobante_pago"
    tamano = int(tamano or len(decoded))
    data_url = f"data:{mime};base64,{raw_b64}"
    return {
        "comprobante_pago": referencia or nombre,
        "comprobante_pago_nombre": nombre,
        "comprobante_pago_mime": mime,
        "comprobante_pago_tamano": tamano,
        "comprobante_pago_base64": raw_b64,
        "comprobante_pago_data_url": data_url,
    }


def cargar_comprobantes_json(value):
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        return [x for x in parsed if isinstance(x, dict)] if isinstance(parsed, list) else []
    except Exception:
        return []


def comprobante_metadata_liviana(item):
    if not isinstance(item, dict):
        return None
    nombre = item.get("nombre") or item.get("name") or item.get("comprobante_pago_nombre") or item.get("comprobante_pago") or "Comprobante"
    mime = item.get("mime") or item.get("comprobante_pago_mime") or "application/octet-stream"
    tamano = item.get("tamano", item.get("size", item.get("comprobante_pago_tamano", 0)))
    return {
        "nombre": nombre,
        "comprobante_pago_nombre": nombre,
        "mime": mime,
        "comprobante_pago_mime": mime,
        "tamano": tamano or 0,
        "comprobante_pago_tamano": tamano or 0,
        "tiene_archivo": bool(item.get("data_url") or item.get("base64") or item.get("comprobante_pago_data_url") or item.get("comprobante_pago_base64")),
    }


def comprobantes_metadata_liviana(value):
    return [x for x in (comprobante_metadata_liviana(item) for item in cargar_comprobantes_json(value)) if x]


def normalizar_pagos_detalle(items=None, metodo_pago=None, monto_pagado=None):
    pagos = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        metodo = str(item.get("metodo") or item.get("metodo_pago") or "").strip().upper()
        try:
            monto = float(item.get("monto", item.get("monto_pagado", 0)) or 0)
        except Exception:
            monto = 0
        if metodo and monto > 0:
            pagos.append({"metodo": metodo, "monto": round(monto, 2)})
    if not pagos:
        metodo = str(metodo_pago or "").strip().upper()
        try:
            monto = float(monto_pagado or 0)
        except Exception:
            monto = 0
        if metodo and monto > 0:
            pagos.append({"metodo": metodo, "monto": round(monto, 2)})
    total = round(sum(float(p.get("monto") or 0) for p in pagos), 2)
    metodo_resumen = " + ".join(p["metodo"] for p in pagos) if pagos else (str(metodo_pago or "").strip().upper() or None)
    return pagos, total, metodo_resumen, json.dumps(pagos, ensure_ascii=False) if pagos else ""


STOCK_DOC_TYPES = {"BOLETA", "FACTURA", "PASE"}
TEST_PRODUCT_MARKERS = ("PRUEBA", "RANDOM", "GENERICO", "GENÃ‰RICO", "COTIZACION", "COTIZACIÃ“N")


def split_series_text(value):
    raw = re.split(r"[,;\n\r|]+", str(value or ""))
    cleaned = []
    for item in raw:
        serie = normalize_serie_key(item)
        if not serie:
            continue
        cleaned.append(serie)
    return cleaned


def normalize_serie_key(value):
    serie = str(value or "").strip()
    serie = re.sub(r"^(s\s*/?\s*n|sn|serie)\s*[:\-]?\s*", "", serie, flags=re.I).strip()
    serie = re.sub(r"[^A-Z0-9]+", "", serie.upper())
    return serie


SERIE_SQL_KEY = "regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g')"


def is_test_product_name(*values):
    text = " ".join(str(v or "") for v in values).upper()
    return any(marker in text for marker in TEST_PRODUCT_MARKERS)


def venta_linea_es_prueba(modo_prueba, *values):
    if modo_prueba:
        return True
    return is_test_product_name(*values)


def procesar_modo_prueba_venta(cur, producto_id, cantidad, series_texto, sucursal):
    """Venta flexible: no exige coincidencia nombre/serie ni bloquea por producto incorrecto."""
    sucursal = inventario_sucursal(sucursal)
    cantidad = max(0, int(float(cantidad or 0)))
    selected = split_series_text(series_texto)
    touched_products = set()

    for serie in selected:
        cur.execute("""
        SELECT ps.id, ps.producto_id
        FROM producto_series ps
        WHERE COALESCE(ps.sucursal,%s)=%s
          AND regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g')=%s
          AND UPPER(COALESCE(ps.estado,'DISPONIBLE')) IN ('DISPONIBLE', 'RESERVADO')
        ORDER BY ps.id
        LIMIT 1
        """, (DEFAULT_SUCURSAL, sucursal, serie))
        row = cur.fetchone()
        if row:
            cur.execute("""
            UPDATE producto_series
            SET estado='VENDIDO',
                fecha_salida=TO_CHAR((timezone('America/Lima', now()))::date, 'YYYY-MM-DD')
            WHERE id=%s
            """, (row[0],))
            if row[1]:
                touched_products.add(row[1])

    if producto_id and cantidad > 0 and not selected:
        cur.execute("""
        UPDATE productos SET stock = GREATEST(COALESCE(stock,0) - %s, 0)
        WHERE id = %s AND COALESCE(sucursal,%s)=%s
        """, (cantidad, producto_id, DEFAULT_SUCURSAL, sucursal))
        touched_products.add(producto_id)

    for pid in touched_products:
        sync_producto_stock_from_series(cur, pid, sucursal)
    return None


def normalize_match_text(value):
    text = str(value or "").upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def series_texto_a_set(series_texto):
    return set(split_series_text(series_texto))


def series_desde_detalle_rows(rows):
    out = set()
    for row in rows or []:
        if isinstance(row, dict):
            out.update(series_texto_a_set(row.get("series_texto") or row.get("serie") or ""))
        else:
            try:
                out.update(series_texto_a_set(row[3] if len(row) > 3 else ""))
            except Exception:
                pass
    return out


def procesar_combo_generico_venta(cur, descripcion_doc, series_texto, sucursal, permitir_series=None):
    sucursal = inventario_sucursal(sucursal)
    texto_doc = normalize_match_text(descripcion_doc)
    selected = split_series_text(series_texto)
    touched_products = set()
    permitir_series = set(permitir_series or [])

    if selected:
        if len(set(selected)) != len(selected):
            return "Combo/PRUEBA: hay series repetidas en el documento."
        cur.execute("""
        SELECT ps.id,
               regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g') AS serie,
               ps.producto_id,
               UPPER(COALESCE(ps.estado,'DISPONIBLE')) AS estado,
               COALESCE(p.nombre,'') AS producto_nombre
        FROM producto_series ps
        LEFT JOIN productos p ON p.id=ps.producto_id AND COALESCE(p.sucursal,%s)=%s
        WHERE COALESCE(ps.sucursal,%s)=%s
          AND regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g')=ANY(%s)
        """, (DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal, selected))
        rows = dict_fetchall(cur)
        found = defaultdict(list)
        for row in rows:
            found[str(row.get("serie") or "").upper()].append(row)
        for serie in selected:
            matches = found.get(serie, [])
            if not matches:
                continue
            disponibles = [r for r in matches if str(r.get("estado") or "").upper() in ("DISPONIBLE", "RESERVADO")]
            if not disponibles and serie in permitir_series:
                disponibles = [r for r in matches if str(r.get("estado") or "").upper() == "VENDIDO"]
            if not disponibles:
                estados = ", ".join(sorted({str(r.get("estado") or "") for r in matches}))
                return f"Combo/PRUEBA: la serie {serie} no esta disponible ({estados})."
            if len(disponibles) > 1:
                candidatos = []
                for row in disponibles:
                    nombre = normalize_match_text(row.get("producto_nombre") or "")
                    if nombre and nombre in texto_doc:
                        candidatos.append(row)
                if len(candidatos) == 1:
                    row = candidatos[0]
                else:
                    nombres = ", ".join([r.get("producto_nombre") or "producto sin nombre" for r in disponibles])
                    return f"Combo/PRUEBA: la serie {serie} existe en varios productos. Especifica el producto en el texto: {nombres}."
            else:
                row = disponibles[0]
            cur.execute("""
            UPDATE producto_series
            SET estado='VENDIDO',
                fecha_salida=TO_CHAR((timezone('America/Lima', now()))::date, 'YYYY-MM-DD')
            WHERE id=%s
            """, (row.get("id"),))
            if row.get("producto_id"):
                touched_products.add(row.get("producto_id"))

    for producto_id in touched_products:
        sync_producto_stock_from_series(cur, producto_id, sucursal)

    if texto_doc:
        cur.execute("""
        SELECT id, COALESCE(nombre,'') AS nombre
        FROM productos
        WHERE COALESCE(sucursal,%s)=%s
        ORDER BY LENGTH(COALESCE(nombre,'')) DESC
        """, (DEFAULT_SUCURSAL, sucursal))
        for prod in dict_fetchall(cur):
            producto_id = prod.get("id")
            if not producto_id or producto_id in touched_products:
                continue
            nombre = normalize_match_text(prod.get("nombre") or "")
            if len(nombre) < 8 or nombre not in texto_doc:
                continue
            if producto_tiene_series_activas(cur, producto_id, sucursal):
                continue
            cur.execute("""
            UPDATE productos
            SET stock = GREATEST(COALESCE(stock,0) - 1, 0)
            WHERE id=%s AND COALESCE(sucursal,%s)=%s
            """, (producto_id, DEFAULT_SUCURSAL, sucursal))
            touched_products.add(producto_id)

    return None


def sync_producto_stock_from_series(cur, producto_id, sucursal):
    sucursal = inventario_sucursal(sucursal)
    cur.execute("""
    UPDATE productos
    SET stock = (
        SELECT COUNT(*) FROM producto_series
        WHERE producto_id=%s
          AND COALESCE(sucursal,%s)=%s
          AND UPPER(COALESCE(estado,''))='DISPONIBLE'
    )
    WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (producto_id, DEFAULT_SUCURSAL, sucursal, producto_id, DEFAULT_SUCURSAL, sucursal))


def producto_tiene_series_activas(cur, producto_id, sucursal):
    sucursal = inventario_sucursal(sucursal)
    if not producto_id:
        return False
    cur.execute("""
    SELECT COUNT(*)
    FROM producto_series
    WHERE producto_id=%s
      AND COALESCE(sucursal,%s)=%s
      AND UPPER(COALESCE(estado,'DISPONIBLE')) IN ('DISPONIBLE','RESERVADO')
    """, (producto_id, DEFAULT_SUCURSAL, sucursal))
    row = cur.fetchone()
    return bool(row and int(row[0] or 0) > 0)


def es_ram_kingston(nombre):
    text = str(nombre or "").upper()
    return "KINGSTON" in text and ("RAM" in text or "MEM" in text or "MEMORIA" in text)


def resolver_producto_por_series_venta(cur, producto_id, nombre_doc, cantidad, series_texto, sucursal):
    sucursal = inventario_sucursal(sucursal)
    selected = split_series_text(series_texto)
    if not selected:
        return producto_id, None
    if len(selected) != max(0, int(float(cantidad or 0))):
        return producto_id, None

    resolved_ids = set()
    for serie in selected:
        cur.execute("""
        SELECT ps.id,
               ps.producto_id,
               UPPER(COALESCE(ps.estado,'DISPONIBLE')) AS estado,
               COALESCE(p.nombre,'') AS producto_nombre
        FROM producto_series ps
        LEFT JOIN productos p ON p.id=ps.producto_id AND COALESCE(p.sucursal,%s)=%s
        WHERE COALESCE(ps.sucursal,%s)=%s
          AND regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g')=%s
        """, (DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal, serie))
        rows = dict_fetchall(cur)
        active_rows = [r for r in rows if str(r.get("estado") or "").upper() in ("DISPONIBLE", "RESERVADO")]
        if not active_rows:
            continue

        if len(active_rows) > 1:
            names = [r.get("producto_nombre") for r in active_rows]
            if any(es_ram_kingston(n) for n in names) or es_ram_kingston(nombre_doc):
                return producto_id, f"{nombre_doc}: la serie {serie} esta duplicada en memorias Kingston. Selecciona el producto real para evitar descontar una RAM incorrecta."
            same_product = [r for r in active_rows if str(r.get("producto_id")) == str(producto_id)]
            if len(same_product) == 1:
                resolved_ids.add(same_product[0].get("producto_id"))
                continue
            product_ids = {r.get("producto_id") for r in active_rows if r.get("producto_id")}
            if len(product_ids) != 1:
                opciones = ", ".join(sorted({str(r.get("producto_nombre") or r.get("producto_id")) for r in active_rows}))
                return producto_id, f"{nombre_doc}: la serie {serie} existe en varios productos ({opciones}). Selecciona el producto real antes de vender."

        picked = active_rows[0]
        if picked.get("producto_id"):
            resolved_ids.add(picked.get("producto_id"))

    if len(resolved_ids) == 1:
        return list(resolved_ids)[0], None
    if len(resolved_ids) > 1:
        return producto_id, f"{nombre_doc}: las series escaneadas pertenecen a productos diferentes. Separa cada producto en una linea."
    return producto_id, None


def validar_y_marcar_series_venta(cur, producto_id, nombre_doc, marca_doc, modelo_doc, cantidad, series_texto, sucursal, permitir_series=None):
    sucursal = inventario_sucursal(sucursal)
    cantidad = max(0, int(float(cantidad or 0)))
    if cantidad <= 0 or not producto_id:
        return None

    cur.execute("""
    SELECT COALESCE(nombre,''), COALESCE(marca,''), COALESCE(modelo,''), COALESCE(stock,0)
    FROM productos
    WHERE id=%s AND COALESCE(sucursal,%s)=%s
    LIMIT 1
    """, (producto_id, DEFAULT_SUCURSAL, sucursal))
    prod = cur.fetchone()
    if not prod:
        return f"Producto {producto_id} no encontrado."

    prod_nombre, prod_marca, prod_modelo, stock_actual = prod
    if is_test_product_name(prod_nombre, nombre_doc, marca_doc, modelo_doc):
        return None

    cur.execute("""
    SELECT id, regexp_replace(UPPER(COALESCE(serie,'')), '[^A-Z0-9]', '', 'g') AS serie, UPPER(COALESCE(estado,'DISPONIBLE')) AS estado
    FROM producto_series
    WHERE producto_id=%s AND COALESCE(sucursal,%s)=%s
    """, (producto_id, DEFAULT_SUCURSAL, sucursal))
    permitir_series = set(permitir_series or [])
    registered = {str(r.get("serie") or "").strip().upper(): r for r in dict_fetchall(cur) if str(r.get("serie") or "").strip()}
    registered_count = len(registered)
    active_count = sum(1 for r in registered.values() if r.get("estado") in ("DISPONIBLE", "RESERVADO"))
    selected = split_series_text(series_texto)

    if not registered_count or (not selected and not active_count):
        cur.execute("""
        UPDATE productos SET stock = GREATEST(COALESCE(stock,0) - %s, 0)
        WHERE id = %s AND COALESCE(sucursal,%s)=%s
        """, (cantidad, producto_id, DEFAULT_SUCURSAL, sucursal))
        return None

    if len(selected) != cantidad:
        return f"{prod_nombre}: selecciona o ingresa {cantidad} serie(s) antes de emitir boleta/factura."
    if len(set(selected)) != len(selected):
        return f"{prod_nombre}: hay series repetidas en el documento."

    for serie in selected:
        row = registered.get(serie)
        if not row:
            cur.execute("""
            SELECT ps.producto_id,
                   COALESCE(p.nombre,'') AS producto_nombre,
                   UPPER(COALESCE(ps.estado,'DISPONIBLE')) AS estado
            FROM producto_series ps
            LEFT JOIN productos p ON p.id=ps.producto_id
            WHERE regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g')=%s AND COALESCE(ps.sucursal,%s)=%s
            LIMIT 1
            """, (serie, DEFAULT_SUCURSAL, sucursal))
            other = dict_fetchone(cur)
            if other and str(other.get("estado") or "").upper() in ("DISPONIBLE", "RESERVADO"):
                return f"{prod_nombre}: la serie {serie} pertenece a otro producto ({other.get('producto_nombre')}) o esta en estado {other.get('estado')}."
            cur.execute("""
            INSERT INTO producto_series (
                producto_id, serie, proveedor, estado, almacen, fecha_ingreso, fecha_salida, sucursal, usuario_ingreso
            )
            VALUES (%s,%s,'VENTA DIRECTA','VENDIDO','VENTA',
                    TO_CHAR((timezone('America/Lima', now()))::date, 'YYYY-MM-DD'),
                    TO_CHAR((timezone('America/Lima', now()))::date, 'YYYY-MM-DD'),
                    %s,'SISTEMA')
            """, (producto_id, serie, sucursal))
            continue
        if row and row.get("estado") not in ("DISPONIBLE", "RESERVADO"):
            if serie in permitir_series and str(row.get("estado") or "").upper() == "VENDIDO":
                pass
            else:
                return f"{prod_nombre}: la serie {serie} esta en estado {row.get('estado')}."
        cur.execute("""
        UPDATE producto_series
        SET estado='VENDIDO',
            fecha_salida=TO_CHAR((timezone('America/Lima', now()))::date, 'YYYY-MM-DD')
        WHERE id=%s
        """, (row.get("id"),))

    sync_producto_stock_from_series(cur, producto_id, sucursal)
    return None


def descontar_stock_venta(cur, producto_id, nombre_doc, marca_doc, modelo_doc, cantidad, series_texto, sucursal):
    sucursal = inventario_sucursal(sucursal)
    try:
        cantidad = int(cantidad or 0)
    except Exception:
        cantidad = 0
    if cantidad <= 0:
        return

    selected = split_series_text(series_texto)
    if selected:
        cur.execute("""
        SELECT ps.id,
               ps.producto_id,
               UPPER(COALESCE(ps.estado,'DISPONIBLE')) AS estado,
               COALESCE(p.nombre,'') AS producto_nombre
        FROM producto_series ps
        LEFT JOIN productos p ON p.id=ps.producto_id
        WHERE COALESCE(ps.sucursal,%s)=%s
          AND regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g')=ANY(%s)
        """, (DEFAULT_SUCURSAL, sucursal, selected))
        rows = dict_fetchall(cur)
        touched_products = set()
        for row in rows:
            estado = str(row.get("estado") or "DISPONIBLE").upper()
            if estado not in ("DISPONIBLE", "RESERVADO"):
                continue
            serie_producto_id = row.get("producto_id")
            if not serie_producto_id:
                continue
            cur.execute("""
            UPDATE producto_series
            SET estado='VENDIDO',
                fecha_salida=TO_CHAR((timezone('America/Lima', now()))::date, 'YYYY-MM-DD')
            WHERE id=%s
            """, (row.get("id"),))
            touched_products.add(serie_producto_id)
        for serie_producto_id in touched_products:
            sync_producto_stock_from_series(cur, serie_producto_id, sucursal)
        if touched_products:
            return

    if not producto_id:
        return

    cur.execute("""
    SELECT nombre, marca, modelo
    FROM productos
    WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (producto_id, DEFAULT_SUCURSAL, sucursal))
    prod = cur.fetchone()
    if not prod:
        return
    prod_nombre, prod_marca, prod_modelo = prod
    if is_test_product_name(prod_nombre, nombre_doc, marca_doc, modelo_doc):
        return
    if producto_tiene_series_activas(cur, producto_id, sucursal):
        return

    cur.execute("""
    UPDATE productos
    SET stock = GREATEST(COALESCE(stock,0) - %s, 0)
    WHERE id = %s AND COALESCE(sucursal,%s)=%s
    """, (cantidad, producto_id, DEFAULT_SUCURSAL, sucursal))


def normalizar_comprobantes_pago(data, existentes=None):
    def get_value(key, default=None):
        if isinstance(data, dict):
            return data.get(key, default)
        return getattr(data, key, default)
    recibidos = []
    for item in get_value("comprobantes_pago", None) or []:
        normalizado = normalizar_un_comprobante(item)
        if normalizado:
            recibidos.append(normalizado)
    legacy = normalizar_comprobante_pago(data)
    if legacy.get("comprobante_pago_base64") or legacy.get("comprobante_pago_data_url"):
        recibidos.append(legacy)
    if not recibidos:
        return cargar_comprobantes_json(existentes), comprobante_payload_vacio(), None
    combinados = cargar_comprobantes_json(existentes)
    vistos = {str(x.get("comprobante_pago_data_url") or x.get("comprobante_pago_base64") or x.get("comprobante_pago_nombre") or "") for x in combinados}
    for item in recibidos:
        key = str(item.get("comprobante_pago_data_url") or item.get("comprobante_pago_base64") or item.get("comprobante_pago_nombre") or "")
        if key and key in vistos:
            continue
        combinados.append(item)
        vistos.add(key)
    principal = combinados[0] if combinados else comprobante_payload_vacio()
    return combinados, principal, json.dumps(combinados, ensure_ascii=False)


def http_get_json(url, headers=None, timeout=5):
    safe_headers = {"User-Agent": "G&G-ERP/1.0", "Accept": "application/json"}
    safe_headers.update(headers or {})
    req = urllib.request.Request(url, headers=safe_headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "ignore")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")[:240]
        except Exception:
            body = ""
        raise RuntimeError(f"HTTP {e.code}: {body or e.reason}") from e


def normalizar_dni(data, numero, source):
    if not isinstance(data, dict):
        return None
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict):
        return None
    nombres = first_value(payload, "nombres", "first_name")
    paterno = first_value(payload, "apellidoPaterno", "apellido_paterno", "paterno", "ape_paterno", "first_last_name")
    materno = first_value(payload, "apellidoMaterno", "apellido_materno", "materno", "ape_materno", "second_last_name")
    nombre = first_value(
        payload,
        "nombreCompleto", "nombre_completo", "full_name", "razonSocial", "razon_social", "nombre",
    )
    if not nombre:
        nombre = " ".join(x for x in [paterno, materno, nombres] if x).strip()
    if not nombre:
        return None
    return {
        "ok": True,
        "success": True,
        "found": True,
        "source": source,
        "tipo_documento": "DNI",
        "numero_documento": numero,
        "nombre": nombre.upper(),
        "direccion": first_value(payload, "direccion", "domicilio", "direccionCompleta"),
    }


def normalizar_ruc(data, numero, source):
    payload = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    nombre = first_value(payload, "razonSocial", "razon_social", "nombre", "nombre_o_razon_social", "nombreORazonSocial")
    direccion = first_value(payload, "direccion", "direccionFiscal", "domicilioFiscal", "domicilio_fiscal", "direccion_completa")
    if not nombre:
        return None
    return {
        "ok": True,
        "success": True,
        "found": True,
        "source": source,
        "tipo_documento": "RUC",
        "numero_documento": numero,
        "nombre": nombre.upper(),
        "razon_social": nombre.upper(),
        "direccion": str(direccion or "").upper(),
        "estado": first_value(payload, "estado", "estadoContribuyente", "estado_contribuyente"),
        "condicion": first_value(payload, "condicion", "condicionContribuyente", "condicion_contribuyente"),
    }


def buscar_cliente_db(documento, sucursal=DEFAULT_SUCURSAL):
    documento = only_digits(documento)
    sucursal = norm_sucursal(sucursal)
    if not documento:
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS telefono TEXT DEFAULT ''")
    cur.execute("""
    SELECT id, tipo_documento, numero_documento, nombre, direccion, COALESCE(telefono,'') AS telefono, COALESCE(sucursal,%s) AS sucursal
    FROM clientes
    WHERE numero_documento=%s AND COALESCE(sucursal,%s)=%s
    LIMIT 1
    """, (DEFAULT_SUCURSAL, documento, DEFAULT_SUCURSAL, sucursal))
    row = dict_fetchone(cur)
    conn.close()
    if not row:
        return None
    row.update({"ok": True, "success": True, "found": True, "source": "clientes"})
    return row


def consulta_documento_custom(tipo, numero):
    template = os.getenv(f"DOC_LOOKUP_{tipo}_URL", "").strip()
    if not template:
        return None
    token = os.getenv("DOC_LOOKUP_TOKEN", "").strip()
    header_name = os.getenv("DOC_LOOKUP_AUTH_HEADER", "Authorization").strip() or "Authorization"
    header_prefix = os.getenv("DOC_LOOKUP_AUTH_PREFIX", "Bearer ")
    headers = {"Accept": "application/json"}
    if token:
        headers[header_name] = f"{header_prefix}{token}"
    url = template.format(
        numero=urllib.parse.quote(numero),
        documento=urllib.parse.quote(numero),
        tipo=urllib.parse.quote(tipo),
    )
    data = http_get_json(url, headers=headers)
    return normalizar_dni(data, numero, "custom") if tipo == "DNI" else normalizar_ruc(data, numero, "custom")


def consulta_documento_apis_net_pe(tipo, numero):
    token = os.getenv("APIS_NET_PE_TOKEN", "").strip()
    if not token:
        return None
    base = os.getenv("APIS_NET_PE_BASE", "https://api.apis.net.pe/v2").strip().rstrip("/")
    endpoint = "reniec/dni" if tipo == "DNI" else "sunat/ruc"
    url = f"{base}/{endpoint}?numero={urllib.parse.quote(numero)}"
    data = http_get_json(url, headers={"Authorization": f"Bearer {token}"}, timeout=5)
    return normalizar_dni(data, numero, "apis_net_pe") if tipo == "DNI" else normalizar_ruc(data, numero, "apis_net_pe")


def consulta_documento_apis_net_pe_v1(tipo, numero):
    if os.getenv("DISABLE_APIS_NET_PE_V1", "").strip().lower() in ("1", "true", "si", "yes"):
        return None
    base = os.getenv("APIS_NET_PE_V1_BASE", "https://api.apis.net.pe/v1").strip().rstrip("/")
    endpoint = "dni" if tipo == "DNI" else "ruc"
    url = f"{base}/{endpoint}?numero={urllib.parse.quote(numero)}"
    token = os.getenv("APIS_NET_PE_TOKEN", "").strip() or os.getenv("APIS_NET_PE_V1_TOKEN", "").strip()
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error = ""
    for attempt in range(2):
        try:
            data = http_get_json(url, headers=headers, timeout=6)
            result = normalizar_dni(data, numero, "apis_net_pe_v1") if tipo == "DNI" else normalizar_ruc(data, numero, "apis_net_pe_v1")
            if result:
                return result
            last_error = "Respuesta sin nombre para este documento."
            break
        except Exception as e:
            last_error = str(e)
            if "429" in last_error and attempt == 0:
                time.sleep(1.5)
                continue
            break
    if last_error:
        raise RuntimeError(last_error)
    return None


def consulta_documento_decolecta(tipo, numero):
    token = os.getenv("DECOLECTA_TOKEN", "").strip()
    if not token:
        return None
    base = os.getenv("DECOLECTA_BASE", "https://api.decolecta.com/v1").strip().rstrip("/")
    endpoint = "reniec/dni" if tipo == "DNI" else "sunat/ruc"
    url = f"{base}/{endpoint}?numero={urllib.parse.quote(numero)}"
    data = http_get_json(url, headers={"Authorization": f"Bearer {token}"}, timeout=6)
    return normalizar_dni(data, numero, "decolecta") if tipo == "DNI" else normalizar_ruc(data, numero, "decolecta")


def _mensaje_error_consulta_documento(last_error, provider_configured, tipo):
    err = str(last_error or "").lower()
    if "429" in err or "too many requests" in err:
        return "Consulta DNI/RUC saturada temporalmente. Espera 5 segundos e intenta de nuevo."
    if "401" in err or "403" in err or "unauthorized" in err:
        return "Token de consulta DNI/RUC invalido o vencido en el servidor (APIS_NET_PE_TOKEN)."
    if "timeout" in err or "timed out" in err:
        return "El servicio de consulta DNI/RUC no respondio a tiempo. Intenta nuevamente."
    if last_error:
        return str(last_error)
    if provider_configured:
        return f"No se encontraron datos de {tipo} para ese numero."
    return "No se encontraron datos. Configura APIS_NET_PE_TOKEN en Render para consultas DNI/RUC."


def consulta_documento_impl(numero, sucursal=DEFAULT_SUCURSAL):
    numero = only_digits(numero)
    tipo = "DNI" if len(numero) == 8 else "RUC" if len(numero) == 11 else ""
    if not tipo:
        return {"ok": False, "success": False, "found": False, "msg": "Ingresa 8 digitos para DNI o 11 para RUC."}

    local = buscar_cliente_db(numero, sucursal)
    if local:
        local["tipo_documento"] = local.get("tipo_documento") or tipo
        local["numero_documento"] = local.get("numero_documento") or numero
        return local

    last_error = ""
    provider_configured = bool(
        os.getenv(f"DOC_LOOKUP_{tipo}_URL", "").strip()
        or os.getenv("APIS_NET_PE_TOKEN", "").strip()
        or os.getenv("APIS_NET_PE_V1_TOKEN", "").strip()
        or os.getenv("DECOLECTA_TOKEN", "").strip()
    )
    for provider in (
        consulta_documento_custom,
        consulta_documento_apis_net_pe_v1,
        consulta_documento_apis_net_pe,
        consulta_documento_decolecta,
    ):
        try:
            result = provider(tipo, numero)
            if result and result.get("found"):
                return result
        except Exception as e:
            last_error = str(e)

    msg = _mensaje_error_consulta_documento(last_error, provider_configured, tipo)
    return {"ok": False, "success": False, "found": False, "tipo_documento": tipo, "numero_documento": numero, "msg": msg}


# ================= MODELOS =================
class ItemVenta(BaseModel):
    id: int
    cantidad: int
    precio: float
    total: float
    producto_id: Optional[int] = None
    nombre: str = ""
    marca: str = ""
    modelo: str = ""
    serie: str = ""
    series_texto: str = ""


class Venta(BaseModel):
    tipo: str
    es_pase: bool = False
    cliente_nombre: str
    items: List[ItemVenta]
    fecha_emision: str = ""
    tipo_documento_cliente: str = ""
    numero_documento_cliente: str = ""
    direccion_cliente: str = ""
    usuario_emisor: str = ""
    observacion: str = ""
    fecha_vencimiento: str = ""
    estado_pago: str = "PAGADO"
    metodo_pago: str = ""
    sucursal: str = DEFAULT_SUCURSAL
    emitir_legal_sunat: bool = False
    modo_prueba: bool = False


class Cliente(BaseModel):
    tipo_documento: str
    numero_documento: str
    nombre: str
    direccion: str
    telefono: str = ""
    sucursal: str = DEFAULT_SUCURSAL


class ReservaCliente(BaseModel):
    tipo_documento: str = "DNI"
    numero_documento: str = ""
    cliente_nombre: str = ""
    producto_id: Optional[int] = None
    producto_nombre: str = ""
    cantidad: int = 1
    monto_total: float = 0
    monto_reserva: float = 0
    estado: str = "RESERVADO"
    observacion: str = ""
    usuario: str = ""
    comprobante_pago: Optional[str] = ""
    comprobante_pago_nombre: Optional[str] = ""
    comprobante_pago_mime: Optional[str] = ""
    comprobante_pago_tamano: Optional[int] = None
    comprobante_pago_base64: Optional[str] = ""
    comprobante_pago_data_url: Optional[str] = ""
    comprobantes_pago: Optional[List[dict]] = None
    sucursal: str = DEFAULT_SUCURSAL


class SerieProducto(BaseModel):
    producto_id: int
    serie: str
    proveedor: str = ""
    estado: str = "DISPONIBLE"
    almacen: str = "TIENDA"
    fecha_ingreso: str = ""
    fecha_salida: Optional[str] = None
    usuario_ingreso: str = ""
    sucursal: str = DEFAULT_SUCURSAL


class SeriesMoverAlmacen(BaseModel):
    serie_ids: List[int]
    almacen: str
    usuario: str = ""
    sucursal: str = DEFAULT_SUCURSAL


class DocumentoManualSeries(BaseModel):
    tipo: str = "BOLETA"
    numero: str = ""
    cliente_nombre: str = "CLIENTE MANUAL"
    fecha_emision: str = ""
    series_texto: str = ""
    usuario_emisor: str = ""
    observacion: str = ""
    sucursal: str = DEFAULT_SUCURSAL


class SeriesDocumentoReset(BaseModel):
    sucursal: str = DEFAULT_SUCURSAL
    correlativo: int = 1
    tipos: Optional[List[str]] = None
    usuario: str = ""


class ServicioTecnico(BaseModel):
    tipo_documento: str = "DNI"
    numero_documento: str = ""
    cliente_nombre: str = ""
    telefono: str = ""
    equipo: str = ""
    servicio: str = ""
    diagnostico: str = ""
    observacion: str = ""
    precio: float = 0
    usuario: str = ""
    sucursal: str = DEFAULT_SUCURSAL


class StockAjuste(BaseModel):
    stock: int


class StockTransferencia(BaseModel):
    producto_id: int
    cantidad: int
    sucursal_origen: str = DEFAULT_SUCURSAL
    sucursal_destino: str = DEFAULT_SUCURSAL
    usuario: str = ""
    nota: str = ""


class InventarioConteoCreate(BaseModel):
    categoria: str
    usuario: str = ""
    sucursal: str = DEFAULT_SUCURSAL


class InventarioConteoScan(BaseModel):
    serie: str
    usuario: str = ""


class Usuario(BaseModel):
    usuario: str
    clave: str
    rol: str = "VENTAS"
    foto_url: Optional[str] = ""
    fondo_url: Optional[str] = ""
    boquitoqui_enabled: bool = False
    sucursal: str = DEFAULT_SUCURSAL
    color_tema: Optional[str] = "#304fb8"


class UsuarioRolUpdate(BaseModel):
    rol: str


class UsuarioRadioUpdate(BaseModel):
    boquitoqui_enabled: bool = False


class UsuarioColorUpdate(BaseModel):
    usuario: Optional[str] = ""
    color_tema: str = "#304fb8"


class UsuarioFondoUpdate(BaseModel):
    usuario: Optional[str] = ""
    fondo_url: str = ""


class UsuarioOnlineHeartbeat(BaseModel):
    usuario: str
    vista: str = ""
    dispositivo: str = ""
    sucursal: str = DEFAULT_SUCURSAL


class BoquitoquiMensaje(BaseModel):
    usuario_emisor: str
    destinatario: str = ""
    grupo: str = "GENERAL"
    audio_mime: str = "audio/webm"
    audio_base64: str
    duracion_ms: int = 0
    sucursal: str = DEFAULT_SUCURSAL


class CajaMovimiento(BaseModel):
    tipo: str = "INGRESO"
    detalle: str
    monto: float
    usuario: str = ""
    documento_tipo: str = "MOVIMIENTO"
    documento_numero: str = ""
    estado_pago: str = "PAGADO"
    metodo_pago: str = ""
    observacion: str = ""
    sucursal: str = DEFAULT_SUCURSAL


class Proveedor(BaseModel):
    nombre: str
    ruc: str = ""
    telefono: str = ""
    direccion: str = ""
    sucursal: str = DEFAULT_SUCURSAL


class Compra(BaseModel):
    proveedor_nombre: str = ""
    proveedor: str = ""
    comprobante: str = ""
    total: float = 0
    usuario_registro: str = ""
    usuario: str = ""
    detalle: str = ""
    sucursal: str = DEFAULT_SUCURSAL
    items: List[dict] = []  # [{producto_id, nombre, cantidad, precio, series_texto}]


class EstadoPagoUpdate(BaseModel):
    estado_pago: str
    metodo_pago: Optional[str] = None
    monto_pagado: Optional[float] = None
    pagos_detalle: Optional[List[dict]] = None
    observacion_pago: Optional[str] = ""
    comprobante_pago: Optional[str] = ""
    comprobante_pago_nombre: Optional[str] = ""
    comprobante_pago_mime: Optional[str] = ""
    comprobante_pago_tamano: Optional[int] = None
    comprobante_pago_base64: Optional[str] = ""
    comprobante_pago_data_url: Optional[str] = ""
    comprobantes_pago: Optional[List[dict]] = None


class EstadoSunatUpdate(BaseModel):
    sunat_estado: str = "PROCESO"
    sunat_modo: str = "MANUAL"


class SunatConfigUpdate(BaseModel):
    ambiente: str = "BETA"
    envio_automatico: bool = False
    fecha_activacion_sunat: str = ""
    proveedor_sunat: str = "directo"
    api_base_url: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_sucursal_id: int = 1
    ruc: str = ""
    razon_social: str = ""
    nombre_comercial: str = ""
    ubigeo: str = "150101"
    direccion: str = ""
    departamento: str = "LIMA"
    provincia: str = "LIMA"
    distrito: str = "LIMA"
    usuario_sol: str = ""
    clave_sol: str = ""
    endpoint_url: str = ""
    certificado_pfx_base64: str = ""
    certificado_password: str = ""


PLATAFORM_API_SECRET_AVISO = (
    "El api_secret se guarda como hash SHA256 en la plataforma. "
    "No existe forma de recuperar el valor original; solo se puede generar uno nuevo. "
    "Este diseño es intencional: ni el equipo tecnico puede ver el secret de un cliente."
)
PLATAFORM_API_SECRET_AVISO_REGISTRO = (
    f"{PLATAFORM_API_SECRET_AVISO} "
    "Al registrar un cliente nuevo, el sistema devuelve el api_secret en texto plano UNA UNICA VEZ. "
    "Copialo y guardalo en un lugar seguro antes de cerrar esta ventana."
)


class SunatPlataformRegistro(BaseModel):
    cert_path: str = ""
    certificado_pfx_base64: str = ""
    cert_password: str = ""
    entorno: str = "beta"


class SunatEnviarRequest(BaseModel):
    regenerar: bool = False
    permitir_sin_firma: bool = False


class DocumentoObservacionInternaUpdate(BaseModel):
    observacion_interna: str = ""
    usuario: str = ""


class DocumentoConvertirUpdate(BaseModel):
    tipo: str = "BOLETA"
    estado_pago: str = "PAGADO"
    metodo_pago: str = "EFECTIVO"
    usuario_emisor: str = ""
    observacion: str = ""
    sucursal: str = DEFAULT_SUCURSAL


class DocumentoDetalleSeriesUpdate(BaseModel):
    series_texto: str = ""
    usuario: str = ""


class ProductoPrecioVentaUpdate(BaseModel):
    precio_venta: float = 0
    usuario: str = ""
    sucursal: str = DEFAULT_SUCURSAL


class Producto(BaseModel):
    nombre: str
    categoria: str
    marca: str
    modelo: str
    precio_compra: float
    precio_venta: float
    stock: int
    imagen_url: Optional[str] = ""
    observacion: Optional[str] = ""
    almacen: Optional[str] = "TIENDA"
    sku_woo: Optional[str] = ""
    categoria_web: Optional[str] = ""
    subcategoria_web: Optional[str] = ""
    woo_categoria_id: Optional[int] = 0
    woo_subcategoria_id: Optional[int] = 0
    sucursal: str = DEFAULT_SUCURSAL


class WooProduct(BaseModel):
    name: str
    sku: str = ""
    status: str = "publish"
    regular_price: str = ""
    sale_price: str = ""
    short_description: str = ""
    description: str = ""
    manage_stock: bool = True
    stock_quantity: Optional[int] = None
    images: Optional[list] = None
    categories: Optional[list] = None


class Garantia(BaseModel):
    cliente: str = ""
    documento: str = ""
    producto: str = ""
    serie: str = ""
    falla: str = ""
    estado: str = "RECIBIDO"
    solucion: str = ""
    usuario: str = ""
    sucursal: str = DEFAULT_SUCURSAL
    producto_cambio_id: Optional[int] = None
    producto_cambio: str = ""
    serie_cambio: str = ""
    cantidad_cambio: int = 1
    diferencia_precio: float = 0
    aplicar_cambio: bool = False


class GarantiaSeguimiento(BaseModel):
    tipo_resolucion: str = ""
    observacion_seguimiento: str = ""
    monto_devolucion: float = 0
    proveedor_garantia: str = ""
    estado: str = ""
    solucion: str = ""
    serie_nueva: str = ""
    usuario: str = ""
    sucursal: str = DEFAULT_SUCURSAL
    generar_nota_credito: bool = True


RESOLUCIONES_GARANTIA = {
    "PROVEEDOR_RESPONDIO": "Proveedor respondio",
    "CAMBIO_PRODUCTO": "Cambio de producto",
    "DEVOLUCION_DINERO": "Devolucion de dinero",
    "NOTA_CREDITO": "Nota de credito",
    "REPARADO": "Reparado y entregado",
    "RECHAZADO": "Rechazado",
    "EN_PROCESO": "En proceso con proveedor",
    "OTRO": "Otro",
}


# ================= TEST CONEXION =================
@app.get("/")
def home():
    return {"ok": True, "app": "ERP API"}


@app.get("/test-conn")
def test_conn():
    try:
        conn = get_conn()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def migrate_schema():
    """Crea tablas y columnas nuevas (idempotente). Se ejecuta al arranque y desde GET /init."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            usuario TEXT UNIQUE,
            clave TEXT,
            rol TEXT,
            foto_url TEXT DEFAULT ''
        );
        """)
        cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS foto_url TEXT DEFAULT ''")
        cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS fondo_url TEXT DEFAULT ''")
        cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'")
        cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS boquitoqui_enabled BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS color_tema TEXT DEFAULT '#304fb8'")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sucursales (
            codigo TEXT PRIMARY KEY,
            nombre TEXT,
            activa BOOLEAN DEFAULT TRUE,
            creada_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        INSERT INTO sucursales (codigo, nombre, activa)
        VALUES ('computer_army','COMPUTER ARMY',TRUE)
        ON CONFLICT (codigo) DO UPDATE SET nombre=EXCLUDED.nombre, activa=TRUE
        """)
        cur.execute("""
        INSERT INTO sucursales (codigo, nombre, activa)
        VALUES ('pc_fast_store','PC FAST STORE',TRUE)
        ON CONFLICT (codigo) DO UPDATE SET nombre=EXCLUDED.nombre, activa=TRUE
        """)
        cur.execute("""
        INSERT INTO sucursales (codigo, nombre, activa)
        VALUES ('ferreteria','FERRETERIA',TRUE)
        ON CONFLICT (codigo) DO UPDATE SET nombre=EXCLUDED.nombre, activa=TRUE
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS boquitoqui_mensajes (
            id SERIAL PRIMARY KEY,
            sucursal TEXT DEFAULT 'computer_army',
            usuario_emisor TEXT,
            destinatario TEXT DEFAULT '',
            grupo TEXT DEFAULT 'GENERAL',
            audio_mime TEXT DEFAULT 'audio/webm',
            audio_base64 TEXT,
            duracion_ms INTEGER DEFAULT 0,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_boquitoqui_sucursal_id ON boquitoqui_mensajes (sucursal, id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_boquitoqui_destinatario ON boquitoqui_mensajes (sucursal, destinatario)")
        cur.execute("DELETE FROM boquitoqui_mensajes")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios_online (
            usuario TEXT PRIMARY KEY,
            sucursal TEXT DEFAULT 'computer_army',
            vista TEXT DEFAULT '',
            dispositivo TEXT DEFAULT '',
            ultima_actividad TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        ensure_usuario_permisos_table(cur)

        for usuario, clave, rol in [
            ("Giomar", "43yk0rr21", "ADMIN"),
            ("Mily", "081508Pr", "ADMIN"),
        ]:
            cur.execute("""
            INSERT INTO usuarios (usuario, clave, rol, sucursal)
            VALUES (%s,%s,%s,'computer_army')
            ON CONFLICT (usuario)
            DO UPDATE SET clave=EXCLUDED.clave, rol=EXCLUDED.rol, sucursal='computer_army'
            """, (usuario, clave, rol))

        cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            tipo_documento TEXT,
            numero_documento TEXT UNIQUE,
            nombre TEXT,
            direccion TEXT,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        cur.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'")
        cur.execute("ALTER TABLE clientes DROP CONSTRAINT IF EXISTS clientes_numero_documento_key")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS reservas_clientes (
            id SERIAL PRIMARY KEY,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tipo_documento TEXT DEFAULT 'DNI',
            numero_documento TEXT DEFAULT '',
            cliente_nombre TEXT DEFAULT '',
            producto_id INT,
            producto_nombre TEXT DEFAULT '',
            cantidad INT DEFAULT 1,
            monto_total NUMERIC DEFAULT 0,
            monto_reserva NUMERIC DEFAULT 0,
            saldo NUMERIC DEFAULT 0,
            estado TEXT DEFAULT 'RESERVADO',
            observacion TEXT DEFAULT '',
            usuario TEXT DEFAULT '',
            sucursal TEXT DEFAULT 'computer_army'
        );
        """)
        for column_sql in [
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS tipo_documento TEXT DEFAULT 'DNI'",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS numero_documento TEXT DEFAULT ''",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS cliente_nombre TEXT DEFAULT ''",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS producto_id INT",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS producto_nombre TEXT DEFAULT ''",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS cantidad INT DEFAULT 1",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS monto_total NUMERIC DEFAULT 0",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS monto_reserva NUMERIC DEFAULT 0",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS saldo NUMERIC DEFAULT 0",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'RESERVADO'",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS observacion TEXT DEFAULT ''",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS usuario TEXT DEFAULT ''",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS comprobante_pago TEXT DEFAULT ''",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS comprobante_pago_nombre TEXT DEFAULT ''",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS comprobante_pago_mime TEXT DEFAULT ''",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS comprobante_pago_tamano BIGINT DEFAULT 0",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS comprobante_pago_base64 TEXT DEFAULT ''",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS comprobante_pago_data_url TEXT DEFAULT ''",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS comprobantes_pago_json TEXT DEFAULT ''",
            "ALTER TABLE reservas_clientes ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'",
        ]:
            cur.execute(column_sql)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reservas_clientes_doc ON reservas_clientes (sucursal, numero_documento, estado)")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS productos (
            id SERIAL PRIMARY KEY,
            nombre TEXT,
            categoria TEXT,
            marca TEXT,
            modelo TEXT,
            precio_compra NUMERIC,
            precio_venta NUMERIC,
            stock INT,
            imagen_url TEXT DEFAULT ''
        );
        """)

        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS imagen_url TEXT DEFAULT ''")
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'")
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS woo_id INT")
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS sku_woo TEXT DEFAULT ''")
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS categoria_web TEXT DEFAULT ''")
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS subcategoria_web TEXT DEFAULT ''")
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS woo_categoria_id INT")
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS woo_subcategoria_id INT")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id SERIAL PRIMARY KEY,
            tipo TEXT,
            serie TEXT,
            correlativo INT
        );
        """)
        cur.execute("ALTER TABLE series DROP CONSTRAINT IF EXISTS series_tipo_key")
        cur.execute("ALTER TABLE series ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'")
        cur.execute("UPDATE series SET sucursal='computer_army' WHERE COALESCE(sucursal,'')=''")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_series_tipo_sucursal ON series (tipo, sucursal)")

        seed_branch_series(cur, DEFAULT_SUCURSAL)
        seed_branch_series(cur, PC_FAST_SUCURSAL)
        seed_branch_series(cur, FERRETERIA_SUCURSAL)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS producto_series (
            id SERIAL PRIMARY KEY,
            producto_id INT REFERENCES productos(id) ON DELETE CASCADE,
            serie TEXT,
            proveedor TEXT,
            estado TEXT DEFAULT 'DISPONIBLE',
            fecha_ingreso TEXT,
            fecha_salida TEXT,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("ALTER TABLE producto_series DROP CONSTRAINT IF EXISTS producto_series_serie_key")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS usuario_ingreso TEXT DEFAULT ''")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS inventario_conteos (
            id SERIAL PRIMARY KEY,
            categoria TEXT,
            usuario TEXT,
            sucursal TEXT DEFAULT 'computer_army',
            estado TEXT DEFAULT 'ABIERTO',
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cerrado_en TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS inventario_conteo_scans (
            id SERIAL PRIMARY KEY,
            conteo_id INT REFERENCES inventario_conteos(id) ON DELETE CASCADE,
            serie TEXT,
            producto_id INT,
            producto_nombre TEXT,
            estado TEXT,
            usuario TEXT,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("ALTER TABLE inventario_conteos ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'")
        cur.execute("ALTER TABLE inventario_conteo_scans ADD COLUMN IF NOT EXISTS usuario TEXT DEFAULT ''")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS ventas (
            id SERIAL PRIMARY KEY,
            tipo TEXT,
            numero TEXT,
            cliente TEXT,
            total NUMERIC,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        for column_sql in [
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS documento_cliente TEXT",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS direccion_cliente TEXT",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS subtotal NUMERIC DEFAULT 0",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS igv NUMERIC DEFAULT 0",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS observacion TEXT",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS observacion_interna TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS fecha_vencimiento DATE",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS usuario_emisor TEXT",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'EMITIDO'",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS estado_pago TEXT DEFAULT 'PAGADO'",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS metodo_pago TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS monto_pagado NUMERIC DEFAULT 0",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS pagos_detalle_json TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS saldo_pago NUMERIC DEFAULT 0",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS observacion_pago TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS comprobante_pago TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS comprobante_pago_nombre TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS comprobante_pago_mime TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS comprobante_pago_tamano NUMERIC DEFAULT 0",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS comprobante_pago_base64 TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS comprobante_pago_data_url TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS comprobantes_pago_json TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sunat_estado TEXT DEFAULT 'PENDIENTE'",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sunat_modo TEXT DEFAULT 'MANUAL'",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sunat_fecha TIMESTAMP",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sunat_xml_nombre TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sunat_xml_base64 TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sunat_zip_nombre TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sunat_zip_base64 TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sunat_hash TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sunat_ticket TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sunat_cdr_base64 TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sunat_respuesta_json TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS es_pase BOOLEAN DEFAULT FALSE",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'",
        ]:
            cur.execute(column_sql)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS ventas_detalle (
            id SERIAL PRIMARY KEY,
            venta_id INT,
            producto_id INT,
            cantidad INT,
            precio NUMERIC,
            total NUMERIC
        );
        """)

        for column_sql in [
            "ALTER TABLE ventas_detalle ADD COLUMN IF NOT EXISTS descripcion TEXT",
            "ALTER TABLE ventas_detalle ADD COLUMN IF NOT EXISTS marca TEXT",
            "ALTER TABLE ventas_detalle ADD COLUMN IF NOT EXISTS modelo TEXT",
            "ALTER TABLE ventas_detalle ADD COLUMN IF NOT EXISTS series_texto TEXT",
            "ALTER TABLE ventas_detalle ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'",
        ]:
            cur.execute(column_sql)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS caja_movimientos (
            id SERIAL PRIMARY KEY,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tipo TEXT,
            detalle TEXT,
            monto NUMERIC,
            usuario TEXT,
            documento_tipo TEXT,
            documento_numero TEXT,
            estado_pago TEXT DEFAULT 'PAGADO',
            metodo_pago TEXT DEFAULT '',
            observacion TEXT DEFAULT ''
        );
        """)

        cur.execute("ALTER TABLE caja_movimientos ADD COLUMN IF NOT EXISTS metodo_pago TEXT DEFAULT ''")
        cur.execute("ALTER TABLE caja_movimientos ADD COLUMN IF NOT EXISTS observacion TEXT DEFAULT ''")
        cur.execute("ALTER TABLE caja_movimientos ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS proveedores (
            id SERIAL PRIMARY KEY,
            nombre TEXT,
            ruc TEXT DEFAULT '',
            telefono TEXT DEFAULT '',
            direccion TEXT DEFAULT '',
            sucursal TEXT DEFAULT 'computer_army',
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        for column_sql in [
            "ALTER TABLE proveedores ADD COLUMN IF NOT EXISTS ruc TEXT DEFAULT ''",
            "ALTER TABLE proveedores ADD COLUMN IF NOT EXISTS telefono TEXT DEFAULT ''",
            "ALTER TABLE proveedores ADD COLUMN IF NOT EXISTS direccion TEXT DEFAULT ''",
            "ALTER TABLE proveedores ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'",
            "ALTER TABLE proveedores ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        ]:
            cur.execute(column_sql)

        cur.execute("""
        UPDATE ventas
        SET fecha_vencimiento = COALESCE(fecha_vencimiento, DATE(fecha))
        WHERE UPPER(COALESCE(tipo,''))='PROFORMA'
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS compras (
            id SERIAL PRIMARY KEY,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            proveedor_nombre TEXT,
            comprobante TEXT DEFAULT '',
            total NUMERIC DEFAULT 0,
            usuario_registro TEXT DEFAULT '',
            detalle TEXT DEFAULT '',
            sucursal TEXT DEFAULT 'computer_army'
        );
        """)
        for column_sql in [
            "ALTER TABLE compras ADD COLUMN IF NOT EXISTS fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE compras ADD COLUMN IF NOT EXISTS proveedor_nombre TEXT",
            "ALTER TABLE compras ADD COLUMN IF NOT EXISTS comprobante TEXT DEFAULT ''",
            "ALTER TABLE compras ADD COLUMN IF NOT EXISTS total NUMERIC DEFAULT 0",
            "ALTER TABLE compras ADD COLUMN IF NOT EXISTS usuario_registro TEXT DEFAULT ''",
            "ALTER TABLE compras ADD COLUMN IF NOT EXISTS detalle TEXT DEFAULT ''",
            "ALTER TABLE compras ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'",
            "ALTER TABLE compras ADD COLUMN IF NOT EXISTS items_json TEXT DEFAULT ''",
        ]:
            cur.execute(column_sql)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            clave TEXT PRIMARY KEY,
            valor TEXT,
            actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS garantias (
            id SERIAL PRIMARY KEY,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cliente TEXT,
            documento TEXT,
            producto TEXT,
            serie TEXT,
            falla TEXT,
            estado TEXT DEFAULT 'RECIBIDO',
            solucion TEXT DEFAULT '',
            usuario TEXT DEFAULT ''
        );
        """)
        for column_sql in [
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS solucion TEXT DEFAULT ''",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS usuario TEXT DEFAULT ''",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS producto_cambio_id INT",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS producto_cambio TEXT DEFAULT ''",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS serie_cambio TEXT DEFAULT ''",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS cantidad_cambio INT DEFAULT 0",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS diferencia_precio NUMERIC DEFAULT 0",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS cambio_aplicado BOOLEAN DEFAULT FALSE",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS cambio_fecha TIMESTAMP",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS documento_cambio_id INT",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS documento_cambio_numero TEXT DEFAULT ''",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS tipo_resolucion TEXT DEFAULT ''",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS observacion_seguimiento TEXT DEFAULT ''",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS monto_devolucion NUMERIC DEFAULT 0",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS proveedor_garantia TEXT DEFAULT ''",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS documento_seguimiento_id INT",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS documento_seguimiento_numero TEXT DEFAULT ''",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS seguimiento_fecha TIMESTAMP",
            "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS seguimiento_usuario TEXT DEFAULT ''",
        ]:
            cur.execute(column_sql)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS auditoria (
            id SERIAL PRIMARY KEY,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usuario TEXT,
            rol TEXT,
            empresa TEXT,
            accion TEXT,
            detalle TEXT
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_transferencias (
            id SERIAL PRIMARY KEY,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            producto_id INT,
            producto_nombre TEXT,
            cantidad INT,
            sucursal_origen TEXT,
            sucursal_destino TEXT,
            usuario TEXT,
            nota TEXT
        );
        """)

        conn.commit()
        conn.close()

        return {"ok": True, "msg": "Base completa lista"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/init")
def init_http():
    """Misma migracion que al arranque del servidor; puedes llamarla manual tras un deploy."""
    return migrate_schema()


# ================= AUTO UPDATE =================
@app.get("/app/version")
def app_version():
    latest_version = "1.0.70"
    latest_url = "https://github.com/giomar456/erp-api/releases/download/v1.0.71/erp_sql_pro_v20_v1.0.71.exe"
    latest_name = "erp_sql_pro_v20_v1.0.70.exe"
    latest_notes = "Actualizacion G&G ERP web v1.74: salida manual sobre boletas existentes, anulacion con restauracion de stock, PDF mas legible y servicios tecnicos."

    version = os.getenv("APP_VERSION", latest_version)
    download_url = os.getenv("APP_DOWNLOAD_URL", latest_url)
    exe_name = os.getenv("APP_EXE_NAME", latest_name)
    notes = os.getenv("APP_UPDATE_NOTES", latest_notes)
    force_update = os.getenv("APP_FORCE_UPDATE", "false").lower() in ("1", "true", "yes", "si")

    if version in ("", "1.0.0", "1.0.1", "1.0.2", "1.0.3") or not download_url or "/v1.0.1/" in download_url:
        version = latest_version
        download_url = latest_url
        exe_name = latest_name
        notes = latest_notes

    android_version = os.getenv("ANDROID_APP_VERSION", "1.77")
    android_download_url = os.getenv("ANDROID_APP_DOWNLOAD_URL", "")
    android_apk_name = os.getenv("ANDROID_APP_APK_NAME", "GG_ERP_TELEFONO_v1.77_CAJA_PRODUCTOS_INSTALABLE.apk")
    android_dex_download_url = os.getenv("ANDROID_APP_DEX_DOWNLOAD_URL", android_download_url)
    android_dex_apk_name = os.getenv("ANDROID_APP_DEX_APK_NAME", "GG_ERP_TABLET_DEX_v1.77_CAJA_PRODUCTOS_INSTALABLE.apk")
    android_notes = os.getenv("ANDROID_APP_UPDATE_NOTES", "Actualizacion Android G&G ERP v1.77: EMITIR SUNAT B002/F002, compras con producto nuevo, detalle y documento de compra, fix guardar compra.")
    return {
        "ok": True,
        "success": True,
        "version": version,
        "url": download_url,
        "name": exe_name,
        "notes": notes,
        "force_update": force_update,
        "android_version": android_version,
        "android_url": android_download_url,
        "android_name": android_apk_name,
        "android_dex_url": android_dex_download_url,
        "android_dex_name": android_dex_apk_name,
        "android_notes": android_notes
    }

# ================= LOGIN =================
@app.post("/login")
def login(data: dict):
    sucursal = norm_sucursal(data.get("sucursal") or data.get("empresa"))
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, usuario, rol, COALESCE(foto_url,'') AS foto_url,
               COALESCE(fondo_url,'') AS fondo_url,
               COALESCE(sucursal,%s) AS sucursal,
               COALESCE(boquitoqui_enabled,FALSE) AS boquitoqui_enabled,
               COALESCE(color_tema,'#304fb8') AS color_tema
        FROM usuarios
        WHERE lower(usuario)=lower(%s) AND clave=%s
    """,
                (DEFAULT_SUCURSAL, data["usuario"], data["clave"]))
    user = dict_fetchone(cur)
    if not user:
        conn.close()
        return {"ok": False}
    user["permisos"] = permisos_usuario(cur, user.get("id"), user.get("usuario"), user.get("rol"))
    conn.close()
    if str(user["usuario"]).strip().lower() != "giomar":
        user_branch = norm_sucursal(user.get("sucursal"))
        if user_branch != sucursal:
            return {"ok": False, "msg": "No tienes acceso a esta sucursal."}
        sucursal = user_branch

    return {"ok": True, "id": user["id"], "usuario": user["usuario"], "rol": user["rol"], "foto_url": user.get("foto_url", ""), "fondo_url": user.get("fondo_url", ""), "boquitoqui_enabled": bool(user.get("boquitoqui_enabled")), "color_tema": norm_theme_color(user.get("color_tema")), "sucursal": sucursal, "empresa": sucursal, "permisos": user.get("permisos") or dict(DEFAULT_FEATURES)}


# ================= USUARIOS =================
@app.get("/usuarios")
def listar_usuarios(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
        SELECT id, usuario, rol, COALESCE(foto_url,'') AS foto_url,
               COALESCE(fondo_url,'') AS fondo_url,
               COALESCE(sucursal,%s) AS sucursal,
               COALESCE(boquitoqui_enabled,FALSE) AS boquitoqui_enabled,
               COALESCE(color_tema,'#304fb8') AS color_tema
        FROM usuarios
        WHERE COALESCE(sucursal,%s)=%s OR lower(usuario)='giomar'
        ORDER BY usuario
    """, (DEFAULT_SUCURSAL, DEFAULT_SUCURSAL, sucursal))
    data = dict_fetchall(cur)
    conn.close()
    return data


@app.get("/usuarios/perfil")
def perfil_usuario(usuario: str = ""):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, usuario, rol, COALESCE(foto_url,'') AS foto_url,
               COALESCE(fondo_url,'') AS fondo_url,
               COALESCE(sucursal,%s) AS sucursal,
               COALESCE(boquitoqui_enabled,FALSE) AS boquitoqui_enabled,
               COALESCE(color_tema,'#304fb8') AS color_tema
        FROM usuarios
        WHERE lower(usuario)=lower(%s)
    """, (DEFAULT_SUCURSAL, usuario.strip()))
    data = dict_fetchone(cur)
    if not data:
        conn.close()
        return {"ok": False, "found": False}
    data["permisos"] = permisos_usuario(cur, data.get("id"), data.get("usuario"), data.get("rol"))
    conn.close()
    return {"ok": True, "found": True, **data}


@app.post("/usuarios")
def guardar_usuario(data: Usuario):
    conn = get_conn()
    cur = conn.cursor()
    usuario = (data.usuario or "").strip()
    clave = data.clave or ""
    rol = (data.rol or "VENTAS").upper()
    foto_url = data.foto_url or ""
    fondo_url = data.fondo_url or ""
    radio_enabled = bool(data.boquitoqui_enabled)
    sucursal = norm_sucursal(data.sucursal)
    color_tema = norm_theme_color(data.color_tema)
    if rol not in ("ADMIN", "VENTAS"):
        rol = "VENTAS"
    if not usuario:
        conn.close()
        return {"ok": False, "msg": "Usuario obligatorio"}
    cur.execute("SELECT id FROM usuarios WHERE lower(usuario)=lower(%s)", (usuario,))
    existing = cur.fetchone()
    if not existing and not clave:
        conn.close()
        return {"ok": False, "msg": "Usuario y clave son obligatorios"}
    if existing:
        cur.execute("""
        UPDATE usuarios
        SET usuario=%s, clave=CASE WHEN %s <> '' THEN %s ELSE clave END, rol=%s, sucursal=%s, boquitoqui_enabled=%s,
            color_tema=%s,
            foto_url=CASE WHEN %s <> '' THEN %s ELSE COALESCE(foto_url,'') END,
            fondo_url=%s
        WHERE id=%s
        RETURNING id
        """, (usuario, clave, clave, rol, sucursal, radio_enabled, color_tema, foto_url, foto_url, fondo_url, existing[0]))
    else:
        cur.execute("""
        INSERT INTO usuarios (usuario, clave, rol, foto_url, fondo_url, sucursal, boquitoqui_enabled, color_tema)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """, (usuario, clave, rol, foto_url, fondo_url, sucursal, radio_enabled, color_tema))
    user_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return {"ok": True, "success": True, "id": user_id}


@app.get("/sucursales")
def listar_sucursales():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT codigo, nombre, COALESCE(activa, TRUE) AS activa
        FROM sucursales
        WHERE COALESCE(activa, TRUE)=TRUE
        ORDER BY nombre
    """)
    data = dict_fetchall(cur)
    conn.close()
    return data


@app.post("/sucursales")
def guardar_sucursal(data: dict):
    usuario = str(data.get("usuario", "")).strip().lower()
    if usuario != "giomar":
        return {"ok": False, "msg": "Solo Giomar puede crear sucursales."}
    codigo = norm_sucursal(data.get("codigo"))
    nombre = str(data.get("nombre") or codigo.replace("_", " ").upper()).strip().upper()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sucursales (codigo, nombre, activa)
        VALUES (%s,%s,TRUE)
        ON CONFLICT (codigo) DO UPDATE SET nombre=EXCLUDED.nombre, activa=TRUE
        RETURNING codigo
    """, (codigo, nombre))
    seed_branch_series(cur, codigo)
    conn.commit()
    conn.close()
    return {"ok": True, "success": True, "codigo": codigo, "nombre": nombre}


@app.delete("/sucursales/{codigo}")
def eliminar_sucursal(codigo: str, usuario: str = ""):
    if str(usuario).strip().lower() != "giomar":
        return {"ok": False, "msg": "Solo Giomar puede eliminar sucursales."}
    codigo = norm_sucursal(codigo)
    if codigo == DEFAULT_SUCURSAL:
        return {"ok": False, "msg": "COMPUTER ARMY es la sucursal principal y no se puede eliminar."}
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE sucursales SET activa=FALSE WHERE codigo=%s RETURNING codigo", (codigo,))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row:
        return {"ok": False, "msg": "Sucursal no encontrada."}
    return {"ok": True, "success": True, "codigo": codigo}


@app.get("/sucursales/{codigo}/permisos")
def obtener_permisos_sucursal(codigo: str):
    codigo = norm_sucursal(codigo)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sucursal_permisos (
        sucursal TEXT PRIMARY KEY,
        permisos TEXT,
        actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("SELECT permisos FROM sucursal_permisos WHERE sucursal=%s", (codigo,))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    permisos = dict(DEFAULT_FEATURES)
    permisos["pagina_web"] = False
    if row and row[0]:
        try:
            custom = json.loads(row[0])
            if isinstance(custom, dict):
                for k, v in custom.items():
                    if k in permisos:
                        permisos[k] = bool(v)
        except Exception:
            pass
    return {"ok": True, "success": True, "sucursal": codigo, "permisos": permisos}


@app.post("/sucursales/{codigo}/permisos")
def guardar_permisos_sucursal(codigo: str, data: dict):
    usuario = str(data.get("usuario", "")).strip().lower()
    if usuario != "giomar":
        return {"ok": False, "success": False, "msg": "Solo Giomar puede modificar permisos de sucursales."}
    codigo = norm_sucursal(codigo)
    permisos = dict(DEFAULT_FEATURES)
    permisos["pagina_web"] = False
    incoming = data.get("permisos", {})
    if isinstance(incoming, dict):
        for k, v in incoming.items():
            if k in permisos:
                permisos[k] = bool(v)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sucursal_permisos (
        sucursal TEXT PRIMARY KEY,
        permisos TEXT,
        actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("""
    INSERT INTO sucursal_permisos (sucursal, permisos, actualizado)
    VALUES (%s,%s,CURRENT_TIMESTAMP)
    ON CONFLICT (sucursal)
    DO UPDATE SET permisos=EXCLUDED.permisos, actualizado=CURRENT_TIMESTAMP
    """, (codigo, json.dumps(permisos, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return {"ok": True, "success": True, "sucursal": codigo, "permisos": permisos}


@app.put("/usuarios/{usuario_id}/foto")
def actualizar_foto_usuario(usuario_id: int, data: dict):
    foto_url = str(data.get("foto_url", "") or "")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE usuarios
        SET foto_url=%s
        WHERE id=%s
        RETURNING id
    """, (foto_url, usuario_id))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row:
        return {"ok": False, "msg": "Usuario no encontrado"}
    return {"ok": True, "success": True}


@app.put("/usuarios/{usuario_id}/fondo")
def actualizar_fondo_usuario_admin(usuario_id: int, data: UsuarioFondoUpdate):
    fondo_url = str(data.fondo_url or "").strip()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE usuarios
        SET fondo_url=%s
        WHERE id=%s
        RETURNING id
    """, (fondo_url, usuario_id))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row:
        return {"ok": False, "msg": "Usuario no encontrado"}
    return {"ok": True, "success": True, "id": row[0], "fondo_url": fondo_url}


@app.put("/usuarios/{usuario_id}/rol")
def cambiar_rol_usuario(usuario_id: int, data: UsuarioRolUpdate):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT usuario FROM usuarios WHERE id=%s", (usuario_id,))
    current = cur.fetchone()
    if not current:
        conn.close()
        return {"ok": False, "msg": "Usuario no encontrado"}
    if str(current[0]).strip().lower() == "giomar":
        conn.close()
        return {"ok": False, "msg": "Giomar es control maestro y no se puede cambiar su rol"}
    rol = (data.rol or "VENTAS").upper()
    if rol not in ("ADMIN", "VENTAS"):
        rol = "VENTAS"
    cur.execute("""
    UPDATE usuarios SET rol=%s
    WHERE id=%s
    RETURNING id
    """, (rol, usuario_id))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row:
        return {"ok": False, "msg": "Usuario no encontrado"}
    return {"ok": True, "success": True, "id": row[0], "rol": rol}


@app.put("/usuarios/{usuario_id}/boquitoqui")
def cambiar_boquitoqui_usuario(usuario_id: int, data: UsuarioRadioUpdate):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    UPDATE usuarios SET boquitoqui_enabled=%s
    WHERE id=%s
    RETURNING id
    """, (bool(data.boquitoqui_enabled), usuario_id))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row:
        return {"ok": False, "msg": "Usuario no encontrado"}
    return {"ok": True, "success": True, "id": row[0], "boquitoqui_enabled": bool(data.boquitoqui_enabled)}


@app.put("/usuarios/{usuario_id}/color")
def cambiar_color_usuario_admin(usuario_id: int, data: UsuarioColorUpdate):
    color = norm_theme_color(data.color_tema)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    UPDATE usuarios SET color_tema=%s
    WHERE id=%s
    RETURNING id
    """, (color, usuario_id))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row:
        return {"ok": False, "msg": "Usuario no encontrado"}
    return {"ok": True, "success": True, "id": row[0], "color_tema": color}


@app.put("/usuarios/color")
def cambiar_color_usuario(data: UsuarioColorUpdate):
    usuario = (data.usuario or "").strip()
    if not usuario:
        return {"ok": False, "msg": "Usuario requerido."}
    color = norm_theme_color(data.color_tema)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    UPDATE usuarios SET color_tema=%s
    WHERE lower(usuario)=lower(%s)
    RETURNING id
    """, (color, usuario))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row:
        return {"ok": False, "msg": "Usuario no encontrado"}
    return {"ok": True, "success": True, "id": row[0], "color_tema": color}


@app.put("/usuarios/fondo")
def cambiar_fondo_usuario(data: UsuarioFondoUpdate):
    usuario = (data.usuario or "").strip()
    if not usuario:
        return {"ok": False, "msg": "Usuario requerido."}
    fondo_url = str(data.fondo_url or "").strip()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    UPDATE usuarios SET fondo_url=%s
    WHERE lower(usuario)=lower(%s)
    RETURNING id
    """, (fondo_url, usuario))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row:
        return {"ok": False, "msg": "Usuario no encontrado"}
    return {"ok": True, "success": True, "id": row[0], "fondo_url": fondo_url}


@app.get("/usuarios/{usuario_id}/permisos")
def obtener_permisos_usuario(usuario_id: int):
    conn = get_conn()
    cur = conn.cursor()
    try:
        ensure_usuario_permisos_table(cur)
        cur.execute("SELECT id, usuario, rol FROM usuarios WHERE id=%s", (usuario_id,))
        user = dict_fetchone(cur)
        if not user:
            conn.close()
            return {"ok": False, "success": False, "msg": "Usuario no encontrado."}
        permisos = permisos_usuario(cur, user.get("id"), user.get("usuario"), user.get("rol"))
        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "usuario_id": usuario_id, "permisos": permisos}
    except Exception as e:
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.post("/usuarios/{usuario_id}/permisos")
def guardar_permisos_usuario(usuario_id: int, data: dict):
    admin = str(data.get("usuario") or data.get("admin") or "").strip().lower()
    if admin != "giomar":
        return {"ok": False, "success": False, "msg": "Solo Giomar maestro puede modificar permisos de usuarios."}
    conn = get_conn()
    cur = conn.cursor()
    try:
        ensure_usuario_permisos_table(cur)
        cur.execute("SELECT id, usuario FROM usuarios WHERE id=%s", (usuario_id,))
        user = dict_fetchone(cur)
        if not user:
            conn.close()
            return {"ok": False, "success": False, "msg": "Usuario no encontrado."}
        if str(user.get("usuario") or "").strip().lower() == "giomar":
            conn.close()
            return {"ok": False, "success": False, "msg": "Giomar maestro siempre tiene todos los permisos."}
        permisos = normalize_feature_permissions(data.get("permisos") or {})
        cur.execute("""
        INSERT INTO usuario_permisos (usuario_id, permisos, actualizado)
        VALUES (%s,%s,CURRENT_TIMESTAMP)
        ON CONFLICT (usuario_id)
        DO UPDATE SET permisos=EXCLUDED.permisos, actualizado=CURRENT_TIMESTAMP
        """, (usuario_id, json.dumps(permisos, ensure_ascii=False)))
        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "usuario_id": usuario_id, "permisos": permisos}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.get("/usuarios/online")
def listar_usuarios_online(sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.id, u.usuario, u.rol, COALESCE(u.foto_url,'') AS foto_url,
               COALESCE(u.fondo_url,'') AS fondo_url,
               COALESCE(u.sucursal,%s) AS sucursal,
               COALESCE(u.boquitoqui_enabled,FALSE) AS boquitoqui_enabled,
               COALESCE(u.color_tema,'#304fb8') AS color_tema,
               CASE
                   WHEN o.ultima_actividad IS NOT NULL
                    AND o.ultima_actividad >= CURRENT_TIMESTAMP - INTERVAL '90 seconds'
                   THEN TRUE ELSE FALSE
               END AS online,
               COALESCE(o.vista,'') AS vista,
               COALESCE(o.dispositivo,'') AS dispositivo,
               TO_CHAR(o.ultima_actividad, 'YYYY-MM-DD HH24:MI:SS') AS ultima_actividad
        FROM usuarios u
        LEFT JOIN usuarios_online o ON lower(o.usuario)=lower(u.usuario)
        ORDER BY online DESC, u.usuario
    """, (DEFAULT_SUCURSAL,))
    data = dict_fetchall(cur)
    for item in data:
        item["permisos"] = permisos_usuario(cur, item.get("id"), item.get("usuario"), item.get("rol"))
    conn.close()
    return {"ok": True, "success": True, "data": data}


@app.post("/usuarios/online")
def registrar_usuario_online(data: UsuarioOnlineHeartbeat):
    usuario = (data.usuario or "").strip()
    if not usuario:
        return {"ok": False, "success": False, "msg": "Usuario obligatorio"}
    sucursal = norm_sucursal(data.sucursal)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO usuarios_online (usuario, sucursal, vista, dispositivo, ultima_actividad)
        VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP)
        ON CONFLICT (usuario)
        DO UPDATE SET sucursal=EXCLUDED.sucursal,
                      vista=EXCLUDED.vista,
                      dispositivo=EXCLUDED.dispositivo,
                      ultima_actividad=CURRENT_TIMESTAMP
    """, (usuario, sucursal, (data.vista or "")[:80], (data.dispositivo or "")[:80]))
    conn.commit()
    conn.close()
    return {"ok": True, "success": True}


@app.delete("/usuarios/{usuario_id}")
def eliminar_usuario(usuario_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT usuario FROM usuarios WHERE id=%s", (usuario_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "msg": "Usuario no encontrado"}
    if str(row[0]).strip().lower() == "giomar":
        conn.close()
        return {"ok": False, "msg": "No se puede eliminar Giomar"}
    cur.execute("DELETE FROM usuarios WHERE id=%s", (usuario_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "success": True}


@app.get("/boquitoqui/mensajes")
def listar_boquitoqui_mensajes(
    since_id: int = 0,
    usuario: str = "",
    sucursal: str = DEFAULT_SUCURSAL,
    limit: int = 25,
):
    return {"ok": True, "success": True, "data": []}


@app.get("/boquitoqui/ultimo")
def ultimo_boquitoqui_mensaje(usuario: str = "", sucursal: str = DEFAULT_SUCURSAL, include_audio: bool = False):
    return {"ok": True, "success": True, "data": None}


@app.post("/boquitoqui/mensajes")
def guardar_boquitoqui_mensaje(data: BoquitoquiMensaje):
    return enviar_boquitoqui_live(data)


def _boquitoqui_live_cleanup(now_ts=None):
    now_ts = now_ts or time.time()
    stale_before = now_ts - BOQUITOQUI_LIVE_TTL_SECONDS
    empty_keys = []
    for key, queue in _boquitoqui_live_queues.items():
        while queue and float(queue[0].get("_ts", 0)) < stale_before:
            queue.popleft()
        if not queue:
            empty_keys.append(key)
    for key in empty_keys:
        try:
            del _boquitoqui_live_queues[key]
        except KeyError:
            pass


def _boquitoqui_live_key(sucursal, usuario):
    return (norm_sucursal(sucursal), str(usuario or "").strip().lower())


@app.get("/boquitoqui/live")
def listar_boquitoqui_live(
    since_id: int = 0,
    usuario: str = "",
    sucursal: str = DEFAULT_SUCURSAL,
    limit: int = 20,
):
    sucursal = norm_sucursal(sucursal)
    usuario = (usuario or "").strip()
    if not usuario:
        return {"ok": False, "success": False, "msg": "Usuario obligatorio.", "data": []}
    limit = max(1, min(int(limit or 20), 40))
    key = _boquitoqui_live_key(sucursal, usuario)
    with _boquitoqui_live_lock:
        _boquitoqui_live_cleanup()
        rows = [
            {k: v for k, v in item.items() if k != "_ts"}
            for item in list(_boquitoqui_live_queues.get(key, []))
            if int(item.get("id") or 0) > int(since_id or 0)
        ][:limit]
    return {"ok": True, "success": True, "data": rows}


@app.post("/boquitoqui/live")
def enviar_boquitoqui_live(data: BoquitoquiMensaje):
    global _boquitoqui_live_next_id
    sucursal = norm_sucursal(data.sucursal)
    usuario = (data.usuario_emisor or "").strip()
    destinatario = (data.destinatario or "").strip()
    grupo = (data.grupo or "GENERAL").strip().upper()
    audio_mime = (data.audio_mime or "audio/wav").strip()[:80]
    audio_base64 = (data.audio_base64 or "").strip()
    duracion_ms = max(0, min(int(data.duracion_ms or 0), 30000))
    if not usuario:
        return {"ok": False, "success": False, "msg": "Usuario emisor obligatorio."}
    if not audio_base64:
        return {"ok": False, "success": False, "msg": "Audio vacio."}
    if len(audio_base64) > 650000:
        return {"ok": False, "success": False, "msg": "Audio muy grande. MantÃ©n presionado por tramos cortos."}

    recipients = []
    if destinatario:
        recipients.append(destinatario)
    else:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT usuario
            FROM usuarios
            WHERE lower(usuario)<>lower(%s)
              AND lower(COALESCE(sucursal,%s))=lower(%s)
            LIMIT 50
        """, (usuario, sucursal, sucursal))
        recipients = [str(row[0]).strip() for row in cur.fetchall() if str(row[0]).strip()]
        conn.close()
    if not recipients:
        return {"ok": False, "success": False, "msg": "No hay usuario receptor."}

    with _boquitoqui_live_lock:
        _boquitoqui_live_cleanup()
        _boquitoqui_live_next_id += 1
        msg_id = _boquitoqui_live_next_id
        now_ts = time.time()
        for receptor in recipients:
            queue = _boquitoqui_live_queues[_boquitoqui_live_key(sucursal, receptor)]
            queue.append({
                "id": msg_id,
                "_ts": now_ts,
                "sucursal": sucursal,
                "usuario_emisor": usuario,
                "destinatario": receptor,
                "grupo": grupo,
                "audio_mime": audio_mime,
                "audio_base64": audio_base64,
                "duracion_ms": duracion_ms,
                "creado_en": lima_now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            while len(queue) > BOQUITOQUI_LIVE_MAX_QUEUE:
                queue.popleft()
    return {"ok": True, "success": True, "id": msg_id, "recipients": recipients}


# ================= AUDITORIA CENTRAL =================
@app.post("/auditoria")
def registrar_auditoria(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auditoria (
        id SERIAL PRIMARY KEY,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        usuario TEXT,
        rol TEXT,
        empresa TEXT,
        accion TEXT,
        detalle TEXT
    );
    """)
    cur.execute("""
    INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
    VALUES (%s,%s,%s,%s,%s)
    RETURNING id
    """, (
        str(data.get("usuario", "")),
        str(data.get("rol", "")),
        str(data.get("empresa", "")),
        str(data.get("accion", "")),
        str(data.get("detalle", "")),
    ))
    audit_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return {"ok": True, "success": True, "id": audit_id}


@app.get("/auditoria")
def listar_auditoria(q: str = "", limit: int = 1000):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auditoria (
        id SERIAL PRIMARY KEY,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        usuario TEXT,
        rol TEXT,
        empresa TEXT,
        accion TEXT,
        detalle TEXT
    );
    """)
    limit = max(1, min(int(limit or 1000), 5000))
    texto = f"%{(q or '').lower()}%"
    cur.execute("""
    SELECT id, to_char(fecha, 'YYYY-MM-DD HH24:MI:SS') AS fecha,
           COALESCE(usuario,'') AS usuario,
           COALESCE(rol,'') AS rol,
           COALESCE(empresa,'') AS empresa,
           COALESCE(accion,'') AS accion,
           COALESCE(detalle,'') AS detalle
    FROM auditoria
    WHERE %s = '%%'
       OR LOWER(COALESCE(usuario,'')) LIKE %s
       OR LOWER(COALESCE(rol,'')) LIKE %s
       OR LOWER(COALESCE(empresa,'')) LIKE %s
       OR LOWER(COALESCE(accion,'')) LIKE %s
       OR LOWER(COALESCE(detalle,'')) LIKE %s
    ORDER BY id DESC
    LIMIT %s
    """, (texto, texto, texto, texto, texto, texto, limit))
    data = dict_fetchall(cur)
    conn.commit()
    conn.close()
    return data


# ================= CONFIGURACION CENTRAL =================
@app.get("/config/documento")
def obtener_config_documento(sucursal: str = DEFAULT_SUCURSAL):
    return {"ok": True, "success": True, "data": cargar_config_documento_dict(sucursal)}


@app.post("/config/documento")
def guardar_config_documento(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.get("sucursal") or data.get("empresa") or DEFAULT_SUCURSAL)
    clave = f"documento:{sucursal}"
    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_config (
        clave TEXT PRIMARY KEY,
        valor TEXT,
        actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("""
    INSERT INTO app_config (clave, valor, actualizado)
    VALUES (%s,%s,CURRENT_TIMESTAMP)
    ON CONFLICT (clave)
    DO UPDATE SET valor=EXCLUDED.valor, actualizado=CURRENT_TIMESTAMP
    """, (clave, json.dumps(data, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return {"ok": True, "success": True}


def documento_config_default():
    return {
        "empresa": "CORPORACION COMPUTER ARMY EIRL",
        "company_name": "CORPORACION COMPUTER ARMY EIRL",
        "ruc": "20611068701",
        "direccion": "PRINCIPAL >> AV. INCA GARCILASO DE LA VEGA NRO. 1348 INT2B 130-131 - CERCADO DE LIMA - LIMA - PERU",
        "address": "PRINCIPAL >> AV. INCA GARCILASO DE LA VEGA NRO. 1348 INT2B 130-131 - CERCADO DE LIMA - LIMA - PERU",
        "telefono": "903039171",
        "mensaje": "MEJORES PRECIOS EN TARJETAS DE VIDEOS",
        "cuenta_bcp": "1941066028058",
        "cuenta_interbank": "2003005323345",
        "logo": "",
        "doc_editor": {
            "template_name": "ARMY referencia exacta",
            "show_logo": True,
            "show_serie": True,
            "show_banks": True,
            "keyfacil_exact": True,
            "show_reference_footer": False,
            "title_font": 14,
            "header_font": 14,
            "body_font": 7,
            "table_font": 7,
            "pdf_desc_font": 7.0,
            "pdf_series_font": 6.2,
            "pdf_row_height": 6.5,
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
            "texts": {
                "empresa": "CORPORACION COMPUTER ARMY EIRL",
                "direccion": "PRINCIPAL >> AV. INCA GARCILASO DE LA VEGA NRO. 1348 INT2B 130-131 - CERCADO DE LIMA - LIMA - PERU",
                "slogan": "MEJORES PRECIOS EN TARJETAS DE VIDEOS",
                "legal_line1": "Autorizado mediante resolucion Nro 034-005-0010431/SUNAT",
                "legal_line2": "",
                "legal_line3": "Emitido mediante G&G ERP",
                "garantia_1": "UN ANO DE GARANTIA DE CADA PRODUCTO Y 6 MESES PARA PERIFERICOS",
                "garantia_2": "NO SE ACEPTAN CAMBIOS NI DEVOLUCIONES. SOLO DEFECTO DE FABRICA",
                "garantia_3": "CONSERVAR CAJAS Y ACCESORIOS DE CADA PRODUCTO",
                "garantia_4": "NO HAY GARANTIA por software, dano fisico, roto, quemado, sulfatado, presencia de oxido o presencia de sulfato",
                "garantia_5": "ENSAMBLAJE PROFESIONAL Y INSTALACION DE SISTEMA OPERATIVO WINDOWS, PAQUETE DE OFFICE GRATIS",
                "garantia_6": "POR PC COMPLETA",
            },
            "layout": {
                "max_productos": 12,
                "alto_fila_mm": 6.5,
                "alto_tabla_mm": 86,
                "letra_tabla_px": 7.0,
                "letra_descripcion_px": 7.0,
                "logo_ancho_mm": 24,
                "logo_alto_mm": 15,
                "logo_bajar_mm": 23,
                "margen_superior_mm": 8,
            },
        },
    }


def cargar_config_documento_dict(sucursal=DEFAULT_SUCURSAL):
    base = documento_config_default()
    conn = get_conn()
    cur = conn.cursor()
    clave = f"documento:{norm_sucursal(sucursal)}"
    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_config (
        clave TEXT PRIMARY KEY,
        valor TEXT,
        actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("SELECT valor FROM app_config WHERE clave=%s", (clave,))
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT valor FROM app_config WHERE clave=%s", ("documento",))
        row = cur.fetchone()
    conn.commit()
    conn.close()
    if row and row[0]:
        try:
            saved = json.loads(row[0])
            if isinstance(saved, dict):
                base.update(saved)
                doc_saved = saved.get("doc_editor") if isinstance(saved.get("doc_editor"), dict) else {}
                base["doc_editor"] = {**documento_config_default()["doc_editor"], **doc_saved}
                layout = {}
                layout.update(documento_config_default()["doc_editor"]["layout"])
                if isinstance(doc_saved.get("layout"), dict):
                    layout.update(doc_saved.get("layout"))
                base["doc_editor"]["layout"] = layout
                texts = {}
                texts.update(documento_config_default()["doc_editor"]["texts"])
                if isinstance(doc_saved.get("texts"), dict):
                    texts.update(doc_saved.get("texts"))
                base["doc_editor"]["texts"] = texts
        except Exception:
            pass
    return base


def _pdf_text_lines(canvas_obj, text, max_width, font_name, font_size, max_lines=2):
    words = str(text or "").replace("\n", " ").split()
    lines = []
    current = ""
    def split_long_word(word):
        parts = []
        chunk = ""
        for ch in str(word or ""):
            test = f"{chunk}{ch}"
            if chunk and canvas_obj.stringWidth(test, font_name, font_size) > max_width:
                parts.append(chunk)
                chunk = ch
            else:
                chunk = test
        if chunk:
            parts.append(chunk)
        return parts or [word]
    for word in words:
        expanded = split_long_word(word) if canvas_obj.stringWidth(word, font_name, font_size) > max_width else [word]
        for word in expanded:
            test = f"{current} {word}".strip()
            if canvas_obj.stringWidth(test, font_name, font_size) <= max_width or not current:
                current = test
            else:
                lines.append(current)
                current = word
                if len(lines) >= max_lines:
                    break
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines or [""]


def _pdf_series_items(value):
    seen = set()
    out = []
    for item in re.split(r"[,;\n\r|]+", str(value or "")):
        serie = re.sub(r"^(s\s*/?\s*n|sn|serie)\s*[:\-]?\s*", "", str(item or "").strip(), flags=re.I).strip()
        if not serie:
            continue
        key = re.sub(r"[^A-Z0-9]+", "", serie.upper())
        if key and key not in seen:
            seen.add(key)
            out.append(serie.upper())
    return out


def _pdf_item_row_height(desc_lines_count, series_count, desc_gap, serie_gap, extra_lines=0):
    base = 4.2
    height = base + max(1, desc_lines_count) * desc_gap
    if series_count:
        height += 2.0
        height += series_count * serie_gap
    if extra_lines:
        height += extra_lines * serie_gap
    return max(6.5, height)


def _pdf_money(value):
    try:
        return f"{float(value or 0):.2f}"
    except Exception:
        return "0.00"


def _pdf_words_soles(value):
    try:
        total = float(value or 0)
    except Exception:
        total = 0
    unidades = ["", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE"]
    decenas = {10: "DIEZ", 11: "ONCE", 12: "DOCE", 13: "TRECE", 14: "CATORCE", 15: "QUINCE", 20: "VEINTE", 30: "TREINTA", 40: "CUARENTA", 50: "CINCUENTA", 60: "SESENTA", 70: "SETENTA", 80: "OCHENTA", 90: "NOVENTA"}
    centenas = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]
    def n99(n):
        if n < 10:
            return unidades[n]
        if n in decenas:
            return decenas[n]
        if n < 20:
            return "DIECI" + unidades[n - 10]
        if n < 30:
            return "VEINTI" + unidades[n - 20]
        d = (n // 10) * 10
        u = n % 10
        return decenas[d] + (f" Y {unidades[u]}" if u else "")
    def n999(n):
        if n == 100:
            return "CIEN"
        if n < 100:
            return n99(n)
        return centenas[n // 100] + (f" {n99(n % 100)}" if n % 100 else "")
    entero = int(total)
    cent = int(round((total - entero) * 100))
    if entero == 0:
        words = "CERO"
    elif entero < 1000:
        words = n999(entero)
    elif entero < 1000000:
        miles = entero // 1000
        resto = entero % 1000
        words = "MIL" if miles == 1 else f"{n999(miles)} MIL"
        if resto:
            words += f" {n999(resto)}"
    else:
        words = str(entero)
    return f"SON {words} Y {cent:02d}/100 SOLES"


def _draw_pdf_logo(c, cfg, x, y, w, h, mm_unit, page_h):
    try:
        from reportlab.lib.utils import ImageReader
        logo = str(cfg.get("logo") or cfg.get("document_logo") or "").strip()
        if not logo:
            candidate = os.path.join(WEBAPP_DIR, "army-logo-doc.png")
            logo = candidate if os.path.exists(candidate) else ""
        if not logo:
            return
        if logo.startswith("data:image") and "," in logo:
            raw = base64.b64decode(logo.split(",", 1)[1])
            image = ImageReader(io.BytesIO(raw))
        elif logo.startswith(("http://", "https://")):
            with urllib.request.urlopen(logo, timeout=8) as resp:
                image = ImageReader(io.BytesIO(resp.read()))
        elif os.path.exists(logo):
            image = logo
        else:
            return
        c.drawImage(image, x * mm_unit, page_h - ((y + h) * mm_unit), width=w * mm_unit, height=h * mm_unit, preserveAspectRatio=True, mask="auto")
    except Exception:
        pass


def public_base_url():
    return (os.getenv("PUBLIC_BASE_URL") or os.getenv("APP_PUBLIC_URL") or "https://erp-api-7x3d.onrender.com").rstrip("/")


def public_document_url(documento):
    doc_id = documento.get("id") if isinstance(documento, dict) else None
    if not doc_id:
        return ""
    sucursal = norm_sucursal((documento or {}).get("sucursal") or DEFAULT_SUCURSAL)
    return f"{public_base_url()}/public/documento/{doc_id}?sucursal={urllib.parse.quote(sucursal)}"


def _draw_pdf_qr(c, value, x, y, size, mm_unit, page_h):
    if not value:
        return False
    try:
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderPDF
        qr = QrCodeWidget(value)
        bounds = qr.getBounds()
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        drawing = Drawing(size * mm_unit, size * mm_unit, transform=[
            (size * mm_unit) / width, 0, 0, (size * mm_unit) / height,
            -bounds[0] * (size * mm_unit) / width, -bounds[1] * (size * mm_unit) / height
        ])
        drawing.add(qr)
        renderPDF.draw(drawing, c, x * mm_unit, page_h - ((y + size) * mm_unit))
        return True
    except Exception:
        return False


def generar_pdf_documento_original(documento, detalle, cfg):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    page_w, page_h = A4

    def X(v): return v * mm
    def Y(v): return page_h - (v * mm)
    def font(name="Helvetica", size=8): c.setFont(name, size)
    def txt(x, y, text, size=8, bold=False): font("Helvetica-Bold" if bold else "Helvetica", size); c.drawString(X(x), Y(y), str(text or ""))
    def txt_r(x, y, text, size=8, bold=False): font("Helvetica-Bold" if bold else "Helvetica", size); c.drawRightString(X(x), Y(y), str(text or ""))
    def txt_c(x, y, text, size=8, bold=False): font("Helvetica-Bold" if bold else "Helvetica", size); c.drawCentredString(X(x), Y(y), str(text or ""))
    def rect(x, y, w, h): c.rect(X(x), Y(y + h), X(w), X(h), fill=0, stroke=1)
    def line(x1, y1, x2, y2): c.line(X(x1), Y(y1), X(x2), Y(y2))
    def fit(text, width_mm, font_name="Helvetica", size=7, max_lines=1):
        return _pdf_text_lines(c, str(text or ""), X(width_mm), font_name, size, max_lines)

    doc_type = str(documento.get("tipo") or "DOCUMENTO").upper()
    numero = str(documento.get("numero") or "")
    is_proforma_doc = doc_type == "PROFORMA"
    title = {
        "BOLETA": "BOLETA DE VENTA\nELECTRONICA",
        "FACTURA": "FACTURA\nELECTRONICA",
        "PROFORMA": "COTIZACION",
        "PASE": "PASE",
        "NOTA DE VENTA": "NOTA DE VENTA",
    }.get(doc_type, doc_type)
    editor = cfg.get("doc_editor") if isinstance(cfg.get("doc_editor"), dict) else {}
    # Formato fijo restaurado del respaldo 20260609_123145. No usar medidas guardadas
    # en app_config para evitar que la boleta se mueva entre actualizaciones.
    max_rows = 12

    # Plantilla fija A4 alineada al formato Computer Army usado en PC/Android.
    logo_w = 24
    logo_h = 15
    _draw_pdf_logo(c, cfg, 16, 25, logo_w, logo_h, mm, page_h)

    empresa = str(cfg.get("company_name") or cfg.get("empresa") or "CORPORACION COMPUTER ARMY EIRL").upper()
    direccion = str(cfg.get("address") or cfg.get("direccion") or "").upper()
    slogan = str(cfg.get("mensaje") or "MEJORES PRECIOS EN TARJETAS DE VIDEOS").upper()

    for i, ln in enumerate(fit(empresa, 78, "Helvetica-Bold", 15.8, 2)):
        txt(44, 14.6 + i * 5.2, ln, 15.8, True)
    for i, ln in enumerate(fit(direccion, 82, "Helvetica-Bold", 7.2, 3)):
        txt(44, 26.5 + i * 3.9, ln, 7.2, True)
    txt(44, 43.0, slogan, 7.2, True)

    rect(124, 6, 72, 39)
    txt_c(160, 13.0, f"RUC {cfg.get('ruc') or '20611068701'}", 11.8)
    for i, ln in enumerate(title.split("\n")):
        txt_c(160, 24.5 + i * 5.4, ln, 16.0, True)
    txt_c(160, 40.5, numero, 11.6)

    fecha = str(documento.get("fecha_emision") or documento.get("fecha") or lima_today_iso())[:10]
    venc = str(documento.get("fecha_vencimiento") or "-")[:10] if documento.get("fecha_vencimiento") else "-"
    client_y = 52
    doc_cliente = str(documento.get("documento_cliente") or "").upper()
    cliente = str(documento.get("cliente_nombre") or "USUARIO X").upper()
    direccion_cliente = str(documento.get("direccion_cliente") or "SIN DIRECCION").upper()
    txt(7, client_y, "DOCUMENTO", 7.4, True); txt(42, client_y, doc_cliente, 7.2)
    txt(7, client_y + 5.0, "CLIENTE", 7.4, True)
    for i, ln in enumerate(fit(cliente, 91, "Helvetica", 7.2, 2)):
        txt(42, client_y + 5.0 + i * 3.5, ln, 7.2)
    txt(7, client_y + 10.0, "DIRECCION", 7.4, True)
    for i, ln in enumerate(fit(direccion_cliente, 91, "Helvetica", 7.2, 2)):
        txt(42, client_y + 10.0 + i * 3.5, ln, 7.2)
    txt(124, client_y, "FECHA EMISION", 7.4, True); txt(169, client_y, fecha, 7.2)
    txt(124, client_y + 5.0, "FECHA VENCIMIENTO", 7.4, True); txt(169, client_y + 5.0, venc, 7.2)
    txt(124, client_y + 10.0, "MONEDA", 7.4, True); txt(169, client_y + 10.0, "SOLES", 7.2)

    tx, ty, tw = 7.0, 69.5, 199.0
    header_h = 4.8
    row_h = 6.5
    th = header_h + (row_h * max_rows)
    rect(tx, ty, tw, th)
    c.setFillGray(0); c.rect(X(tx), Y(ty + header_h), X(tw), X(header_h), fill=1, stroke=0); c.setFillGray(1)
    cols = [tx, tx + 8.5, tx + 28.5, tx + 144.0, tx + 160.0, tx + 180.0, tx + tw]
    headers = ["Nro", "UNIDAD", "DESCRIPCION", "CANT.", "TOTAL", "P. UNIT."]
    centers = [(cols[i] + cols[i+1]) / 2 for i in range(len(cols)-1)]
    for idx, h in enumerate(headers):
        txt_c(centers[idx], ty + 3.8, h, 9.4, True)
    c.setFillGray(0)
    for cx in cols[1:-1]:
        line(cx, ty, cx, ty + th)

    row_y = ty + header_h + 4.5
    for idx, item in enumerate((detalle or [])[:max_rows], start=1):
        qty = float(item.get("cantidad") or 0)
        price = float(item.get("precio_unitario") or item.get("precio") or 0)
        total = float(item.get("total") or qty * price)
        desc = str(item.get("descripcion") or item.get("nombre") or "").upper()
        series = str(item.get("series_texto") or item.get("serie") or "").strip()
        series_items = _pdf_series_items(series)
        desc_max = 2 if series_items else 3
        desc_font = 6.8 if series_items else (6.25 if len(desc) > 82 else 7.35)
        desc_gap = 2.35 if series_items else (2.05 if len(desc) > 82 else 2.25)
        serie_font = 6.4 if len(series_items) >= 4 else 6.6
        serie_gap = 3.1 if len(series_items) >= 3 else 3.4
        desc_lines = fit(desc, 108, "Helvetica-Bold", desc_font, desc_max)
        shown = list(series_items)
        overflow = 0
        item_h = _pdf_item_row_height(len(desc_lines), len(shown), desc_gap, serie_gap, overflow)
        remaining_h = (ty + th) - (ty + header_h + 4.5) - (row_y - (ty + header_h + 4.5))
        if item_h > remaining_h and remaining_h > 0:
            compact_gap = max(2.6, serie_gap - 0.5)
            compact_font = max(6.0, serie_font - 0.3)
            while shown and _pdf_item_row_height(len(desc_lines), len(shown), desc_gap, compact_gap, overflow) > remaining_h:
                shown = shown[:-1]
                overflow = len(series_items) - len(shown)
            serie_gap = compact_gap
            serie_font = compact_font
            item_h = _pdf_item_row_height(len(desc_lines), len(shown), desc_gap, serie_gap, overflow)
        txt_c(centers[0], row_y, idx, 8.0)
        txt_c(centers[1], row_y, "UNIDADES", 7.8)
        cursor_y = row_y
        for ln in desc_lines:
            txt(cols[2] + 1.6, cursor_y, ln, desc_font, True)
            cursor_y += desc_gap
        if shown:
            cursor_y += 1.6
            for sidx, serie_line in enumerate(shown):
                prefix = "S/N: " if sidx == 0 else "     "
                for ln in fit(f"{prefix}{serie_line}", 108, "Helvetica", serie_font, 2):
                    txt(cols[2] + 1.6, cursor_y, ln, serie_font)
                    cursor_y += serie_gap
            if overflow:
                txt(cols[2] + 1.6, cursor_y, f"     +{overflow} serie(s) mas", 5.8)
        txt_r(cols[4] - 1.2, row_y, f"{qty:.2f}", 8.0)
        txt_r(cols[5] - 1.2, row_y, _pdf_money(total), 8.0)
        txt_r(cols[6] - 1.2, row_y, _pdf_money(price), 8.0)
        row_y += max(item_h, row_h)

    total_doc = float(documento.get("total") or sum(float(x.get("total") or 0) for x in detalle or []))
    igv_doc = float(documento.get("igv") or 0)
    subtotal_doc = float(documento.get("subtotal") or 0)
    if igv_doc <= 0 or subtotal_doc <= 0 or subtotal_doc >= total_doc:
        subtotal_doc = round(total_doc / 1.18, 2) if total_doc else 0
        igv_doc = round(total_doc - subtotal_doc, 2)
    line(tx, ty + th, tx + tw, ty + th)
    words_y = ty + th + 4.0
    txt_c(tx + tw / 2, words_y, _pdf_words_soles(total_doc), 6.2)
    line(tx, ty + th + 7.2, tx + tw, ty + th + 7.2)

    block_y = ty + th + 7.0
    totals_x, totals_y = 141, block_y
    rect(totals_x, totals_y, 71, 22)
    line(totals_x, totals_y + 7, totals_x + 71, totals_y + 7)
    line(totals_x, totals_y + 14, totals_x + 71, totals_y + 14)
    txt(totals_x + 3, totals_y + 4, "GRAVADO", 10.2, True); txt(totals_x + 36, totals_y + 4, "S/", 10.0); txt_r(totals_x + 68, totals_y + 4, _pdf_money(subtotal_doc), 10.0)
    txt(totals_x + 3, totals_y + 11, "I.G.V. 18%", 10.2, True); txt(totals_x + 36, totals_y + 11, "S/", 10.0); txt_r(totals_x + 68, totals_y + 11, _pdf_money(igv_doc), 10.0)
    txt(totals_x + 3, totals_y + 18, "TOTAL", 10.8, True); txt(totals_x + 36, totals_y + 18, "S/", 10.8, True); txt_r(totals_x + 68, totals_y + 18, _pdf_money(total_doc), 10.8, True)

    info_y = 176
    txt(7.0, info_y, "USUARIO", 7.0, True); txt(65, info_y, f"{documento.get('usuario_emisor') or 'COMPUTER ARMY'} - {fecha}", 6.6)
    condicion_pago = "COTIZACION" if is_proforma_doc else (documento.get("estado_pago") or "CONTADO")
    txt(7.0, info_y + 4.8, "CONDICION DE PAGO", 7.0, True); txt(65, info_y + 4.8, condicion_pago, 6.8)
    txt(65, info_y + 12.0, "CUENTAS BANCARIAS", 6.8, True)
    txt(94, info_y + 12.0, f"Bcp soles :{cfg.get('cuenta_bcp') or '1941066028058'}", 6.5)
    txt(65, info_y + 16.0, "Titular:Computer Army Eirl", 6.5)
    txt(65, info_y + 23.2, f"Interbank soles cuenta corriente : {cfg.get('cuenta_interbank') or '2003005323345'}", 6.3)
    txt(65, info_y + 27.2, "Titular: Computer Army eirl", 6.5)
    qr_url = public_document_url(documento)
    if not _draw_pdf_qr(c, qr_url, 181, info_y + 27, 20, mm, page_h):
        rect(181, info_y + 27, 20, 20)

    legal_y = 216
    if is_proforma_doc:
        txt(5.0, legal_y, "COTIZACION - NO TIENE VALIDEZ TRIBUTARIA", 7.0, True)
        txt(5.0, legal_y + 5, f"VALIDA SOLO POR 48 HORAS HASTA {venc}", 7.0, True)
        txt(5.0, legal_y + 10, "Precios y stock sujetos a confirmacion al emitir boleta/factura.", 6.5)
        txt(5.0, legal_y + 15, PROFORMA_VALIDITY_NOTE, 6.3)
    else:
        txt(5.0, legal_y, "Autorizado mediante resolucion Nro 034-005-0010431/SUNAT", 7.0)
        txt(5.0, legal_y + 5, f"Representacion impresa de la {title.replace(chr(10), ' ')}", 7.0)
        txt(5.0, legal_y + 10, "Para consultar el comprobante visita G&G ERP", 8.6)
        txt(5.0, legal_y + 15, "Resumen", 8.6)
    texts = editor.get("texts") if isinstance(editor.get("texts"), dict) else {}
    wy = 244
    for key in ("garantia_1", "garantia_2", "garantia_3", "garantia_4", "garantia_5", "garantia_6"):
        text = texts.get(key, "")
        if text:
            txt_c(105, wy, text, 9.0)
            wy += 4.3
            if wy > 268:
                break
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


# ================= CLIENTES =================
@app.get("/consulta/documento/{numero}")
def consulta_documento(numero: str, sucursal: str = DEFAULT_SUCURSAL):
    return consulta_documento_impl(numero, sucursal)


@app.get("/consulta/documento")
def consulta_documento_query(numero: str = "", documento: str = "", dni: str = "", ruc: str = "", sucursal: str = DEFAULT_SUCURSAL):
    value = numero or documento or dni or ruc
    return consulta_documento_impl(value, sucursal)


@app.get("/consulta/dni/{dni}")
def consulta_dni(dni: str, sucursal: str = DEFAULT_SUCURSAL):
    return consulta_documento_impl(dni, sucursal)


@app.get("/consulta/ruc/{ruc}")
def consulta_ruc(ruc: str, sucursal: str = DEFAULT_SUCURSAL):
    return consulta_documento_impl(ruc, sucursal)


@app.get("/clientes/{documento}")
def buscar_cliente(documento: str, sucursal: str = DEFAULT_SUCURSAL):
    return consulta_documento_impl(documento, sucursal)


@app.post("/clientes")
def crear_cliente(data: Cliente):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    cur.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS telefono TEXT DEFAULT ''")

    cur.execute("""
    SELECT id FROM clientes
    WHERE numero_documento=%s AND COALESCE(sucursal,%s)=%s
    """, (data.numero_documento, DEFAULT_SUCURSAL, sucursal))
    row = cur.fetchone()
    if row:
        cur.execute("""
        UPDATE clientes
        SET tipo_documento=%s, nombre=%s, direccion=%s, telefono=%s
        WHERE id=%s
        RETURNING id
        """, (data.tipo_documento, data.nombre, data.direccion, data.telefono or "", row[0]))
    else:
        cur.execute("""
        INSERT INTO clientes (tipo_documento,numero_documento,nombre,direccion,telefono,sucursal)
        VALUES (%s,%s,%s,%s,%s,%s)
        RETURNING id
        """, (data.tipo_documento, data.numero_documento, data.nombre, data.direccion, data.telefono or "", sucursal))
    cliente_id = cur.fetchone()[0]

    conn.commit()
    conn.close()

    return {"ok": True, "id": cliente_id}


@app.get("/clientes")
def listar_clientes(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    cur.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS telefono TEXT DEFAULT ''")

    cur.execute("""
    SELECT id, tipo_documento, numero_documento, nombre, direccion, COALESCE(telefono,'') AS telefono, COALESCE(sucursal,%s) AS sucursal
    FROM clientes
    WHERE COALESCE(sucursal,%s)=%s
    ORDER BY id DESC
    """, (DEFAULT_SUCURSAL, DEFAULT_SUCURSAL, sucursal))
    data = dict_fetchall(cur)

    conn.close()

    return data


def asegurar_tabla_servicios(cur):
    cur.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS telefono TEXT DEFAULT ''")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS servicios_tecnicos (
        id SERIAL PRIMARY KEY,
        fecha TIMESTAMP DEFAULT (timezone('America/Lima', now())),
        tipo_documento TEXT DEFAULT 'DNI',
        numero_documento TEXT DEFAULT '',
        cliente_nombre TEXT DEFAULT '',
        telefono TEXT DEFAULT '',
        equipo TEXT DEFAULT '',
        servicio TEXT DEFAULT '',
        diagnostico TEXT DEFAULT '',
        observacion TEXT DEFAULT '',
        precio NUMERIC DEFAULT 0,
        usuario TEXT DEFAULT '',
        estado TEXT DEFAULT 'RECIBIDO',
        sucursal TEXT DEFAULT 'computer_army'
    )
    """)


@app.get("/servicios-tecnicos")
def listar_servicios_tecnicos(q: str = "", sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        asegurar_tabla_servicios(cur)
        texto = f"%{(q or '').lower()}%"
        cur.execute("""
        SELECT id, to_char(fecha, 'YYYY-MM-DD HH24:MI') AS fecha,
               tipo_documento, numero_documento, cliente_nombre, telefono,
               equipo, servicio, diagnostico, observacion, COALESCE(precio,0) AS precio,
               usuario, estado, COALESCE(sucursal,%s) AS sucursal
        FROM servicios_tecnicos
        WHERE COALESCE(sucursal,%s)=%s
          AND (%s='%%'
               OR LOWER(COALESCE(numero_documento,'')) LIKE %s
               OR LOWER(COALESCE(cliente_nombre,'')) LIKE %s
               OR LOWER(COALESCE(telefono,'')) LIKE %s
               OR LOWER(COALESCE(equipo,'')) LIKE %s
               OR LOWER(COALESCE(servicio,'')) LIKE %s)
        ORDER BY id DESC
        LIMIT 200
        """, (DEFAULT_SUCURSAL, DEFAULT_SUCURSAL, sucursal, texto, texto, texto, texto, texto, texto))
        return dict_fetchall(cur)
    finally:
        conn.close()


@app.post("/servicios-tecnicos")
def guardar_servicio_tecnico(data: ServicioTecnico):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(data.sucursal)
        asegurar_tabla_servicios(cur)
        numero = only_digits(data.numero_documento)
        tipo = (data.tipo_documento or ("DNI" if len(numero) == 8 else "RUC" if len(numero) == 11 else "DNI")).upper()
        cliente = (data.cliente_nombre or "CLIENTE SERVICIO").strip().upper()
        telefono = (data.telefono or "").strip()
        if numero:
            cur.execute("""
            INSERT INTO clientes (tipo_documento, numero_documento, nombre, direccion, telefono, sucursal)
            VALUES (%s,%s,%s,'',%s,%s)
            ON CONFLICT DO NOTHING
            """, (tipo, numero, cliente, telefono, sucursal))
            cur.execute("""
            UPDATE clientes
            SET tipo_documento=%s,
                nombre=CASE WHEN %s<>'' THEN %s ELSE nombre END,
                telefono=CASE WHEN %s<>'' THEN %s ELSE COALESCE(telefono,'') END
            WHERE numero_documento=%s AND COALESCE(sucursal,%s)=%s
            """, (tipo, cliente, cliente, telefono, telefono, numero, DEFAULT_SUCURSAL, sucursal))
        cur.execute("""
        INSERT INTO servicios_tecnicos (
            tipo_documento, numero_documento, cliente_nombre, telefono, equipo,
            servicio, diagnostico, observacion, precio, usuario, sucursal
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id, to_char(fecha, 'YYYY-MM-DD HH24:MI')
        """, (
            tipo, numero, cliente, telefono, data.equipo or "", data.servicio or "",
            data.diagnostico or "", data.observacion or "", data.precio or 0,
            data.usuario or "", sucursal,
        ))
        row = cur.fetchone()
        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "id": row[0], "fecha": row[1]}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.post("/reservas")
def crear_reserva(data: ReservaCliente):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    documento = only_digits(data.numero_documento)
    cliente = (data.cliente_nombre or "CLIENTE RESERVA").strip() or "CLIENTE RESERVA"
    producto_nombre = (data.producto_nombre or "").strip()
    producto_id = data.producto_id
    if producto_id and not producto_nombre:
        cur.execute("""
        SELECT COALESCE(nombre,'') FROM productos
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        LIMIT 1
        """, (producto_id, DEFAULT_SUCURSAL, sucursal))
        row = cur.fetchone()
        producto_nombre = row[0] if row else ""
    if not documento:
        conn.close()
        return {"ok": False, "success": False, "msg": "Ingresa DNI/RUC del cliente para controlar la reserva."}
    if not producto_nombre:
        conn.close()
        return {"ok": False, "success": False, "msg": "Selecciona o escribe el producto reservado."}
    cantidad = max(1, int(data.cantidad or 1))
    monto_total = round(float(data.monto_total or 0), 2)
    monto_reserva = round(float(data.monto_reserva or 0), 2)
    saldo = max(0.0, round(monto_total - monto_reserva, 2))
    estado = (data.estado or "RESERVADO").upper()
    if estado not in ("RESERVADO", "PAGADO", "ENTREGADO", "ANULADO"):
        estado = "RESERVADO"
    try:
        comprobantes, comprobante, comprobantes_json = normalizar_comprobantes_pago(data)
    except ValueError as e:
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}
    cur.execute("""
    INSERT INTO reservas_clientes (
        tipo_documento, numero_documento, cliente_nombre, producto_id, producto_nombre,
        cantidad, monto_total, monto_reserva, saldo, estado, observacion, usuario,
        comprobante_pago, comprobante_pago_nombre, comprobante_pago_mime, comprobante_pago_tamano,
        comprobante_pago_base64, comprobante_pago_data_url, comprobantes_pago_json, sucursal
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    RETURNING id, fecha
    """, (
        (data.tipo_documento or "DNI").upper(), documento, cliente, producto_id, producto_nombre,
        cantidad, monto_total, monto_reserva, saldo, estado, data.observacion or "", data.usuario or "",
        comprobante.get("comprobante_pago") or "",
        comprobante.get("comprobante_pago_nombre") or "",
        comprobante.get("comprobante_pago_mime") or "",
        comprobante.get("comprobante_pago_tamano") or 0,
        comprobante.get("comprobante_pago_base64") or "",
        comprobante.get("comprobante_pago_data_url") or "",
        comprobantes_json or "",
        sucursal
    ))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    return {"ok": True, "success": True, "id": row[0], "fecha": row[1], "saldo": saldo}


@app.get("/reservas")
def listar_reservas(documento: str = "", estado: str = "", sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    documento_digits = only_digits(documento)
    estado = (estado or "").upper()
    where = ["COALESCE(sucursal,%s)=%s"]
    params = [DEFAULT_SUCURSAL, sucursal]
    if documento_digits:
        where.append("regexp_replace(COALESCE(numero_documento,''), '\\D', '', 'g')=%s")
        params.append(documento_digits)
    if estado and estado != "TODOS":
        where.append("UPPER(COALESCE(estado,''))=%s")
        params.append(estado)
    cur.execute(f"""
        SELECT id, to_char(fecha, 'YYYY-MM-DD HH24:MI') AS fecha,
               COALESCE(tipo_documento,'DNI') AS tipo_documento,
               COALESCE(numero_documento,'') AS numero_documento,
               COALESCE(cliente_nombre,'') AS cliente_nombre,
               producto_id,
               COALESCE(producto_nombre,'') AS producto_nombre,
               COALESCE(cantidad,1) AS cantidad,
               COALESCE(monto_total,0) AS monto_total,
               COALESCE(monto_reserva,0) AS monto_reserva,
               COALESCE(saldo,0) AS saldo,
               COALESCE(estado,'RESERVADO') AS estado,
               COALESCE(observacion,'') AS observacion,
               COALESCE(usuario,'') AS usuario,
               COALESCE(comprobante_pago_nombre,'') AS comprobante_pago_nombre,
               COALESCE(comprobante_pago_mime,'') AS comprobante_pago_mime,
               COALESCE(comprobante_pago_tamano,0) AS comprobante_pago_tamano,
               COALESCE(comprobantes_pago_json,'') AS comprobantes_pago_json
        FROM reservas_clientes
        WHERE {' AND '.join(where)}
        ORDER BY fecha DESC, id DESC
        LIMIT 200
    """, tuple(params))
    reservas = []
    for row in dict_fetchall(cur):
        item = _jsonable_row(row)
        item["comprobantes_pago"] = comprobantes_metadata_liviana(item.get("comprobantes_pago_json"))
        item["comprobantes_pago_count"] = len(item["comprobantes_pago"])
        item["comprobantes_pago_json"] = ""
        reservas.append(item)
    documentos = []
    if documento_digits:
        cur.execute("""
            SELECT id, tipo, numero, COALESCE(cliente,'') AS cliente_nombre,
                   COALESCE(documento_cliente,'') AS documento_cliente,
                   COALESCE(total,0) AS total,
                   COALESCE(estado_pago,'PAGADO') AS estado_pago,
                   to_char(fecha, 'YYYY-MM-DD HH24:MI') AS fecha
            FROM ventas
            WHERE regexp_replace(COALESCE(documento_cliente,''), '\\D', '', 'g')=%s
              AND COALESCE(sucursal,%s)=%s
            ORDER BY fecha DESC, id DESC
            LIMIT 100
        """, (documento_digits, DEFAULT_SUCURSAL, sucursal))
        documentos = [_jsonable_row(row) for row in dict_fetchall(cur)]
    conn.close()
    return {"ok": True, "success": True, "data": reservas, "reservas": reservas, "documentos": documentos}


@app.get("/reservas/{reserva_id}")
def detalle_reserva(reserva_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
        SELECT id, to_char(fecha, 'YYYY-MM-DD HH24:MI') AS fecha,
               COALESCE(tipo_documento,'DNI') AS tipo_documento,
               COALESCE(numero_documento,'') AS numero_documento,
               COALESCE(cliente_nombre,'') AS cliente_nombre,
               producto_id,
               COALESCE(producto_nombre,'') AS producto_nombre,
               COALESCE(cantidad,1) AS cantidad,
               COALESCE(monto_total,0) AS monto_total,
               COALESCE(monto_reserva,0) AS monto_reserva,
               COALESCE(saldo,0) AS saldo,
               COALESCE(estado,'RESERVADO') AS estado,
               COALESCE(observacion,'') AS observacion,
               COALESCE(usuario,'') AS usuario,
               COALESCE(comprobante_pago,'') AS comprobante_pago,
               COALESCE(comprobante_pago_nombre,'') AS comprobante_pago_nombre,
               COALESCE(comprobante_pago_mime,'') AS comprobante_pago_mime,
               COALESCE(comprobante_pago_tamano,0) AS comprobante_pago_tamano,
               COALESCE(comprobante_pago_base64,'') AS comprobante_pago_base64,
               COALESCE(comprobante_pago_data_url,'') AS comprobante_pago_data_url,
               COALESCE(comprobantes_pago_json,'') AS comprobantes_pago_json
        FROM reservas_clientes
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        LIMIT 1
    """, (reserva_id, DEFAULT_SUCURSAL, sucursal))
    row = dict_fetchone(cur)
    conn.close()
    if not row:
        return {"ok": False, "success": False, "msg": "Reserva no encontrada."}
    row = _jsonable_row(row)
    row["comprobantes_pago"] = cargar_comprobantes_json(row.get("comprobantes_pago_json"))
    return {"ok": True, "success": True, "data": row, "reserva": row}


@app.put("/reservas/{reserva_id}")
def actualizar_reserva(reserva_id: int, data: dict):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.get("sucursal") or DEFAULT_SUCURSAL)
    estado = str(data.get("estado") or "RESERVADO").upper()
    if estado not in ("RESERVADO", "PAGADO", "ENTREGADO", "ANULADO"):
        estado = "RESERVADO"
    monto_total = data.get("monto_total")
    monto_reserva = data.get("monto_reserva")
    observacion = str(data.get("observacion") or "")
    tipo_documento = str(data.get("tipo_documento") or "").upper().strip()
    numero_documento = only_digits(data.get("numero_documento") or "")
    cliente_nombre = str(data.get("cliente_nombre") or "").strip()
    producto_nombre = str(data.get("producto_nombre") or "").strip()
    producto_id = data.get("producto_id")
    cantidad = data.get("cantidad")
    try:
        producto_id = int(producto_id) if str(producto_id or "").strip() else None
    except Exception:
        producto_id = None
    try:
        cantidad = max(1, int(float(cantidad))) if cantidad not in (None, "") else None
    except Exception:
        cantidad = None
    cur.execute("""
        SELECT COALESCE(monto_total,0), COALESCE(monto_reserva,0),
               COALESCE(comprobantes_pago_json,'')
        FROM reservas_clientes
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        LIMIT 1
    """, (reserva_id, DEFAULT_SUCURSAL, sucursal))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "success": False, "msg": "Reserva no encontrada."}
    total = round(float(monto_total if monto_total not in (None, "") else row[0] or 0), 2)
    reservado = round(float(monto_reserva if monto_reserva not in (None, "") else row[1] or 0), 2)
    saldo = max(0.0, round(total - reservado, 2))
    try:
        comprobantes, comprobante, comprobantes_json = normalizar_comprobantes_pago(data, row[2] or "")
    except ValueError as e:
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}
    cur.execute("""
        UPDATE reservas_clientes
        SET estado=%s, monto_total=%s, monto_reserva=%s, saldo=%s,
            tipo_documento=CASE WHEN %s <> '' THEN %s ELSE COALESCE(tipo_documento,'DNI') END,
            numero_documento=CASE WHEN %s <> '' THEN %s ELSE COALESCE(numero_documento,'') END,
            cliente_nombre=CASE WHEN %s <> '' THEN %s ELSE COALESCE(cliente_nombre,'') END,
            producto_id=COALESCE(%s, producto_id),
            producto_nombre=CASE WHEN %s <> '' THEN %s ELSE COALESCE(producto_nombre,'') END,
            cantidad=COALESCE(%s, cantidad, 1),
            observacion=CASE WHEN %s <> '' THEN %s ELSE COALESCE(observacion,'') END,
            comprobante_pago=COALESCE(%s, comprobante_pago, ''),
            comprobante_pago_nombre=COALESCE(%s, comprobante_pago_nombre, ''),
            comprobante_pago_mime=COALESCE(%s, comprobante_pago_mime, ''),
            comprobante_pago_tamano=COALESCE(%s, comprobante_pago_tamano, 0),
            comprobante_pago_base64=COALESCE(%s, comprobante_pago_base64, ''),
            comprobante_pago_data_url=COALESCE(%s, comprobante_pago_data_url, ''),
            comprobantes_pago_json=COALESCE(%s, comprobantes_pago_json, '')
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (
        estado, total, reservado, saldo,
        tipo_documento, tipo_documento,
        numero_documento, numero_documento,
        cliente_nombre, cliente_nombre,
        producto_id,
        producto_nombre, producto_nombre,
        cantidad,
        observacion, observacion,
        comprobante.get("comprobante_pago"),
        comprobante.get("comprobante_pago_nombre"),
        comprobante.get("comprobante_pago_mime"),
        comprobante.get("comprobante_pago_tamano"),
        comprobante.get("comprobante_pago_base64"),
        comprobante.get("comprobante_pago_data_url"),
        comprobantes_json,
        reserva_id, DEFAULT_SUCURSAL, sucursal
    ))
    conn.commit()
    conn.close()
    return {"ok": True, "success": True, "id": reserva_id, "saldo": saldo, "estado": estado}


# ================= PRODUCTOS =================
def ensure_producto_web_columns(cur):
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS observacion TEXT DEFAULT ''")
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS sku_woo TEXT DEFAULT ''")
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS categoria_web TEXT DEFAULT ''")
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS subcategoria_web TEXT DEFAULT ''")
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS woo_categoria_id INT")
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS woo_subcategoria_id INT")


@app.post("/productos")
def crear_producto(data: Producto):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = inventario_sucursal(data.sucursal)
    ensure_producto_web_columns(cur)

    cur.execute("""
    INSERT INTO productos (
        nombre,categoria,marca,modelo,precio_compra,precio_venta,stock,imagen_url,observacion,almacen,sucursal,sku_woo,
        categoria_web,subcategoria_web,woo_categoria_id,woo_subcategoria_id
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    RETURNING id
    """, (
        data.nombre, data.categoria, data.marca, data.modelo, data.precio_compra,
        data.precio_venta, data.stock, data.imagen_url or "", data.observacion or "",
        (data.almacen or "TIENDA").strip().upper(), sucursal, (data.sku_woo or "").strip().upper(),
        (data.categoria_web or "").strip(), (data.subcategoria_web or "").strip(),
        int(data.woo_categoria_id or 0), int(data.woo_subcategoria_id or 0),
    ))
    producto_id = cur.fetchone()[0]

    conn.commit()
    conn.close()

    woo_sync = maybe_sync_new_product_to_woo(producto_id, sucursal=sucursal)
    return {"ok": True, "id": producto_id, "woo_sync": woo_sync}


@app.get("/productos")
def listar_productos(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal_real = norm_sucursal(sucursal)
    sucursal = inventario_sucursal(sucursal_real)
    ensure_producto_web_columns(cur)
    cur.execute("""
    UPDATE productos p
    SET stock = (
        SELECT COUNT(*)
        FROM producto_series ps
        WHERE ps.producto_id = p.id
          AND COALESCE(ps.sucursal,%s)=%s
          AND UPPER(COALESCE(ps.estado,'DISPONIBLE')) IN ('DISPONIBLE','RESERVADO')
    )
    WHERE COALESCE(p.sucursal,%s)=%s
      AND EXISTS (
        SELECT 1
        FROM producto_series ps
        WHERE ps.producto_id = p.id
          AND COALESCE(ps.sucursal,%s)=%s
      )
    """, (DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal))

    cur.execute("""
    SELECT id, nombre, categoria, marca, modelo, precio_compra, precio_venta, stock,
           COALESCE(imagen_url, '') AS imagen_url,
           COALESCE(observacion, '') AS observacion,
           COALESCE(almacen, 'TIENDA') AS almacen,
           COALESCE(sku_woo, '') AS sku_woo,
           COALESCE(categoria_web, '') AS categoria_web,
           COALESCE(subcategoria_web, '') AS subcategoria_web,
           COALESCE(woo_categoria_id, 0) AS woo_categoria_id,
           COALESCE(woo_subcategoria_id, 0) AS woo_subcategoria_id,
           %s AS sucursal,
           COALESCE(sucursal,%s) AS inventario_sucursal
    FROM productos
    WHERE COALESCE(sucursal,%s)=%s
    ORDER BY nombre
    """, (sucursal_real, DEFAULT_SUCURSAL, DEFAULT_SUCURSAL, sucursal))
    data = dict_fetchall(cur)

    conn.commit()
    conn.close()

    return data


@app.put("/productos/{producto_id}")
def actualizar_producto(producto_id: int, data: Producto, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = inventario_sucursal(data.sucursal or sucursal)
    try:
        ensure_producto_web_columns(cur)
        cur.execute("""
        UPDATE productos
        SET nombre=%s, categoria=%s, marca=%s, modelo=%s,
            precio_compra=%s, precio_venta=%s, stock=%s, imagen_url=%s, observacion=%s, almacen=%s, sku_woo=%s,
            categoria_web=%s, subcategoria_web=%s, woo_categoria_id=%s, woo_subcategoria_id=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id
        """, (
            data.nombre, data.categoria, data.marca, data.modelo,
            data.precio_compra, data.precio_venta, data.stock, data.imagen_url or "", data.observacion or "",
            (data.almacen or "TIENDA").strip().upper(), (data.sku_woo or "").strip().upper(),
            (data.categoria_web or "").strip(), (data.subcategoria_web or "").strip(),
            int(data.woo_categoria_id or 0), int(data.woo_subcategoria_id or 0),
            producto_id, DEFAULT_SUCURSAL, sucursal
        ))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "success": False, "msg": "Producto no encontrado"}
        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "id": row[0]}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.patch("/productos/{producto_id}/precio-venta")
def actualizar_precio_venta_producto(producto_id: int, data: ProductoPrecioVentaUpdate, sucursal: str = DEFAULT_SUCURSAL):
    if not usuario_puede_editar_precio_venta(data.model_dump() if hasattr(data, "model_dump") else data.dict()):
        return {"ok": False, "success": False, "msg": "Solo Giomar puede actualizar precios desde ventas."}
    conn = get_conn()
    cur = conn.cursor()
    sucursal = inventario_sucursal(data.sucursal or sucursal)
    try:
        precio = round(max(0, float(data.precio_venta or 0)), 2)
        cur.execute("""
        UPDATE productos
        SET precio_venta=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id, nombre, precio_venta
        """, (precio, producto_id, DEFAULT_SUCURSAL, sucursal))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "success": False, "msg": "Producto no encontrado."}
        usuario = str(data.usuario or "giomar").strip() or "giomar"
        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,'',%s,'PRECIO VENTA',%s)
        """, (
            usuario,
            sucursal,
            json.dumps({
                "producto_id": row[0],
                "nombre": row[1],
                "precio_venta": float(row[2] or 0),
                "origen": "ventas",
            }, ensure_ascii=False),
        ))
        conn.commit()
        return {
            "ok": True,
            "success": True,
            "id": row[0],
            "nombre": row[1],
            "precio_venta": float(row[2] or 0),
        }
    except Exception as e:
        conn.rollback()
        return {"ok": False, "success": False, "msg": str(e)}
    finally:
        conn.close()


@app.get("/public/producto/{producto_id}/imagen")
@app.get("/productos/{producto_id}/imagen")
def servir_imagen_producto(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(imagen_url,'') AS imagen_url
        FROM productos
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (producto_id, DEFAULT_SUCURSAL, sucursal))
    row = dict_fetchone(cur)
    conn.close()
    if not row:
        return Response("Imagen no encontrada", status_code=404, media_type="text/plain")
    imagen_url = str(row.get("imagen_url") or "").strip()
    if not imagen_url:
        return Response("Sin imagen", status_code=404, media_type="text/plain")
    if imagen_url.startswith(("http://", "https://")):
        return Response(status_code=302, headers={"Location": imagen_url})
    raw, mime = parse_data_image_url(imagen_url)
    if not raw:
        return Response("Imagen invalida", status_code=404, media_type="text/plain")
    return Response(content=raw, media_type=mime or "image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.delete("/productos/{producto_id}")
def eliminar_producto(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = inventario_sucursal(sucursal)
    try:
        cur.execute("DELETE FROM producto_series WHERE producto_id=%s AND COALESCE(sucursal,%s)=%s", (producto_id, DEFAULT_SUCURSAL, sucursal))
        cur.execute("DELETE FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s RETURNING id", (producto_id, DEFAULT_SUCURSAL, sucursal))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "success": False, "msg": "Producto no encontrado"}
        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "id": row[0]}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.get("/series")
def listar_series(q: str = "", sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = inventario_sucursal(sucursal)
    texto = f"%{(q or '').lower()}%"
    serie_norm = re.sub(r"[^A-Z0-9]", "", str(q or "").upper())
    cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
    cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS usuario_ingreso TEXT DEFAULT ''")
    cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    cur.execute("""
    SELECT
        ps.id,
        ps.producto_id,
        p.nombre AS producto_nombre,
        p.marca,
        p.modelo,
        ps.serie,
        ps.proveedor,
        ps.estado,
        COALESCE(ps.almacen, 'TIENDA') AS almacen,
        COALESCE(ps.usuario_ingreso, '') AS usuario_ingreso,
        ps.fecha_ingreso,
        ps.fecha_salida,
        ps.creado_en
    FROM producto_series ps
    LEFT JOIN productos p ON p.id = ps.producto_id AND COALESCE(p.sucursal,%s)=%s
    WHERE COALESCE(ps.sucursal,%s)=%s
      AND (%s = '%%'
       OR LOWER(COALESCE(ps.serie,'')) LIKE %s
       OR (%s <> '' AND regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g') = %s)
       OR LOWER(COALESCE(ps.proveedor,'')) LIKE %s
       OR LOWER(COALESCE(ps.almacen,'')) LIKE %s
       OR LOWER(COALESCE(ps.estado,'')) LIKE %s
       OR LOWER(COALESCE(p.nombre,'')) LIKE %s
       OR LOWER(COALESCE(p.marca,'')) LIKE %s
       OR LOWER(COALESCE(p.modelo,'')) LIKE %s)
    ORDER BY ps.id DESC
    """, (DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal, texto, texto, serie_norm, serie_norm, texto, texto, texto, texto, texto, texto))
    data = dict_fetchall(cur)
    conn.close()
    return data


@app.get("/series/duplicadas")
def listar_series_duplicadas(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = inventario_sucursal(sucursal)
        cur.execute("""
        WITH normalizadas AS (
            SELECT
                UPPER(TRIM(COALESCE(ps.serie,''))) AS serie_norm,
                ps.id,
                ps.serie,
                ps.producto_id,
                COALESCE(p.nombre,'') AS producto_nombre,
                COALESCE(ps.estado,'') AS estado,
                COALESCE(ps.proveedor,'') AS proveedor
            FROM producto_series ps
            LEFT JOIN productos p ON p.id=ps.producto_id AND COALESCE(p.sucursal,%s)=%s
            WHERE COALESCE(ps.sucursal,%s)=%s
              AND TRIM(COALESCE(ps.serie,''))<>''
        ),
        repetidas AS (
            SELECT serie_norm
            FROM normalizadas
            GROUP BY serie_norm
            HAVING COUNT(DISTINCT producto_id) > 1 OR COUNT(*) > 1
        )
        SELECT n.*
        FROM normalizadas n
        INNER JOIN repetidas r ON r.serie_norm=n.serie_norm
        ORDER BY n.serie_norm, n.producto_nombre
        """, (DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal))
        return dict_fetchall(cur)
    finally:
        conn.close()


@app.post("/series")
def guardar_serie_producto(data: SerieProducto):
    usuario_op = str(data.usuario_ingreso or "").strip()
    if not usuario_puede_editar_series({"usuario_ingreso": usuario_op, "usuario": usuario_op}):
        return {"ok": False, "msg": "Solo giomar y mily pueden ingresar, editar o eliminar series."}
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = inventario_sucursal(data.sucursal)
        series = split_series_text(data.serie)
        almacen = (data.almacen or "TIENDA").strip().upper()
        if not series:
            conn.close()
            return {"ok": False, "msg": "La serie no puede estar vacia"}

        cur.execute("SELECT stock, nombre FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s", (data.producto_id, DEFAULT_SUCURSAL, sucursal))
        producto = cur.fetchone()
        if not producto:
            conn.close()
            return {"ok": False, "msg": "Producto no encontrado"}
        prod_nombre = producto[1] or f"ID {data.producto_id}"

        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS usuario_ingreso TEXT DEFAULT ''")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        serie_ids = []
        series_nuevas = []
        series_actualizadas = []
        for serie in series:
            cur.execute("""
            SELECT id
            FROM producto_series
            WHERE producto_id=%s
              AND COALESCE(sucursal,%s)=%s
              AND regexp_replace(UPPER(COALESCE(serie,'')), '[^A-Z0-9]', '', 'g')=%s
            LIMIT 1
            """, (data.producto_id, DEFAULT_SUCURSAL, sucursal, serie))
            existing = cur.fetchone()
            if existing:
                cur.execute("""
                UPDATE producto_series
                SET proveedor=%s,
                    estado=%s,
                    almacen=%s,
                    fecha_ingreso=%s,
                    fecha_salida=%s,
                    usuario_ingreso=CASE WHEN %s<>'' THEN %s ELSE COALESCE(usuario_ingreso,'') END
                WHERE id=%s
                RETURNING id
                """, (
                    data.proveedor, data.estado, almacen,
                    data.fecha_ingreso or lima_today_iso(), data.fecha_salida,
                    data.usuario_ingreso or "", data.usuario_ingreso or "", existing[0]
                ))
                series_actualizadas.append(serie)
            else:
                cur.execute("""
                INSERT INTO producto_series (
                    producto_id, serie, proveedor, estado, almacen, fecha_ingreso, fecha_salida, sucursal, usuario_ingreso
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
                """, (
                    data.producto_id, serie, data.proveedor, data.estado, almacen,
                    data.fecha_ingreso or lima_today_iso(), data.fecha_salida, sucursal, data.usuario_ingreso or ""
                ))
                series_nuevas.append(serie)
            serie_ids.append(cur.fetchone()[0])

        estado_serie = (data.estado or "").upper()
        if estado_serie == "AGOTADO":
            cur.execute("""
            UPDATE productos
            SET stock = 0
            WHERE id=%s AND COALESCE(sucursal,%s)=%s
            """, (data.producto_id, DEFAULT_SUCURSAL, sucursal))
        elif estado_serie == "DISPONIBLE":
            cur.execute("""
            UPDATE productos
            SET stock = (
                SELECT COUNT(*) FROM producto_series
                WHERE producto_id=%s AND COALESCE(sucursal,%s)=%s AND UPPER(COALESCE(estado,''))='DISPONIBLE'
            )
            WHERE id=%s AND COALESCE(sucursal,%s)=%s
            """, (data.producto_id, DEFAULT_SUCURSAL, sucursal, data.producto_id, DEFAULT_SUCURSAL, sucursal))

        conn.commit()

        accion_audit = "SERIES_INGRESO" if series_nuevas and not series_actualizadas else "SERIES_ACTUALIZAR" if series_actualizadas and not series_nuevas else "SERIES_INGRESO_ACTUALIZAR"
        registrar_auditoria_mercaderia(
            cur,
            usuario=usuario_op,
            sucursal=sucursal,
            accion=accion_audit,
            detalle=(
                f"Usuario={usuario_op or 'SISTEMA'} | Producto={prod_nombre} (ID {data.producto_id}) | "
                f"Nuevas={len(series_nuevas)} [{_resumen_lista_auditoria(series_nuevas)}] | "
                f"Actualizadas={len(series_actualizadas)} [{_resumen_lista_auditoria(series_actualizadas)}] | "
                f"Estado={data.estado} | Almacen={almacen} | Proveedor={data.proveedor or '-'}"
            ),
        )

        conn.close()
        return {"ok": True, "success": True, "id": serie_ids[0], "ids": serie_ids, "series_guardadas": series}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        return {"ok": False, "msg": str(e)}


@app.put("/series/{serie_id}")
def actualizar_serie_producto(serie_id: int, data: SerieProducto, sucursal: str = DEFAULT_SUCURSAL):
    usuario_op = str(data.usuario_ingreso or "").strip()
    if not usuario_puede_editar_series({"usuario_ingreso": usuario_op, "usuario": usuario_op}):
        return {"ok": False, "msg": "Solo giomar y mily pueden ingresar, editar o eliminar series."}
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = inventario_sucursal(data.sucursal or sucursal)
        series = split_series_text(data.serie)
        almacen = (data.almacen or "TIENDA").strip().upper()
        if not series:
            conn.close()
            return {"ok": False, "msg": "La serie no puede estar vacia"}

        cur.execute("""
        SELECT ps.producto_id,
               COALESCE(ps.serie,'') AS serie,
               COALESCE(ps.estado,'DISPONIBLE') AS estado,
               COALESCE(ps.almacen,'TIENDA') AS almacen,
               COALESCE(ps.proveedor,'') AS proveedor,
               COALESCE(p.nombre,'') AS producto_nombre
        FROM producto_series ps
        LEFT JOIN productos p ON p.id=ps.producto_id AND COALESCE(p.sucursal,%s)=%s
        WHERE ps.id=%s AND COALESCE(ps.sucursal,%s)=%s
        """, (DEFAULT_SUCURSAL, sucursal, serie_id, DEFAULT_SUCURSAL, sucursal))
        old_row = dict_fetchone(cur)
        if not old_row:
            conn.close()
            return {"ok": False, "msg": "Serie no encontrada"}
        producto_anterior = old_row.get("producto_id")

        cur.execute("SELECT id FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s", (data.producto_id, DEFAULT_SUCURSAL, sucursal))
        if not cur.fetchone():
            conn.close()
            return {"ok": False, "msg": "Producto no encontrado"}

        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS usuario_ingreso TEXT DEFAULT ''")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        serie = series[0]
        cur.execute("""
        SELECT ps.id,
               ps.producto_id,
               COALESCE(p.nombre,'') AS producto_nombre
        FROM producto_series ps
        LEFT JOIN productos p ON p.id=ps.producto_id AND COALESCE(p.sucursal,%s)=%s
        WHERE regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g')=%s
          AND COALESCE(ps.sucursal,%s)=%s
          AND ps.id<>%s
          AND COALESCE(ps.producto_id,0)=%s
        LIMIT 1
        """, (DEFAULT_SUCURSAL, sucursal, serie, DEFAULT_SUCURSAL, sucursal, serie_id, data.producto_id))
        duplicada = dict_fetchone(cur)
        if duplicada:
            conn.close()
            return {"ok": False, "success": False, "msg": f"La serie {serie} ya existe en este producto.", "duplicada": duplicada}
        cur.execute("""
        UPDATE producto_series
        SET producto_id=%s,
            serie=%s,
            proveedor=%s,
            estado=%s,
            almacen=%s,
            fecha_ingreso=%s,
            fecha_salida=%s,
            usuario_ingreso=CASE WHEN %s<>'' THEN %s ELSE COALESCE(usuario_ingreso,'') END,
            sucursal=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id
        """, (
            data.producto_id, serie, data.proveedor, data.estado, almacen,
            data.fecha_ingreso or lima_today_iso(), data.fecha_salida,
            data.usuario_ingreso or "", data.usuario_ingreso or "", sucursal,
            serie_id, DEFAULT_SUCURSAL, sucursal
        ))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "msg": "Serie no encontrada"}

        estado_serie = (data.estado or "").upper()
        for producto_id in {producto_anterior, data.producto_id}:
            if producto_id == data.producto_id and estado_serie == "AGOTADO":
                cur.execute("""
                UPDATE productos
                SET stock = 0
                WHERE id=%s AND COALESCE(sucursal,%s)=%s
                """, (producto_id, DEFAULT_SUCURSAL, sucursal))
            else:
                cur.execute("""
                UPDATE productos
                SET stock = (
                    SELECT COUNT(*) FROM producto_series
                    WHERE producto_id=%s AND COALESCE(sucursal,%s)=%s AND UPPER(COALESCE(estado,''))='DISPONIBLE'
                )
                WHERE id=%s AND COALESCE(sucursal,%s)=%s
                """, (producto_id, DEFAULT_SUCURSAL, sucursal, producto_id, DEFAULT_SUCURSAL, sucursal))

        conn.commit()

        cur.execute("SELECT COALESCE(nombre,'') FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s", (data.producto_id, DEFAULT_SUCURSAL, sucursal))
        prod_row = cur.fetchone()
        prod_nombre = (prod_row[0] if prod_row else "") or f"ID {data.producto_id}"
        registrar_auditoria_mercaderia(
            cur,
            usuario=usuario_op,
            sucursal=sucursal,
            accion="SERIES_EDITAR",
            detalle=(
                f"Usuario={usuario_op or 'SISTEMA'} | SerieID={serie_id} | "
                f"Antes: {old_row.get('serie')} / {old_row.get('estado')} / {old_row.get('almacen')} / {old_row.get('proveedor') or '-'} / "
                f"Producto={old_row.get('producto_nombre') or producto_anterior} | "
                f"Despues: {serie} / {data.estado} / {almacen} / {data.proveedor or '-'} / Producto={prod_nombre} (ID {data.producto_id})"
            ),
        )

        conn.close()
        return {"ok": True, "success": True, "id": serie_id, "series_guardadas": [serie]}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        return {"ok": False, "msg": str(e)}


@app.delete("/series/{serie_id}")
def eliminar_serie_producto(serie_id: int, sucursal: str = DEFAULT_SUCURSAL, usuario: str = ""):
    if not usuario_puede_editar_series({"usuario": usuario, "usuario_ingreso": usuario}):
        return {"ok": False, "msg": "Solo giomar y mily pueden ingresar, editar o eliminar series."}
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = inventario_sucursal(sucursal)
        cur.execute("""
        SELECT ps.producto_id,
               COALESCE(ps.serie,'') AS serie,
               COALESCE(ps.estado,'DISPONIBLE') AS estado,
               COALESCE(ps.almacen,'TIENDA') AS almacen,
               COALESCE(ps.proveedor,'') AS proveedor,
               COALESCE(p.nombre,'') AS producto_nombre
        FROM producto_series ps
        LEFT JOIN productos p ON p.id=ps.producto_id AND COALESCE(p.sucursal,%s)=%s
        WHERE ps.id=%s AND COALESCE(ps.sucursal,%s)=%s
        """, (DEFAULT_SUCURSAL, sucursal, serie_id, DEFAULT_SUCURSAL, sucursal))
        old_row = dict_fetchone(cur)
        if not old_row:
            conn.close()
            return {"ok": False, "msg": "Serie no encontrada"}
        producto_id = old_row.get("producto_id")
        cur.execute("""
        DELETE FROM producto_series
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (serie_id, DEFAULT_SUCURSAL, sucursal))
        cur.execute("""
        UPDATE productos
        SET stock = (
            SELECT COUNT(*) FROM producto_series
            WHERE producto_id=%s AND COALESCE(sucursal,%s)=%s AND UPPER(COALESCE(estado,''))='DISPONIBLE'
        )
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (producto_id, DEFAULT_SUCURSAL, sucursal, producto_id, DEFAULT_SUCURSAL, sucursal))
        conn.commit()
        registrar_auditoria_mercaderia(
            cur,
            usuario=usuario,
            sucursal=sucursal,
            accion="SERIES_ELIMINAR",
            detalle=(
                f"Usuario={usuario or 'SISTEMA'} | SerieID={serie_id} | Serie={old_row.get('serie')} | "
                f"Estado={old_row.get('estado')} | Almacen={old_row.get('almacen')} | "
                f"Producto={old_row.get('producto_nombre') or producto_id} (ID {producto_id})"
            ),
        )
        conn.close()
        return {"ok": True, "success": True, "id": serie_id}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        return {"ok": False, "msg": str(e)}


def resumen_inventario_conteo(cur, conteo_id, sucursal):
    cur.execute("""
    SELECT id, categoria, usuario, sucursal, estado, creado_en, cerrado_en
    FROM inventario_conteos
    WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (conteo_id, DEFAULT_SUCURSAL, sucursal))
    conteo = dict_fetchone(cur)
    if not conteo:
        return None
    categoria = str(conteo.get("categoria") or "").strip()
    cur.execute("""
    SELECT ps.id, ps.producto_id, COALESCE(p.nombre,'') AS producto_nombre,
           COALESCE(p.categoria,'') AS categoria, ps.serie, COALESCE(ps.estado,'DISPONIBLE') AS estado
    FROM producto_series ps
    LEFT JOIN productos p ON p.id=ps.producto_id
    WHERE COALESCE(ps.sucursal,%s)=%s
      AND (%s='' OR LOWER(COALESCE(p.categoria,''))=LOWER(%s))
      AND UPPER(COALESCE(ps.estado,'DISPONIBLE')) IN ('DISPONIBLE','RESERVADO')
    ORDER BY p.nombre, ps.serie
    """, (DEFAULT_SUCURSAL, sucursal, categoria, categoria))
    esperadas = dict_fetchall(cur)
    cur.execute("""
    SELECT id, serie, producto_id, producto_nombre, estado, usuario, creado_en
    FROM inventario_conteo_scans
    WHERE conteo_id=%s
    ORDER BY id DESC
    """, (conteo_id,))
    scans = dict_fetchall(cur)
    ok_series = {str(s.get("serie") or "").upper() for s in scans if str(s.get("estado") or "").upper() == "OK"}
    faltantes = [s for s in esperadas if str(s.get("serie") or "").upper() not in ok_series]
    por_producto = {}
    for item in esperadas:
        pid = str(item.get("producto_id") or "")
        row = por_producto.setdefault(pid, {
            "producto_id": item.get("producto_id"),
            "producto_nombre": item.get("producto_nombre"),
            "categoria": item.get("categoria"),
            "sistema": 0,
            "fisico": 0,
            "diferencia": 0,
        })
        row["sistema"] += 1
    for item in scans:
        if str(item.get("estado") or "").upper() != "OK":
            continue
        pid = str(item.get("producto_id") or "")
        row = por_producto.setdefault(pid, {
            "producto_id": item.get("producto_id"),
            "producto_nombre": item.get("producto_nombre"),
            "categoria": categoria,
            "sistema": 0,
            "fisico": 0,
            "diferencia": 0,
        })
        row["fisico"] += 1
    for row in por_producto.values():
        row["diferencia"] = int(row.get("fisico") or 0) - int(row.get("sistema") or 0)
    scans_json = [_jsonable_row(x) for x in scans]
    faltantes_json = [_jsonable_row(x) for x in faltantes]
    return {
        "ok": True,
        "success": True,
        "conteo": _jsonable_row(conteo),
        "resumen": {
            "sistema": len(esperadas),
            "fisico": len(ok_series),
            "faltantes": len(faltantes),
            "errores": len([s for s in scans if str(s.get("estado") or "").upper() != "OK"]),
        },
        "productos": list(por_producto.values()),
        "scans": scans_json,
        "faltantes": faltantes_json,
    }


@app.post("/inventario/conteos")
def crear_inventario_conteo(data: InventarioConteoCreate):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(data.sucursal)
        categoria = (data.categoria or "").strip()
        if not categoria or categoria.upper() == "TODAS":
            conn.close()
            return {"ok": False, "success": False, "msg": "Selecciona una categoria para comenzar inventario."}
        cur.execute("""
        INSERT INTO inventario_conteos (categoria, usuario, sucursal, estado)
        VALUES (%s,%s,%s,'ABIERTO')
        RETURNING id
        """, (categoria, data.usuario or "", sucursal))
        conteo_id = cur.fetchone()[0]
        conn.commit()
        result = resumen_inventario_conteo(cur, conteo_id, sucursal)
        conn.close()
        return result
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.get("/inventario/conteos/{conteo_id}")
def obtener_inventario_conteo(conteo_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        result = resumen_inventario_conteo(cur, conteo_id, sucursal)
        conn.close()
        return result or {"ok": False, "success": False, "msg": "Conteo no encontrado"}
    except Exception as e:
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.post("/inventario/conteos/{conteo_id}/scan")
def escanear_inventario_conteo(conteo_id: int, data: InventarioConteoScan, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        serie = normalize_serie_key(data.serie)
        if not serie:
            conn.close()
            return {"ok": False, "success": False, "msg": "Escanea o ingresa una serie."}
        cur.execute("""
        SELECT id, categoria, estado
        FROM inventario_conteos
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (conteo_id, DEFAULT_SUCURSAL, sucursal))
        conteo = dict_fetchone(cur)
        if not conteo:
            conn.close()
            return {"ok": False, "success": False, "msg": "Conteo no encontrado."}
        if str(conteo.get("estado") or "").upper() != "ABIERTO":
            conn.close()
            return {"ok": False, "success": False, "msg": "Este inventario ya esta cerrado."}
        cur.execute("""
        SELECT id FROM inventario_conteo_scans
        WHERE conteo_id=%s AND regexp_replace(UPPER(COALESCE(serie,'')), '[^A-Z0-9]', '', 'g')=%s
        LIMIT 1
        """, (conteo_id, serie))
        if cur.fetchone():
            conn.close()
            return {"ok": False, "success": False, "estado": "DUPLICADA", "msg": f"Serie {serie} ya fue contada."}
        cur.execute("""
        SELECT ps.producto_id, COALESCE(p.nombre,'') AS producto_nombre,
               COALESCE(p.categoria,'') AS categoria,
               UPPER(COALESCE(ps.estado,'DISPONIBLE')) AS estado
        FROM producto_series ps
        LEFT JOIN productos p ON p.id=ps.producto_id
        WHERE regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g')=%s AND COALESCE(ps.sucursal,%s)=%s
        LIMIT 1
        """, (serie, DEFAULT_SUCURSAL, sucursal))
        row = dict_fetchone(cur)
        estado_scan = "NO_REGISTRADA"
        producto_id = None
        producto_nombre = ""
        if row:
            producto_id = row.get("producto_id")
            producto_nombre = row.get("producto_nombre") or ""
            if str(row.get("categoria") or "").lower() != str(conteo.get("categoria") or "").lower():
                estado_scan = "FUERA_CATEGORIA"
            elif str(row.get("estado") or "").upper() not in ("DISPONIBLE", "RESERVADO"):
                estado_scan = str(row.get("estado") or "NO_DISPONIBLE").upper()
            else:
                estado_scan = "OK"
        cur.execute("""
        INSERT INTO inventario_conteo_scans (conteo_id, serie, producto_id, producto_nombre, estado, usuario)
        VALUES (%s,%s,%s,%s,%s,%s)
        RETURNING id
        """, (conteo_id, serie, producto_id, producto_nombre, estado_scan, data.usuario or ""))
        scan_id = cur.fetchone()[0]
        conn.commit()
        result = resumen_inventario_conteo(cur, conteo_id, sucursal) or {}
        result.update({
            "scan": {
                "id": scan_id,
                "serie": serie,
                "producto_id": producto_id,
                "producto_nombre": producto_nombre,
                "estado": estado_scan,
            },
            "msg": "Serie contada." if estado_scan == "OK" else f"Revisar serie {serie}: {estado_scan}",
        })
        conn.close()
        return result
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.post("/inventario/conteos/{conteo_id}/cerrar")
def cerrar_inventario_conteo(conteo_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cur.execute("""
        UPDATE inventario_conteos
        SET estado='CERRADO', cerrado_en=timezone('America/Lima', now())
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id
        """, (conteo_id, DEFAULT_SUCURSAL, sucursal))
        if not cur.fetchone():
            conn.close()
            return {"ok": False, "success": False, "msg": "Conteo no encontrado."}
        conn.commit()
        result = resumen_inventario_conteo(cur, conteo_id, sucursal)
        conn.close()
        return result
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.post("/productos/{producto_id}/ajustar-stock")
def ajustar_stock(producto_id: int, data: StockAjuste, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = inventario_sucursal(sucursal)
        nuevo_stock = max(0, int(data.stock))
        cur.execute("UPDATE productos SET stock=%s WHERE id=%s AND COALESCE(sucursal,%s)=%s RETURNING id", (nuevo_stock, producto_id, DEFAULT_SUCURSAL, sucursal))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "msg": "Producto no encontrado"}
        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "id": producto_id, "stock": nuevo_stock}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


@app.post("/series/mover-almacen")
def mover_series_almacen(data: SeriesMoverAlmacen, sucursal: str = DEFAULT_SUCURSAL):
    if not usuario_puede_editar_series({"usuario": data.usuario, "usuario_ingreso": data.usuario}):
        return {"ok": False, "success": False, "msg": "Solo giomar y mily pueden ingresar, editar o eliminar series."}
    ids = [int(x) for x in (data.serie_ids or []) if str(x).strip()]
    almacen = (data.almacen or "").strip().upper()
    if not ids:
        return {"ok": False, "success": False, "msg": "Selecciona una o mas series."}
    if not almacen:
        return {"ok": False, "success": False, "msg": "Ingresa el almacen destino."}
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = inventario_sucursal(data.sucursal or sucursal)
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
        cur.execute("""
        SELECT ps.id, COALESCE(ps.serie,'') AS serie, COALESCE(ps.almacen,'TIENDA') AS almacen,
               COALESCE(p.nombre,'') AS producto_nombre, ps.producto_id
        FROM producto_series ps
        LEFT JOIN productos p ON p.id=ps.producto_id AND COALESCE(p.sucursal,%s)=%s
        WHERE ps.id = ANY(%s) AND COALESCE(ps.sucursal,%s)=%s
        """, (DEFAULT_SUCURSAL, sucursal, ids, DEFAULT_SUCURSAL, sucursal))
        antes = dict_fetchall(cur)
        cur.execute("""
        UPDATE producto_series
        SET almacen=%s
        WHERE id = ANY(%s) AND COALESCE(sucursal,%s)=%s
        RETURNING id, producto_id
        """, (almacen, ids, DEFAULT_SUCURSAL, sucursal))
        rows = cur.fetchall()
        conn.commit()
        series_txt = _resumen_lista_auditoria([f"{r.get('serie')} ({r.get('almacen')})" for r in antes])
        registrar_auditoria_mercaderia(
            cur,
            usuario=data.usuario,
            sucursal=sucursal,
            accion="SERIES_MOVER_ALMACEN",
            detalle=(
                f"Usuario={data.usuario or 'SISTEMA'} | Cantidad={len(rows)} | Destino={almacen} | "
                f"Series={series_txt}"
            ),
        )
        conn.close()
        return {"ok": True, "success": True, "actualizadas": len(rows), "almacen": almacen}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.get("/productos/{producto_id}/movimientos")
def movimientos_producto(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cur.execute("""
        SELECT id, COALESCE(nombre,''), COALESCE(categoria,''), COALESCE(marca,''), COALESCE(modelo,'')
        FROM productos
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        LIMIT 1
        """, (producto_id, DEFAULT_SUCURSAL, sucursal))
        producto = cur.fetchone()
        if not producto:
            conn.close()
            return {"ok": False, "data": [], "msg": "Producto no encontrado"}

        _, nombre, categoria, marca, modelo = producto
        movimientos = []

        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS usuario_ingreso TEXT DEFAULT ''")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        cur.execute("""
        SELECT
            COALESCE(fecha_ingreso::text, '') AS fecha_ingreso,
            to_char(creado_en, 'YYYY-MM-DD HH24:MI:SS') AS creado_en,
            COALESCE(serie,'') AS serie,
            COALESCE(proveedor,'') AS proveedor,
            COALESCE(estado,'DISPONIBLE') AS estado,
            COALESCE(almacen,'TIENDA') AS almacen,
            COALESCE(usuario_ingreso,'') AS usuario_ingreso
        FROM producto_series
        WHERE producto_id=%s AND COALESCE(sucursal,%s)=%s
        ORDER BY COALESCE(fecha_ingreso, creado_en::date) DESC, id DESC
        LIMIT 120
        """, (producto_id, DEFAULT_SUCURSAL, sucursal))
        for row in dict_fetchall(cur):
            fecha = row.get("fecha_ingreso") or row.get("creado_en") or ""
            movimientos.append({
                "origen": "INGRESO SERIE",
                "fecha": fecha,
                "titulo": f"Ingreso serie {row.get('serie') or ''}".strip(),
                "detalle": f"{row.get('estado') or 'DISPONIBLE'} / {row.get('proveedor') or 'Sin proveedor'} / {row.get('almacen') or 'TIENDA'}",
                "serie": row.get("serie"),
                "usuario": row.get("usuario_ingreso"),
                "proveedor": row.get("proveedor"),
                "estado": row.get("estado"),
                "almacen": row.get("almacen"),
            })

        cur.execute("""
        SELECT
            v.id AS documento_id,
            to_char(v.fecha, 'YYYY-MM-DD HH24:MI:SS') AS fecha,
            COALESCE(v.tipo,'') AS tipo,
            COALESCE(v.numero,'') AS numero,
            COALESCE(v.cliente,'') AS cliente,
            COALESCE(vd.descripcion, '') AS descripcion,
            COALESCE(vd.series_texto, '') AS serie,
            COALESCE(vd.cantidad, 0) AS cantidad,
            COALESCE(vd.total, 0) AS total
        FROM ventas_detalle vd
        JOIN ventas v ON v.id = vd.venta_id
        WHERE vd.producto_id=%s
          AND COALESCE(vd.sucursal,%s)=%s
          AND COALESCE(v.sucursal,%s)=%s
          AND UPPER(COALESCE(v.tipo,'')) IN ('BOLETA','FACTURA')
        ORDER BY v.fecha DESC, v.id DESC
        LIMIT 80
        """, (producto_id, DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal))
        for row in dict_fetchall(cur):
            movimientos.append({
                "origen": "VENTA",
                "fecha": row.get("fecha"),
                "titulo": f"{row.get('tipo') or 'DOC'} {row.get('numero') or ''}".strip(),
                "detalle": f"{row.get('cliente') or 'Cliente'} - Cant. {row.get('cantidad') or 0}",
                "documento": row.get("numero"),
                "documento_tipo": row.get("tipo"),
                "serie": row.get("serie"),
                "cantidad": row.get("cantidad"),
                "total": row.get("total"),
            })

        cur.execute("""
        SELECT COALESCE(serie,'') AS serie
        FROM producto_series
        WHERE producto_id=%s AND COALESCE(sucursal,%s)=%s AND COALESCE(serie,'')<>''
        """, (producto_id, DEFAULT_SUCURSAL, sucursal))
        series_rows = [str(r.get("serie") or "").strip() for r in dict_fetchall(cur) if str(r.get("serie") or "").strip()]

        garantia_params = [DEFAULT_SUCURSAL, sucursal, f"%{nombre}%"]
        serie_filter = ""
        if series_rows:
            serie_filter = " OR UPPER(COALESCE(serie,'')) = ANY(%s)"
            garantia_params.append([s.upper() for s in series_rows])
        cur.execute(f"""
        SELECT
            id,
            to_char(fecha, 'YYYY-MM-DD HH24:MI:SS') AS fecha,
            COALESCE(cliente,'') AS cliente,
            COALESCE(documento,'') AS documento,
            COALESCE(producto,'') AS producto,
            COALESCE(serie,'') AS serie,
            COALESCE(falla,'') AS falla,
            COALESCE(estado,'RECIBIDO') AS estado
        FROM garantias
        WHERE COALESCE(sucursal,%s)=%s
          AND (producto ILIKE %s{serie_filter})
        ORDER BY fecha DESC, id DESC
        LIMIT 60
        """, tuple(garantia_params))
        for row in dict_fetchall(cur):
            movimientos.append({
                "origen": "GARANTIA",
                "fecha": row.get("fecha"),
                "titulo": f"Garantia {row.get('estado') or ''}".strip(),
                "detalle": f"{row.get('cliente') or 'Cliente'} - {row.get('falla') or 'Sin falla'}",
                "documento": row.get("documento"),
                "serie": row.get("serie"),
                "estado": row.get("estado"),
            })

        cur.execute("""
        SELECT
            to_char(fecha, 'YYYY-MM-DD HH24:MI:SS') AS fecha,
            COALESCE(cantidad,0) AS cantidad,
            COALESCE(sucursal_origen,'') AS sucursal_origen,
            COALESCE(sucursal_destino,'') AS sucursal_destino,
            COALESCE(usuario,'') AS usuario,
            COALESCE(nota,'') AS nota
        FROM stock_transferencias
        WHERE producto_id=%s
          AND (COALESCE(sucursal_origen,'')=%s OR COALESCE(sucursal_destino,'')=%s)
        ORDER BY fecha DESC, id DESC
        LIMIT 40
        """, (producto_id, sucursal, sucursal))
        for row in dict_fetchall(cur):
            movimientos.append({
                "origen": "TRANSFERENCIA",
                "fecha": row.get("fecha"),
                "titulo": f"Transferencia x{row.get('cantidad') or 0}",
                "detalle": f"{row.get('sucursal_origen') or '-'} -> {row.get('sucursal_destino') or '-'}",
                "usuario": row.get("usuario"),
                "nota": row.get("nota"),
                "cantidad": row.get("cantidad"),
            })

        movimientos.sort(key=lambda x: str(x.get("fecha") or ""), reverse=True)
        conn.close()
        return {
            "ok": True,
            "success": True,
            "producto": {
                "id": producto_id,
                "nombre": nombre,
                "categoria": categoria,
                "marca": marca,
                "modelo": modelo,
            },
            "data": movimientos[:120],
            "movimientos": movimientos[:120],
        }
    except Exception as e:
        conn.close()
        return {"ok": False, "data": [], "msg": str(e)}


@app.get("/backup/export")
def exportar_backup(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        tables = [
            "productos",
            "producto_series",
            "ventas",
            "ventas_detalle",
            "caja_movimientos",
            "clientes",
            "compras",
            "proveedores",
            "garantias",
            "usuarios",
            "auditoria",
            "stock_transferencias",
            "inventario_conteos",
            "inventario_conteo_scans",
            "app_config",
        ]
        data = {
            "ok": True,
            "success": True,
            "sucursal": sucursal,
            "generado": lima_now().strftime("%Y-%m-%d %H:%M:%S"),
            "tablas": {},
        }
        for table in tables:
            try:
                if table == "app_config":
                    cur.execute("SELECT * FROM app_config ORDER BY clave")
                elif table == "auditoria":
                    cur.execute("SELECT * FROM auditoria WHERE COALESCE(empresa,%s)=%s ORDER BY id", (DEFAULT_SUCURSAL, sucursal))
                elif table == "stock_transferencias":
                    cur.execute("""
                    SELECT * FROM stock_transferencias
                    WHERE COALESCE(sucursal_origen,'')=%s OR COALESCE(sucursal_destino,'')=%s
                    ORDER BY id
                    """, (sucursal, sucursal))
                elif table == "inventario_conteo_scans":
                    cur.execute("""
                    SELECT s.*
                    FROM inventario_conteo_scans s
                    LEFT JOIN inventario_conteos c ON c.id=s.conteo_id
                    WHERE COALESCE(c.sucursal,%s)=%s
                    ORDER BY s.id
                    """, (DEFAULT_SUCURSAL, sucursal))
                elif table == "ventas_detalle":
                    cur.execute("""
                    SELECT vd.*
                    FROM ventas_detalle vd
                    LEFT JOIN ventas v ON v.id=vd.venta_id
                    WHERE COALESCE(vd.sucursal,%s)=%s OR COALESCE(v.sucursal,%s)=%s
                    ORDER BY vd.id
                    """, (DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal))
                else:
                    cur.execute(f"SELECT * FROM {table} WHERE COALESCE(sucursal,%s)=%s ORDER BY 1", (DEFAULT_SUCURSAL, sucursal))
                data["tablas"][table] = dict_fetchall(cur)
            except Exception as table_error:
                data["tablas"][table] = {"error": str(table_error)}
        conn.close()
        return data
    except Exception as e:
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


# ================= SERIES =================
@app.get("/series/{tipo}")
def get_serie(tipo: str, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)

    cur.execute("""
    SELECT id, serie, correlativo
    FROM series
    WHERE UPPER(tipo)=UPPER(%s) AND COALESCE(sucursal,%s)=%s
    """, (tipo, DEFAULT_SUCURSAL, sucursal))
    row = cur.fetchone()

    conn.close()

    if not row:
        return {"numero": "000001"}

    _, serie, corr = row
    return {"numero": f"{serie}-{str(corr).zfill(6)}"}


@app.post("/series/documentos/reset")
def reset_series_documentos(data: SeriesDocumentoReset = None, sucursal: str = DEFAULT_SUCURSAL):
    data = data or SeriesDocumentoReset()
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(data.sucursal or sucursal)
        seed_branch_series(cur, sucursal)
        tipos = data.tipos or [
            "BOLETA", "FACTURA", "BOLETA_ELECTRONICA", "FACTURA_ELECTRONICA",
            "PROFORMA", "NOTA DE VENTA", "PASE", "GARANTIA", "NOTA DE CREDITO",
        ]
        correlativo = max(1, int(data.correlativo or 1))
        updated = []
        for tipo in tipos:
            tipo_clean = str(tipo or "").strip().upper()
            if not tipo_clean:
                continue
            cur.execute("""
            UPDATE series
            SET correlativo=%s
            WHERE UPPER(tipo)=%s AND COALESCE(sucursal,%s)=%s
            RETURNING id, tipo, serie, correlativo
            """, (correlativo, tipo_clean, DEFAULT_SUCURSAL, sucursal))
            row = cur.fetchone()
            if row:
                updated.append({"id": row[0], "tipo": row[1], "serie": row[2], "correlativo": row[3]})
        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,'',%s,'SERIES RESET',%s)
        """, (str(data.usuario or "SISTEMA").strip() or "SISTEMA", sucursal, json.dumps(updated, ensure_ascii=False)))
        conn.commit()
        return {"ok": True, "success": True, "sucursal": sucursal, "correlativo": correlativo, "series": updated}
    except Exception as e:
        conn.rollback()
        return {"ok": False, "success": False, "msg": str(e)}
    finally:
        conn.close()


# ================= VENTAS / DOCUMENTOS =================
@app.post("/ventas")
def crear_venta(data: Venta):
    conn = get_conn()
    cur = conn.cursor()

    try:
        sucursal = norm_sucursal(data.sucursal)
        sucursal_inventario = inventario_sucursal(sucursal)
        doc_tipo_upper = (data.tipo or "").strip().upper()
        if doc_tipo_upper:
            data.tipo = doc_tipo_upper
        legal_sunat = bool(getattr(data, "emitir_legal_sunat", False))
        modo_prueba = bool(getattr(data, "modo_prueba", False))
        row, serie_error = _resolver_fila_serie_documento(cur, doc_tipo_upper, sucursal, legal_sunat)
        if serie_error or not row:
            conn.close()
            return {"ok": False, "msg": serie_error or f"No existe serie para {data.tipo}"}

        serie_id, serie, corr = row
        numero = f"{serie}-{str(corr).zfill(6)}"
        total = round(sum([float(i.total) for i in data.items]), 2)
        subtotal = total
        igv = 0
        documento_cliente = data.numero_documento_cliente or ""
        if data.tipo_documento_cliente and documento_cliente:
            documento_cliente = f"{data.tipo_documento_cliente}: {documento_cliente}"

        estado_pago = (data.estado_pago or "PAGADO").upper()
        if estado_pago not in ("PAGADO", "CREDITO", "DEUDA"):
            estado_pago = "PAGADO"
        metodo_pago = (data.metodo_pago or "").upper()
        fecha_emision = parse_fecha_emision(data.fecha_emision)
        fecha_vencimiento = data.fecha_vencimiento or None
        es_proforma = doc_tipo_upper == "PROFORMA"
        mueve_stock = doc_tipo_upper in STOCK_DOC_TYPES
        if es_proforma and not fecha_vencimiento:
            fecha_vencimiento = proforma_fecha_vencimiento(fecha_emision)
        if es_proforma:
            estado_pago = "DEUDA"
            metodo_pago = ""
            data.observacion = proforma_observacion_valida(data.observacion)

        resolved_product_ids = {}
        if mueve_stock:
            for item_index, item in enumerate(data.items):
                producto_id = item.producto_id or item.id
                descripcion = item.nombre
                marca = item.marca
                modelo = item.modelo
                if producto_id and not descripcion:
                    cur.execute("SELECT nombre, marca, modelo FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s", (producto_id, DEFAULT_SUCURSAL, sucursal_inventario))
                    prod = cur.fetchone()
                    if prod:
                        descripcion = prod[0] or ""
                        marca = marca or (prod[1] or "")
                        modelo = modelo or (prod[2] or "")
                series_texto = item.series_texto or item.serie
                if venta_linea_es_prueba(modo_prueba, descripcion, marca, modelo):
                    error_prueba = procesar_modo_prueba_venta(cur, producto_id, item.cantidad, series_texto, sucursal)
                    if error_prueba:
                        conn.rollback()
                        conn.close()
                        return {"ok": False, "success": False, "msg": error_prueba}
                    continue
                if is_test_product_name(descripcion, marca, modelo) or ((not producto_id) and series_texto):
                    error_combo = procesar_combo_generico_venta(cur, descripcion, series_texto, sucursal)
                    if error_combo:
                        conn.rollback()
                        conn.close()
                        return {"ok": False, "success": False, "msg": error_combo}
                    continue
                producto_id, error_resolver = resolver_producto_por_series_venta(
                    cur,
                    producto_id,
                    descripcion,
                    item.cantidad,
                    series_texto,
                    sucursal,
                )
                if error_resolver:
                    conn.rollback()
                    conn.close()
                    return {"ok": False, "success": False, "msg": error_resolver}
                resolved_product_ids[item_index] = producto_id
                error_series = validar_y_marcar_series_venta(
                    cur,
                    producto_id,
                    descripcion,
                    marca,
                    modelo,
                    item.cantidad,
                    series_texto,
                    sucursal,
                )
                if error_series:
                    conn.rollback()
                    conn.close()
                    return {"ok": False, "success": False, "msg": error_series}

        sunat_estado_doc, sunat_modo_doc = ("INTERNO", "NO_ENVIAR")
        if doc_tipo_upper in ("BOLETA", "FACTURA"):
            if legal_sunat:
                sunat_estado_doc, sunat_modo_doc = "PENDIENTE", "ELECTRONICO"
            else:
                sunat_estado_doc, sunat_modo_doc = "INTERNO", "NO_ENVIAR"

        cur.execute("""
        INSERT INTO ventas (
            fecha, tipo, es_pase, numero, cliente, documento_cliente, direccion_cliente,
            subtotal, igv, total, observacion, fecha_vencimiento, usuario_emisor, estado, estado_pago, metodo_pago, sucursal,
            sunat_estado, sunat_modo
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'EMITIDO',%s,%s,%s,%s,%s)
        RETURNING id
        """, (
            fecha_emision, data.tipo, bool(getattr(data, 'es_pase', False)), numero, data.cliente_nombre, documento_cliente,
            data.direccion_cliente, subtotal, igv, total,
            data.observacion, fecha_vencimiento, data.usuario_emisor, estado_pago, metodo_pago, sucursal,
            sunat_estado_doc, sunat_modo_doc,
        ))

        venta_id = cur.fetchone()[0]

        for item_index, item in enumerate(data.items):
            producto_id = resolved_product_ids.get(item_index) or item.producto_id or item.id
            descripcion = item.nombre
            marca = item.marca
            modelo = item.modelo

            if not descripcion:
                cur.execute("SELECT nombre, marca, modelo FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s", (producto_id, DEFAULT_SUCURSAL, sucursal_inventario))
                prod = cur.fetchone()
                if prod:
                    descripcion = prod[0] or ""
                    marca = marca or (prod[1] or "")
                    modelo = modelo or (prod[2] or "")

            cur.execute("""
            INSERT INTO ventas_detalle (
                venta_id, producto_id, descripcion, marca, modelo,
                series_texto, cantidad, precio, total, sucursal
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                venta_id, producto_id, descripcion, marca, modelo,
                item.series_texto or item.serie,
                item.cantidad, item.precio, item.total, sucursal
            ))

        cur.execute("UPDATE series SET correlativo = correlativo + 1 WHERE id=%s", (serie_id,))

        if mueve_stock:
            caja_observacion = (data.observacion or "").strip()
            cur.execute("""
            INSERT INTO caja_movimientos (
                fecha, tipo, detalle, monto, usuario, documento_tipo, documento_numero, estado_pago, metodo_pago, observacion, sucursal
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                fecha_emision,
                "INGRESO" if estado_pago == "PAGADO" else estado_pago,
                f"{data.tipo} {numero} - {data.cliente_nombre}",
                total, data.usuario_emisor, data.tipo, numero, estado_pago, metodo_pago, caja_observacion, sucursal
            ))

        conn.commit()
        conn.close()

        sunat_auto = None
        if doc_tipo_upper in ("BOLETA", "FACTURA") and legal_sunat:
            try:
                sunat_auto = enviar_documento_sunat(
                    venta_id,
                    SunatEnviarRequest(regenerar=True, permitir_sin_firma=False),
                    sucursal,
                )
            except Exception as sunat_error:
                sunat_auto = {"ok": False, "auto": True, "msg": str(sunat_error)}

        return {
            "ok": True,
            "success": True,
            "data": {"id": venta_id, "numero": numero, "total": total},
            "id": venta_id,
            "numero": numero,
            "subtotal": subtotal,
            "igv": igv,
            "total": total,
            "fecha_emision": fecha_emision.strftime("%Y-%m-%d %H:%M:%S"),
            "fecha_vencimiento": fecha_vencimiento or "",
            "estado_pago": estado_pago,
            "metodo_pago": metodo_pago,
            "sunat_auto": sunat_auto,
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


@app.post("/documentos/emitir")
def emitir_documento(data: Venta):
    return crear_venta(data)


@app.post("/documentos/manual-series")
def crear_documento_manual_series(data: DocumentoManualSeries):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(data.sucursal)
        doc_tipo = (data.tipo or "BOLETA").strip().upper()
        if doc_tipo not in STOCK_DOC_TYPES:
            doc_tipo = "BOLETA"
        series = split_series_text(data.series_texto)
        if not series:
            conn.close()
            return {"ok": False, "success": False, "msg": "Ingresa una o mas series para descontar stock."}
        if len(series) != len(set(series)):
            conn.close()
            return {"ok": False, "success": False, "msg": "Hay series repetidas en la boleta manual."}

        numero = (data.numero or "").strip().upper()
        if not numero:
            numero = f"MANUAL-{lima_now().strftime('%Y%m%d%H%M%S')}"
        cur.execute("""
        SELECT id FROM ventas
        WHERE UPPER(COALESCE(tipo,''))=%s
          AND UPPER(COALESCE(numero,''))=%s
          AND COALESCE(sucursal,%s)=%s
        LIMIT 1
        """, (doc_tipo, numero, DEFAULT_SUCURSAL, sucursal))
        existing_doc = cur.fetchone()

        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS usuario_ingreso TEXT DEFAULT ''")
        cur.execute("""
        SELECT ps.id AS serie_id,
               regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g') AS serie,
               ps.producto_id,
               UPPER(COALESCE(ps.estado,'DISPONIBLE')) AS estado,
               COALESCE(p.nombre,'') AS producto_nombre,
               COALESCE(p.marca,'') AS marca,
               COALESCE(p.modelo,'') AS modelo,
               COALESCE(p.precio_venta,0) AS precio_venta
        FROM producto_series ps
        LEFT JOIN productos p ON p.id=ps.producto_id AND COALESCE(p.sucursal,%s)=%s
        WHERE COALESCE(ps.sucursal,%s)=%s
          AND regexp_replace(UPPER(COALESCE(ps.serie,'')), '[^A-Z0-9]', '', 'g')=ANY(%s)
        """, (DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal, series))
        found = {str(r.get("serie") or "").upper(): r for r in dict_fetchall(cur)}
        faltantes = [serie for serie in series if serie not in found]
        bloqueadas = [f"{serie} ({found[serie].get('estado')})" for serie in series if serie in found and found[serie].get("estado") not in ("DISPONIBLE", "RESERVADO")]
        if bloqueadas:
            conn.close()
            msg = []
            if bloqueadas:
                msg.append("Series no disponibles: " + ", ".join(bloqueadas))
            return {"ok": False, "success": False, "msg": " | ".join(msg), "faltantes": faltantes, "bloqueadas": bloqueadas}

        fecha_emision = parse_fecha_emision(data.fecha_emision)
        cliente = (data.cliente_nombre or "CLIENTE MANUAL").strip() or "CLIENTE MANUAL"
        total = round(sum(float(found[s].get("precio_venta") or 0) for s in series if s in found), 2)
        if existing_doc:
            venta_id = existing_doc[0]
        else:
            sunat_estado_doc, sunat_modo_doc = _sunat_defaults_nuevo_documento(cur, sucursal, fecha_emision)
            cur.execute("""
            INSERT INTO ventas (
                fecha, tipo, numero, cliente, documento_cliente, direccion_cliente,
                subtotal, igv, total, observacion, fecha_vencimiento, usuario_emisor,
                estado, estado_pago, metodo_pago, sucursal, sunat_estado, sunat_modo
            )
            VALUES (%s,%s,%s,%s,'','',%s,0,%s,%s,%s,%s,'EMITIDO','PAGADO','MANUAL',%s,%s,%s)
            RETURNING id
            """, (
                fecha_emision, doc_tipo, numero, cliente, total, total,
                data.observacion or f"{doc_tipo} manual ingresado por series",
                fecha_emision.date().isoformat(), data.usuario_emisor or "", sucursal,
                sunat_estado_doc, sunat_modo_doc,
            ))
            venta_id = cur.fetchone()[0]

        touched_products = set()
        for serie in series:
            if serie not in found:
                cur.execute("""
                INSERT INTO ventas_detalle (
                    venta_id, producto_id, descripcion, marca, modelo,
                    series_texto, cantidad, precio, total, sucursal
                )
                VALUES (%s,NULL,%s,'','',%s,1,0,0,%s)
                """, (venta_id, f"SERIE NO REGISTRADA {serie}", serie, sucursal))
                continue
            row = found[serie]
            producto_id = row.get("producto_id")
            precio = float(row.get("precio_venta") or 0)
            cur.execute("""
            INSERT INTO ventas_detalle (
                venta_id, producto_id, descripcion, marca, modelo,
                series_texto, cantidad, precio, total, sucursal
            )
            VALUES (%s,%s,%s,%s,%s,%s,1,%s,%s,%s)
            """, (
                venta_id, producto_id, row.get("producto_nombre") or "PRODUCTO POR SERIE",
                row.get("marca") or "", row.get("modelo") or "", serie, precio, precio, sucursal
            ))
            cur.execute("""
            UPDATE producto_series
            SET estado='VENDIDO',
                fecha_salida=TO_CHAR((timezone('America/Lima', now()))::date, 'YYYY-MM-DD')
            WHERE id=%s
            """, (row.get("serie_id"),))
            if producto_id:
                touched_products.add(producto_id)
        for producto_id in touched_products:
            sync_producto_stock_from_series(cur, producto_id, sucursal)

        if not existing_doc:
            cur.execute("""
            INSERT INTO caja_movimientos (
                fecha, tipo, detalle, monto, usuario, documento_tipo, documento_numero, estado_pago, metodo_pago, observacion, sucursal
            )
            VALUES (%s,'INGRESO',%s,%s,%s,%s,%s,'PAGADO','MANUAL',%s,%s)
            """, (
                fecha_emision, f"{doc_tipo} {numero} - {cliente}",
                total, data.usuario_emisor or "", doc_tipo, numero, data.observacion or "", sucursal
            ))

        conn.commit()
        conn.close()
        return {
            "ok": True,
            "success": True,
            "msg": f"{doc_tipo} {numero} {'actualizado' if existing_doc else 'registrado'}. Las series quedaron en historial como VENDIDO, no fueron eliminadas.",
            "id": venta_id,
            "tipo": doc_tipo,
            "numero": numero,
            "series": series,
            "total": total,
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.post("/proformas")
def crear_proforma(data: Venta):
    data.tipo = "PROFORMA"
    data.estado_pago = "DEUDA"
    data.metodo_pago = ""
    if not data.cliente_nombre:
        data.cliente_nombre = "CLIENTE GENERAL"
    if not data.fecha_vencimiento:
        data.fecha_vencimiento = proforma_fecha_vencimiento(data.fecha_emision)
    data.observacion = proforma_observacion_valida(data.observacion)
    return crear_venta(data)


@app.post("/documentos/{documento_id}/convertir")
def convertir_proforma_documento(documento_id: int, data: DocumentoConvertirUpdate):
    sucursal = norm_sucursal(data.sucursal)
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
        SELECT id, tipo, numero, cliente, COALESCE(documento_cliente,'') AS documento_cliente,
               COALESCE(direccion_cliente,'') AS direccion_cliente,
               COALESCE(observacion,'') AS observacion,
               COALESCE(sucursal,%s) AS sucursal
        FROM ventas
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        LIMIT 1
        """, (DEFAULT_SUCURSAL, documento_id, DEFAULT_SUCURSAL, sucursal))
        doc = dict_fetchone(cur)
        if not doc:
            conn.close()
            return {"ok": False, "success": False, "msg": "Proforma no encontrada."}
        if str(doc.get("tipo") or "").upper() != "PROFORMA":
            conn.close()
            return {"ok": False, "success": False, "msg": "Solo se puede convertir una PROFORMA."}

        cur.execute("""
        SELECT vd.producto_id,
               COALESCE(vd.descripcion, p.nombre, '') AS descripcion,
               COALESCE(vd.marca, p.marca, '') AS marca,
               COALESCE(vd.modelo, p.modelo, '') AS modelo,
               COALESCE(vd.series_texto, '') AS series_texto,
               COALESCE(vd.cantidad, 1) AS cantidad,
               COALESCE(vd.precio, 0) AS precio,
               COALESCE(vd.total, COALESCE(vd.cantidad,1) * COALESCE(vd.precio,0)) AS total
        FROM ventas_detalle vd
        LEFT JOIN productos p ON p.id=vd.producto_id
        WHERE vd.venta_id=%s
        ORDER BY vd.id
        """, (documento_id,))
        rows = dict_fetchall(cur)
        conn.close()
        if not rows:
            return {"ok": False, "success": False, "msg": "La proforma no tiene productos."}

        tipo_doc_cliente = ""
        numero_doc_cliente = str(doc.get("documento_cliente") or "").strip()
        m = re.match(r"^\s*(DNI|RUC|CE|PASAPORTE)\s*:\s*(.+)$", numero_doc_cliente, flags=re.I)
        if m:
            tipo_doc_cliente = m.group(1).upper()
            numero_doc_cliente = m.group(2).strip()

        target_tipo = str(data.tipo or "BOLETA").strip().upper()
        if target_tipo not in ("BOLETA", "FACTURA"):
            target_tipo = "BOLETA"
        estado_pago = str(data.estado_pago or "PAGADO").strip().upper()
        if estado_pago not in ("PAGADO", "CREDITO", "DEUDA"):
            estado_pago = "PAGADO"

        venta = Venta(
            tipo=target_tipo,
            cliente_nombre=doc.get("cliente") or "CLIENTE GENERAL",
            items=[
                ItemVenta(
                    id=int(row.get("producto_id") or 0),
                    producto_id=row.get("producto_id"),
                    nombre=row.get("descripcion") or "",
                    marca=row.get("marca") or "",
                    modelo=row.get("modelo") or "",
                    series_texto=row.get("series_texto") or "",
                    cantidad=int(float(row.get("cantidad") or 1)),
                    precio=float(row.get("precio") or 0),
                    total=float(row.get("total") or 0),
                ) for row in rows
            ],
            fecha_emision=lima_now().strftime("%Y-%m-%d %H:%M:%S"),
            tipo_documento_cliente=tipo_doc_cliente,
            numero_documento_cliente=numero_doc_cliente,
            direccion_cliente=doc.get("direccion_cliente") or "",
            usuario_emisor=data.usuario_emisor or "",
            observacion=(data.observacion or f"Convertido desde PROFORMA {doc.get('numero')}").strip(),
            estado_pago=estado_pago,
            metodo_pago="" if estado_pago != "PAGADO" else str(data.metodo_pago or "EFECTIVO").upper(),
            sucursal=sucursal,
        )
        res = crear_venta(venta)
        if not (isinstance(res, dict) and (res.get("ok") or res.get("success"))):
            return res

        conn2 = get_conn()
        cur2 = conn2.cursor()
        cur2.execute("""
        UPDATE ventas
        SET estado='PROCESADO', estado_pago='PROCESADO',
            observacion=TRIM(COALESCE(observacion,'') || %s)
        WHERE id=%s
        """, (f"\nConvertida a {target_tipo} {res.get('numero') or ''}", documento_id))
        conn2.commit()
        conn2.close()
        return {"ok": True, "success": True, "msg": f"Proforma convertida a {target_tipo} {res.get('numero')}", "documento_origen_id": documento_id, "documento_nuevo": res}
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return {"ok": False, "success": False, "msg": str(e)}


@app.get("/documentos")
def listar_documentos(sucursal: str = DEFAULT_SUCURSAL, fecha: str = "", q: str = ""):
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        sucursal = norm_sucursal(sucursal)
        filtro_fecha = (fecha or "").strip()
        texto = f"%{(q or '').strip().lower()}%"
        cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS observacion_interna TEXT DEFAULT ''")

        cur.execute("""
        SELECT
            v.id,
            v.tipo,
            v.numero,
            v.cliente AS cliente_nombre,
            COALESCE(documento_cliente, '') AS documento_cliente,
            COALESCE(direccion_cliente, '') AS direccion_cliente,
            v.fecha AS fecha_emision,
            COALESCE(TO_CHAR(v.fecha_vencimiento, 'YYYY-MM-DD'), '') AS fecha_vencimiento,
            COALESCE(v.subtotal, v.total, 0) AS subtotal,
            COALESCE(v.igv, 0) AS igv,
            COALESCE(v.total, 0) AS total,
            COALESCE(v.observacion, '') AS observacion,
            COALESCE(v.observacion_interna, '') AS observacion_interna,
            COALESCE(v.usuario_emisor, '') AS usuario_emisor,
            COALESCE(v.estado, 'EMITIDO') AS estado,
            COALESCE(v.estado_pago, 'PAGADO') AS estado_pago,
            COALESCE(v.metodo_pago, '') AS metodo_pago,
            COALESCE(v.monto_pagado, CASE WHEN COALESCE(v.estado_pago,'PAGADO')='PAGADO' THEN COALESCE(v.total,0) ELSE 0 END) AS monto_pagado,
            COALESCE(v.pagos_detalle_json, '') AS pagos_detalle_json,
            COALESCE(v.saldo_pago, GREATEST(COALESCE(v.total,0) - COALESCE(v.monto_pagado,0), 0)) AS saldo_pago,
            COALESCE(v.observacion_pago, '') AS observacion_pago,
            COALESCE(v.comprobante_pago, '') AS comprobante_pago,
            COALESCE(v.comprobante_pago_nombre, '') AS comprobante_pago_nombre,
            COALESCE(v.comprobante_pago_mime, '') AS comprobante_pago_mime,
            COALESCE(v.comprobante_pago_tamano, 0) AS comprobante_pago_tamano,
            COALESCE(v.comprobantes_pago_json, '') AS comprobantes_pago_json,
            COALESCE(v.sunat_estado, 'PENDIENTE') AS sunat_estado,
            COALESCE(v.sunat_modo, 'MANUAL') AS sunat_modo,
            v.sunat_fecha,
            COALESCE((
                SELECT string_agg(
                    COALESCE(vd.descripcion,'') || ' ' ||
                    COALESCE(vd.marca,'') || ' ' ||
                    COALESCE(vd.modelo,'') || ' ' ||
                    COALESCE(vd.series_texto,''),
                    ' '
                )
                FROM ventas_detalle vd
                WHERE vd.venta_id = v.id
                  AND COALESCE(vd.sucursal,%s)=%s
            ), '') AS detalle_busqueda
        FROM ventas v
        WHERE COALESCE(v.sucursal,%s)=%s
          AND (%s='' OR TO_CHAR(v.fecha, 'YYYY-MM-DD')=%s)
          AND (%s='%%'
               OR LOWER(COALESCE(v.tipo,'')) LIKE %s
               OR LOWER(COALESCE(v.numero,'')) LIKE %s
               OR LOWER(COALESCE(v.cliente,'')) LIKE %s
               OR LOWER(COALESCE(v.documento_cliente,'')) LIKE %s
               OR LOWER(COALESCE(v.observacion,'')) LIKE %s
               OR EXISTS (
                    SELECT 1
                    FROM ventas_detalle vd
                    WHERE vd.venta_id = v.id
                      AND COALESCE(vd.sucursal,%s)=%s
                      AND (LOWER(COALESCE(vd.descripcion,'')) LIKE %s
                           OR LOWER(COALESCE(vd.marca,'')) LIKE %s
                           OR LOWER(COALESCE(vd.modelo,'')) LIKE %s
                           OR LOWER(COALESCE(vd.series_texto,'')) LIKE %s)
               ))
        ORDER BY v.id DESC
        """, (
            DEFAULT_SUCURSAL, sucursal,
            DEFAULT_SUCURSAL, sucursal, filtro_fecha, filtro_fecha,
            texto, texto, texto, texto, texto, texto,
            DEFAULT_SUCURSAL, sucursal, texto, texto, texto, texto,
        ))
        data = dict_fetchall(cur)
        rows = []
        for r in data:
            row = _jsonable_row(r)
            row["comprobantes_pago"] = comprobantes_metadata_liviana(row.get("comprobantes_pago_json"))
            row["comprobantes_pago_count"] = len(row["comprobantes_pago"])
            row["comprobantes_pago_json"] = ""
            row["pagos_detalle"] = cargar_comprobantes_json(row.get("pagos_detalle_json"))
            rows.append(row)
        return rows
    except Exception as e:
        import traceback
        traceback.print_exc()
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@app.get("/documentos/ultimo")
def ultimo_documento_caja(sucursal: str = DEFAULT_SUCURSAL):
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        sucursal = norm_sucursal(sucursal)
        cur.execute("""
        SELECT
            id,
            tipo,
            numero,
            cliente AS cliente_nombre,
            fecha AS fecha_emision,
            COALESCE(total, 0) AS total,
            COALESCE(usuario_emisor, '') AS usuario_emisor,
            COALESCE(estado_pago, 'PAGADO') AS estado_pago,
            COALESCE(metodo_pago, '') AS metodo_pago
        FROM ventas
        WHERE COALESCE(sucursal,%s)=%s
          AND UPPER(COALESCE(tipo,'')) IN ('BOLETA','FACTURA','NOTA DE VENTA')
        ORDER BY id DESC
        LIMIT 1
        """, (DEFAULT_SUCURSAL, sucursal))
        row = dict_fetchone(cur)
        if not row:
            return {"ok": True, "success": True, "data": None}
        data = _jsonable_row(row)
        data["key"] = f"{data.get('id')}-{data.get('numero')}-{data.get('total')}"
        return {"ok": True, "success": True, "data": data}
    except Exception as e:
        return {"ok": False, "success": False, "msg": str(e)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@app.get("/documentos/{documento_id}/pdf")
def descargar_documento_pdf(documento_id: int, sucursal: str = DEFAULT_SUCURSAL, inline: bool = False):
    detail = detalle_documento(documento_id)
    if not detail.get("ok"):
        return {"ok": False, "success": False, "msg": "Documento no encontrado."}
    documento = detail.get("documento") or {}
    detalle = detail.get("detalle") or detail.get("data") or []
    if not documento:
        return {"ok": False, "success": False, "msg": "Documento no encontrado."}
    try:
        cfg = cargar_config_documento_dict(sucursal or documento.get("sucursal") or DEFAULT_SUCURSAL)
        pdf = generar_pdf_documento_original(documento, detalle, cfg)
        raw_name = f"{documento_pdf_label(documento.get('tipo'))}_{documento.get('numero') or documento_id}.pdf"
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name)
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{safe_name}"',
                "Cache-Control": "no-store",
            },
        )
    except Exception as e:
        return {"ok": False, "success": False, "msg": f"No se pudo generar PDF: {e}"}


@app.post("/documentos/preview/pdf")
def preview_documento_pdf(data: Venta, sucursal: str = DEFAULT_SUCURSAL, inline: bool = True):
    doc_type = str(data.tipo or "PROFORMA").upper()
    numero_preview = {
        "BOLETA": "B001-VISTA-PREVIA",
        "FACTURA": "F001-VISTA-PREVIA",
        "PROFORMA": "VISTA-PREVIA",
        "PASE": "PA001-VISTA-PREVIA",
        "NOTA DE VENTA": "NV001-VISTA-PREVIA",
    }.get(doc_type, "VISTA-PREVIA")
    documento = {
        "id": 0,
        "tipo": doc_type,
        "numero": numero_preview,
        "cliente_nombre": data.cliente_nombre or ("CLIENTE GENERAL" if doc_type == "PROFORMA" else "USUARIO X"),
        "documento_cliente": data.numero_documento_cliente or data.tipo_documento_cliente or "",
        "numero_documento_cliente": data.numero_documento_cliente or "",
        "direccion_cliente": data.direccion_cliente or "SIN DIRECCION",
        "fecha_emision": data.fecha_emision or lima_today_iso(),
        "fecha_vencimiento": data.fecha_vencimiento or (lima_today_iso() if doc_type == "PROFORMA" else ""),
        "estado_pago": data.estado_pago or ("PROFORMA" if doc_type == "PROFORMA" else "CONTADO"),
        "metodo_pago": data.metodo_pago or "",
        "usuario_emisor": data.usuario_emisor or "",
        "sucursal": sucursal or data.sucursal or DEFAULT_SUCURSAL,
    }
    detalle = []
    for item in data.items or []:
        qty = float(item.cantidad or 0)
        price = float(item.precio or 0)
        detalle.append({
            "id": item.id,
            "producto_id": item.producto_id or item.id,
            "nombre": item.nombre or "",
            "descripcion": item.nombre or "",
            "marca": item.marca or "",
            "modelo": item.modelo or "",
            "cantidad": qty,
            "precio": price,
            "precio_unitario": price,
            "total": float(item.total or (qty * price)),
            "serie": item.serie or "",
            "series_texto": item.series_texto or item.serie or "",
        })
    total_doc = round(sum(float(x.get("total") or 0) for x in detalle), 2)
    documento["total"] = total_doc
    documento["subtotal"] = round(total_doc / 1.18, 2) if total_doc else 0
    documento["igv"] = round(total_doc - documento["subtotal"], 2) if total_doc else 0
    try:
        cfg = cargar_config_documento_dict(sucursal or data.sucursal or DEFAULT_SUCURSAL)
        pdf = generar_pdf_documento_original(documento, detalle, cfg)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{doc_type}_{numero_preview}.pdf")
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{safe_name}"',
                "Cache-Control": "no-store",
            },
        )
    except Exception as e:
        return {"ok": False, "success": False, "msg": f"No se pudo generar vista previa PDF: {e}"}


@app.get("/public/documento/{documento_id}")
def documento_publico_qr(documento_id: int, sucursal: str = DEFAULT_SUCURSAL):
    detail = detalle_documento(documento_id)
    if not detail.get("ok"):
        return Response("<h1>Documento no encontrado</h1>", media_type="text/html", status_code=404)
    documento = detail.get("documento") or {}
    numero = html.escape(str(documento.get("numero") or documento_id))
    tipo = html.escape(str(documento.get("tipo") or "DOCUMENTO"))
    cliente = html.escape(str(documento.get("cliente_nombre") or "CLIENTE"))
    fecha = html.escape(str(documento.get("fecha_emision") or "")[:10])
    total = _pdf_money(documento.get("total") or 0)
    safe_sucursal = urllib.parse.quote(norm_sucursal(sucursal or documento.get("sucursal") or DEFAULT_SUCURSAL))
    pdf_inline = f"/documentos/{documento_id}/pdf?sucursal={safe_sucursal}&inline=true"
    pdf_download = f"/documentos/{documento_id}/pdf?sucursal={safe_sucursal}"
    title = f"{tipo} {numero}"
    body = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>
    *{{box-sizing:border-box}} body{{margin:0;background:#edf2f7;color:#0f172a;font-family:Arial,Helvetica,sans-serif}}
    header{{background:#fff;border-bottom:1px solid #dbe4ef;padding:14px 18px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:2}}
    header img{{width:46px;height:46px;object-fit:contain}} h1{{font-size:18px;margin:0;font-weight:900}} .sub{{font-size:12px;color:#64748b;margin-top:2px}}
    main{{max-width:980px;margin:16px auto;padding:0 12px}} .card{{background:#fff;border:1px solid #dbe4ef;border-radius:8px;box-shadow:0 8px 22px rgba(15,23,42,.08);overflow:hidden}}
    .summary{{display:grid;grid-template-columns:1fr auto;gap:10px;padding:14px 16px;border-bottom:1px solid #e2e8f0}}
    .summary b{{font-size:16px}} .total{{font-size:20px;font-weight:900;color:#0f766e;text-align:right}}
    .actions{{display:flex;gap:8px;flex-wrap:wrap;padding:10px;background:#f8fafc;border-bottom:1px solid #e2e8f0}}
    button,a.btn{{border:0;border-radius:7px;padding:10px 13px;font-weight:900;text-decoration:none;cursor:pointer;color:white;background:#2563eb}}
    a.download{{background:#7c3aed}} button.print{{background:#059669}} iframe{{width:100%;height:76vh;border:0;background:white}}
    @media(max-width:640px){{.summary{{grid-template-columns:1fr}} iframe{{height:70vh}}}}
  </style>
</head>
<body>
  <header><img src="/army-logo-doc.png" alt="G&G ERP"><div><h1>{title}</h1><div class="sub">Documento emitido por G&G ERP</div></div></header>
  <main><section class="card">
    <div class="summary"><div><b>{cliente}</b><div class="sub">Fecha: {fecha}</div></div><div class="total">S/ {total}</div></div>
    <div class="actions"><button class="print" onclick="frames.pdf.focus();frames.pdf.print()">Imprimir</button><a class="btn download" href="{pdf_download}">Descargar PDF</a><a class="btn" href="{pdf_inline}" target="_blank" rel="noopener">Abrir PDF</a></div>
    <iframe name="pdf" src="{pdf_inline}" title="PDF"></iframe>
  </section></main>
</body>
</html>"""
    return Response(body, media_type="text/html", headers={"Cache-Control": "no-store"})


@app.put("/documentos/{documento_id}/observacion-interna")
def actualizar_observacion_interna_documento(documento_id: int, data: DocumentoObservacionInternaUpdate, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS observacion_interna TEXT DEFAULT ''")
        observacion = (data.observacion_interna or "").strip()
        cur.execute("""
        UPDATE ventas
        SET observacion_interna=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id, tipo, numero, COALESCE(observacion_interna,'') AS observacion_interna
        """, (observacion, documento_id, DEFAULT_SUCURSAL, sucursal))
        row = dict_fetchone(cur)
        if not row:
            conn.close()
            return {"ok": False, "success": False, "msg": "Documento no encontrado"}
        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,%s,%s,%s,%s)
        """, (data.usuario or "", "", sucursal, "OBSERVACION INTERNA DOCUMENTO", f"{row.get('tipo')} {row.get('numero')} - {observacion}"))
        conn.commit()
        conn.close()
        return {"ok": True, "success": True, **row}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.get("/documentos/{documento_id}")
def detalle_documento(documento_id: int):
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("ALTER TABLE ventas ADD COLUMN IF NOT EXISTS observacion_interna TEXT DEFAULT ''")

        cur.execute("""
        SELECT
            id,
            tipo,
            numero,
            cliente AS cliente_nombre,
            COALESCE(documento_cliente, '') AS documento_cliente,
            COALESCE(direccion_cliente, '') AS direccion_cliente,
            fecha AS fecha_emision,
            COALESCE(TO_CHAR(fecha_vencimiento, 'YYYY-MM-DD'), '') AS fecha_vencimiento,
            COALESCE(subtotal, total, 0) AS subtotal,
            COALESCE(igv, 0) AS igv,
            COALESCE(total, 0) AS total,
            COALESCE(observacion, '') AS observacion,
            COALESCE(observacion_interna, '') AS observacion_interna,
            COALESCE(usuario_emisor, '') AS usuario_emisor,
            COALESCE(estado, 'EMITIDO') AS estado,
            COALESCE(estado_pago, 'PAGADO') AS estado_pago,
            COALESCE(metodo_pago, '') AS metodo_pago,
            COALESCE(monto_pagado, CASE WHEN COALESCE(estado_pago,'PAGADO')='PAGADO' THEN COALESCE(total,0) ELSE 0 END) AS monto_pagado,
            COALESCE(pagos_detalle_json, '') AS pagos_detalle_json,
            COALESCE(saldo_pago, GREATEST(COALESCE(total,0) - COALESCE(monto_pagado,0), 0)) AS saldo_pago,
            COALESCE(observacion_pago, '') AS observacion_pago,
            COALESCE(comprobante_pago, '') AS comprobante_pago,
            COALESCE(comprobante_pago_nombre, '') AS comprobante_pago_nombre,
            COALESCE(comprobante_pago_mime, '') AS comprobante_pago_mime,
            COALESCE(comprobante_pago_tamano, 0) AS comprobante_pago_tamano,
            COALESCE(comprobante_pago_base64, '') AS comprobante_pago_base64,
            COALESCE(comprobante_pago_data_url, '') AS comprobante_pago_data_url,
            COALESCE(comprobantes_pago_json, '') AS comprobantes_pago_json,
            COALESCE(sunat_estado, 'PENDIENTE') AS sunat_estado,
            COALESCE(sunat_modo, 'MANUAL') AS sunat_modo,
            sunat_fecha
        FROM ventas
        WHERE id=%s
        LIMIT 1
        """, (documento_id,))
        documento = dict_fetchone(cur) or {}

        cur.execute("""
        SELECT
            vd.id,
            vd.venta_id AS documento_id,
            vd.producto_id,
            COALESCE(vd.descripcion, p.nombre, '') AS descripcion,
            COALESCE(vd.marca, p.marca, '') AS marca,
            COALESCE(vd.modelo, p.modelo, '') AS modelo,
            COALESCE(vd.series_texto, '') AS series_texto,
            vd.cantidad,
            vd.precio AS precio_unitario,
            vd.total
        FROM ventas_detalle vd
        LEFT JOIN productos p ON p.id = vd.producto_id
        WHERE vd.venta_id = %s
        ORDER BY vd.id
        """, (documento_id,))
        data = dict_fetchall(cur)
        detalle = [_jsonable_row(r) for r in data]
        documento = _jsonable_row(documento) if documento else {}
        documento["comprobantes_pago"] = cargar_comprobantes_json(documento.get("comprobantes_pago_json"))
        documento["pagos_detalle"] = cargar_comprobantes_json(documento.get("pagos_detalle_json"))
        return {
            "ok": True,
            "success": True,
            "documento": documento,
            "data": detalle,
            "detalle": detalle,
            **{k: v for k, v in documento.items() if k.startswith("comprobante_pago")},
        }
    except Exception:
        return {"ok": False, "success": False, "data": [], "detalle": []}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@app.put("/documentos/{documento_id}/editar")
@app.post("/documentos/{documento_id}/editar")
@app.put("/documentos/{documento_id}")
def actualizar_documento(documento_id: int, data: dict, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(data.get("sucursal") or sucursal)
        cur.execute("""
        SELECT tipo, numero, COALESCE(sucursal,%s), COALESCE(estado,'EMITIDO')
        FROM ventas
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (DEFAULT_SUCURSAL, documento_id, DEFAULT_SUCURSAL, sucursal))
        doc = cur.fetchone()
        if not doc:
            conn.close()
            return {"ok": False, "success": False, "msg": "Documento no encontrado"}
        tipo_actual, numero_actual, sucursal_doc, estado_actual = doc
        sucursal_inventario_doc = inventario_sucursal(sucursal_doc)
        tipo_doc_upper = str(tipo_actual or "").upper()
        if str(estado_actual or "").upper() == "ANULADO":
            conn.close()
            return {"ok": False, "success": False, "msg": "No se puede editar un documento anulado."}
        es_proforma_doc = tipo_doc_upper == "PROFORMA"
        if not es_proforma_doc and not usuario_puede_editar_documento(data):
            conn.close()
            return {"ok": False, "success": False, "msg": "Solo Giomar puede cambiar boletas/facturas ya procesadas."}

        motivo_cambio = str(data.get("observacion_cambio") or data.get("motivo_cambio") or "").strip()
        if not motivo_cambio:
            if es_proforma_doc:
                motivo_cambio = "Actualizacion de cotizacion"
            else:
                conn.close()
                return {"ok": False, "success": False, "msg": "Debes indicar la observacion del cambio antes de guardar."}

        cur.execute("""
        SELECT COALESCE(observacion_interna,'')
        FROM ventas
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (documento_id, DEFAULT_SUCURSAL, sucursal))
        obs_row = cur.fetchone()
        observacion_interna_prev = str(obs_row[0] if obs_row else "").strip()

        cur.execute("""
        SELECT descripcion, marca, modelo, series_texto, cantidad, precio, total
        FROM ventas_detalle
        WHERE venta_id=%s
        ORDER BY id
        """, (documento_id,))
        detalle_previo = dict_fetchall(cur)
        series_previas_doc = series_desde_detalle_rows(detalle_previo)

        items = data.get("items") or data.get("detalle") or []
        if not isinstance(items, list) or not items:
            conn.close()
            return {"ok": False, "success": False, "msg": "El documento debe tener productos"}

        total = round(sum(float((i or {}).get("total") or 0) for i in items), 2)
        if total <= 0:
            total = round(sum(float((i or {}).get("cantidad") or 0) * float((i or {}).get("precio") or (i or {}).get("precio_unitario") or 0) for i in items), 2)
        subtotal = float(data.get("subtotal") or total)
        igv = float(data.get("igv") or 0)
        if es_proforma_doc:
            fecha_vencimiento = data.get("fecha_vencimiento") or proforma_fecha_vencimiento()
            data["observacion"] = proforma_observacion_valida(data.get("observacion") or "")
        else:
            fecha_vencimiento = data.get("fecha_vencimiento") or lima_today_iso()

        documento_cliente = data.get("numero_documento_cliente") or ""
        tipo_cliente = data.get("tipo_documento_cliente") or ""
        if tipo_cliente and documento_cliente:
            documento_cliente = f"{tipo_cliente}: {documento_cliente}"
        elif data.get("documento_cliente"):
            documento_cliente = data.get("documento_cliente")

        if tipo_doc_upper in STOCK_DOC_TYPES:
            restaurar_stock_documento(cur, documento_id, tipo_doc_upper, sucursal_doc)

        prepared_items = []
        for item in items:
            producto_id = item.get("producto_id") or item.get("id")
            try:
                producto_id = int(producto_id) if str(producto_id or "").strip() else None
            except Exception:
                producto_id = None
            cantidad = int(float(item.get("cantidad") or 0))
            precio = float(item.get("precio") or item.get("precio_unitario") or 0)
            item_total = float(item.get("total") or (cantidad * precio))
            descripcion = item.get("nombre") or item.get("descripcion") or ""
            marca = item.get("marca") or ""
            modelo = item.get("modelo") or ""
            series_texto = item.get("series_texto") or item.get("serie") or ""
            if producto_id and not descripcion:
                cur.execute("SELECT nombre, marca, modelo FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s", (producto_id, DEFAULT_SUCURSAL, sucursal_inventario_doc))
                prod = cur.fetchone()
                if prod:
                    descripcion = prod[0] or ""
                    marca = marca or (prod[1] or "")
                    modelo = modelo or (prod[2] or "")
            combo_procesado = False
            line_series_previas = series_texto_a_set(series_texto) & series_previas_doc
            if tipo_doc_upper in STOCK_DOC_TYPES:
                if is_test_product_name(descripcion, marca, modelo) or ((not producto_id) and series_texto):
                    error_combo = procesar_combo_generico_venta(
                        cur, descripcion, series_texto, sucursal_doc, permitir_series=line_series_previas or series_previas_doc
                    )
                    if error_combo:
                        conn.rollback()
                        conn.close()
                        return {"ok": False, "success": False, "msg": error_combo}
                    combo_procesado = True
                if not combo_procesado:
                    producto_id, error_resolver = resolver_producto_por_series_venta(
                        cur, producto_id, descripcion, cantidad, series_texto, sucursal_doc
                    )
                    if error_resolver:
                        conn.rollback()
                        conn.close()
                        return {"ok": False, "success": False, "msg": error_resolver}
                    error_series = validar_y_marcar_series_venta(
                        cur, producto_id, descripcion, marca, modelo, cantidad, series_texto, sucursal_doc,
                        permitir_series=line_series_previas or series_previas_doc,
                    )
                    if error_series:
                        conn.rollback()
                        conn.close()
                        return {"ok": False, "success": False, "msg": error_series}
            prepared_items.append({
                "producto_id": producto_id,
                "cantidad": cantidad,
                "precio": precio,
                "total": item_total,
                "descripcion": descripcion,
                "marca": marca,
                "modelo": modelo,
                "series_texto": series_texto,
            })

        usuario_edit = str(
            data.get("usuario_emisor") or data.get("usuario") or data.get("editor") or data.get("user") or "giomar"
        ).strip() or "giomar"
        resumen_cambios = _resumen_cambios_documento(detalle_previo, prepared_items)
        stamp = lima_now().strftime("%Y-%m-%d %H:%M")
        log_line = f"[{stamp}] {usuario_edit.upper()}: {motivo_cambio}"
        if resumen_cambios:
            log_line += f" | {resumen_cambios}"
        observacion_interna_nueva = f"{observacion_interna_prev}\n{log_line}".strip() if observacion_interna_prev else log_line

        cur.execute("""
        UPDATE ventas
        SET cliente=%s,
            documento_cliente=%s,
            direccion_cliente=%s,
            subtotal=%s,
            igv=%s,
            total=%s,
            observacion=%s,
            observacion_interna=%s,
            fecha_vencimiento=%s,
            usuario_emisor=COALESCE(NULLIF(%s,''), usuario_emisor),
            sucursal=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id
        """, (
            data.get("cliente_nombre") or "USUARIO X",
            documento_cliente,
            data.get("direccion_cliente") or "",
            subtotal,
            igv,
            total,
            data.get("observacion") or "",
            observacion_interna_nueva,
            fecha_vencimiento,
            data.get("usuario_emisor") or "",
            sucursal_doc,
            documento_id,
            DEFAULT_SUCURSAL,
            sucursal,
        ))
        if not cur.fetchone():
            conn.close()
            return {"ok": False, "success": False, "msg": "No se pudo actualizar el documento"}

        cur.execute("DELETE FROM ventas_detalle WHERE venta_id=%s", (documento_id,))
        for item in prepared_items:
            cur.execute("""
            INSERT INTO ventas_detalle (
                venta_id, producto_id, descripcion, marca, modelo,
                series_texto, cantidad, precio, total, sucursal
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                documento_id, item.get("producto_id"), item.get("descripcion"), item.get("marca"), item.get("modelo"),
                item.get("series_texto") or "",
                item.get("cantidad"), item.get("precio"), item.get("total"), sucursal_doc
            ))

        detalle_audit = f"{tipo_actual} {numero_actual} editado por {usuario_edit.upper()}. Motivo: {motivo_cambio}"
        if resumen_cambios:
            detalle_audit += f" | {resumen_cambios}"
        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,%s,%s,%s,%s)
        """, (usuario_edit, "", sucursal_doc, "DOCUMENTO ACTUALIZADO", detalle_audit))

        conn.commit()
        conn.close()
        return {
            "ok": True,
            "success": True,
            "id": documento_id,
            "numero": numero_actual,
            "tipo": tipo_actual,
            "total": total,
            "fecha_vencimiento": fecha_vencimiento,
            "msg": (
                f"Cotizacion {numero_actual} actualizada. Valida hasta {fecha_vencimiento}."
                if es_proforma_doc
                else f"{tipo_actual} {numero_actual} actualizado. Stock y series recalculados."
            ),
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": f"Error interno al editar documento: {e}"}


@app.patch("/documentos/{documento_id}")
def actualizar_documento_patch(documento_id: int, data: dict, sucursal: str = DEFAULT_SUCURSAL):
    return actualizar_documento(documento_id, data, sucursal)


@app.put("/documentos/detalle/{detalle_id}/series")
def actualizar_series_detalle_documento(detalle_id: int, data: DocumentoDetalleSeriesUpdate, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        if not usuario_puede_editar_documento({"usuario": getattr(data, "usuario", "")}):
            conn.close()
            return {"ok": False, "msg": "Solo Giomar puede cambiar series de boletas ya procesadas."}
        series_texto = (data.series_texto or "").strip()
        cur.execute("""
        UPDATE ventas_detalle
        SET series_texto=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id, venta_id, producto_id
        """, (series_texto, detalle_id, DEFAULT_SUCURSAL, sucursal))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "msg": "Detalle no encontrado"}

        _, venta_id, producto_id = row
        cur.execute("SELECT tipo, numero FROM ventas WHERE id=%s", (venta_id,))
        doc = cur.fetchone() or ("DOCUMENTO", str(venta_id))
        doc_ref = f"{doc[0]} {doc[1]}"

        series = split_series_text(series_texto)
        for serie in series:
            cur.execute("""
            UPDATE producto_series
            SET estado='VENDIDO',
                fecha_salida=COALESCE(fecha_salida, TO_CHAR((timezone('America/Lima', now()))::date, 'YYYY-MM-DD'))
            WHERE regexp_replace(UPPER(COALESCE(serie,'')), '[^A-Z0-9]', '', 'g')=%s
              AND producto_id=%s
              AND COALESCE(sucursal,%s)=%s
            """, (serie, producto_id, DEFAULT_SUCURSAL, sucursal))

        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,%s,%s,%s,%s)
        """, (data.usuario or "", "", sucursal, "SERIES DOCUMENTO ACTUALIZADAS", f"{doc_ref} - {series_texto}"))

        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "id": detalle_id, "series_texto": series_texto}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


def restaurar_stock_documento(cur, documento_id, tipo, sucursal):
    sucursal_stock = inventario_sucursal(sucursal)
    cur.execute("""
    SELECT producto_id, COALESCE(cantidad, 0), COALESCE(series_texto, '')
    FROM ventas_detalle
    WHERE venta_id=%s
    """, (documento_id,))
    detalles = cur.fetchall()
    touched = set()
    if str(tipo or "").upper() in STOCK_DOC_TYPES:
        for producto_id, cantidad, series_texto in detalles:
            series = split_series_text(series_texto)
            if series:
                cur.execute("""
                UPDATE producto_series
                SET estado='DISPONIBLE', fecha_salida=NULL
                WHERE COALESCE(sucursal,%s)=%s
                  AND regexp_replace(UPPER(COALESCE(serie,'')), '[^A-Z0-9]', '', 'g')=ANY(%s)
                """, (DEFAULT_SUCURSAL, sucursal_stock, series))
                cur.execute("""
                SELECT DISTINCT producto_id
                FROM producto_series
                WHERE COALESCE(sucursal,%s)=%s
                  AND regexp_replace(UPPER(COALESCE(serie,'')), '[^A-Z0-9]', '', 'g')=ANY(%s)
                  AND producto_id IS NOT NULL
                """, (DEFAULT_SUCURSAL, sucursal_stock, series))
                for prow in cur.fetchall():
                    if prow and prow[0]:
                        touched.add(prow[0])
                if producto_id:
                    touched.add(producto_id)
            elif producto_id:
                cur.execute("""
                UPDATE productos
                SET stock = COALESCE(stock, 0) + %s
                WHERE id = %s AND COALESCE(sucursal,%s)=%s
                """, (cantidad or 0, producto_id, DEFAULT_SUCURSAL, sucursal_stock))
        for producto_id in touched:
            sync_producto_stock_from_series(cur, producto_id, sucursal_stock)


@app.post("/documentos/{documento_id}/anular")
def anular_documento(documento_id: int, data: dict = None, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        payload = data or {}
        sucursal = norm_sucursal(payload.get("sucursal") or sucursal)
        usuario = str(payload.get("usuario") or "").strip()
        motivo = str(payload.get("motivo") or "Anulado desde ERP").strip()
        cur.execute("""
        SELECT tipo, numero, COALESCE(estado,'EMITIDO'), COALESCE(sucursal,%s)
        FROM ventas
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (DEFAULT_SUCURSAL, documento_id, DEFAULT_SUCURSAL, sucursal))
        venta = cur.fetchone()
        if not venta:
            conn.close()
            return {"ok": False, "success": False, "msg": "Documento no encontrado"}
        tipo, numero, estado, sucursal = venta
        if str(estado or "").upper() == "ANULADO":
            conn.close()
            return {"ok": False, "success": False, "msg": f"{tipo} {numero} ya esta anulado."}

        restaurar_stock_documento(cur, documento_id, tipo, sucursal)
        cur.execute("""
        UPDATE ventas
        SET estado='ANULADO',
            observacion_interna=TRIM(COALESCE(observacion_interna,'') || CASE WHEN COALESCE(observacion_interna,'')='' THEN '' ELSE E'\n' END || %s)
        WHERE id=%s
        """, (f"ANULADO: {motivo}", documento_id))
        cur.execute("""
        UPDATE caja_movimientos
        SET estado_pago='ANULADO',
            observacion=TRIM(COALESCE(observacion,'') || CASE WHEN COALESCE(observacion,'')='' THEN '' ELSE E'\n' END || %s)
        WHERE documento_tipo=%s AND documento_numero=%s AND COALESCE(sucursal,%s)=%s
        """, (f"ANULADO por {usuario or 'SISTEMA'}: {motivo}", tipo, numero, DEFAULT_SUCURSAL, sucursal))
        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,'',%s,'DOCUMENTO ANULADO',%s)
        """, (usuario, sucursal, f"{tipo} {numero} - {motivo}"))
        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "id": documento_id, "tipo": tipo, "numero": numero, "msg": f"{tipo} {numero} anulado. Stock restaurado."}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.delete("/documentos/{documento_id}")
def eliminar_documento(documento_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cur.execute("SELECT tipo, numero, COALESCE(sucursal,%s) FROM ventas WHERE id=%s AND COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, documento_id, DEFAULT_SUCURSAL, sucursal))
        venta = cur.fetchone()
        if not venta:
            conn.close()
            return {"ok": False, "msg": "Documento no encontrado"}

        tipo, numero, sucursal = venta

        restaurar_stock_documento(cur, documento_id, tipo, sucursal)

        cur.execute("DELETE FROM ventas_detalle WHERE venta_id=%s", (documento_id,))
        cur.execute("""
        DELETE FROM caja_movimientos
        WHERE documento_tipo=%s AND documento_numero=%s AND COALESCE(sucursal,%s)=%s
        """, (tipo, numero, DEFAULT_SUCURSAL, sucursal))
        cur.execute("DELETE FROM ventas WHERE id=%s", (documento_id,))

        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "id": documento_id, "tipo": tipo, "numero": numero}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


@app.post("/stock/transferir")
def transferir_stock(data: StockTransferencia):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS observacion TEXT DEFAULT ''")
        origen_real = norm_sucursal(data.sucursal_origen)
        destino_real = norm_sucursal(data.sucursal_destino)
        origen = inventario_sucursal(origen_real)
        destino = inventario_sucursal(destino_real)
        cantidad = int(data.cantidad or 0)
        if cantidad <= 0:
            conn.close()
            return {"ok": False, "msg": "La cantidad debe ser mayor a 0"}
        if origen == destino:
            conn.close()
            return {"ok": False, "msg": "La sucursal origen y destino usan el mismo inventario fisico."}

        cur.execute("""
        SELECT id, nombre, categoria, marca, modelo, precio_compra, precio_venta,
               COALESCE(stock,0) AS stock, COALESCE(imagen_url,'') AS imagen_url,
               COALESCE(observacion,'') AS observacion,
               COALESCE(woo_id,0) AS woo_id, COALESCE(sku_woo,'') AS sku_woo
        FROM productos
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        FOR UPDATE
        """, (data.producto_id, DEFAULT_SUCURSAL, origen))
        producto = dict_fetchone(cur)
        if not producto:
            conn.close()
            return {"ok": False, "msg": "Producto no encontrado en sucursal origen"}
        if int(producto.get("stock") or 0) < cantidad:
            conn.close()
            return {"ok": False, "msg": "Stock insuficiente en sucursal origen"}

        cur.execute("""
        UPDATE productos
        SET stock = COALESCE(stock,0) - %s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (cantidad, data.producto_id, DEFAULT_SUCURSAL, origen))

        cur.execute("""
        SELECT id FROM productos
        WHERE COALESCE(sucursal,%s)=%s
          AND (
            (%s <> '' AND COALESCE(sku_woo,'')=%s)
            OR LOWER(COALESCE(nombre,''))=LOWER(%s)
          )
        LIMIT 1
        """, (
            DEFAULT_SUCURSAL, destino,
            producto.get("sku_woo") or "", producto.get("sku_woo") or "",
            producto.get("nombre") or "",
        ))
        destino_row = cur.fetchone()
        if destino_row:
            destino_id = destino_row[0]
            cur.execute("""
            UPDATE productos
            SET stock = COALESCE(stock,0) + %s,
                categoria=%s, marca=%s, modelo=%s,
                precio_compra=%s, precio_venta=%s,
                imagen_url=CASE WHEN COALESCE(imagen_url,'')='' THEN %s ELSE imagen_url END,
                observacion=CASE WHEN COALESCE(observacion,'')='' THEN %s ELSE observacion END
            WHERE id=%s
            """, (
                cantidad, producto.get("categoria"), producto.get("marca"), producto.get("modelo"),
                producto.get("precio_compra"), producto.get("precio_venta"),
                producto.get("imagen_url") or "", producto.get("observacion") or "", destino_id,
            ))
        else:
            cur.execute("""
            INSERT INTO productos (
                nombre, categoria, marca, modelo, precio_compra, precio_venta,
                stock, imagen_url, observacion, sucursal, woo_id, sku_woo
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """, (
                producto.get("nombre"), producto.get("categoria"), producto.get("marca"), producto.get("modelo"),
                producto.get("precio_compra"), producto.get("precio_venta"),
                cantidad, producto.get("imagen_url") or "", producto.get("observacion") or "", destino,
                producto.get("woo_id") or None, producto.get("sku_woo") or "",
            ))
            destino_id = cur.fetchone()[0]

        cur.execute("""
        INSERT INTO stock_transferencias (
            producto_id, producto_nombre, cantidad, sucursal_origen,
            sucursal_destino, usuario, nota
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """, (
            data.producto_id, producto.get("nombre") or "", cantidad,
            origen_real, destino_real, data.usuario or "", data.nota or "",
        ))
        transferencia_id = cur.fetchone()[0]

        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,%s,%s,%s,%s)
        """, (
            data.usuario or "", "", origen,
            "TRANSFERENCIA STOCK",
            f"{cantidad} x {producto.get('nombre')} de {origen_real} a {destino_real}",
        ))

        conn.commit()
        conn.close()
        return {
            "ok": True,
            "success": True,
            "id": transferencia_id,
            "producto_destino_id": destino_id,
            "msg": "Transferencia realizada"
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


@app.put("/documentos/{documento_id}/estado-pago")
def actualizar_estado_pago_documento(documento_id: int, data: EstadoPagoUpdate, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        estado_pago = (data.estado_pago or "PAGADO").upper()
        if estado_pago not in ("PAGADO", "CREDITO", "DEUDA"):
            estado_pago = "PAGADO"

        metodo_pago = data.metodo_pago.upper() if data.metodo_pago else None
        cur.execute("""
            SELECT COALESCE(total,0), COALESCE(comprobantes_pago_json,'')
            FROM ventas
            WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (documento_id, DEFAULT_SUCURSAL, sucursal))
        total_row = cur.fetchone()
        total_doc = float(total_row[0] or 0) if total_row else 0.0
        comprobantes_existentes = total_row[1] if total_row else ""
        pagos_detalle, pagos_total, metodo_resumen, pagos_detalle_json = normalizar_pagos_detalle(data.pagos_detalle, metodo_pago, data.monto_pagado)
        if pagos_detalle:
            metodo_pago = metodo_resumen
        monto_pagado = pagos_total if pagos_detalle else data.monto_pagado
        if monto_pagado is None:
            monto_pagado = total_doc if estado_pago == "PAGADO" else 0
        monto_pagado = max(0.0, float(monto_pagado or 0))
        saldo_pago = max(0.0, round(total_doc - monto_pagado, 2))
        if monto_pagado >= total_doc and total_doc > 0:
            estado_pago = "PAGADO"
            saldo_pago = 0.0
        elif monto_pagado > 0:
            estado_pago = "CREDITO"
        elif estado_pago == "PAGADO" and total_doc <= 0:
            saldo_pago = 0.0

        comprobantes, comprobante, comprobantes_json = normalizar_comprobantes_pago(data, comprobantes_existentes)

        cur.execute("""
        UPDATE ventas
        SET estado_pago=%s,
            metodo_pago=COALESCE(%s, metodo_pago, ''),
            monto_pagado=%s,
            pagos_detalle_json=%s,
            saldo_pago=%s,
            observacion_pago=%s,
            comprobante_pago=COALESCE(%s, comprobante_pago, ''),
            comprobante_pago_nombre=COALESCE(%s, comprobante_pago_nombre, ''),
            comprobante_pago_mime=COALESCE(%s, comprobante_pago_mime, ''),
            comprobante_pago_tamano=COALESCE(%s, comprobante_pago_tamano, 0),
            comprobante_pago_base64=COALESCE(%s, comprobante_pago_base64, ''),
            comprobante_pago_data_url=COALESCE(%s, comprobante_pago_data_url, ''),
            comprobantes_pago_json=COALESCE(%s, comprobantes_pago_json, '')
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id, tipo, numero, cliente, total, usuario_emisor, COALESCE(metodo_pago, ''), COALESCE(sucursal,%s), COALESCE(monto_pagado,0), COALESCE(saldo_pago,0), COALESCE(pagos_detalle_json,''),
                  COALESCE(comprobante_pago,''), COALESCE(comprobante_pago_nombre,''), COALESCE(comprobante_pago_mime,''), COALESCE(comprobante_pago_tamano,0),
                  COALESCE(comprobante_pago_base64,''), COALESCE(comprobante_pago_data_url,''), COALESCE(comprobantes_pago_json,'')
        """, (
            estado_pago, metodo_pago, monto_pagado, pagos_detalle_json, saldo_pago, data.observacion_pago or "",
            comprobante["comprobante_pago"], comprobante["comprobante_pago_nombre"], comprobante["comprobante_pago_mime"],
            comprobante["comprobante_pago_tamano"], comprobante["comprobante_pago_base64"], comprobante["comprobante_pago_data_url"], comprobantes_json,
            documento_id, DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL
        ))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "msg": "Documento no encontrado"}

        (
            venta_id, tipo, numero, cliente, total, usuario, metodo_pago_db, sucursal_db,
            monto_pagado_db, saldo_pago_db, pagos_detalle_json_db, comprobante_pago_db, comprobante_nombre_db,
            comprobante_mime_db, comprobante_tamano_db, comprobante_base64_db,
            comprobante_data_url_db, comprobantes_json_db
        ) = row

        cur.execute("""
        UPDATE caja_movimientos
        SET tipo=%s, estado_pago=%s, metodo_pago=%s, monto=%s, observacion=%s
        WHERE documento_tipo=%s AND documento_numero=%s
          AND COALESCE(sucursal,%s)=%s
        """, ("INGRESO" if estado_pago == "PAGADO" else estado_pago, estado_pago, metodo_pago_db, monto_pagado_db, data.observacion_pago or "", tipo, numero, DEFAULT_SUCURSAL, sucursal_db))

        if cur.rowcount == 0:
            cur.execute("""
            INSERT INTO caja_movimientos (
                tipo, detalle, monto, usuario, documento_tipo, documento_numero, estado_pago, metodo_pago, observacion, sucursal
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                "INGRESO" if estado_pago == "PAGADO" else estado_pago,
                f"{tipo} {numero} - {cliente}",
                monto_pagado_db, usuario or "", tipo, numero, estado_pago, metodo_pago_db, data.observacion_pago or "", sucursal_db
            ))

        conn.commit()
        conn.close()
        return {
            "ok": True,
            "success": True,
            "id": venta_id,
            "estado_pago": estado_pago,
            "metodo_pago": metodo_pago_db,
            "monto_pagado": float(monto_pagado_db or 0),
            "saldo_pago": float(saldo_pago_db or 0),
            "pagos_detalle": cargar_comprobantes_json(pagos_detalle_json_db),
            "pagos_detalle_json": pagos_detalle_json_db,
            "comprobante_pago": comprobante_pago_db,
            "comprobante_pago_nombre": comprobante_nombre_db,
            "comprobante_pago_mime": comprobante_mime_db,
            "comprobante_pago_tamano": float(comprobante_tamano_db or 0),
            "comprobante_pago_base64": comprobante_base64_db,
            "comprobante_pago_data_url": comprobante_data_url_db,
            "comprobantes_pago": cargar_comprobantes_json(comprobantes_json_db),
            "comprobantes_pago_json": comprobantes_json_db,
        }
    except ValueError as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


@app.put("/documentos/{documento_id}/sunat")
def actualizar_estado_sunat(documento_id: int, data: EstadoSunatUpdate, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        estado = (data.sunat_estado or "PROCESO").upper()
        if estado not in ("PENDIENTE", "PROCESO", "ACEPTADO", "RECHAZADO", "INTERNO"):
            estado = "PROCESO"
        modo = (data.sunat_modo or "MANUAL").upper()
        if modo not in ("MANUAL", "NO_ENVIAR", "ELECTRONICO", "API", "PLATAFORM"):
            modo = "MANUAL"

        cur.execute("""
        UPDATE ventas
        SET sunat_estado=%s,
            sunat_modo=%s,
            sunat_fecha=CASE WHEN %s IN ('PROCESO','ACEPTADO','RECHAZADO') THEN CURRENT_TIMESTAMP ELSE sunat_fecha END
        WHERE id=%s
          AND tipo IN ('BOLETA','FACTURA')
          AND COALESCE(sucursal,%s)=%s
        RETURNING id, tipo, numero, sunat_estado, sunat_modo, sunat_fecha
        """, (estado, modo, estado, documento_id, DEFAULT_SUCURSAL, sucursal))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "msg": "Documento no encontrado o no es boleta/factura"}
        conn.commit()
        conn.close()
        return {
            "ok": True,
            "success": True,
            "id": row[0],
            "tipo": row[1],
            "numero": row[2],
            "sunat_estado": row[3],
            "sunat_modo": row[4],
            "sunat_fecha": row[5],
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


def _sunat_parse_activation_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[:19] if "T" not in fmt else text.replace("Z", "")[:19], fmt)
            if fmt == "%Y-%m-%d":
                return parsed.replace(hour=0, minute=0, second=0, microsecond=0)
            return parsed
        except Exception:
            continue
    return None


def _sunat_defaults_nuevo_documento(cur, sucursal, fecha_emision):
    cfg = _sunat_get_config(cur, sucursal)
    activation = _sunat_parse_activation_datetime(cfg.get("fecha_activacion_sunat"))
    if not activation:
        return "INTERNO", "NO_ENVIAR"
    doc_fecha = fecha_emision
    if isinstance(doc_fecha, datetime):
        doc_fecha_cmp = doc_fecha
    else:
        doc_fecha_cmp = parse_fecha_emision(doc_fecha)
    if doc_fecha_cmp >= activation:
        return "PENDIENTE", "ELECTRONICO"
    return "INTERNO", "NO_ENVIAR"


def _sunat_envio_bloqueado(doc):
    modo = str(doc.get("sunat_modo") or "").strip().upper()
    estado = str(doc.get("sunat_estado") or "").strip().upper()
    if modo in ("NO_ENVIAR", "INTERNO") or estado == "INTERNO":
        return True, "Documento interno de caja. No se envia a SUNAT."
    return False, ""


SUNAT_DEFAULT_ENDPOINTS = {
    "BETA": "https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService",
    "PRODUCCION": "https://e-factura.sunat.gob.pe/ol-ti-itcpfegem/billService",
}

SUNAT_NS = {
    "": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}
SUNAT_EXT_NS = SUNAT_NS["ext"]
SUNAT_CBC_NS = SUNAT_NS["cbc"]
for _sunat_prefix, _sunat_uri in SUNAT_NS.items():
    ET.register_namespace(_sunat_prefix, _sunat_uri)


def _sunat_tag(prefix, name):
    uri = SUNAT_NS[prefix]
    return f"{{{uri}}}{name}"


def _sunat_el(parent, prefix, name, text=None, attrs=None):
    node = ET.SubElement(parent, _sunat_tag(prefix, name), attrs or {})
    if text is not None:
        node.text = str(text)
    return node


def _sunat_money(value):
    try:
        return f"{float(value or 0):.2f}"
    except Exception:
        return "0.00"


def _sunat_clean_ruc(value):
    return re.sub(r"[^0-9]", "", str(value or ""))


def _sunat_env_suffix(sucursal):
    text = norm_sucursal(sucursal)
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def _sunat_env(sucursal, name, default=""):
    suffix = _sunat_env_suffix(sucursal)
    specific = os.getenv(f"SUNAT_{suffix}_{name}")
    if specific is not None:
        return specific
    return os.getenv(f"SUNAT_{name}", default)


def _sunat_env_cert_pfx_base64(sucursal):
    encoded = str(_sunat_env(sucursal, "CERT_PFX_BASE64", "") or "").strip()
    if encoded:
        return encoded
    cert_path = str(_sunat_env(sucursal, "CERT_PFX_PATH", "") or "").strip()
    if cert_path and os.path.exists(cert_path):
        with open(cert_path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")
    return ""


def _sunat_get_config(cur, sucursal):
    sucursal = norm_sucursal(sucursal)
    cfg = {
        "ambiente": _sunat_env(sucursal, "AMBIENTE", "BETA").strip().upper() or "BETA",
        "envio_automatico": str(_sunat_env(sucursal, "ENVIO_AUTOMATICO", "")).strip().lower() in ("1", "true", "si", "yes", "on"),
        "proveedor_sunat": str(_sunat_env(sucursal, "PROVEEDOR", "directo")).strip().lower() or "directo",
        "api_base_url": str(_sunat_env(sucursal, "API_BASE_URL", os.getenv("PLATAFORM_SUNAT_BASE_URL", "https://apigo.apuuraydev.com/api/v1"))).strip(),
        "api_key": str(_sunat_env(sucursal, "API_KEY", "")).strip(),
        "api_secret": str(_sunat_env(sucursal, "API_SECRET", "")).strip(),
        "api_sucursal_id": int(_sunat_env(sucursal, "API_SUCURSAL_ID", "1") or "1"),
        "ruc": _sunat_env(sucursal, "RUC", "").strip(),
        "razon_social": _sunat_env(sucursal, "RAZON_SOCIAL", "").strip(),
        "nombre_comercial": _sunat_env(sucursal, "NOMBRE_COMERCIAL", "").strip(),
        "ubigeo": _sunat_env(sucursal, "UBIGEO", "150101").strip() or "150101",
        "direccion": _sunat_env(sucursal, "DIRECCION", "").strip(),
        "departamento": _sunat_env(sucursal, "DEPARTAMENTO", "LIMA").strip() or "LIMA",
        "provincia": _sunat_env(sucursal, "PROVINCIA", "LIMA").strip() or "LIMA",
        "distrito": _sunat_env(sucursal, "DISTRITO", "LIMA").strip() or "LIMA",
        "usuario_sol": _sunat_env(sucursal, "USUARIO_SOL", "").strip().upper(),
        "clave_sol": _sunat_env(sucursal, "CLAVE_SOL", "").strip(),
        "endpoint_url": _sunat_env(sucursal, "ENDPOINT_URL", "").strip(),
        "certificado_pfx_base64": _sunat_env_cert_pfx_base64(sucursal),
        "certificado_password": _sunat_env(sucursal, "CERT_PASSWORD", "").strip(),
        "fecha_activacion_sunat": _sunat_env(sucursal, "FECHA_ACTIVACION", "").strip(),
    }
    try:
        cur.execute("SELECT valor FROM app_config WHERE clave=%s", (f"sunat:{sucursal}",))
        row = cur.fetchone()
        if row and row[0]:
            saved = json.loads(row[0])
            if isinstance(saved, dict):
                for key, value in saved.items():
                    if key == "usuario_sol":
                        cfg[key] = str(value or "").strip().upper()
                        continue
                    if value not in (None, ""):
                        cfg[key] = str(value).strip()
    except Exception:
        pass
    cfg["ambiente"] = str(cfg.get("ambiente") or "BETA").strip().upper()
    if cfg["ambiente"] not in ("BETA", "PRODUCCION"):
        cfg["ambiente"] = "BETA"
    if not cfg.get("endpoint_url"):
        cfg["endpoint_url"] = SUNAT_DEFAULT_ENDPOINTS[cfg["ambiente"]]
    proveedor = str(cfg.get("proveedor_sunat") or "directo").strip().lower()
    if proveedor not in ("directo", "plataform", "plataforma", "api", "kodevo", "apigo"):
        proveedor = "directo"
    cfg["proveedor_sunat"] = "plataform" if proveedor in ("plataform", "plataforma", "api", "kodevo", "apigo") else "directo"
    if not str(cfg.get("api_base_url") or "").strip():
        cfg["api_base_url"] = "https://apigo.apuuraydev.com/api/v1"
    try:
        cfg["api_sucursal_id"] = max(1, int(cfg.get("api_sucursal_id") or 1))
    except Exception:
        cfg["api_sucursal_id"] = 1
    return cfg


def _sunat_usa_plataform(cfg):
    return str((cfg or {}).get("proveedor_sunat") or "").strip().lower() == "plataform"


def _sunat_emision_habilitada():
    return str(os.getenv("SUNAT_EMISION_HABILITADA", "0")).strip().lower() in ("1", "true", "si", "yes", "on")


def _sunat_public_config(cfg):
    public = dict(cfg)
    for key in ("clave_sol", "certificado_pfx_base64", "certificado_password", "api_secret"):
        public[key] = "CONFIGURADO" if cfg.get(key) else ""
    public["ruc"] = _sunat_clean_ruc(public.get("ruc"))
    public["proveedor_sunat"] = str(cfg.get("proveedor_sunat") or "directo").strip().lower()
    public["api_key"] = str(cfg.get("api_key") or "").strip()
    public["api_base_url"] = str(cfg.get("api_base_url") or "").strip()
    public["api_sucursal_id"] = int(cfg.get("api_sucursal_id") or 1)
    public["listo_envio"] = bool(public.get("ruc") and cfg.get("clave_sol") and public.get("endpoint_url"))
    public["firma_configurada"] = bool(cfg.get("certificado_pfx_base64") and cfg.get("certificado_password"))
    public["plataform_configurada"] = bool(cfg.get("api_key") and cfg.get("api_secret") and public.get("api_base_url"))
    public["envio_automatico"] = bool(str(cfg.get("envio_automatico")).lower() in ("1", "true", "si", "yes", "on"))
    if _sunat_usa_plataform(cfg):
        public["listo_emitir"] = bool(public["plataform_configurada"])
        public["listo_envio"] = bool(public["plataform_configurada"])
    else:
        public["listo_emitir"] = bool(public["listo_envio"] and public["firma_configurada"])
    public["emision_habilitada"] = _sunat_emision_habilitada()
    public["puede_enviar_sunat"] = bool(public["listo_emitir"] and public["emision_habilitada"])
    return public


def _sunat_verificar_certificado(cfg):
    if not cfg.get("certificado_pfx_base64") or not cfg.get("certificado_password"):
        return {"ok": False, "msg": "Sin certificado digital configurado."}
    if not load_key_and_certificates:
        return {"ok": False, "msg": "Falta libreria cryptography en el servidor."}
    try:
        pfx_bytes = base64.b64decode(cfg.get("certificado_pfx_base64"))
        private_key, certificate, extra_certs = load_key_and_certificates(
            pfx_bytes,
            str(cfg.get("certificado_password") or "").encode("utf-8"),
        )
        if not private_key or not certificate:
            return {"ok": False, "msg": "El certificado no contiene llave privada valida."}
        subject = certificate.subject.rfc4514_string()
        not_after = certificate.not_valid_after_utc.isoformat() if hasattr(certificate, "not_valid_after_utc") else ""
        return {
            "ok": True,
            "msg": "Certificado ARMY cargado correctamente.",
            "subject": subject,
            "vence": not_after,
            "cadenas_extra": len(extra_certs or []),
        }
    except Exception as exc:
        return {"ok": False, "msg": str(exc)}


def _sunat_documento_payload(cur, documento_id, sucursal):
    cur.execute("""
    SELECT id, tipo, numero, cliente, COALESCE(documento_cliente,''), COALESCE(direccion_cliente,''),
           COALESCE(subtotal,0), COALESCE(igv,0), COALESCE(total,0), fecha,
           COALESCE(sucursal,%s), COALESCE(sunat_xml_nombre,''), COALESCE(sunat_xml_base64,''),
           COALESCE(sunat_zip_nombre,''), COALESCE(sunat_zip_base64,''), COALESCE(sunat_hash,''),
           COALESCE(sunat_estado,'PENDIENTE'), COALESCE(sunat_respuesta_json,''),
           COALESCE(sunat_modo,'MANUAL')
    FROM ventas
    WHERE id=%s AND COALESCE(sucursal,%s)=%s
      AND UPPER(COALESCE(tipo,'')) IN ('BOLETA','FACTURA')
    """, (DEFAULT_SUCURSAL, documento_id, DEFAULT_SUCURSAL, sucursal))
    row = cur.fetchone()
    if not row:
        return None, []
    doc = {
        "id": row[0], "tipo": row[1], "numero": row[2], "cliente": row[3],
        "documento_cliente": row[4], "direccion_cliente": row[5],
        "subtotal": float(row[6] or 0), "igv": float(row[7] or 0), "total": float(row[8] or 0),
        "fecha": row[9], "sucursal": row[10], "sunat_xml_nombre": row[11],
        "sunat_xml_base64": row[12], "sunat_zip_nombre": row[13], "sunat_zip_base64": row[14],
        "sunat_hash": row[15], "sunat_estado": row[16], "sunat_respuesta_json": row[17],
        "sunat_modo": row[18],
    }
    cur.execute("""
    SELECT COALESCE(descripcion,''), COALESCE(cantidad,0), COALESCE(precio,0), COALESCE(total,0),
           COALESCE(series_texto,''), COALESCE(producto_id,0)
    FROM ventas_detalle
    WHERE venta_id=%s
    ORDER BY id
    """, (documento_id,))
    detalle = [
        {
            "descripcion": r[0] or "PRODUCTO",
            "cantidad": int(r[1] or 0),
            "precio": float(r[2] or 0),
            "total": float(r[3] or 0),
            "series_texto": r[4] or "",
            "producto_id": r[5],
        }
        for r in cur.fetchall()
    ]
    return doc, detalle


def _sunat_cliente_doc(documento_cliente):
    text = str(documento_cliente or "").strip()
    upper = text.upper()
    number = re.sub(r"[^0-9]", "", text)
    if "RUC" in upper or len(number) == 11:
        return "6", number
    if "DNI" in upper or len(number) == 8:
        return "1", number
    return "0", number or "-"


def _sunat_build_invoice_xml(doc, detalle, cfg):
    tipo = str(doc.get("tipo") or "").upper()
    tipo_codigo = "01" if tipo == "FACTURA" else "03"
    numero = str(doc.get("numero") or "").strip().upper()
    ruc = _sunat_clean_ruc(cfg.get("ruc"))
    if not ruc or len(ruc) != 11:
        raise ValueError("Configura SUNAT_RUC o /sunat/config con un RUC valido de 11 digitos.")
    if not numero or "-" not in numero:
        raise ValueError("El documento debe tener serie-numero, por ejemplo B001-000001.")
    fecha = doc.get("fecha")
    if isinstance(fecha, datetime):
        fecha_txt = fecha.date().isoformat()
        hora_txt = fecha.strftime("%H:%M:%S")
    else:
        fecha_txt = lima_today_iso()
        hora_txt = "00:00:00"
    total = round(float(doc.get("total") or 0), 2)
    igv = round(float(doc.get("igv") or 0), 2)
    gravada = round(float(doc.get("subtotal") or 0), 2)
    if total > 0 and (gravada <= 0 or igv <= 0):
        gravada = round(total / 1.18, 2)
        igv = round(total - gravada, 2)

    invoice = ET.Element(_sunat_tag("", "Invoice"))
    _sunat_el(invoice, "cbc", "UBLVersionID", "2.1")
    _sunat_el(invoice, "cbc", "CustomizationID", "2.0")
    _sunat_el(invoice, "cbc", "ID", numero)
    _sunat_el(invoice, "cbc", "IssueDate", fecha_txt)
    _sunat_el(invoice, "cbc", "IssueTime", hora_txt)
    _sunat_el(invoice, "cbc", "InvoiceTypeCode", tipo_codigo, {
        "listAgencyName": "PE:SUNAT",
        "listName": "Tipo de Documento",
        "listURI": "urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo01",
    })
    _sunat_el(invoice, "cbc", "DocumentCurrencyCode", "PEN")

    supplier = _sunat_el(invoice, "cac", "AccountingSupplierParty")
    party = _sunat_el(supplier, "cac", "Party")
    ident = _sunat_el(party, "cac", "PartyIdentification")
    _sunat_el(ident, "cbc", "ID", ruc, {"schemeID": "6"})
    name = cfg.get("nombre_comercial") or cfg.get("razon_social") or "EMISOR"
    pname = _sunat_el(party, "cac", "PartyName")
    _sunat_el(pname, "cbc", "Name", name)
    legal = _sunat_el(party, "cac", "PartyLegalEntity")
    _sunat_el(legal, "cbc", "RegistrationName", cfg.get("razon_social") or name)
    address = _sunat_el(legal, "cac", "RegistrationAddress")
    _sunat_el(address, "cbc", "ID", cfg.get("ubigeo") or "150101")
    _sunat_el(address, "cbc", "CityName", cfg.get("provincia") or "LIMA")
    _sunat_el(address, "cbc", "CountrySubentity", cfg.get("departamento") or "LIMA")
    _sunat_el(address, "cbc", "District", cfg.get("distrito") or "LIMA")
    addr_line = _sunat_el(address, "cac", "AddressLine")
    _sunat_el(addr_line, "cbc", "Line", cfg.get("direccion") or "-")
    country = _sunat_el(address, "cac", "Country")
    _sunat_el(country, "cbc", "IdentificationCode", "PE")

    customer = _sunat_el(invoice, "cac", "AccountingCustomerParty")
    cparty = _sunat_el(customer, "cac", "Party")
    cdoc_type, cdoc_number = _sunat_cliente_doc(doc.get("documento_cliente"))
    cident = _sunat_el(cparty, "cac", "PartyIdentification")
    _sunat_el(cident, "cbc", "ID", cdoc_number, {"schemeID": cdoc_type})
    clegal = _sunat_el(cparty, "cac", "PartyLegalEntity")
    _sunat_el(clegal, "cbc", "RegistrationName", doc.get("cliente") or "CLIENTE GENERAL")

    tax_total = _sunat_el(invoice, "cac", "TaxTotal")
    _sunat_el(tax_total, "cbc", "TaxAmount", _sunat_money(igv), {"currencyID": "PEN"})
    tax_sub = _sunat_el(tax_total, "cac", "TaxSubtotal")
    _sunat_el(tax_sub, "cbc", "TaxableAmount", _sunat_money(gravada), {"currencyID": "PEN"})
    _sunat_el(tax_sub, "cbc", "TaxAmount", _sunat_money(igv), {"currencyID": "PEN"})
    tax_cat = _sunat_el(tax_sub, "cac", "TaxCategory")
    tax_scheme = _sunat_el(tax_cat, "cac", "TaxScheme")
    _sunat_el(tax_scheme, "cbc", "ID", "1000")
    _sunat_el(tax_scheme, "cbc", "Name", "IGV")
    _sunat_el(tax_scheme, "cbc", "TaxTypeCode", "VAT")

    legal_total = _sunat_el(invoice, "cac", "LegalMonetaryTotal")
    _sunat_el(legal_total, "cbc", "LineExtensionAmount", _sunat_money(gravada), {"currencyID": "PEN"})
    _sunat_el(legal_total, "cbc", "TaxInclusiveAmount", _sunat_money(total), {"currencyID": "PEN"})
    _sunat_el(legal_total, "cbc", "PayableAmount", _sunat_money(total), {"currencyID": "PEN"})

    for idx, item in enumerate(detalle, start=1):
        cantidad = max(1, int(item.get("cantidad") or 1))
        line_total = round(float(item.get("total") or 0), 2)
        unit = round(line_total / cantidad, 2) if cantidad else round(float(item.get("precio") or 0), 2)
        line_gravada = round(line_total / 1.18, 2)
        line_igv = round(line_total - line_gravada, 2)
        line = _sunat_el(invoice, "cac", "InvoiceLine")
        _sunat_el(line, "cbc", "ID", str(idx))
        _sunat_el(line, "cbc", "InvoicedQuantity", str(cantidad), {"unitCode": "NIU"})
        _sunat_el(line, "cbc", "LineExtensionAmount", _sunat_money(line_gravada), {"currencyID": "PEN"})
        pricing = _sunat_el(line, "cac", "PricingReference")
        alt_price = _sunat_el(pricing, "cac", "AlternativeConditionPrice")
        _sunat_el(alt_price, "cbc", "PriceAmount", _sunat_money(unit), {"currencyID": "PEN"})
        _sunat_el(alt_price, "cbc", "PriceTypeCode", "01")
        ltax = _sunat_el(line, "cac", "TaxTotal")
        _sunat_el(ltax, "cbc", "TaxAmount", _sunat_money(line_igv), {"currencyID": "PEN"})
        lsub = _sunat_el(ltax, "cac", "TaxSubtotal")
        _sunat_el(lsub, "cbc", "TaxableAmount", _sunat_money(line_gravada), {"currencyID": "PEN"})
        _sunat_el(lsub, "cbc", "TaxAmount", _sunat_money(line_igv), {"currencyID": "PEN"})
        lcat = _sunat_el(lsub, "cac", "TaxCategory")
        _sunat_el(lcat, "cbc", "Percent", "18.00")
        _sunat_el(lcat, "cbc", "TaxExemptionReasonCode", "10")
        lscheme = _sunat_el(lcat, "cac", "TaxScheme")
        _sunat_el(lscheme, "cbc", "ID", "1000")
        _sunat_el(lscheme, "cbc", "Name", "IGV")
        _sunat_el(lscheme, "cbc", "TaxTypeCode", "VAT")
        desc = item.get("descripcion") or "PRODUCTO"
        if item.get("series_texto"):
            desc = f"{desc} S/N: {item.get('series_texto')}"
        litem = _sunat_el(line, "cac", "Item")
        _sunat_el(litem, "cbc", "Description", desc[:500])
        price = _sunat_el(line, "cac", "Price")
        _sunat_el(price, "cbc", "PriceAmount", _sunat_money(round(unit / 1.18, 2)), {"currencyID": "PEN"})

    xml_bytes = ET.tostring(invoice, encoding="utf-8", xml_declaration=True)
    file_name = f"{ruc}-{tipo_codigo}-{numero}.xml"
    return file_name, xml_bytes


def _sunat_zip_xml(xml_name, xml_bytes):
    zip_buffer = io.BytesIO()
    zip_name = xml_name.replace(".xml", ".zip")
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(xml_name, xml_bytes)
    data = zip_buffer.getvalue()
    return zip_name, data


def _sunat_sign_xml(xml_bytes, cfg):
    if not cfg.get("certificado_pfx_base64") or not cfg.get("certificado_password"):
        return xml_bytes, False, "Certificado no configurado."
    if not (LET and XMLSigner and methods and load_key_and_certificates and serialization):
        raise RuntimeError("Instala dependencias de firma: signxml, cryptography y lxml.")
    pfx_bytes = base64.b64decode(cfg.get("certificado_pfx_base64"))
    private_key, certificate, extra_certs = load_key_and_certificates(
        pfx_bytes,
        str(cfg.get("certificado_password") or "").encode("utf-8"),
    )
    if not private_key or not certificate:
        raise RuntimeError("El PFX no contiene llave privada/certificado valido.")
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_chain = [certificate]
    if extra_certs:
        cert_chain.extend(extra_certs)
    cert_pems = [
        cert.public_bytes(serialization.Encoding.PEM)
        for cert in cert_chain
    ]
    root = LET.fromstring(xml_bytes)
    extensions = LET.Element(f"{{{SUNAT_EXT_NS}}}UBLExtensions", nsmap={"ext": SUNAT_EXT_NS})
    extension = LET.SubElement(extensions, f"{{{SUNAT_EXT_NS}}}UBLExtension")
    ext_content = LET.SubElement(extension, f"{{{SUNAT_EXT_NS}}}ExtensionContent")
    root.insert(0, extensions)

    signed = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    ).sign(root, key=key_pem, cert=cert_pems)
    sig = signed.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
    if sig is not None:
        sig_parent = sig.getparent()
        if sig_parent is not None:
            sig_parent.remove(sig)
        ext_content.append(sig)
    return LET.tostring(signed, xml_declaration=True, encoding="utf-8"), True, "XML firmado."


def _sunat_save_artifacts(cur, documento_id, xml_name, xml_bytes, zip_name, zip_bytes, estado="GENERADO", respuesta=None):
    xml_b64 = base64.b64encode(xml_bytes).decode("ascii")
    zip_b64 = base64.b64encode(zip_bytes).decode("ascii")
    digest = hashlib.sha256(xml_bytes).hexdigest()
    respuesta_json = json.dumps(respuesta or {}, ensure_ascii=False)
    cur.execute("""
    UPDATE ventas
    SET sunat_xml_nombre=%s,
        sunat_xml_base64=%s,
        sunat_zip_nombre=%s,
        sunat_zip_base64=%s,
        sunat_hash=%s,
        sunat_estado=%s,
        sunat_modo='API',
        sunat_fecha=CURRENT_TIMESTAMP,
        sunat_respuesta_json=%s
    WHERE id=%s
    """, (xml_name, xml_b64, zip_name, zip_b64, digest, estado, respuesta_json, documento_id))
    return {"xml_nombre": xml_name, "zip_nombre": zip_name, "hash": digest, "xml_base64": xml_b64, "zip_base64": zip_b64}


def _sunat_generate_for_document(cur, documento_id, sucursal):
    doc, detalle = _sunat_documento_payload(cur, documento_id, sucursal)
    if not doc:
        raise ValueError("Documento no encontrado o no es BOLETA/FACTURA.")
    if not detalle:
        raise ValueError("El documento no tiene detalle.")
    cfg = _sunat_get_config(cur, doc.get("sucursal") or sucursal)
    xml_name, xml_bytes = _sunat_build_invoice_xml(doc, detalle, cfg)
    xml_bytes, firmado, firma_msg = _sunat_sign_xml(xml_bytes, cfg)
    zip_name, zip_bytes = _sunat_zip_xml(xml_name, xml_bytes)
    artifacts = _sunat_save_artifacts(cur, documento_id, xml_name, xml_bytes, zip_name, zip_bytes, respuesta={"firmado": firmado, "firma_msg": firma_msg})
    artifacts["firmado"] = firmado
    artifacts["firma_msg"] = firma_msg
    return doc, cfg, artifacts, xml_bytes, zip_bytes


def _sunat_soap_username(cfg):
    ruc = _sunat_clean_ruc(cfg.get("ruc"))
    usuario_sol = str(cfg.get("usuario_sol") or "").strip().upper()
    if not usuario_sol:
        return ruc
    return f"{ruc}{usuario_sol}"


def _sunat_parse_soap_fault(response_text):
    text = str(response_text or "")
    fault_code = ""
    fault_string = ""
    m_code = re.search(r"<faultcode[^>]*>([^<]+)</faultcode>", text, flags=re.I)
    if m_code:
        fault_code = html.unescape(m_code.group(1).strip())
    m_msg = re.search(r"<faultstring[^>]*>([^<]+)</faultstring>", text, flags=re.I)
    if m_msg:
        fault_string = html.unescape(m_msg.group(1).strip())
    return fault_code, fault_string


def _sunat_soap_send_bill(cfg, zip_name, zip_base64):
    username = _sunat_soap_username(cfg)
    password = str(cfg.get("clave_sol") or "")
    endpoint = cfg.get("endpoint_url") or SUNAT_DEFAULT_ENDPOINTS["BETA"]
    password_type = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText"
    soap = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ser="http://service.sunat.gob.pe" xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
  <soapenv:Header>
    <wsse:Security soapenv:mustUnderstand="1">
      <wsse:UsernameToken Id="SUNAT-TOKEN">
        <wsse:Username>{html.escape(username)}</wsse:Username>
        <wsse:Password Type="{password_type}">{html.escape(password)}</wsse:Password>
      </wsse:UsernameToken>
    </wsse:Security>
  </soapenv:Header>
  <soapenv:Body>
    <ser:sendBill>
      <fileName>{html.escape(zip_name)}</fileName>
      <contentFile>{zip_base64}</contentFile>
    </ser:sendBill>
  </soapenv:Body>
</soapenv:Envelope>"""
    response = requests.post(
        endpoint,
        data=soap.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "urn:sendBill"},
        timeout=60,
    )
    return response.status_code, response.text


@app.get("/sunat/diagnostico")
def diagnostico_sunat(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cfg = _sunat_get_config(cur, sucursal)
        public = _sunat_public_config(cfg)
        clave = str(cfg.get("clave_sol") or "")
        return {
            "ok": True,
            "success": True,
            "sucursal": sucursal,
            "portal_login": {
                "ruc": public.get("ruc"),
                "usuario_sol": public.get("usuario_sol") or "(principal — solo RUC)",
                "nota": "Portal SUNAT: RUC + clave SOL principal. Usuario secundario solo si lo configuras en el ERP.",
            },
            "soap_login": {
                "username": _sunat_soap_username(cfg),
                "clave_configurada": bool(clave),
                "clave_longitud": len(clave),
                "nota": "Usuario principal: solo RUC. Usuario secundario: RUC + codigo (ej. 20611068701ERPFACTU).",
            },
            "config": public,
            "error_0110": {
                "significado": "SUNAT no reconoce el tipo de usuario para facturacion electronica.",
                "causas_frecuentes": [
                    "La clave SOL principal no coincide con la guardada en el ERP.",
                    "El RUC configurado no tiene habilitada la facturacion electronica.",
                    "Si usas usuario secundario, falta asignar programas de comprobantes electronicos.",
                ],
                "que_revisar_en_sunat": [
                    "Ingresar con RUC 20611068701 y clave SOL principal en el portal.",
                    "Tributarios > Comprobantes de pago: SEE-Contribuyente, Envio de documentos, Factura y Boleta electronica.",
                    "Certificado digital comunicado y vigente.",
                ],
            },
            "emision_habilitada": _sunat_emision_habilitada(),
            "listo_emitir": bool(public.get("listo_envio") and public.get("firma_configurada")),
        }
    finally:
        conn.close()


@app.get("/sunat/verificar")
def verificar_instalacion_sunat(sucursal: str = DEFAULT_SUCURSAL):
    """Valida credenciales y certificado sin enviar ningun documento a SUNAT."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cfg = _sunat_get_config(cur, sucursal)
        public = _sunat_public_config(cfg)
        certificado = _sunat_verificar_certificado(cfg)
        listo_emitir = bool(public.get("listo_emitir") and certificado.get("ok"))
        return {
            "ok": listo_emitir,
            "success": listo_emitir,
            "sucursal": sucursal,
            "nota": "Verificacion local completada. No se envio ningun comprobante a SUNAT.",
            "portal_login": {
                "ruc": public.get("ruc"),
                "usuario_sol": public.get("usuario_sol"),
            },
            "soap_login": {
                "username": _sunat_soap_username(cfg),
                "clave_configurada": bool(cfg.get("clave_sol")),
            },
            "config": public,
            "certificado": certificado,
            "listo_emitir": listo_emitir,
            "emision_habilitada": public.get("emision_habilitada"),
            "puede_enviar_sunat": bool(listo_emitir and public.get("emision_habilitada")),
            "bloqueo_emision": None if public.get("emision_habilitada") else "Emision bloqueada en servidor hasta activar SUNAT_EMISION_HABILITADA.",
        }
    finally:
        conn.close()


@app.post("/sunat/probar-credenciales")
def probar_credenciales_sunat(documento_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cfg = _sunat_get_config(cur, sucursal)
        if not cfg.get("clave_sol"):
            return {"ok": False, "success": False, "msg": "Falta clave SOL en la configuracion."}
        doc, _detalle = _sunat_documento_payload(cur, documento_id, sucursal)
        if not doc:
            return {"ok": False, "success": False, "msg": "Documento no encontrado."}
        zip_name = doc.get("sunat_zip_nombre")
        zip_base64 = doc.get("sunat_zip_base64")
        if not zip_name or not zip_base64:
            _doc, _cfg, artifacts, _xml_bytes, _zip_bytes = _sunat_generate_for_document(cur, documento_id, sucursal)
            conn.commit()
            zip_name = artifacts["zip_nombre"]
            zip_base64 = artifacts["zip_base64"]
        status_code, response_text = _sunat_soap_send_bill(cfg, zip_name, zip_base64)
        fault_code, fault_string = _sunat_parse_soap_fault(response_text)
        return {
            "ok": not fault_code,
            "success": not fault_code,
            "documento_id": documento_id,
            "numero": doc.get("numero"),
            "soap_username": _sunat_soap_username(cfg),
            "clave_longitud": len(str(cfg.get("clave_sol") or "")),
            "http_status": status_code,
            "fault_code": fault_code,
            "fault_string": fault_string,
            "respuesta": response_text[:2500],
        }
    except Exception as e:
        conn.rollback()
        return {"ok": False, "success": False, "msg": str(e)}
    finally:
        conn.close()


@app.get("/sunat/config")
def obtener_sunat_config(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cfg = _sunat_get_config(cur, sucursal)
        public = _sunat_public_config(cfg)
        public["aviso_api_secret"] = PLATAFORM_API_SECRET_AVISO
        return {"ok": True, "success": True, "sucursal": sucursal, "data": public}
    finally:
        conn.close()


@app.post("/sunat/config")
def guardar_sunat_config(data: SunatConfigUpdate, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        current = _sunat_get_config(cur, sucursal)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            clave TEXT PRIMARY KEY,
            valor TEXT,
            actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        clean = data.dict()
        clean["ambiente"] = str(clean.get("ambiente") or "BETA").upper()
        clean["ruc"] = _sunat_clean_ruc(clean.get("ruc"))
        clean["usuario_sol"] = str(clean.get("usuario_sol") or "").strip().upper()
        if clean["ambiente"] not in ("BETA", "PRODUCCION"):
            clean["ambiente"] = "BETA"
        clean["proveedor_sunat"] = str(clean.get("proveedor_sunat") or current.get("proveedor_sunat") or "directo").strip().lower()
        if clean["proveedor_sunat"] in ("plataforma", "api", "kodevo", "apigo"):
            clean["proveedor_sunat"] = "plataform"
        if clean["proveedor_sunat"] not in ("directo", "plataform"):
            clean["proveedor_sunat"] = "directo"
        if not str(clean.get("api_base_url") or "").strip():
            clean["api_base_url"] = str(current.get("api_base_url") or "https://apigo.apuuraydev.com/api/v1").strip()
        try:
            clean["api_sucursal_id"] = max(1, int(clean.get("api_sucursal_id") or current.get("api_sucursal_id") or 1))
        except Exception:
            clean["api_sucursal_id"] = 1
        for secret_key in ("clave_sol", "certificado_pfx_base64", "certificado_password", "api_secret"):
            value = str(clean.get(secret_key) or "").strip()
            if value in ("", "CONFIGURADO"):
                clean[secret_key] = current.get(secret_key) or ""
        if not str(clean.get("endpoint_url") or "").strip():
            clean["endpoint_url"] = SUNAT_DEFAULT_ENDPOINTS.get(clean["ambiente"], SUNAT_DEFAULT_ENDPOINTS["BETA"])
        cur.execute("""
        INSERT INTO app_config (clave, valor, actualizado)
        VALUES (%s,%s,CURRENT_TIMESTAMP)
        ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor, actualizado=CURRENT_TIMESTAMP
        """, (f"sunat:{sucursal}", json.dumps(clean, ensure_ascii=False)))
        conn.commit()
        return {"ok": True, "success": True, "sucursal": sucursal, "data": _sunat_public_config(clean)}
    except Exception as e:
        conn.rollback()
        return {"ok": False, "success": False, "msg": str(e)}
    finally:
        conn.close()


@app.post("/sunat/plataform/registrar")
def registrar_empresa_plataform_sunat(data: SunatPlataformRegistro = None, sucursal: str = DEFAULT_SUCURSAL):
    data = data or SunatPlataformRegistro()
    if not plataform_sunat:
        return {"ok": False, "success": False, "msg": "Modulo plataform_sunat_client no disponible en el servidor."}
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cfg = _sunat_get_config(cur, sucursal)
        cert_path = str(data.cert_path or "").strip()
        if not cert_path:
            cert_path = str(_sunat_env(sucursal, "CERT_PFX_PATH", "") or "").strip()
        cert_password = str(data.cert_password or cfg.get("certificado_password") or "").strip()
        cert_b64 = str(data.certificado_pfx_base64 or cfg.get("certificado_pfx_base64") or "").strip()
        if cert_b64 in ("", "CONFIGURADO"):
            cert_b64 = ""
        temp_cert_path = ""
        if not cert_path or not os.path.exists(cert_path):
            if cert_b64:
                try:
                    cert_bytes = base64.b64decode(cert_b64)
                    temp_fd, temp_cert_path = tempfile.mkstemp(suffix=".p12")
                    os.write(temp_fd, cert_bytes)
                    os.close(temp_fd)
                    cert_path = temp_cert_path
                except Exception as exc:
                    return {"ok": False, "success": False, "msg": f"Certificado PFX invalido: {exc}"}
            else:
                return {"ok": False, "success": False, "msg": "Falta certificado .pfx/.p12. Subelo en la pantalla SUNAT o indica cert_path."}
        if not cert_password:
            return {"ok": False, "success": False, "msg": "Falta contrasena del certificado."}
        entorno = "produccion" if str(cfg.get("ambiente") or "BETA").upper() == "PRODUCCION" else str(data.entorno or "beta").strip().lower()
        try:
            status, body, used_base = plataform_sunat.registrar_empresa(
                ruc=_sunat_clean_ruc(cfg.get("ruc")),
                razon_social=str(cfg.get("razon_social") or "").strip(),
                direccion=str(cfg.get("direccion") or "").strip(),
                ubigeo=str(cfg.get("ubigeo") or "150101").strip(),
                sol_user=str(cfg.get("usuario_sol") or "").strip(),
                sol_pass=str(cfg.get("clave_sol") or "").strip(),
                cert_path=cert_path,
                cert_password=cert_password,
                entorno=entorno,
                base_url=str(cfg.get("api_base_url") or "").strip(),
            )
        finally:
            if temp_cert_path:
                try:
                    os.remove(temp_cert_path)
                except Exception:
                    pass
        if status >= 400:
            return {
                "ok": False,
                "success": False,
                "http_status": status,
                "base_url": used_base,
                "respuesta": body,
                "aviso_api_secret": PLATAFORM_API_SECRET_AVISO,
            }
        datos = body.get("datos") if isinstance(body, dict) else {}
        api_key = ""
        api_secret = ""
        if isinstance(datos, dict):
            api_key = str(datos.get("api_key") or "").strip()
            api_secret = str(datos.get("api_secret") or "").strip()
        credenciales_una_vez = None
        if api_key and api_secret:
            credenciales_una_vez = {"api_key": api_key, "api_secret": api_secret}
            cfg["proveedor_sunat"] = "plataform"
            cfg["api_key"] = api_key
            cfg["api_secret"] = api_secret
            cfg["api_base_url"] = used_base
            cur.execute("""
            INSERT INTO app_config (clave, valor, actualizado)
            VALUES (%s,%s,CURRENT_TIMESTAMP)
            ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor, actualizado=CURRENT_TIMESTAMP
            """, (f"sunat:{sucursal}", json.dumps(cfg, ensure_ascii=False)))
            conn.commit()
        public = _sunat_public_config(cfg)
        return {
            "ok": True,
            "success": True,
            "http_status": status,
            "base_url": used_base,
            "data": public,
            "respuesta": body,
            "credenciales_una_vez": credenciales_una_vez,
            "aviso_api_secret": PLATAFORM_API_SECRET_AVISO_REGISTRO,
            "msg": "Empresa registrada. Copia el api_secret ahora: solo se muestra una vez.",
        }
    except Exception as e:
        conn.rollback()
        return {"ok": False, "success": False, "msg": str(e)}
    finally:
        conn.close()


@app.post("/sunat/marcar-historicos-internos")
def marcar_historicos_internos_sunat(sucursal: str = DEFAULT_SUCURSAL):
    """Marca todas las boletas/facturas ya emitidas como internas (nunca se envian a SUNAT)."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cur.execute("""
        UPDATE ventas
        SET sunat_estado='INTERNO',
            sunat_modo='NO_ENVIAR',
            sunat_respuesta_json=%s
        WHERE UPPER(COALESCE(tipo,'')) IN ('BOLETA','FACTURA')
          AND COALESCE(sucursal,%s)=%s
          AND COALESCE(sunat_estado,'PENDIENTE') NOT IN ('ACEPTADO','PROCESO')
        """, (
            json.dumps({"msg": "Documento interno historico de caja. Excluido de envio SUNAT."}, ensure_ascii=False),
            DEFAULT_SUCURSAL,
            sucursal,
        ))
        actualizados = int(cur.rowcount or 0)
        conn.commit()
        return {
            "ok": True,
            "success": True,
            "sucursal": sucursal,
            "actualizados": actualizados,
            "msg": f"{actualizados} documento(s) marcados como internos. No se enviaran a SUNAT.",
        }
    except Exception as e:
        conn.rollback()
        return {"ok": False, "success": False, "msg": str(e)}
    finally:
        conn.close()


@app.post("/sunat/documentos/{documento_id}/xml")
def generar_sunat_xml(documento_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        doc, cfg, artifacts, xml_bytes, zip_bytes = _sunat_generate_for_document(cur, documento_id, sucursal)
        conn.commit()
        return {
            "ok": True,
            "success": True,
            "id": documento_id,
            "tipo": doc.get("tipo"),
            "numero": doc.get("numero"),
            "xml_nombre": artifacts["xml_nombre"],
            "zip_nombre": artifacts["zip_nombre"],
            "hash": artifacts["hash"],
            "xml_base64": artifacts["xml_base64"],
            "zip_base64": artifacts["zip_base64"],
            "firmado": artifacts.get("firmado", False),
            "msg": artifacts.get("firma_msg") or "XML UBL 2.1 y ZIP generados.",
        }
    except Exception as e:
        conn.rollback()
        return {"ok": False, "success": False, "msg": str(e)}
    finally:
        conn.close()


@app.get("/sunat/documentos/{documento_id}/xml")
def descargar_sunat_xml(documento_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        doc, detalle = _sunat_documento_payload(cur, documento_id, sucursal)
        if not doc:
            return {"ok": False, "msg": "Documento no encontrado o no es BOLETA/FACTURA."}
        if not doc.get("sunat_xml_base64"):
            doc, cfg, artifacts, xml_bytes, zip_bytes = _sunat_generate_for_document(cur, documento_id, sucursal)
            conn.commit()
        else:
            xml_bytes = base64.b64decode(doc.get("sunat_xml_base64"))
        return Response(content=xml_bytes, media_type="application/xml")
    except Exception as e:
        conn.rollback()
        return {"ok": False, "success": False, "msg": str(e)}
    finally:
        conn.close()


@app.get("/sunat/documentos/{documento_id}/zip")
def descargar_sunat_zip(documento_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        doc, detalle = _sunat_documento_payload(cur, documento_id, sucursal)
        if not doc:
            return {"ok": False, "msg": "Documento no encontrado o no es BOLETA/FACTURA."}
        if not doc.get("sunat_zip_base64"):
            doc, cfg, artifacts, xml_bytes, zip_bytes = _sunat_generate_for_document(cur, documento_id, sucursal)
            conn.commit()
            zip_name = artifacts["zip_nombre"]
        else:
            zip_bytes = base64.b64decode(doc.get("sunat_zip_base64"))
            zip_name = doc.get("sunat_zip_nombre") or "sunat.zip"
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
        )
    except Exception as e:
        conn.rollback()
        return {"ok": False, "success": False, "msg": str(e)}
    finally:
        conn.close()


def _sunat_enviar_via_plataform(cur, documento_id, doc, detalle, cfg, sucursal):
    if not plataform_sunat:
        return {"ok": False, "success": False, "msg": "Modulo plataform_sunat_client no disponible en el servidor."}
    public_cfg = _sunat_public_config(cfg)
    if not public_cfg.get("plataform_configurada"):
        cur.execute("""
        UPDATE ventas
        SET sunat_estado='PENDIENTE',
            sunat_modo='PLATAFORM',
            sunat_respuesta_json=%s,
            sunat_fecha=CURRENT_TIMESTAMP
        WHERE id=%s
        """, (json.dumps({"msg": "Falta api_key, api_secret o api_base_url de plataform SUNAT."}, ensure_ascii=False), documento_id))
        return {
            "ok": False,
            "success": False,
            "msg": "Falta configurar api_key, api_secret y api_base_url en /sunat/config (proveedor_sunat=plataform).",
            "config": public_cfg,
        }
    resultado = plataform_sunat.emitir_documento_erp(
        api_key=str(cfg.get("api_key") or ""),
        api_secret=str(cfg.get("api_secret") or ""),
        doc=doc,
        detalle=detalle,
        base_url=str(cfg.get("api_base_url") or "").strip(),
        sucursal_id=int(cfg.get("api_sucursal_id") or 1),
        sincronizar_serie=True,
    )
    estado = str(resultado.get("sunat_estado") or "PROCESO").upper()
    if estado not in ("ACEPTADO", "RECHAZADO", "PROCESO"):
        estado = "PROCESO"
    respuesta_json = json.dumps(resultado, ensure_ascii=False)
    cur.execute("""
    UPDATE ventas
    SET sunat_estado=%s,
        sunat_modo='PLATAFORM',
        sunat_fecha=CURRENT_TIMESTAMP,
        sunat_respuesta_json=%s
    WHERE id=%s
    """, (estado, respuesta_json, documento_id))
    return {
        "ok": estado != "RECHAZADO",
        "success": estado != "RECHAZADO",
        "id": documento_id,
        "sunat_estado": estado,
        "proveedor": "plataform",
        "plataform_id": resultado.get("plataform_id"),
        "numero_plataform": resultado.get("numero_plataform"),
        "base_url": resultado.get("base_url"),
        "respuesta": resultado,
        "msg": resultado.get("msg"),
    }


@app.post("/sunat/documentos/{documento_id}/enviar")
def enviar_documento_sunat(documento_id: int, data: SunatEnviarRequest = None, sucursal: str = DEFAULT_SUCURSAL):
    data = data or SunatEnviarRequest()
    if not _sunat_emision_habilitada():
        return {
            "ok": False,
            "success": False,
            "msg": "Emision SUNAT bloqueada en el servidor. La configuracion esta lista, pero aun no se envian comprobantes.",
            "sunat_estado": "PENDIENTE",
            "bloqueo": "SUNAT_EMISION_HABILITADA=0",
        }
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        doc, detalle = _sunat_documento_payload(cur, documento_id, sucursal)
        if not doc:
            return {"ok": False, "success": False, "msg": "Documento no encontrado o no es BOLETA/FACTURA."}
        bloqueado, bloqueo_msg = _sunat_envio_bloqueado(doc)
        if bloqueado:
            return {
                "ok": False,
                "success": False,
                "msg": bloqueo_msg,
                "sunat_estado": doc.get("sunat_estado"),
                "sunat_modo": doc.get("sunat_modo"),
            }
        cfg = _sunat_get_config(cur, doc.get("sucursal") or sucursal)
        if _sunat_usa_plataform(cfg):
            out = _sunat_enviar_via_plataform(cur, documento_id, doc, detalle, cfg, sucursal)
            conn.commit()
            return out
        if data.regenerar or not doc.get("sunat_zip_base64"):
            doc, cfg, artifacts, xml_bytes, zip_bytes = _sunat_generate_for_document(cur, documento_id, sucursal)
            zip_name = artifacts["zip_nombre"]
            zip_base64 = artifacts["zip_base64"]
        else:
            zip_name = doc.get("sunat_zip_nombre")
            zip_base64 = doc.get("sunat_zip_base64")

        public_cfg = _sunat_public_config(cfg)
        if not public_cfg.get("listo_envio"):
            cur.execute("""
            UPDATE ventas
            SET sunat_estado='PENDIENTE',
                sunat_modo='API',
                sunat_respuesta_json=%s,
                sunat_fecha=CURRENT_TIMESTAMP
            WHERE id=%s
            """, (json.dumps({"msg": "Falta configurar RUC, usuario SOL, clave SOL o endpoint SUNAT."}, ensure_ascii=False), documento_id))
            conn.commit()
            return {"ok": False, "success": False, "msg": "Falta configurar RUC, usuario SOL, clave SOL o endpoint SUNAT.", "config": public_cfg}

        if not public_cfg.get("firma_configurada") and not data.permitir_sin_firma:
            cur.execute("""
            UPDATE ventas
            SET sunat_estado='PENDIENTE',
                sunat_modo='API',
                sunat_respuesta_json=%s,
                sunat_fecha=CURRENT_TIMESTAMP
            WHERE id=%s
            """, (json.dumps({"msg": "Falta certificado digital/firma. No se envio a SUNAT."}, ensure_ascii=False), documento_id))
            conn.commit()
            return {"ok": False, "success": False, "msg": "Falta certificado digital/firma. Configura certificado o envia con permitir_sin_firma solo para pruebas tecnicas."}

        status_code, response_text = _sunat_soap_send_bill(cfg, zip_name, zip_base64)
        estado = "PROCESO"
        if 200 <= int(status_code) < 300 and "applicationResponse" in response_text:
            estado = "ACEPTADO"
        elif int(status_code) >= 400 or "Fault" in response_text:
            estado = "RECHAZADO"
        cur.execute("""
        UPDATE ventas
        SET sunat_estado=%s,
            sunat_modo='API',
            sunat_fecha=CURRENT_TIMESTAMP,
            sunat_respuesta_json=%s
        WHERE id=%s
        """, (estado, json.dumps({"http_status": status_code, "response": response_text[:12000]}, ensure_ascii=False), documento_id))
        conn.commit()
        return {"ok": estado != "RECHAZADO", "success": estado != "RECHAZADO", "id": documento_id, "sunat_estado": estado, "http_status": status_code, "respuesta": response_text[:4000]}
    except Exception as e:
        conn.rollback()
        return {"ok": False, "success": False, "msg": str(e)}
    finally:
        conn.close()


def _sunat_auto_send_document(documento_id, sucursal):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        doc, _detalle = _sunat_documento_payload(cur, documento_id, sucursal)
        bloqueado, bloqueo_msg = _sunat_envio_bloqueado(doc or {})
        if bloqueado:
            return {"ok": True, "auto": False, "msg": bloqueo_msg, "sunat_estado": (doc or {}).get("sunat_estado"), "sunat_modo": (doc or {}).get("sunat_modo")}
        cfg = _sunat_get_config(cur, sucursal)
        auto = str(cfg.get("envio_automatico")).lower() in ("1", "true", "si", "yes", "on")
        if not auto:
            return {"ok": True, "auto": False, "msg": "Envio automatico SUNAT desactivado."}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return enviar_documento_sunat(
        int(documento_id),
        SunatEnviarRequest(regenerar=True, permitir_sin_firma=False),
        sucursal,
    )


@app.get("/sunat/documentos/{documento_id}/estado")
def estado_documento_sunat(documento_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cur.execute("""
        SELECT id, tipo, numero, COALESCE(sunat_estado,'PENDIENTE'), COALESCE(sunat_modo,'MANUAL'),
               sunat_fecha, COALESCE(sunat_xml_nombre,''), COALESCE(sunat_zip_nombre,''),
               COALESCE(sunat_hash,''), COALESCE(sunat_ticket,''), COALESCE(sunat_respuesta_json,'')
        FROM ventas
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (documento_id, DEFAULT_SUCURSAL, sucursal))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "success": False, "msg": "Documento no encontrado."}
        respuesta = {}
        try:
            respuesta = json.loads(row[10] or "{}")
        except Exception:
            respuesta = {"raw": row[10] or ""}
        return {
            "ok": True,
            "success": True,
            "id": row[0],
            "tipo": row[1],
            "numero": row[2],
            "sunat_estado": row[3],
            "sunat_modo": row[4],
            "sunat_fecha": row[5],
            "xml_nombre": row[6],
            "zip_nombre": row[7],
            "hash": row[8],
            "ticket": row[9],
            "respuesta": respuesta,
        }
    finally:
        conn.close()


@app.get("/caja")
def listar_caja(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
    SELECT id, fecha, tipo, detalle, monto, usuario,
           COALESCE(documento_tipo, '') AS documento_tipo,
           COALESCE(documento_numero, '') AS documento_numero,
           COALESCE(estado_pago, 'PAGADO') AS estado_pago,
           COALESCE(metodo_pago, '') AS metodo_pago,
           COALESCE(observacion, '') AS observacion,
           COALESCE(sucursal,%s) AS sucursal
    FROM caja_movimientos
    WHERE COALESCE(sucursal,%s)=%s
    ORDER BY id DESC
    """, (DEFAULT_SUCURSAL, DEFAULT_SUCURSAL, sucursal))
    data = dict_fetchall(cur)
    conn.close()
    return data


@app.post("/caja")
def registrar_caja(data: CajaMovimiento):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    estado_pago = (data.estado_pago or "PAGADO").upper()
    if estado_pago not in ("PAGADO", "CREDITO", "DEUDA"):
        estado_pago = "PAGADO"
    metodo_pago = (data.metodo_pago or "").upper()
    cur.execute("""
    INSERT INTO caja_movimientos (
        tipo, detalle, monto, usuario, documento_tipo, documento_numero, estado_pago, metodo_pago, observacion, sucursal
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    RETURNING id
    """, (
        data.tipo, data.detalle, data.monto, data.usuario,
        data.documento_tipo, data.documento_numero, estado_pago, metodo_pago, data.observacion or "", sucursal
    ))
    movimiento_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return {"ok": True, "id": movimiento_id}


# ================= COMPRAS / PROVEEDORES =================
@app.get("/proveedores")
def listar_proveedores(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
    SELECT id, nombre, COALESCE(ruc,'') AS ruc, COALESCE(telefono,'') AS telefono,
           COALESCE(direccion,'') AS direccion, COALESCE(sucursal,%s) AS sucursal,
           creado_en
    FROM proveedores
    WHERE COALESCE(sucursal,%s)=%s
    ORDER BY nombre ASC, id DESC
    """, (DEFAULT_SUCURSAL, DEFAULT_SUCURSAL, sucursal))
    data = [_jsonable_row(r) for r in dict_fetchall(cur)]
    conn.close()
    return data


@app.get("/productos/{producto_id}/series")
def listar_series_producto(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = inventario_sucursal(sucursal)
    cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
    cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS usuario_ingreso TEXT DEFAULT ''")
    cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    cur.execute("""
    SELECT
        ps.id,
        ps.producto_id,
        p.nombre AS producto_nombre,
        p.marca,
        p.modelo,
        ps.serie,
        ps.proveedor,
        ps.estado,
        COALESCE(ps.almacen, 'TIENDA') AS almacen,
        COALESCE(ps.usuario_ingreso, '') AS usuario_ingreso,
        ps.fecha_ingreso,
        ps.fecha_salida,
        ps.creado_en
    FROM producto_series ps
    LEFT JOIN productos p ON p.id = ps.producto_id AND COALESCE(p.sucursal,%s)=%s
    WHERE ps.producto_id=%s AND COALESCE(ps.sucursal,%s)=%s
    ORDER BY
        CASE UPPER(COALESCE(ps.estado,'DISPONIBLE'))
            WHEN 'DISPONIBLE' THEN 0
            WHEN 'RESERVADO' THEN 1
            ELSE 2
        END,
        ps.id DESC
    """, (DEFAULT_SUCURSAL, sucursal, producto_id, DEFAULT_SUCURSAL, sucursal))
    data = dict_fetchall(cur)
    conn.close()
    return data


@app.post("/proveedores")
def guardar_proveedor(data: Proveedor):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    nombre = (data.nombre or "").strip()
    if not nombre:
        conn.close()
        return {"ok": False, "msg": "Proveedor requerido"}
    cur.execute("""
    INSERT INTO proveedores (nombre, ruc, telefono, direccion, sucursal)
    VALUES (%s,%s,%s,%s,%s)
    RETURNING id
    """, (nombre, data.ruc or "", data.telefono or "", data.direccion or "", sucursal))
    proveedor_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return {"ok": True, "success": True, "id": proveedor_id}


def _parse_compra_items(raw):
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, list) else []
    except Exception:
        return []


@app.get("/compras")
def listar_compras(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
    SELECT id, fecha, COALESCE(proveedor_nombre,'') AS proveedor_nombre,
           COALESCE(comprobante,'') AS comprobante, COALESCE(total,0) AS total,
           COALESCE(usuario_registro,'') AS usuario_registro,
           COALESCE(detalle,'') AS detalle, COALESCE(sucursal,%s) AS sucursal,
           COALESCE(items_json,'') AS items_json
    FROM compras
    WHERE COALESCE(sucursal,%s)=%s
    ORDER BY fecha DESC, id DESC
    LIMIT 500
    """, (DEFAULT_SUCURSAL, DEFAULT_SUCURSAL, sucursal))
    data = []
    for row in dict_fetchall(cur):
        item = _jsonable_row(row)
        items = _parse_compra_items(item.get("items_json"))
        item["items_count"] = len(items)
        item["tiene_series"] = any(
            isinstance(it, dict) and (
                (isinstance(it.get("series_list"), list) and any(str(s).strip() for s in it.get("series_list")))
                or str(it.get("series_texto") or "").strip()
            )
            for it in items
        )
        data.append(item)
    conn.close()
    return data


@app.get("/compras/{compra_id}")
def obtener_compra(compra_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
    SELECT id, fecha, COALESCE(proveedor_nombre,'') AS proveedor_nombre,
           COALESCE(comprobante,'') AS comprobante, COALESCE(total,0) AS total,
           COALESCE(usuario_registro,'') AS usuario_registro,
           COALESCE(detalle,'') AS detalle, COALESCE(sucursal,%s) AS sucursal,
           COALESCE(items_json,'') AS items_json
    FROM compras
    WHERE id=%s AND COALESCE(sucursal,%s)=%s
    LIMIT 1
    """, (DEFAULT_SUCURSAL, compra_id, DEFAULT_SUCURSAL, sucursal))
    row = dict_fetchone(cur)
    conn.close()
    if not row:
        return {"ok": False, "msg": "Compra no encontrada"}
    compra = _jsonable_row(row)
    compra["items"] = _parse_compra_items(compra.get("items_json"))
    return {"ok": True, "compra": compra, "items": compra["items"]}


@app.post("/compras")
def guardar_compra(data: Compra):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(data.sucursal)
        inv_sucursal = inventario_sucursal(sucursal)
        proveedor = (data.proveedor_nombre or data.proveedor or "").strip()
        compra_tiene_series = False
        for item in (data.items or []):
            raw_series_list = item.get("series_list")
            series_texto = item.get("series_texto", "")
            if isinstance(raw_series_list, list) and any(str(s).strip() for s in raw_series_list):
                compra_tiene_series = True
                break
            if series_texto and str(series_texto).strip():
                compra_tiene_series = True
                break
        if compra_tiene_series and not usuario_puede_editar_series({
            "usuario": data.usuario or data.usuario_registro,
            "usuario_registro": data.usuario_registro or data.usuario,
        }):
            return {"ok": False, "msg": "Solo giomar y mily pueden ingresar series en compras."}

        if proveedor:
            cur.execute("""
                SELECT id FROM proveedores
                WHERE LOWER(TRIM(COALESCE(nombre,''))) = LOWER(TRIM(%s))
                  AND COALESCE(sucursal,%s)=%s
                LIMIT 1
            """, (proveedor, DEFAULT_SUCURSAL, sucursal))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO proveedores (nombre, sucursal) VALUES (%s,%s)",
                    (proveedor, sucursal),
                )

        cur.execute("""
        INSERT INTO compras (proveedor_nombre, comprobante, total, usuario_registro, detalle, sucursal)
        VALUES (%s,%s,%s,%s,%s,%s)
        RETURNING id
        """, (
            proveedor, data.comprobante or "", float(data.total or 0),
            data.usuario_registro or data.usuario or "", data.detalle or "", sucursal
        ))
        compra_id = cur.fetchone()[0]
        usuario_op = str(data.usuario_registro or data.usuario or "").strip()
        resumen_series_compra = []
        items_snapshot = []
        cur.execute("ALTER TABLE compras ADD COLUMN IF NOT EXISTS items_json TEXT DEFAULT ''")

        for item in (data.items or []):
            try:
                prod_id = int(item.get("producto_id") or 0)
            except (TypeError, ValueError):
                prod_id = 0
            nombre = str(item.get("nombre", "") or "").strip()
            try:
                cantidad = max(1, int(float(item.get("cantidad") or 1)))
            except (TypeError, ValueError):
                cantidad = 1
            try:
                precio = float(item.get("precio") or 0)
            except (TypeError, ValueError):
                precio = 0.0
            try:
                precio_venta = float(item.get("precio_venta") or item.get("precio") or 0)
            except (TypeError, ValueError):
                precio_venta = precio

            if not prod_id and nombre:
                cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS observacion TEXT DEFAULT ''")
                cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
                cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS sku_woo TEXT DEFAULT ''")
                cur.execute("""
                    INSERT INTO productos (nombre, categoria, marca, modelo, precio_compra, precio_venta, stock, imagen_url, observacion, almacen, sucursal, sku_woo)
                    VALUES (%s,%s,%s,%s,%s,%s,0,'','','TIENDA',%s,'')
                    RETURNING id
                """, (
                    nombre,
                    str(item.get("categoria") or "").strip(),
                    str(item.get("marca") or "").strip(),
                    str(item.get("modelo") or "").strip(),
                    precio,
                    precio_venta,
                    inv_sucursal,
                ))
                prod_id = int(cur.fetchone()[0])

            series_texto = item.get("series_texto", "")
            raw_series_list = item.get("series_list")
            if isinstance(raw_series_list, list):
                series_list = [str(s).strip().upper() for s in raw_series_list if str(s).strip()]
            elif series_texto:
                series_list = [s.strip().upper() for s in series_texto.replace("\n", ",").split(",") if s.strip()]
            else:
                series_list = []

            if series_list and len(series_list) != cantidad:
                conn.rollback()
                return {"ok": False, "msg": f"{nombre or 'Producto'}: se requieren {cantidad} serie(s), recibidas {len(series_list)}"}

            if not prod_id:
                continue

            if series_list:
                for serie in series_list:
                    cur.execute("""
                        INSERT INTO producto_series (producto_id, serie, proveedor, estado, almacen, fecha_ingreso, sucursal, usuario_ingreso)
                        VALUES (%s, %s, %s, 'DISPONIBLE', 'TIENDA', TO_CHAR((timezone('America/Lima', now()))::date, 'YYYY-MM-DD'), %s, %s)
                    """, (prod_id, serie, proveedor, inv_sucursal, usuario_op))
                sync_producto_stock_from_series(cur, prod_id, inv_sucursal)
                resumen_series_compra.append(
                    f"{nombre or f'ID {prod_id}'} x{len(series_list)} [{_resumen_lista_auditoria(series_list, max_items=4)}]"
                )
            else:
                cur.execute("""
                    UPDATE productos SET stock = COALESCE(stock,0) + %s
                    WHERE id=%s AND COALESCE(sucursal,%s)=%s
                """, (cantidad, prod_id, DEFAULT_SUCURSAL, inv_sucursal))

            items_snapshot.append({
                "producto_id": prod_id,
                "nombre": nombre,
                "categoria": str(item.get("categoria") or "").strip(),
                "marca": str(item.get("marca") or "").strip(),
                "modelo": str(item.get("modelo") or "").strip(),
                "cantidad": cantidad,
                "precio": round(precio, 2),
                "precio_venta": round(precio_venta, 2),
                "series_list": series_list,
                "series_texto": "\n".join(series_list),
                "subtotal": round(cantidad * precio, 2),
            })

        cur.execute(
            "UPDATE compras SET items_json=%s WHERE id=%s AND COALESCE(sucursal,%s)=%s",
            (json.dumps(items_snapshot, ensure_ascii=False), compra_id, DEFAULT_SUCURSAL, sucursal),
        )

        accion_compra = "COMPRA_SERIES_INGRESO" if resumen_series_compra else "COMPRA_REGISTRADA"
        detalle_compra = (
            f"Usuario={usuario_op or 'SISTEMA'} | CompraID={compra_id} | Proveedor={proveedor or '-'} | "
            f"Comprobante={data.comprobante or '-'} | Total={float(data.total or 0):.2f} | "
            f"Productos={len(data.items or [])}"
        )
        if resumen_series_compra:
            detalle_compra += f" | Series={_resumen_lista_auditoria(resumen_series_compra, max_items=5)}"
        registrar_auditoria_mercaderia(
            cur,
            usuario=usuario_op,
            sucursal=sucursal,
            accion=accion_compra,
            detalle=detalle_compra,
            commit=False,
        )
        conn.commit()
        return {"ok": True, "success": True, "id": compra_id}
    except Exception as exc:
        conn.rollback()
        return {"ok": False, "msg": f"Error al guardar compra: {exc}"}
    finally:
        conn.close()


# ================= WOOCOMMERCE POR SUCURSAL =================
def web_config_for_sucursal(sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_config (
        clave TEXT PRIMARY KEY,
        valor TEXT,
        actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("SELECT valor FROM app_config WHERE clave=%s", (f"web:{sucursal}",))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row or not row[0]:
        return {}
    try:
        data = json.loads(row[0])
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_web_config_for_sucursal(sucursal: str, data: dict):
    sucursal = norm_sucursal(sucursal)
    prev = web_config_for_sucursal(sucursal)
    wc_secret = str(data.get("wc_consumer_secret") or data.get("consumer_secret") or "").strip()
    if not wc_secret:
        wc_secret = str(prev.get("wc_consumer_secret") or "").strip()
    wp_password = str(data.get("wp_app_password") or "").strip()
    if not wp_password:
        wp_password = str(prev.get("wp_app_password") or "").strip()
    clean = {
        "wc_store_url": str(data.get("wc_store_url") or data.get("store_url") or "").strip().rstrip("/"),
        "wc_consumer_key": str(data.get("wc_consumer_key") or data.get("consumer_key") or "").strip(),
        "wc_consumer_secret": wc_secret,
        "woo_auto_sync": bool(data.get("woo_auto_sync", False)),
        "wp_username": str(data.get("wp_username") or prev.get("wp_username") or "").strip(),
        "wp_app_password": wp_password,
    }
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_config (
        clave TEXT PRIMARY KEY,
        valor TEXT,
        actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("""
    INSERT INTO app_config (clave, valor, actualizado)
    VALUES (%s,%s,CURRENT_TIMESTAMP)
    ON CONFLICT (clave)
    DO UPDATE SET valor=EXCLUDED.valor, actualizado=CURRENT_TIMESTAMP
    """, (f"web:{sucursal}", json.dumps(clean, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return clean


def woo_config(sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    web_cfg = web_config_for_sucursal(sucursal)
    site = (web_cfg.get("wc_store_url") or "").strip().rstrip("/")
    ck = (web_cfg.get("wc_consumer_key") or "").strip()
    cs = (web_cfg.get("wc_consumer_secret") or "").strip()
    if not site and sucursal == DEFAULT_SUCURSAL:
        site = (os.getenv("WC_STORE_URL") or os.getenv("WOOCOMMERCE_URL") or os.getenv("WP_URL") or "").strip().rstrip("/")
        ck = (os.getenv("WC_CONSUMER_KEY") or os.getenv("WOOCOMMERCE_CONSUMER_KEY") or "").strip()
        cs = (os.getenv("WC_CONSUMER_SECRET") or os.getenv("WOOCOMMERCE_CONSUMER_SECRET") or "").strip()
    if not site or not ck or not cs:
        return None
    return site, ck, cs


def woo_request(method, endpoint, sucursal: str = DEFAULT_SUCURSAL, **kwargs):
    cfg = woo_config(sucursal)
    if not cfg:
        return {"ok": False, "msg": "Configura URL WooCommerce, Consumer Key y Consumer Secret para esta sucursal."}
    site, ck, cs = cfg
    params = kwargs.pop("params", {}) or {}
    params.setdefault("consumer_key", ck)
    params.setdefault("consumer_secret", cs)
    query = urllib.parse.urlencode(params)
    url = f"{site}/wp-json/wc/v3/{endpoint.lstrip('/')}"
    if query:
        url = f"{url}?{query}"
    try:
        payload = kwargs.get("json")
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        with urllib.request.urlopen(req, timeout=35) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            return {"ok": True, "status": resp.status, "data": data, "site_url": site}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {"raw": raw}
        msg = data.get("message") if isinstance(data, dict) else str(data)
        return {"ok": False, "status": e.code, "msg": msg or "Error WooCommerce", "data": data}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def woo_payload_from_model(data: WooProduct):
    payload = {
        "name": data.name,
        "sku": data.sku,
        "status": data.status or "publish",
        "regular_price": str(data.regular_price or "0"),
        "sale_price": str(data.sale_price or ""),
        "short_description": data.short_description or "",
        "description": data.description or "",
        "manage_stock": bool(data.manage_stock),
    }
    if data.stock_quantity is not None:
        payload["stock_quantity"] = int(data.stock_quantity)
    if data.images:
        payload["images"] = data.images
    if data.categories:
        payload["categories"] = data.categories
    return payload


def parse_data_image_url(value):
    value = str(value or "").strip()
    if not value.startswith("data:image") or "," not in value:
        return None, None
    try:
        header, encoded = value.split(",", 1)
        mime = header.split(";")[0].split(":")[1] if ":" in header else "image/jpeg"
        raw = base64.b64decode(encoded)
        return raw, mime
    except Exception:
        return None, None


def public_product_image_url(producto_id, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    return (
        f"{public_base_url()}/public/producto/{int(producto_id)}/imagen"
        f"?sucursal={urllib.parse.quote(sucursal)}"
    )


def wp_credentials(sucursal: str = DEFAULT_SUCURSAL):
    web_cfg = web_config_for_sucursal(sucursal)
    site = (web_cfg.get("wc_store_url") or "").strip().rstrip("/")
    user = (web_cfg.get("wp_username") or os.getenv("WP_USERNAME") or "").strip()
    pwd = (web_cfg.get("wp_app_password") or os.getenv("WP_APP_PASSWORD") or "").strip()
    if not site and sucursal == DEFAULT_SUCURSAL:
        site = (os.getenv("WC_STORE_URL") or os.getenv("WOOCOMMERCE_URL") or os.getenv("WP_URL") or "").strip().rstrip("/")
    if site and user and pwd:
        return site, user, pwd
    return None


def wp_upload_media(image_bytes, filename, mime_type, sucursal: str = DEFAULT_SUCURSAL):
    creds = wp_credentials(sucursal)
    if not creds:
        return {"ok": False, "msg": "Configura usuario y contraseña de aplicación WordPress para subir imagenes."}
    site, user, pwd = creds
    token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
    url = f"{site}/wp-json/wp/v2/media"
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": mime_type or "image/jpeg",
        "Accept": "application/json",
    }
    try:
        req = urllib.request.Request(url, data=image_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
        source_url = data.get("source_url") or data.get("guid", {}).get("rendered", "")
        if not source_url:
            return {"ok": False, "msg": "WordPress no devolvio la URL de la imagen."}
        return {"ok": True, "source_url": source_url, "media_id": data.get("id"), "data": data}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw) if raw else {}
            msg = detail.get("message") if isinstance(detail, dict) else raw
        except Exception:
            msg = raw
        return {"ok": False, "status": e.code, "msg": msg or "Error al subir imagen a WordPress"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def woo_resolve_product_image_url(p: dict, sucursal: str = DEFAULT_SUCURSAL):
    img = str(p.get("imagen_url") or "").strip()
    if not img:
        return ""
    if img.startswith(("http://", "https://")):
        return img
    producto_id = p.get("id")
    if not producto_id:
        return ""
    raw, mime = parse_data_image_url(img)
    if raw:
        ext = "jpg"
        if "png" in (mime or ""):
            ext = "png"
        elif "webp" in (mime or ""):
            ext = "webp"
        sku = str(p.get("sku_woo") or "").strip().upper() or f"ERP-{producto_id}"
        uploaded = wp_upload_media(raw, f"{sku}.{ext}", mime, sucursal=sucursal)
        if uploaded.get("ok"):
            return uploaded.get("source_url") or ""
        return public_product_image_url(producto_id, sucursal)
    return ""


def woo_auto_sync_enabled(sucursal: str = DEFAULT_SUCURSAL):
    return bool(web_config_for_sucursal(sucursal).get("woo_auto_sync", False))


def woo_save_product_link(producto_id, woo_data: dict, sku: str, sucursal: str = DEFAULT_SUCURSAL):
    woo_id = int(woo_data.get("id") or 0) if isinstance(woo_data, dict) else 0
    sku = str(sku or "").strip().upper()
    if not woo_id and not sku:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS woo_id INT")
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS sku_woo TEXT DEFAULT ''")
    cur.execute("""
        UPDATE productos
        SET woo_id=CASE WHEN %s > 0 THEN %s ELSE woo_id END,
            sku_woo=CASE WHEN %s <> '' THEN %s ELSE sku_woo END
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (woo_id, woo_id, sku, sku, producto_id, DEFAULT_SUCURSAL, norm_sucursal(sucursal)))
    conn.commit()
    conn.close()


def woo_category_for_name(name: str, sucursal: str = DEFAULT_SUCURSAL, parent_id: int = 0, create: bool = False):
    name = str(name or "").strip()
    if not name:
        return None
    params = {"search": name, "per_page": 100}
    if parent_id:
        params["parent"] = int(parent_id)
    found = woo_request("get", "products/categories", sucursal=sucursal, params=params)
    if found.get("ok"):
        for cat in found.get("data") or []:
            if str(cat.get("name", "")).strip().lower() == name.lower():
                return {
                    "id": cat.get("id"),
                    "name": cat.get("name"),
                    "parent": cat.get("parent") or 0,
                }
    if not create:
        return None
    payload = {"name": name}
    if parent_id:
        payload["parent"] = int(parent_id)
    created = woo_request("post", "products/categories", sucursal=sucursal, json=payload)
    if created.get("ok") and isinstance(created.get("data"), dict):
        data = created["data"]
        return {"id": data.get("id"), "name": data.get("name"), "parent": data.get("parent") or 0}
    return None


def woo_list_categories(sucursal: str = DEFAULT_SUCURSAL, parent_id: int = None):
    sucursal = norm_sucursal(sucursal)
    params = {"per_page": 100, "orderby": "name", "order": "asc"}
    if parent_id is not None:
        params["parent"] = int(parent_id)
    rows = []
    page = 1
    while page <= 10:
        params["page"] = page
        r = woo_request("get", "products/categories", sucursal=sucursal, params=params)
        if not r.get("ok"):
            return r
        batch = r.get("data") or []
        if not batch:
            break
        for item in batch:
            rows.append({
                "id": item.get("id"),
                "name": item.get("name") or "",
                "slug": item.get("slug") or "",
                "parent": int(item.get("parent") or 0),
                "count": int(item.get("count") or 0),
            })
        if len(batch) < 100:
            break
        page += 1
    return {"ok": True, "data": rows}


def woo_categories_tree(sucursal: str = DEFAULT_SUCURSAL):
    r = woo_list_categories(sucursal=sucursal, parent_id=None)
    if not r.get("ok"):
        return r
    all_rows = r.get("data") or []
    by_parent = defaultdict(list)
    names = {}
    for row in all_rows:
        names[int(row["id"])] = row["name"]
        by_parent[int(row.get("parent") or 0)].append(row)
    tree = []
    for parent in sorted(by_parent.get(0, []), key=lambda x: str(x.get("name", "")).lower()):
        children = sorted(by_parent.get(int(parent["id"]), []), key=lambda x: str(x.get("name", "")).lower())
        tree.append({
            **parent,
            "subcategorias": children,
        })
    return {"ok": True, "data": tree, "flat": all_rows, "names": names}


def woo_category_ids_for_product(p: dict, sucursal: str = DEFAULT_SUCURSAL):
    sub_id = int(p.get("woo_subcategoria_id") or 0)
    if sub_id > 0:
        return [{"id": sub_id}]
    cat_id = int(p.get("woo_categoria_id") or 0)
    if cat_id > 0:
        return [{"id": cat_id}]
    sub_name = str(p.get("subcategoria_web") or "").strip()
    parent_name = str(p.get("categoria_web") or "").strip()
    parent_id = 0
    if parent_name:
        parent = woo_category_for_name(parent_name, sucursal=sucursal, parent_id=0, create=False)
        if parent and parent.get("id"):
            parent_id = int(parent["id"])
    if sub_name:
        sub = woo_category_for_name(sub_name, sucursal=sucursal, parent_id=parent_id, create=False)
        if sub and sub.get("id"):
            return [{"id": int(sub["id"])}]
    if parent_id:
        return [{"id": parent_id}]
    if parent_name:
        parent = woo_category_for_name(parent_name, sucursal=sucursal, parent_id=0, create=False)
        if parent and parent.get("id"):
            return [{"id": int(parent["id"])}]
    return []


def woo_payload_from_erp_product(p: dict, sucursal: str = DEFAULT_SUCURSAL):
    sku = str(p.get("sku_woo") or "").strip().upper() or f"ERP-{p['id']}"
    payload = {
        "name": p.get("nombre") or f"Producto {p['id']}",
        "sku": sku,
        "status": "publish",
        "regular_price": str(float(p.get("precio_venta") or 0)),
        "manage_stock": True,
        "stock_quantity": int(p.get("stock") or 0),
        "short_description": f"{p.get('marca','')} {p.get('modelo','')}".strip(),
        "description": (
            f"Categoria ERP: {p.get('categoria','')}\n"
            f"Categoria web: {p.get('categoria_web','')}\n"
            f"Subcategoria web: {p.get('subcategoria_web','')}"
        ).strip(),
    }
    image_url = woo_resolve_product_image_url(p, sucursal=sucursal)
    if image_url:
        payload["images"] = [{"src": image_url}]
    categories = woo_category_ids_for_product(p, sucursal=sucursal)
    if categories:
        payload["categories"] = categories
    return sku, payload


def woo_upsert_erp_product(p: dict, sucursal: str = DEFAULT_SUCURSAL):
    sku, payload = woo_payload_from_erp_product(p, sucursal=sucursal)
    found = woo_request("get", "products", sucursal=sucursal, params={"sku": sku, "per_page": 1})
    if not found.get("ok"):
        return found
    existing = found.get("data") or []
    if existing:
        r = woo_request("put", f"products/{existing[0]['id']}", sucursal=sucursal, json=payload)
        action = "actualizado"
    else:
        r = woo_request("post", "products", sucursal=sucursal, json=payload)
        action = "creado"
    if not r.get("ok"):
        return r
    woo_data = r.get("data", {}) or {}
    woo_save_product_link(p.get("id"), woo_data, sku, sucursal=sucursal)
    return {"ok": True, "action": action, "sku": sku, "data": woo_data}


def woo_create_new_erp_product(p: dict, sucursal: str = DEFAULT_SUCURSAL):
    sku, payload = woo_payload_from_erp_product(p, sucursal=sucursal)
    found = woo_request("get", "products", sucursal=sucursal, params={"sku": sku, "per_page": 1})
    if not found.get("ok"):
        return found
    existing = found.get("data") or []
    if existing:
        return {
            "ok": True,
            "skipped": True,
            "msg": f"El SKU {sku} ya existe en la web. No se actualiza automaticamente.",
            "woo_id": existing[0].get("id"),
        }
    r = woo_request("post", "products", sucursal=sucursal, json=payload)
    if not r.get("ok"):
        return r
    woo_data = r.get("data", {}) or {}
    woo_save_product_link(p.get("id"), woo_data, sku, sucursal=sucursal)
    return {"ok": True, "action": "creado", "sku": sku, "data": woo_data}


def maybe_sync_new_product_to_woo(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    if not woo_auto_sync_enabled(sucursal):
        return {"ok": True, "skipped": True, "msg": "Sync de productos nuevos desactivado."}
    if not woo_config(sucursal):
        return {"ok": False, "skipped": True, "msg": "WooCommerce no configurado para esta sucursal."}
    conn = get_conn()
    cur = conn.cursor()
    ensure_producto_web_columns(cur)
    cur.execute("""
        SELECT id, nombre, categoria, marca, modelo, precio_venta, stock,
               COALESCE(imagen_url,'') AS imagen_url, COALESCE(sku_woo,'') AS sku_woo,
               COALESCE(categoria_web,'') AS categoria_web, COALESCE(subcategoria_web,'') AS subcategoria_web,
               COALESCE(woo_categoria_id,0) AS woo_categoria_id, COALESCE(woo_subcategoria_id,0) AS woo_subcategoria_id
        FROM productos
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (producto_id, DEFAULT_SUCURSAL, sucursal))
    p = dict_fetchone(cur)
    conn.close()
    if not p:
        return {"ok": False, "msg": "Producto ERP no encontrado."}
    r = woo_create_new_erp_product(p, sucursal=sucursal)
    if r.get("skipped"):
        return r
    if not r.get("ok"):
        return r
    return {
        "ok": True,
        "synced": True,
        "action": r.get("action"),
        "sku": r.get("sku"),
        "woo_id": (r.get("data") or {}).get("id"),
        "msg": f"Producto nuevo publicado en WooCommerce.",
    }


def woo_apply_web_categories_to_erp(sucursal: str = DEFAULT_SUCURSAL, limit: int = 500):
    sucursal = norm_sucursal(sucursal)
    tree = woo_categories_tree(sucursal=sucursal)
    if not tree.get("ok"):
        return tree
    names = tree.get("names") or {}
    conn = get_conn()
    cur = conn.cursor()
    ensure_producto_web_columns(cur)
    cur.execute("""
        SELECT id, COALESCE(sku_woo,'') AS sku_woo
        FROM productos
        WHERE COALESCE(sucursal,%s)=%s
        ORDER BY id
        LIMIT %s
    """, (DEFAULT_SUCURSAL, sucursal, max(1, min(int(limit or 500), 2000))))
    productos = dict_fetchall(cur)
    updated = 0
    sin_match = 0
    errores = []
    for p in productos:
        sku = str(p.get("sku_woo") or "").strip().upper() or f"ERP-{p['id']}"
        found = woo_request("get", "products", sucursal=sucursal, params={"sku": sku, "per_page": 1})
        if not found.get("ok"):
            errores.append({"id": p.get("id"), "sku": sku, "msg": found.get("msg", "Error WooCommerce")})
            continue
        items = found.get("data") or []
        if not items:
            sin_match += 1
            continue
        item = items[0]
        categories = item.get("categories") or []
        cat_id = 0
        sub_id = 0
        cat_name = ""
        sub_name = ""
        parent_id = 0
        if categories:
            last = categories[-1] if isinstance(categories[-1], dict) else {}
            cat_id = int(last.get("id") or 0)
            sub_name = str(last.get("name") or names.get(cat_id) or "").strip()
            detail = woo_request("get", f"products/categories/{cat_id}", sucursal=sucursal) if cat_id else {}
            parent_id = int((detail.get("data") or {}).get("parent") or 0) if detail.get("ok") else 0
            if parent_id > 0:
                sub_id = cat_id
                cat_name = str(names.get(parent_id) or "").strip()
                if not cat_name:
                    parent = woo_request("get", f"products/categories/{parent_id}", sucursal=sucursal)
                    if parent.get("ok"):
                        cat_name = str((parent.get("data") or {}).get("name") or "").strip()
            else:
                cat_name = sub_name
                sub_name = ""
                sub_id = 0
        woo_cat_id = parent_id if sub_id else cat_id
        cur.execute("""
            UPDATE productos
            SET categoria_web=%s, subcategoria_web=%s, woo_categoria_id=%s, woo_subcategoria_id=%s,
                woo_id=%s
            WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (
            cat_name, sub_name, woo_cat_id, sub_id,
            int(item.get("id") or 0),
            p["id"], DEFAULT_SUCURSAL, sucursal,
        ))
        updated += 1
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "success": True,
        "updated": updated,
        "sin_match": sin_match,
        "total": len(productos),
        "msg": f"Categorias web aplicadas al ERP: {updated}. Sin coincidencia por SKU: {sin_match}.",
        "errores": errores[:20],
    }


def woo_sync_price_by_sku(sku: str, price, sucursal: str = DEFAULT_SUCURSAL):
    sku = str(sku or "").strip().upper()
    if not sku:
        return {"ok": False, "msg": "Producto sin codigo web/SKU."}
    try:
        price_value = float(price or 0)
    except Exception:
        return {"ok": False, "msg": f"Precio invalido para SKU {sku}."}
    if price_value <= 0:
        return {"ok": False, "msg": f"Precio no sincronizado para SKU {sku}: el precio ERP esta en cero."}
    regular_price = f"{price_value:.2f}"
    found = woo_request("get", "products", sucursal=sucursal, params={"sku": sku, "per_page": 1})
    if not found.get("ok"):
        return found
    existing = found.get("data") or []
    if not existing:
        return {"ok": False, "msg": f"No existe producto WooCommerce con SKU {sku}."}
    woo_id = existing[0].get("id")
    updated = woo_request("put", f"products/{woo_id}", sucursal=sucursal, json={"regular_price": regular_price})
    if not updated.get("ok"):
        return updated
    return {"ok": True, "sku": sku, "woo_id": woo_id, "regular_price": regular_price, "data": updated.get("data", {})}


# ================= CATALOGO EXTERNO: COMPUVISION =================
COMPUVISION_HOME_URL = "https://compuvisionperu.pe/CYM/"
COMPUVISION_AJAX_PRODUCTS_URL = "https://compuvisionperu.pe/ajax/ajs_productos.php"


def compuvision_request_product(product_id):
    product_id = str(product_id or "").strip()
    if not product_id:
        return {"ok": False, "msg": "ID de producto requerido."}
    body = urllib.parse.urlencode({"idProd": product_id, "tipo": "prod-s-data"}).encode("utf-8")
    req = urllib.request.Request(
        COMPUVISION_AJAX_PRODUCTS_URL,
        data=body,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 G&G ERP",
            "Referer": COMPUVISION_HOME_URL,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict) or not data.get("prod_id"):
            return {"ok": False, "msg": "Producto CompuVision no encontrado.", "raw": raw[:300]}
        return {"ok": True, "data": compuvision_normalize_product(data)}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def compuvision_home_data():
    req = urllib.request.Request(COMPUVISION_HOME_URL, headers={"User-Agent": "Mozilla/5.0 G&G ERP"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="replace")


def compuvision_exchange_rate(html_text=None):
    try:
        text = html_text if html_text is not None else compuvision_home_data()
        match = re.search(r"Tc:\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
        if match:
            return float(match.group(1))
    except Exception:
        pass
    return 3.45


def compuvision_image_url(value):
    src = str(value or "").strip()
    if not src:
        return ""
    if src.startswith(("http://", "https://")):
        return src
    if src.startswith("../"):
        src = src[3:]
    if src.startswith("/"):
        return f"https://compuvisionperu.pe{src}"
    return f"https://compuvisionperu.pe/{src.lstrip('/')}"


def compuvision_normalize_product(raw):
    tc = compuvision_exchange_rate()
    price_usd = float(raw.get("precio") or raw.get("precio_prod") or 0)
    sale_usd = raw.get("precio_oferta")
    try:
        sale_usd = float(sale_usd) if sale_usd not in (None, "") else None
    except Exception:
        sale_usd = None
    final_usd = sale_usd if sale_usd and sale_usd > 0 else price_usd
    images = raw.get("imagenes") if isinstance(raw.get("imagenes"), list) else []
    image_url = ""
    if images:
        first = images[0] if isinstance(images[0], dict) else {}
        image_url = compuvision_image_url(first.get("imagen_url") or first.get("imagen") or first.get("url"))
    return {
        "proveedor": "COMPUVISION",
        "external_id": str(raw.get("prod_id") or ""),
        "codigo_proveedor": f"CV-{raw.get('prod_id')}",
        "codigo": str(raw.get("prod_cod") or raw.get("cod_esp") or ""),
        "nombre": html.unescape(str(raw.get("nom_prod") or raw.get("nombre") or "")).strip(),
        "categoria": html.unescape(str(raw.get("categoria") or "")).strip().upper(),
        "marca": html.unescape(str(raw.get("marca") or "")).strip().upper(),
        "modelo": html.unescape(str(raw.get("cod_esp") or raw.get("prod_cod") or "")).strip().upper(),
        "precio_usd": round(final_usd, 2),
        "precio_regular_usd": round(price_usd, 2),
        "precio_oferta_usd": sale_usd,
        "tc": tc,
        "precio_soles": round(final_usd * tc, 2),
        "stock": int(float(raw.get("stock") or raw.get("stock_prod") or 0)),
        "garantia": html.unescape(str(raw.get("garantia") or "")).strip(),
        "imagen_url": image_url,
        "url": f"https://compuvisionperu.pe/CYM/producto/{raw.get('prod_id')}",
    }


@app.get("/web/compuvision/product/{product_id}")
def compuvision_product(product_id: str):
    return compuvision_request_product(product_id)


@app.get("/web/compuvision/products")
def compuvision_products(q: str = "", limit: int = 40):
    limit = max(1, min(int(limit or 40), 80))
    try:
        page = compuvision_home_data()
        ids = []
        for match in re.finditer(r"espe_prod_carr\((\d+)\)", page):
            pid = match.group(1)
            if pid not in ids:
                ids.append(pid)
        query = str(q or "").strip().lower()
        data = []
        for pid in ids[: max(limit * 3, limit)]:
            r = compuvision_request_product(pid)
            if not r.get("ok"):
                continue
            item = r.get("data") or {}
            haystack = f"{item.get('nombre','')} {item.get('categoria','')} {item.get('marca','')} {item.get('modelo','')} {item.get('codigo','')} {item.get('external_id','')}".lower()
            if query and query not in haystack:
                continue
            data.append(item)
            if len(data) >= limit:
                break
        return {"ok": True, "success": True, "total": len(data), "data": data}
    except Exception as e:
        return {"ok": False, "success": False, "msg": str(e), "data": []}


@app.post("/web/compuvision/import/{product_id}")
def compuvision_import_product(product_id: str, data: dict = None, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal((data or {}).get("sucursal") or (data or {}).get("empresa") or sucursal)
    r = compuvision_request_product(product_id)
    if not r.get("ok"):
        return r
    p = r.get("data") or {}
    codigo = p.get("codigo_proveedor") or f"CV-{product_id}"
    precio = float(p.get("precio_soles") or 0)
    stock = int(p.get("stock") or 0)
    observacion = f"Proveedor COMPUVISION / ID {p.get('external_id')} / Codigo {p.get('codigo')} / USD {p.get('precio_usd')} / TC {p.get('tc')} / {p.get('garantia')}"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS codigo_proveedor TEXT DEFAULT ''")
    cur.execute("""
        SELECT id FROM productos
        WHERE COALESCE(sucursal,%s)=%s AND codigo_proveedor=%s
        LIMIT 1
    """, (DEFAULT_SUCURSAL, sucursal, codigo))
    existing = cur.fetchone()
    if existing:
        cur.execute("""
        UPDATE productos
        SET nombre=%s, categoria=%s, marca=%s, modelo=%s, precio_compra=%s,
            precio_venta=%s, stock=%s, imagen_url=%s, observacion=%s
        WHERE id=%s
        RETURNING id
        """, (
            p.get("nombre") or f"Producto CompuVision {product_id}",
            p.get("categoria") or "COMPUVISION",
            p.get("marca") or "",
            p.get("modelo") or "",
            precio, precio, stock, p.get("imagen_url") or "", observacion, existing[0]
        ))
        producto_id = cur.fetchone()[0]
        action = "actualizado"
    else:
        cur.execute("""
        INSERT INTO productos (nombre,categoria,marca,modelo,precio_compra,precio_venta,stock,imagen_url,observacion,almacen,sucursal,codigo_proveedor)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """, (
            p.get("nombre") or f"Producto CompuVision {product_id}",
            p.get("categoria") or "COMPUVISION",
            p.get("marca") or "",
            p.get("modelo") or "",
            precio, precio, stock, p.get("imagen_url") or "", observacion, "TIENDA", sucursal, codigo
        ))
        producto_id = cur.fetchone()[0]
        action = "importado"
    conn.commit()
    conn.close()
    return {"ok": True, "success": True, "msg": f"Producto {action} desde CompuVision: {p.get('nombre')}", "id": producto_id, "action": action, "producto": p}


@app.get("/web/config")
def obtener_web_config(sucursal: str = DEFAULT_SUCURSAL):
    data = web_config_for_sucursal(sucursal)
    public = dict(data)
    if public.get("wc_consumer_secret"):
        public["wc_consumer_secret_masked"] = True
    if public.get("wp_app_password"):
        public["wp_app_password_masked"] = True
    return {"ok": True, "success": True, "data": public}


@app.post("/web/config")
def guardar_web_config(data: dict, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(data.get("sucursal") or data.get("empresa") or sucursal)
    clean = save_web_config_for_sucursal(sucursal, data)
    return {"ok": True, "success": True, "sucursal": sucursal, "data": clean}


@app.get("/web/woocommerce/categories")
def woo_categories(parent_id: int = None, tree: bool = False, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    if tree:
        return woo_categories_tree(sucursal=sucursal)
    return woo_list_categories(sucursal=sucursal, parent_id=parent_id)


@app.post("/web/woocommerce/apply-categories-to-erp")
def woo_apply_categories_to_erp(data: dict = None, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal((data or {}).get("sucursal") or (data or {}).get("empresa") or sucursal)
    limit = int((data or {}).get("limit") or 500)
    return woo_apply_web_categories_to_erp(sucursal=sucursal, limit=limit)


@app.get("/web/woocommerce/test")
def woo_test(sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    r = woo_request("get", "products", sucursal=sucursal, params={"per_page": 1})
    if not r.get("ok"):
        return r
    return {"ok": True, "site_url": r.get("site_url"), "msg": "Conexion WooCommerce correcta"}


@app.get("/web/woocommerce/products")
def woo_products(search: str = "", sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    params = {"per_page": 50, "orderby": "date", "order": "desc"}
    if search:
        params["search"] = search
    r = woo_request("get", "products", sucursal=sucursal, params=params)
    if not r.get("ok"):
        return r
    return {"ok": True, "data": r.get("data", [])}


@app.get("/web/woocommerce/products/{producto_id}")
def woo_product(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    r = woo_request("get", f"products/{producto_id}", sucursal=sucursal)
    if not r.get("ok"):
        return r
    return {"ok": True, "data": r.get("data", {})}


@app.post("/web/woocommerce/products")
def woo_create_product(data: WooProduct, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    r = woo_request("post", "products", sucursal=sucursal, json=woo_payload_from_model(data))
    if not r.get("ok"):
        return r
    return {"ok": True, "data": r.get("data", {})}


@app.put("/web/woocommerce/products/{producto_id}")
def woo_update_product(producto_id: int, data: WooProduct, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    r = woo_request("put", f"products/{producto_id}", sucursal=sucursal, json=woo_payload_from_model(data))
    if not r.get("ok"):
        return r
    return {"ok": True, "data": r.get("data", {})}


@app.post("/web/woocommerce/sync-product/{producto_id}")
def woo_sync_product(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, nombre, categoria, marca, modelo, precio_venta, stock,
               COALESCE(imagen_url,'') AS imagen_url, COALESCE(sku_woo,'') AS sku_woo
        FROM productos
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (producto_id, DEFAULT_SUCURSAL, sucursal))
    p = dict_fetchone(cur)
    conn.close()
    if not p:
        return {"ok": False, "msg": "Producto ERP no encontrado."}
    r = woo_upsert_erp_product(p, sucursal=sucursal)
    if not r.get("ok"):
        return r
    return {"ok": True, "msg": f"Producto {r.get('action')} en WooCommerce.", "data": r.get("data", {})}


@app.post("/web/woocommerce/upload-image/{producto_id}")
def woo_upload_product_image(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, nombre, COALESCE(imagen_url,'') AS imagen_url, COALESCE(sku_woo,'') AS sku_woo, COALESCE(woo_id,0) AS woo_id
        FROM productos
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (producto_id, DEFAULT_SUCURSAL, sucursal))
    p = dict_fetchone(cur)
    conn.close()
    if not p:
        return {"ok": False, "msg": "Producto ERP no encontrado."}
    image_url = woo_resolve_product_image_url(p, sucursal=sucursal)
    if not image_url:
        return {"ok": False, "msg": "El producto no tiene imagen para subir."}
    sku = str(p.get("sku_woo") or "").strip().upper() or f"ERP-{producto_id}"
    woo_id = int(p.get("woo_id") or 0)
    if not woo_id:
        found = woo_request("get", "products", sucursal=sucursal, params={"sku": sku, "per_page": 1})
        if found.get("ok") and (found.get("data") or []):
            woo_id = int(found["data"][0].get("id") or 0)
    if not woo_id:
        return {"ok": False, "msg": "Primero sincroniza el producto con WooCommerce."}
    updated = woo_request("put", f"products/{woo_id}", sucursal=sucursal, json={"images": [{"src": image_url}]})
    if not updated.get("ok"):
        return updated
    return {
        "ok": True,
        "msg": "Imagen enviada a WooCommerce.",
        "image_url": image_url,
        "woo_id": woo_id,
        "data": updated.get("data", {}),
    }


@app.post("/web/woocommerce/sync-products")
def woo_sync_products(data: dict = None, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    only_with_stock = bool((data or {}).get("only_with_stock", False))
    conn = get_conn()
    cur = conn.cursor()
    sql = """
        SELECT id, nombre, categoria, marca, modelo, precio_venta, stock, COALESCE(imagen_url,'') AS imagen_url, COALESCE(sku_woo,'') AS sku_woo
        FROM productos
        WHERE COALESCE(sucursal,%s)=%s
    """
    params = [DEFAULT_SUCURSAL, sucursal]
    if only_with_stock:
        sql += " AND COALESCE(stock,0) > 0"
    sql += " ORDER BY id LIMIT 300"
    cur.execute(sql, params)
    productos = dict_fetchall(cur)
    conn.close()
    ok = 0
    errores = []
    for p in productos:
        r = woo_upsert_erp_product(p, sucursal=sucursal)
        if r.get("ok"):
            ok += 1
        else:
            errores.append({"id": p.get("id"), "nombre": p.get("nombre"), "msg": r.get("msg", "Error WooCommerce")})
    return {"ok": True, "success": True, "total": len(productos), "sync_ok": ok, "errores": errores[:20]}


@app.post("/web/woocommerce/sync-price/{producto_id}")
def woo_sync_product_price(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS sku_woo TEXT DEFAULT ''")
    cur.execute("""
        SELECT id, nombre, precio_venta, COALESCE(sku_woo,'') AS sku_woo
        FROM productos
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (producto_id, DEFAULT_SUCURSAL, sucursal))
    p = dict_fetchone(cur)
    conn.close()
    if not p:
        return {"ok": False, "success": False, "msg": "Producto ERP no encontrado."}
    r = woo_sync_price_by_sku(p.get("sku_woo"), p.get("precio_venta"), sucursal=sucursal)
    if not r.get("ok"):
        return {"ok": False, "success": False, "msg": r.get("msg", "No se pudo sincronizar precio."), "producto": p}
    return {"ok": True, "success": True, "msg": f"Precio sincronizado por SKU {r.get('sku')}: S/ {r.get('regular_price')}", "producto": p, "data": r}


@app.post("/web/woocommerce/sync-prices")
def woo_sync_prices(data: dict = None, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    only_with_sku = bool((data or {}).get("only_with_sku", True))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS sku_woo TEXT DEFAULT ''")
    sql = """
        SELECT id, nombre, precio_venta, COALESCE(sku_woo,'') AS sku_woo
        FROM productos
        WHERE COALESCE(sucursal,%s)=%s
    """
    params = [DEFAULT_SUCURSAL, sucursal]
    if only_with_sku:
        sql += " AND TRIM(COALESCE(sku_woo,''))<>''"
    sql += " ORDER BY id LIMIT 500"
    cur.execute(sql, params)
    productos = dict_fetchall(cur)
    conn.close()
    ok = 0
    omitidos = 0
    errores = []
    for p in productos:
        sku = str(p.get("sku_woo") or "").strip()
        if not sku:
            omitidos += 1
            continue
        r = woo_sync_price_by_sku(sku, p.get("precio_venta"), sucursal=sucursal)
        if r.get("ok"):
            ok += 1
        else:
            errores.append({"id": p.get("id"), "nombre": p.get("nombre"), "sku": sku, "msg": r.get("msg", "Error WooCommerce")})
    return {"ok": True, "success": True, "msg": f"Precios sincronizados: {ok}. Omitidos sin SKU: {omitidos}. Errores: {len(errores)}.", "total": len(productos), "sync_ok": ok, "omitidos": omitidos, "errores": errores[:30]}


@app.post("/web/woocommerce/sync-images")
def woo_sync_images_from_web(sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, nombre, COALESCE(imagen_url,'') AS imagen_url
        FROM productos
        WHERE COALESCE(sucursal,%s)=%s
        ORDER BY id
        LIMIT 500
    """, (DEFAULT_SUCURSAL, sucursal))
    productos = dict_fetchall(cur)
    updated = 0
    errores = []
    for p in productos:
        sku = f"ERP-{p['id']}"
        found = woo_request("get", "products", sucursal=sucursal, params={"sku": sku, "per_page": 1})
        if not found.get("ok"):
            errores.append({"id": p.get("id"), "msg": found.get("msg", "Error WooCommerce")})
            continue
        items = found.get("data") or []
        if not items:
            continue
        images = items[0].get("images") or []
        image_url = images[0].get("src", "") if images and isinstance(images[0], dict) else ""
        if image_url:
            cur.execute("""
                UPDATE productos
                SET imagen_url=%s
                WHERE id=%s AND COALESCE(sucursal,%s)=%s
            """, (image_url, p["id"], DEFAULT_SUCURSAL, sucursal))
            updated += 1
    conn.commit()
    conn.close()
    return {"ok": True, "success": True, "total": len(productos), "updated": updated, "errores": errores[:20]}


@app.post("/web/woocommerce/import-products")
def woo_import_products_to_erp(data: dict = None, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    search = str((data or {}).get("search", "") or "").strip()
    only_with_stock = bool((data or {}).get("only_with_stock", False))
    created = 0
    updated = 0
    errores = []
    page = 1
    conn = get_conn()
    cur = conn.cursor()
    try:
        while page <= 10:
            params = {"per_page": 100, "page": page, "orderby": "date", "order": "desc"}
            if search:
                params["search"] = search
            r = woo_request("get", "products", sucursal=sucursal, params=params)
            if not r.get("ok"):
                conn.rollback()
                conn.close()
                return r
            productos_web = r.get("data") or []
            if not productos_web:
                break
            for item in productos_web:
                try:
                    stock = item.get("stock_quantity")
                    stock = int(stock or 0)
                    if only_with_stock and stock <= 0:
                        continue
                    images = item.get("images") or []
                    image_url = images[0].get("src", "") if images and isinstance(images[0], dict) else ""
                    categories = item.get("categories") or []
                    categoria = categories[0].get("name", "WEB") if categories and isinstance(categories[0], dict) else "WEB"
                    sku = str(item.get("sku") or "").strip()
                    woo_id = int(item.get("id") or 0)
                    name = str(item.get("name") or f"Producto web {woo_id}").strip()
                    price_text = item.get("regular_price") or item.get("price") or "0"
                    try:
                        price = float(price_text or 0)
                    except Exception:
                        price = 0
                    cur.execute("""
                        SELECT id FROM productos
                        WHERE COALESCE(sucursal,%s)=%s
                          AND (woo_id=%s OR (%s <> '' AND sku_woo=%s) OR LOWER(nombre)=LOWER(%s))
                        ORDER BY id
                        LIMIT 1
                    """, (DEFAULT_SUCURSAL, sucursal, woo_id, sku, sku, name))
                    row = cur.fetchone()
                    if row:
                        cur.execute("""
                            UPDATE productos
                            SET nombre=%s, categoria=%s, marca=%s, modelo=%s,
                                precio_venta=%s, stock=%s, imagen_url=%s,
                                woo_id=%s, sku_woo=%s
                            WHERE id=%s
                        """, (name, categoria, "", "", price, stock, image_url, woo_id, sku, row[0]))
                        updated += 1
                    else:
                        cur.execute("""
                            INSERT INTO productos (
                                nombre, categoria, marca, modelo, precio_compra, precio_venta,
                                stock, imagen_url, sucursal, woo_id, sku_woo
                            )
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (name, categoria, "", "", 0, price, stock, image_url, sucursal, woo_id, sku))
                        created += 1
                except Exception as e:
                    errores.append({"woo_id": item.get("id"), "nombre": item.get("name"), "msg": str(e)})
            if len(productos_web) < 100:
                break
            page += 1
        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "created": created, "updated": updated, "errores": errores[:20]}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


# ================= GARANTIAS =================
def _resolver_producto_cambio_garantia(cur, data: Garantia, sucursal):
    sucursal_inv = inventario_sucursal(sucursal)
    producto_id = int(data.producto_cambio_id or 0)
    if producto_id:
        cur.execute("""
        SELECT id, COALESCE(nombre,''), COALESCE(marca,''), COALESCE(modelo,''), COALESCE(stock,0)
        FROM productos
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        LIMIT 1
        """, (producto_id, DEFAULT_SUCURSAL, sucursal_inv))
    else:
        nombre = str(data.producto_cambio or "").strip()
        if not nombre:
            return None, "Selecciona el producto que se entregara como cambio."
        cur.execute("""
        SELECT id, COALESCE(nombre,''), COALESCE(marca,''), COALESCE(modelo,''), COALESCE(stock,0)
        FROM productos
        WHERE COALESCE(sucursal,%s)=%s AND UPPER(COALESCE(nombre,''))=UPPER(%s)
        ORDER BY id DESC
        LIMIT 1
        """, (DEFAULT_SUCURSAL, sucursal_inv, nombre))
    row = cur.fetchone()
    if not row:
        return None, "Producto de cambio no encontrado en esta sucursal."
    return {
        "id": int(row[0]),
        "nombre": row[1] or "",
        "marca": row[2] or "",
        "modelo": row[3] or "",
        "stock": int(row[4] or 0),
    }, None


def _buscar_fila_serie_producto(cur, serie_texto, sucursal, producto_id=None):
    serie_norm = normalize_serie_key(serie_texto)
    if not serie_norm:
        return None, "Serie invalida."
    sucursal_inv = inventario_sucursal(sucursal)
    params = [DEFAULT_SUCURSAL, sucursal_inv, serie_norm]
    filtro_prod = ""
    if producto_id:
        filtro_prod = " AND ps.producto_id=%s"
        params.append(int(producto_id))
    cur.execute(f"""
    SELECT ps.id, ps.producto_id, ps.serie,
           UPPER(COALESCE(ps.estado,'DISPONIBLE')) AS estado,
           COALESCE(ps.almacen,'TIENDA') AS almacen
    FROM producto_series ps
    WHERE COALESCE(ps.sucursal,%s)=%s
      AND {SERIE_SQL_KEY}=%s
      {filtro_prod}
    ORDER BY ps.id DESC
    LIMIT 1
    """, tuple(params))
    row = dict_fetchone(cur)
    if not row:
        return None, f"La serie {serie_texto} no esta registrada."
    return row, None


def _marcar_serie_garantia_ingreso(cur, serie_texto, sucursal, usuario=""):
    serie_norm = normalize_serie_key(serie_texto)
    if not serie_norm:
        return None
    sucursal_inv = inventario_sucursal(sucursal)
    cur.execute(f"""
    UPDATE producto_series
    SET estado='GARANTIA_INGRESO',
        almacen='GARANTIA',
        fecha_salida=NULL
    WHERE COALESCE(sucursal,%s)=%s
      AND {SERIE_SQL_KEY}=%s
    RETURNING producto_id
    """, (DEFAULT_SUCURSAL, sucursal_inv, serie_norm))
    row = cur.fetchone()
    if row and row[0]:
        sync_producto_stock_from_series(cur, int(row[0]), sucursal)
    return serie_norm


def _marcar_serie_garantia_cambio(cur, serie_texto, producto_id, sucursal, usuario=""):
    row, error = _buscar_fila_serie_producto(cur, serie_texto, sucursal, producto_id)
    if error:
        return error
    estado = str(row.get("estado") or "").upper()
    if estado not in ("DISPONIBLE", "RESERVADO"):
        return f"La serie {row.get('serie')} no esta disponible para cambio (estado {estado})."
    cur.execute("""
    UPDATE producto_series
    SET estado='GARANTIA_CAMBIO',
        almacen='CLIENTE',
        fecha_salida=TO_CHAR((timezone('America/Lima', now()))::date, 'YYYY-MM-DD')
    WHERE id=%s
    """, (row.get("id"),))
    sync_producto_stock_from_series(cur, int(producto_id), sucursal)
    return None


def _siguiente_numero_garantia(cur, sucursal):
    sucursal = norm_sucursal(sucursal)
    seed_branch_series(cur, sucursal)
    cur.execute("""
    SELECT id, serie, correlativo
    FROM series
    WHERE UPPER(tipo)='GARANTIA' AND COALESCE(sucursal,%s)=%s
    LIMIT 1
    """, (DEFAULT_SUCURSAL, sucursal))
    row = cur.fetchone()
    if not row:
        return None, None, "No existe correlativo interno para documentos de garantia."
    serie_id, serie, corr = row
    numero = f"{serie}-{str(corr).zfill(6)}"
    return serie_id, numero, None


def _crear_documento_cambio_garantia(cur, garantia_id, data: Garantia, producto, sucursal):
    serie_id, numero, error = _siguiente_numero_garantia(cur, sucursal)
    if error:
        return None, error
    sucursal = norm_sucursal(sucursal)
    cliente = (data.cliente or "").strip() or "CLIENTE GARANTIA"
    documento_ref = (data.documento or "").strip()
    observacion = (
        f"CAMBIO GARANTIA #{garantia_id} | Boleta origen: {documento_ref or 'SIN DOC'} | "
        f"INGRESO: {data.serie or ''} | CAMBIO: {data.serie_cambio or ''} | "
        f"Sin cobro ni descuento de precio."
    )
    fecha_emision = lima_now()
    cur.execute("""
    INSERT INTO ventas (
        fecha, tipo, es_pase, numero, cliente, documento_cliente, direccion_cliente,
        subtotal, igv, total, observacion, fecha_vencimiento, usuario_emisor, estado,
        estado_pago, metodo_pago, sucursal
    )
    VALUES (%s,'GARANTIA',FALSE,%s,%s,'','',0,0,0,%s,NULL,%s,'EMITIDO','N/A','',%s)
    RETURNING id
    """, (fecha_emision, numero, cliente, observacion, data.usuario or "", sucursal))
    venta_id = cur.fetchone()[0]
    nombre = producto.get("nombre") or data.producto or ""
    marca = producto.get("marca") or ""
    modelo = producto.get("modelo") or ""
    prod_id = int(producto.get("id") or data.producto_cambio_id or 0)
    lineas = [
        ("INGRESO GARANTIA", data.serie or "", "Serie danada recibida en taller/garantia."),
        ("CAMBIO GARANTIA", data.serie_cambio or "", "Serie entregada al cliente en reemplazo."),
    ]
    for desc_pref, serie_linea, nota in lineas:
        if not str(serie_linea or "").strip():
            continue
        cur.execute("""
        INSERT INTO ventas_detalle (
            venta_id, producto_id, descripcion, marca, modelo,
            series_texto, cantidad, precio, total, sucursal
        )
        VALUES (%s,%s,%s,%s,%s,%s,1,0,0,%s)
        """, (
            venta_id, prod_id, f"{desc_pref} - {nombre} ({nota})",
            marca, modelo, str(serie_linea).strip().upper(), sucursal,
        ))
    cur.execute("UPDATE series SET correlativo = correlativo + 1 WHERE id=%s", (serie_id,))
    try:
        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,%s,%s,%s,%s)
        """, (
            data.usuario or "", "", sucursal, "DOCUMENTO GARANTIA CAMBIO",
            f"{numero} | Ingreso {data.serie or ''} | Cambio {data.serie_cambio or ''} | Garantia #{garantia_id}",
        ))
    except Exception:
        pass
    return {"id": venta_id, "numero": numero, "tipo": "GARANTIA"}, None


def _aplicar_cambio_garantia(cur, garantia_id, data: Garantia, sucursal):
    if not data.aplicar_cambio:
        return None, None
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
    SELECT COALESCE(cambio_aplicado,FALSE)
    FROM garantias
    WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (garantia_id, DEFAULT_SUCURSAL, sucursal))
    row = cur.fetchone()
    if row and bool(row[0]):
        return "Esta garantia ya tiene cambio aplicado.", None

    cantidad = max(1, int(data.cantidad_cambio or 1))
    if cantidad != 1:
        return "El cambio de garantia solo admite 1 serie de reemplazo por operacion.", None
    producto, error = _resolver_producto_cambio_garantia(cur, data, sucursal)
    if error:
        return error, None
    if not str(data.serie_cambio or "").strip():
        return "Selecciona la serie de reemplazo.", None

    if data.serie:
        _marcar_serie_garantia_ingreso(cur, data.serie, sucursal, data.usuario or "")
    error_salida = _marcar_serie_garantia_cambio(
        cur, data.serie_cambio, producto["id"], sucursal, data.usuario or ""
    )
    if error_salida:
        return error_salida, None

    documento, error_doc = _crear_documento_cambio_garantia(cur, garantia_id, data, producto, sucursal)
    if error_doc:
        return error_doc, None

    cur.execute("""
    UPDATE garantias
    SET producto_cambio_id=%s,
        producto_cambio=%s,
        serie_cambio=%s,
        cantidad_cambio=%s,
        diferencia_precio=0,
        cambio_aplicado=TRUE,
        cambio_fecha=CURRENT_TIMESTAMP,
        estado='ENTREGADO',
        documento_cambio_id=%s,
        documento_cambio_numero=%s,
        solucion=CASE
            WHEN COALESCE(solucion,'')='' THEN %s
            ELSE solucion
        END
    WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (
        producto["id"], producto["nombre"], data.serie_cambio, cantidad,
        documento.get("id"), documento.get("numero"),
        f"CAMBIO GARANTIA {documento.get('numero')}: ingreso {data.serie or ''} / entrega {data.serie_cambio or ''}",
        garantia_id, DEFAULT_SUCURSAL, sucursal,
    ))
    return None, documento


def _marcar_serie_garantia(cur, serie_texto, sucursal):
    _marcar_serie_garantia_ingreso(cur, serie_texto, sucursal)


@app.get("/garantias/buscar-serie")
def buscar_serie_garantia(q: str = "", sucursal: str = DEFAULT_SUCURSAL):
    serie_q = str(q or "").strip()
    if not serie_q:
        return {"ok": False, "msg": "Serie requerida"}
    sucursal = norm_sucursal(sucursal)
    sucursal_inv = inventario_sucursal(sucursal)
    serie_norm = normalize_serie_key(serie_q)
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(f"""
        SELECT
            ps.id,
            ps.producto_id,
            COALESCE(p.nombre,'') AS producto_nombre,
            COALESCE(p.marca,'') AS marca,
            COALESCE(p.modelo,'') AS modelo,
            COALESCE(p.categoria,'') AS categoria,
            COALESCE(p.imagen_url,'') AS imagen_url,
            COALESCE(p.stock,0) AS stock,
            ps.serie,
            ps.proveedor,
            ps.estado,
            COALESCE(ps.almacen,'TIENDA') AS almacen,
            ps.fecha_ingreso,
            ps.fecha_salida
        FROM producto_series ps
        LEFT JOIN productos p ON p.id = ps.producto_id AND COALESCE(p.sucursal,%s)=%s
        WHERE COALESCE(ps.sucursal,%s)=%s
          AND ({SERIE_SQL_KEY}=%s OR LOWER(COALESCE(ps.serie,'')) LIKE %s)
        ORDER BY CASE WHEN {SERIE_SQL_KEY}=%s THEN 0 ELSE 1 END, ps.id DESC
        LIMIT 5
        """, (
            DEFAULT_SUCURSAL, sucursal_inv,
            DEFAULT_SUCURSAL, sucursal_inv,
            serie_norm, f"%{serie_q.lower()}%",
            serie_norm,
        ))
        series_rows = dict_fetchall(cur)
        if not series_rows:
            conn.close()
            return {"ok": False, "msg": f"No se encontro la serie {serie_q}"}

        serie_row = series_rows[0]
        producto_id = int(serie_row.get("producto_id") or 0)

        boleta = None
        cur.execute("""
        SELECT
            v.id,
            v.tipo,
            v.numero,
            COALESCE(v.cliente,'') AS cliente_nombre,
            COALESCE(v.documento_cliente,'') AS documento_cliente,
            to_char(v.fecha, 'YYYY-MM-DD') AS fecha_emision,
            COALESCE(v.total,0) AS total,
            vd.id AS detalle_id,
            COALESCE(vd.descripcion,'') AS descripcion,
            COALESCE(vd.marca,'') AS marca,
            COALESCE(vd.modelo,'') AS modelo,
            COALESCE(vd.series_texto,'') AS series_texto,
            COALESCE(vd.cantidad,0) AS cantidad,
            COALESCE(vd.precio,0) AS precio_unitario,
            COALESCE(vd.total,0) AS linea_total,
            COALESCE(vd.producto_id,0) AS producto_id
        FROM ventas_detalle vd
        JOIN ventas v ON v.id = vd.venta_id
        WHERE COALESCE(v.sucursal,%s)=%s
          AND COALESCE(vd.sucursal,%s)=%s
          AND COALESCE(vd.series_texto,'')<>''
          AND (
            LOWER(COALESCE(vd.series_texto,'')) LIKE %s
            OR (%s <> '' AND POSITION(%s IN regexp_replace(UPPER(COALESCE(vd.series_texto,'')), '[^A-Z0-9]', '', 'g')) > 0)
          )
        ORDER BY v.id DESC
        LIMIT 30
        """, (
            DEFAULT_SUCURSAL, sucursal,
            DEFAULT_SUCURSAL, sucursal,
            f"%{serie_q.lower()}%",
            serie_norm, serie_norm,
        ))
        doc_candidates = dict_fetchall(cur)
        for doc_row in doc_candidates:
            series_doc = split_series_text(doc_row.get("series_texto"))
            if serie_norm in series_doc:
                boleta = _jsonable_row(doc_row)
                break
        if not boleta and doc_candidates:
            boleta = _jsonable_row(doc_candidates[0])

        series_disponibles = []
        if producto_id:
            cur.execute(f"""
            SELECT ps.id, ps.serie, ps.estado, COALESCE(ps.almacen,'TIENDA') AS almacen, ps.fecha_ingreso
            FROM producto_series ps
            WHERE ps.producto_id=%s AND COALESCE(ps.sucursal,%s)=%s
              AND UPPER(COALESCE(ps.estado,'DISPONIBLE')) IN ('DISPONIBLE','RESERVADO')
              AND %s <> '' AND {SERIE_SQL_KEY} <> %s
            ORDER BY
                CASE UPPER(COALESCE(ps.estado,'DISPONIBLE')) WHEN 'DISPONIBLE' THEN 0 ELSE 1 END,
                ps.id DESC
            """, (producto_id, DEFAULT_SUCURSAL, sucursal_inv, serie_norm, serie_norm))
            series_disponibles = dict_fetchall(cur)

        producto = {
            "id": producto_id,
            "nombre": serie_row.get("producto_nombre") or "",
            "marca": serie_row.get("marca") or "",
            "modelo": serie_row.get("modelo") or "",
            "categoria": serie_row.get("categoria") or "",
            "imagen_url": serie_row.get("imagen_url") or "",
            "stock": int(serie_row.get("stock") or 0),
        }
        conn.close()
        return {
            "ok": True,
            "success": True,
            "serie": _jsonable_row(serie_row),
            "producto": producto,
            "boleta": boleta,
            "series_disponibles": [_jsonable_row(r) for r in series_disponibles],
        }
    except Exception as e:
        conn.close()
        return {"ok": False, "msg": str(e)}


@app.get("/garantias")
def listar_garantias(q: str = "", sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    filtro = f"%{q.strip()}%"
    cur.execute("""
        SELECT id, to_char(fecha, 'YYYY-MM-DD HH24:MI:SS') AS fecha,
               COALESCE(cliente,'') AS cliente,
               COALESCE(documento,'') AS documento,
               COALESCE(producto,'') AS producto,
               COALESCE(serie,'') AS serie,
               COALESCE(falla,'') AS falla,
               COALESCE(estado,'RECIBIDO') AS estado,
               COALESCE(solucion,'') AS solucion,
               COALESCE(usuario,'') AS usuario,
               COALESCE(producto_cambio_id,0) AS producto_cambio_id,
               COALESCE(producto_cambio,'') AS producto_cambio,
               COALESCE(serie_cambio,'') AS serie_cambio,
               COALESCE(cantidad_cambio,0) AS cantidad_cambio,
               COALESCE(diferencia_precio,0) AS diferencia_precio,
               COALESCE(cambio_aplicado,FALSE) AS cambio_aplicado,
               COALESCE(to_char(cambio_fecha, 'YYYY-MM-DD HH24:MI:SS'),'') AS cambio_fecha,
               COALESCE(documento_cambio_id,0) AS documento_cambio_id,
               COALESCE(documento_cambio_numero,'') AS documento_cambio_numero,
               COALESCE(tipo_resolucion,'') AS tipo_resolucion,
               COALESCE(observacion_seguimiento,'') AS observacion_seguimiento,
               COALESCE(monto_devolucion,0) AS monto_devolucion,
               COALESCE(proveedor_garantia,'') AS proveedor_garantia,
               COALESCE(documento_seguimiento_id,0) AS documento_seguimiento_id,
               COALESCE(documento_seguimiento_numero,'') AS documento_seguimiento_numero,
               COALESCE(to_char(seguimiento_fecha, 'YYYY-MM-DD HH24:MI:SS'),'') AS seguimiento_fecha,
               COALESCE(seguimiento_usuario,'') AS seguimiento_usuario
        FROM garantias
        WHERE COALESCE(sucursal,%s)=%s
          AND (%s = '%%'
           OR cliente ILIKE %s
           OR documento ILIKE %s
           OR producto ILIKE %s
           OR serie ILIKE %s
           OR falla ILIKE %s
           OR serie_cambio ILIKE %s
           OR documento_cambio_numero ILIKE %s
           OR tipo_resolucion ILIKE %s
           OR observacion_seguimiento ILIKE %s
           OR documento_seguimiento_numero ILIKE %s
           OR proveedor_garantia ILIKE %s)
        ORDER BY fecha DESC, id DESC
        LIMIT 300
    """, (
        DEFAULT_SUCURSAL, sucursal, filtro, filtro, filtro, filtro, filtro, filtro,
        filtro, filtro, filtro, filtro, filtro, filtro,
    ))
    data = dict_fetchall(cur)
    conn.close()
    return data


def _garantia_select_sql():
    return """
        SELECT id, to_char(fecha, 'YYYY-MM-DD HH24:MI:SS') AS fecha,
               COALESCE(cliente,'') AS cliente,
               COALESCE(documento,'') AS documento,
               COALESCE(producto,'') AS producto,
               COALESCE(serie,'') AS serie,
               COALESCE(falla,'') AS falla,
               COALESCE(estado,'RECIBIDO') AS estado,
               COALESCE(solucion,'') AS solucion,
               COALESCE(usuario,'') AS usuario,
               COALESCE(producto_cambio_id,0) AS producto_cambio_id,
               COALESCE(producto_cambio,'') AS producto_cambio,
               COALESCE(serie_cambio,'') AS serie_cambio,
               COALESCE(cantidad_cambio,0) AS cantidad_cambio,
               COALESCE(diferencia_precio,0) AS diferencia_precio,
               COALESCE(cambio_aplicado,FALSE) AS cambio_aplicado,
               COALESCE(to_char(cambio_fecha, 'YYYY-MM-DD HH24:MI:SS'),'') AS cambio_fecha,
               COALESCE(documento_cambio_id,0) AS documento_cambio_id,
               COALESCE(documento_cambio_numero,'') AS documento_cambio_numero,
               COALESCE(tipo_resolucion,'') AS tipo_resolucion,
               COALESCE(observacion_seguimiento,'') AS observacion_seguimiento,
               COALESCE(monto_devolucion,0) AS monto_devolucion,
               COALESCE(proveedor_garantia,'') AS proveedor_garantia,
               COALESCE(documento_seguimiento_id,0) AS documento_seguimiento_id,
               COALESCE(documento_seguimiento_numero,'') AS documento_seguimiento_numero,
               COALESCE(to_char(seguimiento_fecha, 'YYYY-MM-DD HH24:MI:SS'),'') AS seguimiento_fecha,
               COALESCE(seguimiento_usuario,'') AS seguimiento_usuario
        FROM garantias
    """


def _fetch_garantia_row(cur, garantia_id, sucursal):
    cur.execute(_garantia_select_sql() + """
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        LIMIT 1
    """, (garantia_id, DEFAULT_SUCURSAL, sucursal))
    return dict_fetchone(cur)


def _siguiente_numero_documento_tipo(cur, sucursal, tipo_doc):
    sucursal = norm_sucursal(sucursal)
    seed_branch_series(cur, sucursal)
    cur.execute("""
    SELECT id, serie, correlativo
    FROM series
    WHERE UPPER(tipo)=UPPER(%s) AND COALESCE(sucursal,%s)=%s
    LIMIT 1
    """, (tipo_doc, DEFAULT_SUCURSAL, sucursal))
    row = cur.fetchone()
    if not row:
        return None, None, f"No existe correlativo para {tipo_doc}."
    serie_id, serie, corr = row
    numero = f"{serie}-{str(corr).zfill(6)}"
    return serie_id, numero, None


def _append_seguimiento_documento_garantia(cur, venta_id, titulo, detalle_texto, sucursal, monto=0):
    if not venta_id:
        return
    sucursal = norm_sucursal(sucursal)
    stamp = lima_now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
    SELECT COALESCE(observacion,'')
    FROM ventas
    WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (venta_id, DEFAULT_SUCURSAL, sucursal))
    row = cur.fetchone()
    obs_prev = str(row[0] if row else "").strip()
    bloque = f"[{stamp}] {titulo}: {detalle_texto}"
    nueva_obs = f"{obs_prev}\n{bloque}".strip() if obs_prev else bloque
    cur.execute("""
    UPDATE ventas
    SET observacion=%s
    WHERE id=%s AND COALESCE(sucursal,%s)=%s
    """, (nueva_obs, venta_id, DEFAULT_SUCURSAL, sucursal))
    cur.execute("""
    INSERT INTO ventas_detalle (
        venta_id, producto_id, descripcion, marca, modelo,
        series_texto, cantidad, precio, total, sucursal
    )
    VALUES (%s,0,%s,'','',%s,1,%s,%s,%s)
    """, (
        venta_id, titulo, detalle_texto[:500],
        float(monto or 0), float(monto or 0), sucursal,
    ))


def _crear_nota_credito_garantia(cur, garantia_row, data: GarantiaSeguimiento, sucursal):
    monto = round(float(data.monto_devolucion or 0), 2)
    if monto <= 0:
        return None, None
    serie_id, numero, error = _siguiente_numero_documento_tipo(cur, sucursal, "NOTA DE CREDITO")
    if error:
        return None, error
    sucursal = norm_sucursal(sucursal)
    cliente = (garantia_row.get("cliente") or "").strip() or "CLIENTE GARANTIA"
    tipo_res = (data.tipo_resolucion or "NOTA_CREDITO").upper()
    label = RESOLUCIONES_GARANTIA.get(tipo_res, tipo_res)
    doc_garantia = garantia_row.get("documento_cambio_numero") or ""
    doc_origen = garantia_row.get("documento") or ""
    observacion = (
        f"NOTA CREDITO GARANTIA #{garantia_row.get('id')} | Doc garantia: {doc_garantia or '-'} | "
        f"Boleta origen: {doc_origen or '-'} | {label} | {data.observacion_seguimiento or ''}"
    )
    fecha_emision = lima_now()
    cur.execute("""
    INSERT INTO ventas (
        fecha, tipo, es_pase, numero, cliente, documento_cliente, direccion_cliente,
        subtotal, igv, total, observacion, fecha_vencimiento, usuario_emisor, estado,
        estado_pago, metodo_pago, sucursal
    )
    VALUES (%s,'NOTA DE CREDITO',FALSE,%s,%s,'','',%s,0,%s,%s,NULL,%s,'EMITIDO','N/A','',%s)
    RETURNING id
    """, (
        fecha_emision, numero, cliente, monto, monto, observacion,
        data.usuario or "", sucursal,
    ))
    venta_id = cur.fetchone()[0]
    producto = garantia_row.get("producto") or "PRODUCTO GARANTIA"
    serie_ref = garantia_row.get("serie") or ""
    cur.execute("""
    INSERT INTO ventas_detalle (
        venta_id, producto_id, descripcion, marca, modelo,
        series_texto, cantidad, precio, total, sucursal
    )
    VALUES (%s,0,%s,'','',%s,1,%s,%s,%s)
    """, (
        venta_id,
        f"NC GARANTIA - {producto} ({label})",
        serie_ref,
        monto, monto, sucursal,
    ))
    cur.execute("UPDATE series SET correlativo = correlativo + 1 WHERE id=%s", (serie_id,))
    try:
        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,%s,%s,%s,%s)
        """, (
            data.usuario or "", "", sucursal, "NOTA CREDITO GARANTIA",
            f"{numero} | Garantia #{garantia_row.get('id')} | Monto {monto:.2f} | {label}",
        ))
    except Exception:
        pass
    return {"id": venta_id, "numero": numero, "tipo": "NOTA DE CREDITO", "monto": monto}, None


@app.get("/garantias/{garantia_id}")
def detalle_garantia(garantia_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    row = _fetch_garantia_row(cur, garantia_id, sucursal)
    conn.close()
    if not row:
        return {"ok": False, "msg": "Garantia no encontrada"}
    return {"ok": True, "success": True, "data": _jsonable_row(row), "resoluciones": RESOLUCIONES_GARANTIA}


@app.put("/garantias/{garantia_id}/seguimiento")
def actualizar_seguimiento_garantia(garantia_id: int, data: GarantiaSeguimiento):
    tipo_res = (data.tipo_resolucion or "").strip().upper()
    if tipo_res not in RESOLUCIONES_GARANTIA:
        return {"ok": False, "msg": "Selecciona un tipo de resolucion valido."}
    obs = (data.observacion_seguimiento or "").strip()
    if not obs:
        return {"ok": False, "msg": "La observacion del seguimiento es obligatoria."}

    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    garantia_row = _fetch_garantia_row(cur, garantia_id, sucursal)
    if not garantia_row:
        conn.close()
        return {"ok": False, "msg": "Garantia no encontrada"}

    label = RESOLUCIONES_GARANTIA.get(tipo_res, tipo_res)
    estado_map = {
        "REPARADO": "ENTREGADO",
        "RECHAZADO": "RECHAZADO",
        "EN_PROCESO": "REVISION",
        "PROVEEDOR_RESPONDIO": "REVISION",
        "DEVOLUCION_DINERO": "ENTREGADO",
        "NOTA_CREDITO": "ENTREGADO",
        "CAMBIO_PRODUCTO": "ENTREGADO",
    }
    nuevo_estado = (data.estado or estado_map.get(tipo_res) or garantia_row.get("estado") or "REVISION").upper()
    if nuevo_estado not in ("RECIBIDO", "REVISION", "APROBADO", "RECHAZADO", "ENTREGADO"):
        nuevo_estado = "REVISION"

    solucion_prev = str(garantia_row.get("solucion") or "").strip()
    solucion_nueva = (data.solucion or "").strip() or f"{label}: {obs}"
    if solucion_prev:
        solucion_nueva = f"{solucion_prev} | {solucion_nueva}"

    documento_seguimiento = None
    monto = round(float(data.monto_devolucion or 0), 2)
    if tipo_res in ("DEVOLUCION_DINERO", "NOTA_CREDITO") and monto > 0 and data.generar_nota_credito:
        documento_seguimiento, error_nc = _crear_nota_credito_garantia(cur, garantia_row, data, sucursal)
        if error_nc:
            conn.rollback()
            conn.close()
            return {"ok": False, "msg": error_nc}

    detalle_doc = obs
    if data.proveedor_garantia:
        detalle_doc = f"Proveedor: {data.proveedor_garantia} | {detalle_doc}"
    if data.serie_nueva:
        detalle_doc = f"Serie nueva: {data.serie_nueva} | {detalle_doc}"
    if monto > 0:
        detalle_doc = f"Monto: {monto:.2f} | {detalle_doc}"
    if documento_seguimiento:
        detalle_doc = f"NC {documento_seguimiento.get('numero')} | {detalle_doc}"

    doc_cambio_id = int(garantia_row.get("documento_cambio_id") or 0)
    if doc_cambio_id:
        _append_seguimiento_documento_garantia(
            cur, doc_cambio_id, f"SEGUIMIENTO - {label}", detalle_doc, sucursal,
            monto if tipo_res in ("DEVOLUCION_DINERO", "NOTA_CREDITO") else 0,
        )

    cur.execute("""
    UPDATE garantias
    SET tipo_resolucion=%s,
        observacion_seguimiento=%s,
        monto_devolucion=%s,
        proveedor_garantia=%s,
        estado=%s,
        solucion=%s,
        documento_seguimiento_id=COALESCE(%s, documento_seguimiento_id),
        documento_seguimiento_numero=CASE
            WHEN %s <> '' THEN %s
            ELSE documento_seguimiento_numero
        END,
        seguimiento_fecha=CURRENT_TIMESTAMP,
        seguimiento_usuario=%s
    WHERE id=%s AND COALESCE(sucursal,%s)=%s
    RETURNING id
    """, (
        tipo_res, obs, monto, (data.proveedor_garantia or "").strip(),
        nuevo_estado, solucion_nueva,
        documento_seguimiento.get("id") if documento_seguimiento else None,
        documento_seguimiento.get("numero") if documento_seguimiento else "",
        documento_seguimiento.get("numero") if documento_seguimiento else "",
        data.usuario or "", garantia_id, DEFAULT_SUCURSAL, sucursal,
    ))
    if not cur.fetchone():
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": "No se pudo actualizar la garantia"}

    try:
        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,%s,%s,%s,%s)
        """, (
            data.usuario or "", "", sucursal, "SEGUIMIENTO GARANTIA",
            f"#{garantia_id} {label} | {obs[:240]}",
        ))
    except Exception:
        pass

    conn.commit()
    updated = _fetch_garantia_row(cur, garantia_id, sucursal)
    conn.close()
    return {
        "ok": True,
        "success": True,
        "id": garantia_id,
        "data": _jsonable_row(updated) if updated else {},
        "documento_seguimiento": documento_seguimiento,
    }


@app.post("/garantias")
def guardar_garantia(data: Garantia):
    estado = (data.estado or "RECIBIDO").upper()
    if estado not in ("RECIBIDO", "REVISION", "APROBADO", "RECHAZADO", "ENTREGADO"):
        estado = "RECIBIDO"
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    cur.execute("""
        INSERT INTO garantias (
            cliente, documento, producto, serie, falla, estado, solucion, usuario, sucursal,
            producto_cambio_id, producto_cambio, serie_cambio, cantidad_cambio, diferencia_precio
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        data.cliente, data.documento, data.producto, data.serie,
        data.falla, estado, data.solucion, data.usuario, sucursal,
        data.producto_cambio_id, data.producto_cambio, data.serie_cambio,
        max(0, int(data.cantidad_cambio or 0)), float(data.diferencia_precio or 0)
    ))
    garantia_id = cur.fetchone()[0]
    if data.serie and not data.aplicar_cambio:
        _marcar_serie_garantia(cur, data.serie, sucursal)
    error_cambio, documento_cambio = _aplicar_cambio_garantia(cur, garantia_id, data, sucursal)
    if error_cambio:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": error_cambio}
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "success": True,
        "id": garantia_id,
        "documento_cambio": documento_cambio,
    }


@app.put("/garantias/{garantia_id}")
def actualizar_garantia(garantia_id: int, data: Garantia):
    estado = (data.estado or "RECIBIDO").upper()
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    cur.execute("""
        UPDATE garantias
        SET cliente=%s, documento=%s, producto=%s, serie=%s,
            falla=%s, estado=%s, solucion=%s, usuario=%s,
            producto_cambio_id=COALESCE(%s, producto_cambio_id),
            producto_cambio=%s,
            serie_cambio=%s,
            cantidad_cambio=%s,
            diferencia_precio=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id
    """, (
        data.cliente, data.documento, data.producto, data.serie,
        data.falla, estado, data.solucion, data.usuario,
        data.producto_cambio_id, data.producto_cambio, data.serie_cambio,
        max(0, int(data.cantidad_cambio or 0)), float(data.diferencia_precio or 0),
        garantia_id, DEFAULT_SUCURSAL, sucursal
    ))
    row = cur.fetchone()
    documento_cambio = None
    if row:
        error_cambio, documento_cambio = _aplicar_cambio_garantia(cur, garantia_id, data, sucursal)
        if error_cambio:
            conn.rollback()
            conn.close()
            return {"ok": False, "success": False, "msg": error_cambio}
    conn.commit()
    conn.close()
    if not row:
        return {"ok": False, "msg": "Garantia no encontrada"}
    return {"ok": True, "success": True, "documento_cambio": documento_cambio}


@app.get("/dashboard")
def dashboard(sucursal: str = DEFAULT_SUCURSAL, fecha: Optional[str] = None):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    tipos_venta_sql = "('BOLETA','FACTURA','NOTA DE VENTA')"
    target_date = f"'{fecha}'::date" if fecha else "(timezone('America/Lima', now()))::date"

    cur.execute("SELECT COUNT(*) FROM clientes WHERE COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, sucursal))
    clientes = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM productos WHERE COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, sucursal))
    productos = cur.fetchone()[0]
    cur.execute(f"""
        SELECT COUNT(*) FROM ventas
        WHERE UPPER(COALESCE(tipo,'')) IN {tipos_venta_sql}
          AND COALESCE(sucursal,%s)=%s
    """, (DEFAULT_SUCURSAL, sucursal))
    documentos = cur.fetchone()[0]
    cur.execute(f"""
        SELECT COALESCE(SUM(total),0)
        FROM ventas
        WHERE UPPER(COALESCE(tipo,'')) IN {tipos_venta_sql}
          AND fecha >= date_trunc('month', (timezone('America/Lima', now()))::date)
          AND COALESCE(sucursal,%s)=%s
    """, (DEFAULT_SUCURSAL, sucursal))
    total_ventas_mes = float(cur.fetchone()[0] or 0)
    cur.execute(f"""
        SELECT COALESCE(SUM(total),0)
        FROM ventas
        WHERE UPPER(COALESCE(tipo,'')) IN {tipos_venta_sql}
          AND fecha::date = {target_date}
          AND COALESCE(sucursal,%s)=%s
    """, (DEFAULT_SUCURSAL, sucursal))
    total_ventas_hoy = float(cur.fetchone()[0] or 0)
    try:
        cur.execute(f"""
        SELECT COALESCE(SUM(
            CASE
                WHEN COALESCE(estado_pago,'PAGADO')='PAGADO'
                    THEN COALESCE(NULLIF(monto_pagado,0), total, 0)
                WHEN COALESCE(monto_pagado,0) > 0
                    THEN monto_pagado
                ELSE 0
            END
        ),0)
        FROM ventas
        WHERE UPPER(COALESCE(tipo,'')) IN {tipos_venta_sql}
          AND fecha >= date_trunc('month', (timezone('America/Lima', now()))::date)
          AND COALESCE(sucursal,%s)=%s
        """, (DEFAULT_SUCURSAL, sucursal))
        saldo_caja_mes = float(cur.fetchone()[0] or 0)
    except Exception:
        saldo_caja_mes = total_ventas_mes
    try:
        cur.execute(f"""
        SELECT COALESCE(SUM(
            CASE
                WHEN COALESCE(estado_pago,'PAGADO')='PAGADO'
                    THEN COALESCE(NULLIF(monto_pagado,0), total, 0)
                WHEN COALESCE(monto_pagado,0) > 0
                    THEN monto_pagado
                ELSE 0
            END
        ),0)
        FROM ventas
        WHERE UPPER(COALESCE(tipo,'')) IN {tipos_venta_sql}
          AND fecha::date = {target_date}
          AND COALESCE(sucursal,%s)=%s
        """, (DEFAULT_SUCURSAL, sucursal))
        saldo_caja_hoy = float(cur.fetchone()[0] or 0)
    except Exception:
        saldo_caja_hoy = total_ventas_hoy

    cur.execute(f"""
        SELECT to_char(fecha::date, 'YYYY-MM-DD') AS dia, COALESCE(SUM(total), 0) AS total
        FROM ventas
        WHERE fecha >= (timezone('America/Lima', now()))::date - INTERVAL '29 days'
          AND UPPER(COALESCE(tipo,'')) IN {tipos_venta_sql}
          AND COALESCE(sucursal,%s)=%s
        GROUP BY fecha::date
        ORDER BY fecha::date
    """, (DEFAULT_SUCURSAL, sucursal))
    ventas_por_dia = [{"dia": r[0], "total": float(r[1] or 0)} for r in cur.fetchall()]

    cur.execute(f"""
        SELECT tipo, numero, COALESCE(cliente,''), COALESCE(total,0),
               COALESCE(estado_pago,'PAGADO'), COALESCE(usuario_emisor,'')
        FROM ventas
        WHERE UPPER(COALESCE(tipo,'')) IN {tipos_venta_sql}
          AND COALESCE(sucursal,%s)=%s
        ORDER BY fecha DESC, id DESC
        LIMIT 8
    """, (DEFAULT_SUCURSAL, sucursal))
    recientes = [
        {
            "tipo": r[0],
            "numero": r[1],
            "cliente": r[2],
            "total": float(r[3] or 0),
            "estado_pago": r[4],
            "usuario": r[5],
        }
        for r in cur.fetchall()
    ]

    cur.execute(f"""
        SELECT COALESCE(NULLIF(metodo_pago,''),'SIN METODO') AS metodo,
               COALESCE(SUM(COALESCE(NULLIF(monto_pagado,0), total, 0)),0) AS total
        FROM ventas
        WHERE COALESCE(estado_pago,'PAGADO')='PAGADO'
          AND UPPER(COALESCE(tipo,'')) IN {tipos_venta_sql}
          AND fecha::date = {target_date}
          AND COALESCE(sucursal,%s)=%s
        GROUP BY COALESCE(NULLIF(metodo_pago,''),'SIN METODO')
        ORDER BY total DESC
    """, (DEFAULT_SUCURSAL, sucursal))
    metodos_pago = [{"metodo": r[0], "total": float(r[1] or 0)} for r in cur.fetchall()]

    cur.execute("""
        SELECT id, nombre, categoria, marca, modelo, stock, precio_venta, COALESCE(imagen_url,'') AS imagen_url
        FROM productos
        WHERE COALESCE(stock,0) <= 5
          AND COALESCE(sucursal,%s)=%s
        ORDER BY stock ASC, nombre ASC
        LIMIT 8
    """, (DEFAULT_SUCURSAL, sucursal))
    productos_bajos = [
        {
            "id": r[0],
            "nombre": r[1],
            "categoria": r[2],
            "marca": r[3],
            "modelo": r[4],
            "stock": int(r[5] or 0),
            "precio_venta": float(r[6] or 0),
            "imagen_url": r[7],
        }
        for r in cur.fetchall()
    ]

    cur.execute("SELECT COUNT(*) FROM productos WHERE COALESCE(stock,0) <= 5 AND COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, sucursal))
    stock_bajo = int(cur.fetchone()[0] or 0)
    try:
        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(saldo),0)
            FROM reservas_clientes
            WHERE UPPER(COALESCE(estado,'RESERVADO'))='RESERVADO'
              AND COALESCE(sucursal,%s)=%s
        """, (DEFAULT_SUCURSAL, sucursal))
        reserva_row = cur.fetchone()
        reservas_activas = int(reserva_row[0] or 0)
        reservas_saldo = float(reserva_row[1] or 0)
    except Exception:
        conn.rollback()
        reservas_activas = 0
        reservas_saldo = 0.0
    cur.execute(f"""
        SELECT COUNT(*) FROM ventas
        WHERE COALESCE(estado_pago,'PAGADO') IN ('CREDITO','DEUDA')
          AND UPPER(COALESCE(tipo,'')) IN {tipos_venta_sql}
          AND COALESCE(sucursal,%s)=%s
    """, (DEFAULT_SUCURSAL, sucursal))
    facturas_cobrar = int(cur.fetchone()[0] or 0)
    try:
        cur.execute(f"""
            SELECT id, tipo, numero, COALESCE(cliente,''), COALESCE(total,0),
                   COALESCE(monto_pagado,0), COALESCE(estado_pago,'DEUDA'),
                   to_char(fecha, 'YYYY-MM-DD HH24:MI') AS fecha
            FROM ventas
            WHERE COALESCE(estado_pago,'PAGADO') IN ('CREDITO','DEUDA')
              AND UPPER(COALESCE(tipo,'')) IN {tipos_venta_sql}
              AND COALESCE(total,0) > COALESCE(monto_pagado,0)
              AND COALESCE(sucursal,%s)=%s
            ORDER BY fecha DESC, id DESC
            LIMIT 12
        """, (DEFAULT_SUCURSAL, sucursal))
        cuentas_cobrar = [
            {
                "id": r[0],
                "tipo": r[1],
                "numero": r[2],
                "cliente": r[3],
                "total": float(r[4] or 0),
                "pagado": float(r[5] or 0),
                "saldo": max(0.0, float(r[4] or 0) - float(r[5] or 0)),
                "estado_pago": r[6],
                "fecha": r[7],
            }
            for r in cur.fetchall()
        ]
        total_cuentas_cobrar = round(sum(float(row.get("saldo") or 0) for row in cuentas_cobrar), 2)
    except Exception:
        conn.rollback()
        cuentas_cobrar = []
        total_cuentas_cobrar = 0.0
    cur.execute("""
        SELECT COUNT(*) FROM ventas
        WHERE COALESCE(sunat_estado,'PENDIENTE') IN ('PENDIENTE','PROCESO')
          AND COALESCE(sunat_estado,'') <> 'INTERNO'
          AND UPPER(COALESCE(sunat_modo,'')) NOT IN ('NO_ENVIAR','INTERNO')
          AND UPPER(COALESCE(tipo,'')) IN ('BOLETA','FACTURA')
          AND COALESCE(sucursal,%s)=%s
    """, (DEFAULT_SUCURSAL, sucursal))
    documentos_pendientes = int(cur.fetchone()[0] or 0)
    cur.execute("SELECT COUNT(*) FROM clientes WHERE creado_en >= (timezone('America/Lima', now()))::date AND COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, sucursal))
    clientes_hoy = int(cur.fetchone()[0] or 0)
    try:
        cur.execute("SELECT COUNT(*) FROM compras WHERE COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, sucursal))
        compras_pendientes = int(cur.fetchone()[0] or 0)
    except Exception:
        compras_pendientes = 0

    conn.close()
    return {
        "clientes": clientes,
        "productos": productos,
        "documentos": documentos,
        "compras": 0,
        "total_ventas": total_ventas_hoy,
        "total_ventas_hoy": total_ventas_hoy,
        "total_ventas_mes": total_ventas_mes,
        "saldo_caja": saldo_caja_hoy,
        "saldo_caja_hoy": saldo_caja_hoy,
        "saldo_caja_mes": saldo_caja_mes,
        "ventas_por_dia": ventas_por_dia,
        "recientes": recientes,
        "metodos_pago": metodos_pago,
        "productos_bajos": productos_bajos,
        "stock_bajo": stock_bajo,
        "reservas_activas": reservas_activas,
        "reservas_saldo": reservas_saldo,
        "facturas_cobrar": facturas_cobrar,
        "cuentas_cobrar": cuentas_cobrar,
        "total_cuentas_cobrar": total_cuentas_cobrar,
        "documentos_pendientes": documentos_pendientes,
        "compras_pendientes": compras_pendientes,
        "clientes_hoy": clientes_hoy,
    }


@app.on_event("startup")
def _erp_run_migrations_at_boot():
    """Asegura columnas (monto_pagado, sunat_*, etc.) antes de atender /documentos."""
    result = migrate_schema()
    if not result.get("ok"):
        import logging
        logging.getLogger("uvicorn.error").error("migrate_schema al arranque: %s", result.get("error", result))


if __name__ == "__main__":
    import sys
    out = migrate_schema()
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0 if out.get("ok") else 1)


