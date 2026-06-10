from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
from decimal import Decimal
from datetime import date, datetime
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

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEBAPP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")
if os.path.isdir(WEBAPP_DIR):
    assets_dir = os.path.join(WEBAPP_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/erp/assets", StaticFiles(directory=assets_dir), name="erp_assets")
        app.mount("/assets", StaticFiles(directory=assets_dir), name="root_assets")
    sounds_dir = os.path.join(WEBAPP_DIR, "sounds")
    if os.path.isdir(sounds_dir):
        app.mount("/erp/sounds", StaticFiles(directory=sounds_dir), name="erp_sounds")
        app.mount("/sounds", StaticFiles(directory=sounds_dir), name="root_sounds")


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
MAX_COMPROBANTE_PAGO_BYTES = 15 * 1024 * 1024
BOQUITOQUI_LIVE_TTL_SECONDS = 10
BOQUITOQUI_LIVE_MAX_QUEUE = 30
_boquitoqui_live_lock = threading.Lock()
_boquitoqui_live_next_id = 1
_boquitoqui_live_queues = defaultdict(deque)

DEFAULT_FEATURES = {
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
    "pagina_web": True,
    "ajustes": True,
}


def norm_sucursal(value: str = ""):
    value = (value or DEFAULT_SUCURSAL).strip().lower().replace(" ", "_")
    return value or DEFAULT_SUCURSAL


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
        serie = str(item or "").strip()
        if not serie:
            continue
        serie = re.sub(r"^(s\s*/?\s*n|sn|serie)\s*[:\-]?\s*", "", serie, flags=re.I).strip()
        if serie:
            cleaned.append(serie.upper())
    return cleaned


def is_test_product_name(*values):
    text = " ".join(str(v or "") for v in values).upper()
    return any(marker in text for marker in TEST_PRODUCT_MARKERS)


def sync_producto_stock_from_series(cur, producto_id, sucursal):
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


def validar_y_marcar_series_venta(cur, producto_id, nombre_doc, marca_doc, modelo_doc, cantidad, series_texto, sucursal):
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
    SELECT id, UPPER(COALESCE(serie,'')) AS serie, UPPER(COALESCE(estado,'DISPONIBLE')) AS estado
    FROM producto_series
    WHERE producto_id=%s AND COALESCE(sucursal,%s)=%s
    """, (producto_id, DEFAULT_SUCURSAL, sucursal))
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
            WHERE UPPER(ps.serie)=UPPER(%s) AND COALESCE(ps.sucursal,%s)=%s
            LIMIT 1
            """, (serie, DEFAULT_SUCURSAL, sucursal))
            other = dict_fetchone(cur)
            if other:
                return f"{prod_nombre}: la serie {serie} pertenece a otro producto ({other.get('producto_nombre')}) o esta en estado {other.get('estado')}."
            return f"{prod_nombre}: la serie {serie} no esta registrada para este producto. Corrige series antes de pasar a Caja."
        if row and row.get("estado") not in ("DISPONIBLE", "RESERVADO"):
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
          AND UPPER(ps.serie)=ANY(%s)
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


def http_get_json(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "ignore")
        return json.loads(raw) if raw else {}


def normalizar_dni(data, numero, source):
    payload = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    nombres = first_value(payload, "nombres", "nombre", "first_name")
    paterno = first_value(payload, "apellidoPaterno", "apellido_paterno", "paterno", "ape_paterno", "first_last_name")
    materno = first_value(payload, "apellidoMaterno", "apellido_materno", "materno", "ape_materno", "second_last_name")
    nombre = first_value(payload, "nombreCompleto", "nombre_completo", "full_name", "razonSocial", "razon_social")
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
    cur.execute("""
    SELECT id, tipo_documento, numero_documento, nombre, direccion, COALESCE(sucursal,%s) AS sucursal
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
    data = http_get_json(url, headers={"Accept": "application/json", "Authorization": f"Bearer {token}"})
    return normalizar_dni(data, numero, "apis_net_pe") if tipo == "DNI" else normalizar_ruc(data, numero, "apis_net_pe")


def consulta_documento_apis_net_pe_v1(tipo, numero):
    if os.getenv("DISABLE_APIS_NET_PE_V1", "").strip().lower() in ("1", "true", "si", "yes"):
        return None
    base = os.getenv("APIS_NET_PE_V1_BASE", "https://api.apis.net.pe/v1").strip().rstrip("/")
    endpoint = "dni" if tipo == "DNI" else "ruc"
    url = f"{base}/{endpoint}?numero={urllib.parse.quote(numero)}"
    data = http_get_json(url, headers={"Accept": "application/json"})
    return normalizar_dni(data, numero, "apis_net_pe_v1") if tipo == "DNI" else normalizar_ruc(data, numero, "apis_net_pe_v1")


def consulta_documento_impl(numero, sucursal=DEFAULT_SUCURSAL):
    numero = only_digits(numero)
    tipo = "DNI" if len(numero) == 8 else "RUC" if len(numero) == 11 else ""
    if not tipo:
        return {"ok": False, "success": False, "found": False, "msg": "Ingresa 8 digitos para DNI o 11 para RUC."}

    local = buscar_cliente_db(numero, sucursal)
    if local:
        local["tipo_documento"] = tipo
        return local

    last_error = ""
    provider_configured = False
    for provider in (consulta_documento_custom, consulta_documento_apis_net_pe, consulta_documento_apis_net_pe_v1):
        try:
            if provider == consulta_documento_custom:
                provider_configured = provider_configured or bool(os.getenv(f"DOC_LOOKUP_{tipo}_URL", "").strip())
            if provider == consulta_documento_apis_net_pe:
                provider_configured = provider_configured or bool(os.getenv("APIS_NET_PE_TOKEN", "").strip())
            result = provider(tipo, numero)
            if result and result.get("found"):
                return result
        except Exception as e:
            last_error = str(e)

    if last_error:
        msg = last_error
    elif provider_configured:
        msg = "El proveedor respondio, pero no devolvio datos legibles para este documento."
    else:
        msg = "No se encontraron datos. Configura APIS_NET_PE_TOKEN o DOC_LOOKUP_DNI_URL/DOC_LOOKUP_RUC_URL en Render."
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


class Cliente(BaseModel):
    tipo_documento: str
    numero_documento: str
    nombre: str
    direccion: str
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


class DocumentoManualSeries(BaseModel):
    tipo: str = "BOLETA"
    numero: str = ""
    cliente_nombre: str = "CLIENTE MANUAL"
    fecha_emision: str = ""
    series_texto: str = ""
    usuario_emisor: str = ""
    observacion: str = ""
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


class DocumentoObservacionInternaUpdate(BaseModel):
    observacion_interna: str = ""
    usuario: str = ""


class DocumentoDetalleSeriesUpdate(BaseModel):
    series_texto: str = ""
    usuario: str = ""


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

        cur.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id SERIAL PRIMARY KEY,
            tipo TEXT UNIQUE,
            serie TEXT,
            correlativo INT
        );
        """)

        cur.execute("""
        INSERT INTO series (tipo, serie, correlativo)
        VALUES
            ('PROFORMA','P001',1),
            ('NOTA DE VENTA','N001',1),
            ('PASE','PA001',1),
            ('BOLETA','B001',1),
            ('FACTURA','F001',1)
        ON CONFLICT (tipo) DO NOTHING;
        """)
        cur.execute("ALTER TABLE series ADD COLUMN IF NOT EXISTS sucursal TEXT DEFAULT 'computer_army'")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS producto_series (
            id SERIAL PRIMARY KEY,
            producto_id INT REFERENCES productos(id) ON DELETE CASCADE,
            serie TEXT UNIQUE,
            proveedor TEXT,
            estado TEXT DEFAULT 'DISPONIBLE',
            fecha_ingreso TEXT,
            fecha_salida TEXT,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
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
    latest_url = "https://github.com/giomar456/erp-api/releases/download/v1.0.70/erp_sql_pro_v20_v1.0.70.exe"
    latest_name = "erp_sql_pro_v20_v1.0.70.exe"
    latest_notes = "Actualizacion G&G ERP v1.0.70: formato PDF referencia 1.0.52, visor PDF real, QR publico, edicion de proformas y reservas."

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

    android_version = os.getenv("ANDROID_APP_VERSION", "1.62")
    android_download_url = os.getenv("ANDROID_APP_DOWNLOAD_URL", "")
    android_apk_name = os.getenv("ANDROID_APP_APK_NAME", "GG_ERP_TELEFONO_v1.57_CAJA_PRODUCTOS_INSTALABLE.apk")
    android_dex_download_url = os.getenv("ANDROID_APP_DEX_DOWNLOAD_URL", android_download_url)
    android_dex_apk_name = os.getenv("ANDROID_APP_DEX_APK_NAME", "GG_ERP_TABLET_DEX_v1.57_CAJA_PRODUCTOS_INSTALABLE.apk")
    android_notes = os.getenv("ANDROID_APP_UPDATE_NOTES", "Actualizacion Android G&G ERP v1.62: PDF real para descargar/compartir, QR publico, edicion de proformas y reservas.")
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
               COALESCE(sucursal,%s) AS sucursal,
               COALESCE(boquitoqui_enabled,FALSE) AS boquitoqui_enabled,
               COALESCE(color_tema,'#304fb8') AS color_tema
        FROM usuarios
        WHERE lower(usuario)=lower(%s) AND clave=%s
    """,
                (DEFAULT_SUCURSAL, data["usuario"], data["clave"]))
    user = dict_fetchone(cur)

    conn.close()

    if not user:
        return {"ok": False}
    if str(user["usuario"]).strip().lower() != "giomar":
        user_branch = norm_sucursal(user.get("sucursal"))
        if user_branch != sucursal:
            return {"ok": False, "msg": "No tienes acceso a esta sucursal."}
        sucursal = user_branch

    return {"ok": True, "id": user["id"], "usuario": user["usuario"], "rol": user["rol"], "foto_url": user.get("foto_url", ""), "boquitoqui_enabled": bool(user.get("boquitoqui_enabled")), "color_tema": norm_theme_color(user.get("color_tema")), "sucursal": sucursal, "empresa": sucursal}


# ================= USUARIOS =================
@app.get("/usuarios")
def listar_usuarios(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
        SELECT id, usuario, rol, COALESCE(foto_url,'') AS foto_url,
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
        SELECT usuario, rol, COALESCE(foto_url,'') AS foto_url,
               COALESCE(sucursal,%s) AS sucursal,
               COALESCE(boquitoqui_enabled,FALSE) AS boquitoqui_enabled,
               COALESCE(color_tema,'#304fb8') AS color_tema
        FROM usuarios
        WHERE lower(usuario)=lower(%s)
    """, (DEFAULT_SUCURSAL, usuario.strip()))
    data = dict_fetchone(cur)
    conn.close()
    if not data:
        return {"ok": False, "found": False}
    return {"ok": True, "found": True, **data}


@app.post("/usuarios")
def guardar_usuario(data: Usuario):
    conn = get_conn()
    cur = conn.cursor()
    usuario = (data.usuario or "").strip()
    clave = data.clave or ""
    rol = (data.rol or "VENTAS").upper()
    foto_url = data.foto_url or ""
    radio_enabled = bool(data.boquitoqui_enabled)
    sucursal = norm_sucursal(data.sucursal)
    color_tema = norm_theme_color(data.color_tema)
    if rol not in ("ADMIN", "VENTAS"):
        rol = "VENTAS"
    if not usuario or not clave:
        conn.close()
        return {"ok": False, "msg": "Usuario y clave son obligatorios"}
    cur.execute("SELECT id FROM usuarios WHERE lower(usuario)=lower(%s)", (usuario,))
    existing = cur.fetchone()
    if existing:
        cur.execute("""
        UPDATE usuarios
        SET usuario=%s, clave=%s, rol=%s, sucursal=%s, boquitoqui_enabled=%s,
            color_tema=%s,
            foto_url=CASE WHEN %s <> '' THEN %s ELSE COALESCE(foto_url,'') END
        WHERE id=%s
        RETURNING id
        """, (usuario, clave, rol, sucursal, radio_enabled, color_tema, foto_url, foto_url, existing[0]))
    else:
        cur.execute("""
        INSERT INTO usuarios (usuario, clave, rol, foto_url, sucursal, boquitoqui_enabled, color_tema)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """, (usuario, clave, rol, foto_url, sucursal, radio_enabled, color_tema))
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


@app.get("/usuarios/online")
def listar_usuarios_online(sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.id, u.usuario, u.rol, COALESCE(u.foto_url,'') AS foto_url,
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
    for word in words:
        test = f"{current} {word}".strip()
        if canvas_obj.stringWidth(test, font_name, font_size) <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines or [""]


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
    title = {
        "BOLETA": "BOLETA DE VENTA\nELECTRONICA",
        "FACTURA": "FACTURA\nELECTRONICA",
        "PROFORMA": "PROFORMA",
        "PASE": "PASE",
        "NOTA DE VENTA": "NOTA DE VENTA",
    }.get(doc_type, doc_type)
    editor = cfg.get("doc_editor") if isinstance(cfg.get("doc_editor"), dict) else {}
    layout = editor.get("layout") if isinstance(editor.get("layout"), dict) else {}
    max_rows = max(1, min(int(float(layout.get("max_productos", 12) or 12)), 12))

    # Plantilla fija A4 alineada al formato Computer Army usado en PC/Android.
    logo_w = min(max(float(layout.get("logo_ancho_mm", 24) or 24), 16), 36)
    logo_h = min(max(float(layout.get("logo_alto_mm", 15) or 15), 10), 26)
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

    fecha = str(documento.get("fecha_emision") or documento.get("fecha") or local_date())[:10]
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
    row_h = max(5.8, min(float(layout.get("alto_fila_mm", 6.5) or 6.5), 8.2))
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
        txt_c(centers[0], row_y, idx, 8.0)
        txt_c(centers[1], row_y, "UNIDADES", 7.8)
        desc_lines = fit(desc, 108, "Helvetica-Bold", 7.0, 3)
        for j, ln in enumerate(desc_lines):
            txt(cols[2] + 1.6, row_y + j * 2.6, ln, 7.0, True)
        if series:
            txt(cols[2] + 1.6, row_y + min(len(desc_lines), 3) * 2.5, "SN:" + series[:92], 6.0)
        txt_r(cols[4] - 1.2, row_y, f"{qty:.2f}", 8.0)
        txt_r(cols[5] - 1.2, row_y, _pdf_money(total), 8.0)
        txt_r(cols[6] - 1.2, row_y, _pdf_money(price), 8.0)
        row_y += row_h

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
    txt(7.0, info_y + 4.8, "CONDICION DE PAGO", 7.0, True); txt(65, info_y + 4.8, documento.get("estado_pago") or "CONTADO", 6.8)
    txt(65, info_y + 12.0, "CUENTAS BANCARIAS", 6.8, True)
    txt(94, info_y + 12.0, f"Bcp soles :{cfg.get('cuenta_bcp') or '1941066028058'}", 6.5)
    txt(65, info_y + 16.0, "Titular:Computer Army Eirl", 6.5)
    txt(65, info_y + 23.2, f"Interbank soles cuenta corriente : {cfg.get('cuenta_interbank') or '2003005323345'}", 6.3)
    txt(65, info_y + 27.2, "Titular: Computer Army eirl", 6.5)
    qr_url = public_document_url(documento)
    if not _draw_pdf_qr(c, qr_url, 181, info_y + 27, 20, mm, page_h):
        rect(181, info_y + 27, 20, 20)

    legal_y = 216
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


@app.get("/consulta/dni/{dni}")
def consulta_dni(dni: str, sucursal: str = DEFAULT_SUCURSAL):
    return consulta_documento_impl(dni, sucursal)


@app.get("/consulta/ruc/{ruc}")
def consulta_ruc(ruc: str, sucursal: str = DEFAULT_SUCURSAL):
    return consulta_documento_impl(ruc, sucursal)


@app.get("/clientes/{documento}")
def buscar_cliente(documento: str, sucursal: str = DEFAULT_SUCURSAL):
    row = buscar_cliente_db(documento, sucursal)
    if row:
        return row
    documento = only_digits(documento)
    tipo = "DNI" if len(documento) == 8 else "RUC" if len(documento) == 11 else ""
    return {"ok": False, "success": False, "found": False, "tipo_documento": tipo, "numero_documento": documento}


@app.post("/clientes")
def crear_cliente(data: Cliente):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)

    cur.execute("""
    SELECT id FROM clientes
    WHERE numero_documento=%s AND COALESCE(sucursal,%s)=%s
    """, (data.numero_documento, DEFAULT_SUCURSAL, sucursal))
    row = cur.fetchone()
    if row:
        cur.execute("""
        UPDATE clientes
        SET tipo_documento=%s, nombre=%s, direccion=%s
        WHERE id=%s
        RETURNING id
        """, (data.tipo_documento, data.nombre, data.direccion, row[0]))
    else:
        cur.execute("""
        INSERT INTO clientes (tipo_documento,numero_documento,nombre,direccion,sucursal)
        VALUES (%s,%s,%s,%s,%s)
        RETURNING id
        """, (data.tipo_documento, data.numero_documento, data.nombre, data.direccion, sucursal))
    cliente_id = cur.fetchone()[0]

    conn.commit()
    conn.close()

    return {"ok": True, "id": cliente_id}


@app.get("/clientes")
def listar_clientes(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)

    cur.execute("""
    SELECT id, tipo_documento, numero_documento, nombre, direccion, COALESCE(sucursal,%s) AS sucursal
    FROM clientes
    WHERE COALESCE(sucursal,%s)=%s
    ORDER BY id DESC
    """, (DEFAULT_SUCURSAL, DEFAULT_SUCURSAL, sucursal))
    data = dict_fetchall(cur)

    conn.close()

    return data


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
@app.post("/productos")
def crear_producto(data: Producto):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS observacion TEXT DEFAULT ''")
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")

    cur.execute("""
    INSERT INTO productos (nombre,categoria,marca,modelo,precio_compra,precio_venta,stock,imagen_url,observacion,almacen,sucursal)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    RETURNING id
    """, (data.nombre, data.categoria, data.marca,
          data.modelo, data.precio_compra,
          data.precio_venta, data.stock, data.imagen_url or "", data.observacion or "", (data.almacen or "TIENDA").strip().upper(), sucursal))
    producto_id = cur.fetchone()[0]

    conn.commit()
    conn.close()

    return {"ok": True, "id": producto_id}


@app.get("/productos")
def listar_productos(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS observacion TEXT DEFAULT ''")
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")

    cur.execute("""
    SELECT id, nombre, categoria, marca, modelo, precio_compra, precio_venta, stock,
           COALESCE(imagen_url, '') AS imagen_url,
           COALESCE(observacion, '') AS observacion,
           COALESCE(almacen, 'TIENDA') AS almacen,
           COALESCE(sucursal,%s) AS sucursal
    FROM productos
    WHERE COALESCE(sucursal,%s)=%s
    ORDER BY nombre
    """, (DEFAULT_SUCURSAL, DEFAULT_SUCURSAL, sucursal))
    data = dict_fetchall(cur)

    conn.close()

    return data


@app.put("/productos/{producto_id}")
def actualizar_producto(producto_id: int, data: Producto, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal or sucursal)
    try:
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS observacion TEXT DEFAULT ''")
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
        cur.execute("""
        UPDATE productos
        SET nombre=%s, categoria=%s, marca=%s, modelo=%s,
            precio_compra=%s, precio_venta=%s, stock=%s, imagen_url=%s, observacion=%s, almacen=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id
        """, (
            data.nombre, data.categoria, data.marca, data.modelo,
            data.precio_compra, data.precio_venta, data.stock, data.imagen_url or "", data.observacion or "", (data.almacen or "TIENDA").strip().upper(), producto_id, DEFAULT_SUCURSAL, sucursal
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


@app.delete("/productos/{producto_id}")
def eliminar_producto(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
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
    sucursal = norm_sucursal(sucursal)
    texto = f"%{(q or '').lower()}%"
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
       OR LOWER(COALESCE(ps.proveedor,'')) LIKE %s
       OR LOWER(COALESCE(ps.almacen,'')) LIKE %s
       OR LOWER(COALESCE(ps.estado,'')) LIKE %s
       OR LOWER(COALESCE(p.nombre,'')) LIKE %s
       OR LOWER(COALESCE(p.marca,'')) LIKE %s
       OR LOWER(COALESCE(p.modelo,'')) LIKE %s)
    ORDER BY ps.id DESC
    """, (DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal, texto, texto, texto, texto, texto, texto, texto, texto))
    data = dict_fetchall(cur)
    conn.close()
    return data


@app.get("/series/duplicadas")
def listar_series_duplicadas(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
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
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(data.sucursal)
        series = split_series_text(data.serie)
        almacen = (data.almacen or "TIENDA").strip().upper()
        if not series:
            conn.close()
            return {"ok": False, "msg": "La serie no puede estar vacia"}

        cur.execute("SELECT stock FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s", (data.producto_id, DEFAULT_SUCURSAL, sucursal))
        producto = cur.fetchone()
        if not producto:
            conn.close()
            return {"ok": False, "msg": "Producto no encontrado"}

        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS usuario_ingreso TEXT DEFAULT ''")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        cur.execute("""
        SELECT UPPER(ps.serie) AS serie,
               ps.producto_id,
               COALESCE(p.nombre,'') AS producto_nombre
        FROM producto_series ps
        LEFT JOIN productos p ON p.id=ps.producto_id AND COALESCE(p.sucursal,%s)=%s
        WHERE COALESCE(ps.sucursal,%s)=%s
          AND UPPER(ps.serie)=ANY(%s)
          AND COALESCE(ps.producto_id,0)<>%s
        """, (DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal, series, data.producto_id))
        duplicadas = dict_fetchall(cur)
        if duplicadas:
            detalle = "; ".join([f"{r.get('serie')} ya existe en {r.get('producto_nombre') or 'otro producto'}" for r in duplicadas])
            conn.close()
            return {"ok": False, "success": False, "msg": "Serie duplicada en otro producto: " + detalle, "duplicadas": duplicadas}
        serie_ids = []
        for serie in series:
            cur.execute("""
            INSERT INTO producto_series (
                producto_id, serie, proveedor, estado, almacen, fecha_ingreso, fecha_salida, sucursal, usuario_ingreso
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (serie)
            DO UPDATE SET producto_id=EXCLUDED.producto_id,
                          proveedor=EXCLUDED.proveedor,
                          estado=EXCLUDED.estado,
                          almacen=EXCLUDED.almacen,
                          fecha_ingreso=EXCLUDED.fecha_ingreso,
                          fecha_salida=EXCLUDED.fecha_salida,
                          sucursal=EXCLUDED.sucursal,
                          usuario_ingreso=CASE
                              WHEN COALESCE(EXCLUDED.usuario_ingreso,'')<>'' THEN EXCLUDED.usuario_ingreso
                              ELSE producto_series.usuario_ingreso
                          END
            RETURNING id
            """, (
                data.producto_id, serie, data.proveedor, data.estado, almacen,
                data.fecha_ingreso or lima_today_iso(), data.fecha_salida, sucursal, data.usuario_ingreso or ""
            ))
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
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(data.sucursal or sucursal)
        series = split_series_text(data.serie)
        almacen = (data.almacen or "TIENDA").strip().upper()
        if not series:
            conn.close()
            return {"ok": False, "msg": "La serie no puede estar vacia"}

        cur.execute("""
        SELECT producto_id FROM producto_series
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (serie_id, DEFAULT_SUCURSAL, sucursal))
        old = cur.fetchone()
        if not old:
            conn.close()
            return {"ok": False, "msg": "Serie no encontrada"}
        producto_anterior = old[0]

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
        WHERE UPPER(ps.serie)=UPPER(%s)
          AND COALESCE(ps.sucursal,%s)=%s
          AND ps.id<>%s
        LIMIT 1
        """, (DEFAULT_SUCURSAL, sucursal, serie, DEFAULT_SUCURSAL, sucursal, serie_id))
        duplicada = dict_fetchone(cur)
        if duplicada:
            conn.close()
            return {"ok": False, "success": False, "msg": f"Serie duplicada en otro producto: {serie} ya existe en {duplicada.get('producto_nombre') or 'otro producto'}", "duplicada": duplicada}
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
def eliminar_serie_producto(serie_id: int, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
        cur.execute("""
        DELETE FROM producto_series
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING producto_id
        """, (serie_id, DEFAULT_SUCURSAL, sucursal))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "msg": "Serie no encontrada"}
        producto_id = row[0]
        cur.execute("""
        UPDATE productos
        SET stock = (
            SELECT COUNT(*) FROM producto_series
            WHERE producto_id=%s AND COALESCE(sucursal,%s)=%s AND UPPER(COALESCE(estado,''))='DISPONIBLE'
        )
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (producto_id, DEFAULT_SUCURSAL, sucursal, producto_id, DEFAULT_SUCURSAL, sucursal))
        conn.commit()
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
        serie = (data.serie or "").strip().upper()
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
        WHERE conteo_id=%s AND UPPER(serie)=UPPER(%s)
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
        WHERE UPPER(ps.serie)=UPPER(%s) AND COALESCE(ps.sucursal,%s)=%s
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
        sucursal = norm_sucursal(sucursal)
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
def get_serie(tipo: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, serie, correlativo FROM series WHERE tipo=%s", (tipo,))
    row = cur.fetchone()

    conn.close()

    if not row:
        return {"numero": "000001"}

    _, serie, corr = row
    return {"numero": f"{serie}-{str(corr).zfill(6)}"}


# ================= VENTAS / DOCUMENTOS =================
@app.post("/ventas")
def crear_venta(data: Venta):
    conn = get_conn()
    cur = conn.cursor()

    try:
        sucursal = norm_sucursal(data.sucursal)
        doc_tipo_upper = (data.tipo or "").strip().upper()
        if doc_tipo_upper:
            data.tipo = doc_tipo_upper
        cur.execute("SELECT id, serie, correlativo FROM series WHERE UPPER(tipo)=%s", (doc_tipo_upper,))
        row = cur.fetchone()

        if not row:
            conn.close()
            return {"ok": False, "msg": f"No existe serie para {data.tipo}"}

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
            fecha_vencimiento = fecha_emision.date().isoformat()
        if es_proforma:
            estado_pago = "DEUDA"
            metodo_pago = ""

        if mueve_stock:
            for item in data.items:
                producto_id = item.producto_id or item.id
                descripcion = item.nombre
                marca = item.marca
                modelo = item.modelo
                if producto_id and not descripcion:
                    cur.execute("SELECT nombre, marca, modelo FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s", (producto_id, DEFAULT_SUCURSAL, sucursal))
                    prod = cur.fetchone()
                    if prod:
                        descripcion = prod[0] or ""
                        marca = marca or (prod[1] or "")
                        modelo = modelo or (prod[2] or "")
                error_series = validar_y_marcar_series_venta(
                    cur,
                    producto_id,
                    descripcion,
                    marca,
                    modelo,
                    item.cantidad,
                    item.series_texto or item.serie,
                    sucursal,
                )
                if error_series:
                    conn.rollback()
                    conn.close()
                    return {"ok": False, "success": False, "msg": error_series}

        cur.execute("""
        INSERT INTO ventas (
            fecha, tipo, numero, cliente, documento_cliente, direccion_cliente,
            subtotal, igv, total, observacion, fecha_vencimiento, usuario_emisor, estado, estado_pago, metodo_pago, sucursal
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'EMITIDO',%s,%s,%s)
        RETURNING id
        """, (
            fecha_emision, data.tipo, numero, data.cliente_nombre, documento_cliente,
            data.direccion_cliente, subtotal, igv, total,
            data.observacion, fecha_vencimiento, data.usuario_emisor, estado_pago, metodo_pago, sucursal
        ))

        venta_id = cur.fetchone()[0]

        for item in data.items:
            producto_id = item.producto_id or item.id
            descripcion = item.nombre
            marca = item.marca
            modelo = item.modelo

            if not descripcion:
                cur.execute("SELECT nombre, marca, modelo FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s", (producto_id, DEFAULT_SUCURSAL, sucursal))
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
            "metodo_pago": metodo_pago
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
        if cur.fetchone():
            conn.close()
            return {"ok": False, "success": False, "msg": f"{doc_tipo} {numero} ya existe."}

        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS almacen TEXT DEFAULT 'TIENDA'")
        cur.execute("ALTER TABLE producto_series ADD COLUMN IF NOT EXISTS usuario_ingreso TEXT DEFAULT ''")
        cur.execute("""
        SELECT ps.id AS serie_id,
               UPPER(ps.serie) AS serie,
               ps.producto_id,
               UPPER(COALESCE(ps.estado,'DISPONIBLE')) AS estado,
               COALESCE(p.nombre,'') AS producto_nombre,
               COALESCE(p.marca,'') AS marca,
               COALESCE(p.modelo,'') AS modelo,
               COALESCE(p.precio_venta,0) AS precio_venta
        FROM producto_series ps
        LEFT JOIN productos p ON p.id=ps.producto_id AND COALESCE(p.sucursal,%s)=%s
        WHERE COALESCE(ps.sucursal,%s)=%s
          AND UPPER(ps.serie)=ANY(%s)
        """, (DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal, series))
        found = {str(r.get("serie") or "").upper(): r for r in dict_fetchall(cur)}
        faltantes = [serie for serie in series if serie not in found]
        bloqueadas = [f"{serie} ({found[serie].get('estado')})" for serie in series if serie in found and found[serie].get("estado") not in ("DISPONIBLE", "RESERVADO")]
        if faltantes or bloqueadas:
            conn.close()
            msg = []
            if faltantes:
                msg.append("Series no registradas: " + ", ".join(faltantes))
            if bloqueadas:
                msg.append("Series no disponibles: " + ", ".join(bloqueadas))
            return {"ok": False, "success": False, "msg": " | ".join(msg), "faltantes": faltantes, "bloqueadas": bloqueadas}

        fecha_emision = parse_fecha_emision(data.fecha_emision)
        cliente = (data.cliente_nombre or "CLIENTE MANUAL").strip() or "CLIENTE MANUAL"
        total = round(sum(float(found[s].get("precio_venta") or 0) for s in series), 2)
        cur.execute("""
        INSERT INTO ventas (
            fecha, tipo, numero, cliente, documento_cliente, direccion_cliente,
            subtotal, igv, total, observacion, fecha_vencimiento, usuario_emisor,
            estado, estado_pago, metodo_pago, sucursal
        )
        VALUES (%s,%s,%s,%s,'','',%s,0,%s,%s,%s,%s,'EMITIDO','PAGADO','MANUAL',%s)
        RETURNING id
        """, (
            fecha_emision, doc_tipo, numero, cliente, total, total,
            data.observacion or f"{doc_tipo} manual ingresado por series",
            fecha_emision.date().isoformat(), data.usuario_emisor or "", sucursal
        ))
        venta_id = cur.fetchone()[0]

        touched_products = set()
        for serie in series:
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
            "msg": f"{doc_tipo} {numero} registrado. Las series quedaron en historial como VENDIDO, no fueron eliminadas.",
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
    return crear_venta(data)


@app.get("/documentos")
def listar_documentos(sucursal: str = DEFAULT_SUCURSAL, fecha: str = ""):
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        sucursal = norm_sucursal(sucursal)
        filtro_fecha = (fecha or "").strip()
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
            COALESCE(comprobantes_pago_json, '') AS comprobantes_pago_json,
            COALESCE(sunat_estado, 'PENDIENTE') AS sunat_estado,
            COALESCE(sunat_modo, 'MANUAL') AS sunat_modo,
            sunat_fecha
        FROM ventas
        WHERE COALESCE(sucursal,%s)=%s
          AND (%s='' OR TO_CHAR(fecha, 'YYYY-MM-DD')=%s)
        ORDER BY id DESC
        """, (DEFAULT_SUCURSAL, sucursal, filtro_fecha, filtro_fecha))
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
        raw_name = f"{documento.get('tipo') or 'DOCUMENTO'}_{documento.get('numero') or documento_id}.pdf"
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
        "fecha_emision": data.fecha_emision or local_date(),
        "fecha_vencimiento": data.fecha_vencimiento or (local_date() if doc_type == "PROFORMA" else ""),
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
        SELECT tipo, numero, COALESCE(sucursal,%s)
        FROM ventas
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        """, (DEFAULT_SUCURSAL, documento_id, DEFAULT_SUCURSAL, sucursal))
        doc = cur.fetchone()
        if not doc:
            conn.close()
            return {"ok": False, "success": False, "msg": "Documento no encontrado"}
        tipo_actual, numero_actual, sucursal_doc = doc
        if str(tipo_actual or "").upper() != "PROFORMA":
            conn.close()
            return {"ok": False, "success": False, "msg": "Solo se puede editar PROFORMA desde este editor"}

        items = data.get("items") or data.get("detalle") or []
        if not isinstance(items, list) or not items:
            conn.close()
            return {"ok": False, "success": False, "msg": "La proforma debe tener productos"}

        total = round(sum(float((i or {}).get("total") or 0) for i in items), 2)
        if total <= 0:
            total = round(sum(float((i or {}).get("cantidad") or 0) * float((i or {}).get("precio") or (i or {}).get("precio_unitario") or 0) for i in items), 2)
        subtotal = float(data.get("subtotal") or total)
        igv = float(data.get("igv") or 0)
        fecha_vencimiento = data.get("fecha_vencimiento") or lima_today_iso()

        documento_cliente = data.get("numero_documento_cliente") or ""
        tipo_cliente = data.get("tipo_documento_cliente") or ""
        if tipo_cliente and documento_cliente:
            documento_cliente = f"{tipo_cliente}: {documento_cliente}"
        elif data.get("documento_cliente"):
            documento_cliente = data.get("documento_cliente")

        cur.execute("""
        UPDATE ventas
        SET cliente=%s,
            documento_cliente=%s,
            direccion_cliente=%s,
            subtotal=%s,
            igv=%s,
            total=%s,
            observacion=%s,
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
            fecha_vencimiento,
            data.get("usuario_emisor") or "",
            sucursal_doc,
            documento_id,
            DEFAULT_SUCURSAL,
            sucursal,
        ))
        if not cur.fetchone():
            conn.close()
            return {"ok": False, "success": False, "msg": "No se pudo actualizar la proforma"}

        cur.execute("DELETE FROM ventas_detalle WHERE venta_id=%s", (documento_id,))
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
            if producto_id and not descripcion:
                cur.execute("SELECT nombre, marca, modelo FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s", (producto_id, DEFAULT_SUCURSAL, sucursal_doc))
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
                documento_id, producto_id, descripcion, marca, modelo,
                item.get("series_texto") or item.get("serie") or "",
                cantidad, precio, item_total, sucursal_doc
            ))

        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,%s,%s,%s,%s)
        """, (data.get("usuario_emisor") or "", "", sucursal_doc, "PROFORMA ACTUALIZADA", f"{tipo_actual} {numero_actual} - {total}"))

        conn.commit()
        conn.close()
        return {
            "ok": True,
            "success": True,
            "id": documento_id,
            "numero": numero_actual,
            "total": total,
            "fecha_vencimiento": fecha_vencimiento,
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "success": False, "msg": str(e)}


@app.patch("/documentos/{documento_id}")
def actualizar_documento_patch(documento_id: int, data: dict, sucursal: str = DEFAULT_SUCURSAL):
    return actualizar_documento(documento_id, data, sucursal)


@app.put("/documentos/detalle/{detalle_id}/series")
def actualizar_series_detalle_documento(detalle_id: int, data: DocumentoDetalleSeriesUpdate, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(sucursal)
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

        raw_series = re.split(r"[,;\n\r]+", series_texto)
        series = [s.strip() for s in raw_series if s.strip()]
        for serie in series:
            cur.execute("""
            UPDATE producto_series
            SET estado='VENDIDO',
                fecha_salida=COALESCE(fecha_salida, TO_CHAR((timezone('America/Lima', now()))::date, 'YYYY-MM-DD'))
            WHERE UPPER(serie)=UPPER(%s)
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

        cur.execute("""
        SELECT producto_id, COALESCE(cantidad, 0), COALESCE(series_texto, '')
        FROM ventas_detalle
        WHERE venta_id=%s AND producto_id IS NOT NULL
        """, (documento_id,))
        detalles = cur.fetchall()

        if str(tipo or "").upper() in STOCK_DOC_TYPES:
            for producto_id, cantidad, series_texto in detalles:
                series = split_series_text(series_texto)
                if series:
                    cur.execute("""
                    UPDATE producto_series
                    SET estado='DISPONIBLE', fecha_salida=NULL
                    WHERE producto_id=%s
                      AND COALESCE(sucursal,%s)=%s
                      AND UPPER(serie)=ANY(%s)
                    """, (producto_id, DEFAULT_SUCURSAL, sucursal, series))
                    sync_producto_stock_from_series(cur, producto_id, sucursal)
                else:
                    cur.execute("""
                    UPDATE productos
                    SET stock = COALESCE(stock, 0) + %s
                    WHERE id = %s AND COALESCE(sucursal,%s)=%s
                    """, (cantidad or 0, producto_id, DEFAULT_SUCURSAL, sucursal))

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
        origen = norm_sucursal(data.sucursal_origen)
        destino = norm_sucursal(data.sucursal_destino)
        cantidad = int(data.cantidad or 0)
        if cantidad <= 0:
            conn.close()
            return {"ok": False, "msg": "La cantidad debe ser mayor a 0"}
        if origen == destino:
            conn.close()
            return {"ok": False, "msg": "La sucursal origen y destino deben ser diferentes"}

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
            origen, destino, data.usuario or "", data.nota or "",
        ))
        transferencia_id = cur.fetchone()[0]

        cur.execute("""
        INSERT INTO auditoria (usuario, rol, empresa, accion, detalle)
        VALUES (%s,%s,%s,%s,%s)
        """, (
            data.usuario or "", "", origen,
            "TRANSFERENCIA STOCK",
            f"{cantidad} x {producto.get('nombre')} de {origen} a {destino}",
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
        if estado not in ("PENDIENTE", "PROCESO", "ACEPTADO", "RECHAZADO"):
            estado = "PROCESO"
        modo = (data.sunat_modo or "MANUAL").upper()
        if modo not in ("MANUAL", "NO_ENVIAR"):
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
    sucursal = norm_sucursal(sucursal)
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


@app.get("/compras")
def listar_compras(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
    SELECT id, fecha, COALESCE(proveedor_nombre,'') AS proveedor_nombre,
           COALESCE(comprobante,'') AS comprobante, COALESCE(total,0) AS total,
           COALESCE(usuario_registro,'') AS usuario_registro,
           COALESCE(detalle,'') AS detalle, COALESCE(sucursal,%s) AS sucursal
    FROM compras
    WHERE COALESCE(sucursal,%s)=%s
    ORDER BY fecha DESC, id DESC
    LIMIT 500
    """, (DEFAULT_SUCURSAL, DEFAULT_SUCURSAL, sucursal))
    data = [_jsonable_row(r) for r in dict_fetchall(cur)]
    conn.close()
    return data


@app.post("/compras")
def guardar_compra(data: Compra):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    proveedor = (data.proveedor_nombre or data.proveedor or "").strip()
    cur.execute("""
    INSERT INTO compras (proveedor_nombre, comprobante, total, usuario_registro, detalle, sucursal)
    VALUES (%s,%s,%s,%s,%s,%s)
    RETURNING id
    """, (
        proveedor, data.comprobante or "", float(data.total or 0),
        data.usuario_registro or data.usuario or "", data.detalle or "", sucursal
    ))
    compra_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return {"ok": True, "success": True, "id": compra_id}


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
    clean = {
        "wc_store_url": str(data.get("wc_store_url") or data.get("store_url") or "").strip().rstrip("/"),
        "wc_consumer_key": str(data.get("wc_consumer_key") or data.get("consumer_key") or "").strip(),
        "wc_consumer_secret": str(data.get("wc_consumer_secret") or data.get("consumer_secret") or "").strip(),
        "woo_auto_sync": bool(data.get("woo_auto_sync", False)),
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


def woo_category_for_name(name: str, sucursal: str = DEFAULT_SUCURSAL):
    name = str(name or "").strip()
    if not name:
        return None
    found = woo_request("get", "products/categories", sucursal=sucursal, params={"search": name, "per_page": 20})
    if found.get("ok"):
        for cat in found.get("data") or []:
            if str(cat.get("name", "")).strip().lower() == name.lower():
                return {"id": cat.get("id"), "name": cat.get("name")}
    created = woo_request("post", "products/categories", sucursal=sucursal, json={"name": name})
    if created.get("ok") and isinstance(created.get("data"), dict):
        return {"id": created["data"].get("id"), "name": created["data"].get("name")}
    return None


def woo_payload_from_erp_product(p: dict, sucursal: str = DEFAULT_SUCURSAL):
    sku = f"ERP-{p['id']}"
    payload = {
        "name": p.get("nombre") or f"Producto {p['id']}",
        "sku": sku,
        "status": "publish",
        "regular_price": str(float(p.get("precio_venta") or 0)),
        "manage_stock": True,
        "stock_quantity": int(p.get("stock") or 0),
        "short_description": f"{p.get('marca','')} {p.get('modelo','')}".strip(),
        "description": f"Categoria: {p.get('categoria','')}",
    }
    img = str(p.get("imagen_url") or "").strip()
    if img.startswith(("http://", "https://")):
        payload["images"] = [{"src": img}]
    cat = woo_category_for_name(p.get("categoria", ""), sucursal=sucursal)
    if cat and cat.get("id"):
        payload["categories"] = [{"id": int(cat["id"])}]
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
    return {"ok": True, "action": action, "data": r.get("data", {})}


@app.get("/web/config")
def obtener_web_config(sucursal: str = DEFAULT_SUCURSAL):
    data = web_config_for_sucursal(sucursal)
    public = dict(data)
    if public.get("wc_consumer_secret"):
        public["wc_consumer_secret_masked"] = True
    return {"ok": True, "success": True, "data": public}


@app.post("/web/config")
def guardar_web_config(data: dict, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(data.get("sucursal") or data.get("empresa") or sucursal)
    clean = save_web_config_for_sucursal(sucursal, data)
    return {"ok": True, "success": True, "sucursal": sucursal, "data": clean}


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
        SELECT id, nombre, categoria, marca, modelo, precio_venta, stock, COALESCE(imagen_url,'') AS imagen_url
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


@app.post("/web/woocommerce/sync-products")
def woo_sync_products(data: dict = None, sucursal: str = DEFAULT_SUCURSAL):
    sucursal = norm_sucursal(sucursal)
    only_with_stock = bool((data or {}).get("only_with_stock", False))
    conn = get_conn()
    cur = conn.cursor()
    sql = """
        SELECT id, nombre, categoria, marca, modelo, precio_venta, stock, COALESCE(imagen_url,'') AS imagen_url
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
               COALESCE(usuario,'') AS usuario
        FROM garantias
        WHERE COALESCE(sucursal,%s)=%s
          AND (%s = '%%'
           OR cliente ILIKE %s
           OR documento ILIKE %s
           OR producto ILIKE %s
           OR serie ILIKE %s
           OR falla ILIKE %s)
        ORDER BY fecha DESC, id DESC
        LIMIT 300
    """, (DEFAULT_SUCURSAL, sucursal, filtro, filtro, filtro, filtro, filtro, filtro))
    data = dict_fetchall(cur)
    conn.close()
    return data


@app.post("/garantias")
def guardar_garantia(data: Garantia):
    estado = (data.estado or "RECIBIDO").upper()
    if estado not in ("RECIBIDO", "REVISION", "APROBADO", "RECHAZADO", "ENTREGADO"):
        estado = "RECIBIDO"
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    cur.execute("""
        INSERT INTO garantias (cliente, documento, producto, serie, falla, estado, solucion, usuario, sucursal)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        data.cliente, data.documento, data.producto, data.serie,
        data.falla, estado, data.solucion, data.usuario, sucursal
    ))
    garantia_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return {"ok": True, "success": True, "id": garantia_id}


@app.put("/garantias/{garantia_id}")
def actualizar_garantia(garantia_id: int, data: Garantia):
    estado = (data.estado or "RECIBIDO").upper()
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    cur.execute("""
        UPDATE garantias
        SET cliente=%s, documento=%s, producto=%s, serie=%s,
            falla=%s, estado=%s, solucion=%s, usuario=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id
    """, (
        data.cliente, data.documento, data.producto, data.serie,
        data.falla, estado, data.solucion, data.usuario, garantia_id, DEFAULT_SUCURSAL, sucursal
    ))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row:
        return {"ok": False, "msg": "Garantia no encontrada"}
    return {"ok": True, "success": True}


@app.get("/dashboard")
def dashboard(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    tipos_venta_sql = "('BOLETA','FACTURA','NOTA DE VENTA')"

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
          AND fecha::date = (timezone('America/Lima', now()))::date
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
          AND fecha::date = (timezone('America/Lima', now()))::date
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
          AND fecha::date = (timezone('America/Lima', now()))::date
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


