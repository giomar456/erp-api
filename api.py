from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from decimal import Decimal
from datetime import date, datetime
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
import base64
import binascii
import psycopg2
import os
import json
import urllib.parse
import urllib.request
import urllib.error

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

LIMA_TZ = ZoneInfo("America/Lima") if ZoneInfo else None


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

DEFAULT_FEATURES = {
    "dashboard": True,
    "ventas": True,
    "clientes": True,
    "productos": True,
    "inventario": True,
    "compras": True,
    "contabilidad": True,
    "caja": True,
    "usuarios": True,
    "garantias": True,
    "auditoria": True,
    "pagina_web": True,
    "ajustes": True,
}


def norm_sucursal(value: str = ""):
    value = (value or DEFAULT_SUCURSAL).strip().lower().replace(" ", "_")
    return value or DEFAULT_SUCURSAL


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
    nombre = (data.comprobante_pago_nombre or "").strip()
    referencia = (data.comprobante_pago or "").strip()
    mime = (data.comprobante_pago_mime or "").strip() or "application/octet-stream"
    tamano = data.comprobante_pago_tamano
    raw_b64 = (data.comprobante_pago_base64 or "").strip()
    data_url = (data.comprobante_pago_data_url or "").strip()

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


def normalizar_comprobantes_pago(data, existentes=None):
    recibidos = []
    for item in getattr(data, "comprobantes_pago", None) or []:
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
    if len(combinados) > 4:
        raise ValueError("Solo puedes guardar hasta 4 comprobantes por documento.")
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
    nombre = first_value(payload, "razonSocial", "razon_social", "nombre", "nombre_o_razon_social")
    direccion = first_value(payload, "direccion", "direccionFiscal", "domicilioFiscal", "domicilio_fiscal")
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
        "direccion": direccion.upper(),
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
    for provider in (consulta_documento_custom, consulta_documento_apis_net_pe):
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


class SerieProducto(BaseModel):
    producto_id: int
    serie: str
    proveedor: str = ""
    estado: str = "DISPONIBLE"
    fecha_ingreso: str = ""
    fecha_salida: Optional[str] = None
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


class Usuario(BaseModel):
    usuario: str
    clave: str
    rol: str = "VENTAS"
    foto_url: Optional[str] = ""
    sucursal: str = DEFAULT_SUCURSAL


class UsuarioRolUpdate(BaseModel):
    rol: str


class CajaMovimiento(BaseModel):
    tipo: str = "INGRESO"
    detalle: str
    monto: float
    usuario: str = ""
    documento_tipo: str = "MOVIMIENTO"
    documento_numero: str = ""
    estado_pago: str = "PAGADO"
    metodo_pago: str = ""
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
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS fecha_vencimiento DATE",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS usuario_emisor TEXT",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'EMITIDO'",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS estado_pago TEXT DEFAULT 'PAGADO'",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS metodo_pago TEXT DEFAULT ''",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS monto_pagado NUMERIC DEFAULT 0",
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
            metodo_pago TEXT DEFAULT ''
        );
        """)

        cur.execute("ALTER TABLE caja_movimientos ADD COLUMN IF NOT EXISTS metodo_pago TEXT DEFAULT ''")
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
    latest_version = "1.0.19"
    latest_url = "https://github.com/giomar456/erp-api/releases/download/v1.0.19/erp_sql_pro_v20_v1.0.19.exe"
    latest_name = "erp_sql_pro_v20_v1.0.19.exe"
    latest_notes = "Actualizacion G&G ERP v1.0.19: proformas/PDF con descripciones largas en varias lineas sin cortar ni invadir columnas."

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

    android_version = os.getenv("ANDROID_APP_VERSION", "1.15")
    android_download_url = os.getenv("ANDROID_APP_DOWNLOAD_URL", "")
    android_apk_name = os.getenv("ANDROID_APP_APK_NAME", "GG_ERP_ANDROID.apk")
    android_notes = os.getenv("ANDROID_APP_UPDATE_NOTES", "Actualizacion Android G&G ERP v1.15: Ventas procesa PROFORMA sin descontar stock/caja y agrega vista previa para compartir o descargar con formato de impresion.")
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
               COALESCE(sucursal,%s) AS sucursal
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

    return {"ok": True, "id": user["id"], "usuario": user["usuario"], "rol": user["rol"], "foto_url": user.get("foto_url", ""), "sucursal": sucursal, "empresa": sucursal}


# ================= USUARIOS =================
@app.get("/usuarios")
def listar_usuarios(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)
    cur.execute("""
        SELECT id, usuario, rol, COALESCE(foto_url,'') AS foto_url, COALESCE(sucursal,%s) AS sucursal
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
        SELECT usuario, rol, COALESCE(foto_url,'') AS foto_url, COALESCE(sucursal,%s) AS sucursal
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
    sucursal = norm_sucursal(data.sucursal)
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
        SET usuario=%s, clave=%s, rol=%s, sucursal=%s,
            foto_url=CASE WHEN %s <> '' THEN %s ELSE COALESCE(foto_url,'') END
        WHERE id=%s
        RETURNING id
        """, (usuario, clave, rol, sucursal, foto_url, foto_url, existing[0]))
    else:
        cur.execute("""
        INSERT INTO usuarios (usuario, clave, rol, foto_url, sucursal)
        VALUES (%s,%s,%s,%s,%s)
        RETURNING id
        """, (usuario, clave, rol, foto_url, sucursal))
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
    if not row or not row[0]:
        return {"ok": True, "success": True, "data": {}}
    try:
        return {"ok": True, "success": True, "data": json.loads(row[0])}
    except Exception:
        return {"ok": True, "success": True, "data": {}}


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


# ================= PRODUCTOS =================
@app.post("/productos")
def crear_producto(data: Producto):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(data.sucursal)
    cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS observacion TEXT DEFAULT ''")

    cur.execute("""
    INSERT INTO productos (nombre,categoria,marca,modelo,precio_compra,precio_venta,stock,imagen_url,observacion,sucursal)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    RETURNING id
    """, (data.nombre, data.categoria, data.marca,
          data.modelo, data.precio_compra,
          data.precio_venta, data.stock, data.imagen_url or "", data.observacion or "", sucursal))
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

    cur.execute("""
    SELECT id, nombre, categoria, marca, modelo, precio_compra, precio_venta, stock,
           COALESCE(imagen_url, '') AS imagen_url,
           COALESCE(observacion, '') AS observacion,
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
        cur.execute("""
        UPDATE productos
        SET nombre=%s, categoria=%s, marca=%s, modelo=%s,
            precio_compra=%s, precio_venta=%s, stock=%s, imagen_url=%s, observacion=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id
        """, (
            data.nombre, data.categoria, data.marca, data.modelo,
            data.precio_compra, data.precio_venta, data.stock, data.imagen_url or "", data.observacion or "", producto_id, DEFAULT_SUCURSAL, sucursal
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
        ps.fecha_ingreso,
        ps.fecha_salida
    FROM producto_series ps
    LEFT JOIN productos p ON p.id = ps.producto_id AND COALESCE(p.sucursal,%s)=%s
    WHERE COALESCE(ps.sucursal,%s)=%s
      AND (%s = '%%'
       OR LOWER(COALESCE(ps.serie,'')) LIKE %s
       OR LOWER(COALESCE(ps.proveedor,'')) LIKE %s
       OR LOWER(COALESCE(ps.estado,'')) LIKE %s
       OR LOWER(COALESCE(p.nombre,'')) LIKE %s
       OR LOWER(COALESCE(p.marca,'')) LIKE %s
       OR LOWER(COALESCE(p.modelo,'')) LIKE %s)
    ORDER BY ps.id DESC
    """, (DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL, sucursal, texto, texto, texto, texto, texto, texto, texto))
    data = dict_fetchall(cur)
    conn.close()
    return data


@app.post("/series")
def guardar_serie_producto(data: SerieProducto):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(data.sucursal)
        serie = (data.serie or "").strip()
        if not serie:
            conn.close()
            return {"ok": False, "msg": "La serie no puede estar vacia"}

        cur.execute("SELECT stock FROM productos WHERE id=%s AND COALESCE(sucursal,%s)=%s", (data.producto_id, DEFAULT_SUCURSAL, sucursal))
        producto = cur.fetchone()
        if not producto:
            conn.close()
            return {"ok": False, "msg": "Producto no encontrado"}

        cur.execute("""
        INSERT INTO producto_series (
            producto_id, serie, proveedor, estado, fecha_ingreso, fecha_salida, sucursal
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (serie)
        DO UPDATE SET producto_id=EXCLUDED.producto_id,
                      proveedor=EXCLUDED.proveedor,
                      estado=EXCLUDED.estado,
                      fecha_ingreso=EXCLUDED.fecha_ingreso,
                      fecha_salida=EXCLUDED.fecha_salida,
                      sucursal=EXCLUDED.sucursal
        RETURNING id
        """, (
            data.producto_id, serie, data.proveedor, data.estado,
            data.fecha_ingreso, data.fecha_salida, sucursal
        ))
        serie_id = cur.fetchone()[0]

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
        return {"ok": True, "success": True, "id": serie_id}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


@app.put("/series/{serie_id}")
def actualizar_serie_producto(serie_id: int, data: SerieProducto, sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    try:
        sucursal = norm_sucursal(data.sucursal or sucursal)
        serie = (data.serie or "").strip()
        if not serie:
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

        cur.execute("""
        UPDATE producto_series
        SET producto_id=%s,
            serie=%s,
            proveedor=%s,
            estado=%s,
            fecha_ingreso=%s,
            fecha_salida=%s,
            sucursal=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id
        """, (
            data.producto_id, serie, data.proveedor, data.estado,
            data.fecha_ingreso, data.fecha_salida, sucursal,
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
        return {"ok": True, "success": True, "id": serie_id}
    except Exception as e:
        conn.rollback()
        conn.close()
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
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


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
        cur.execute("SELECT id, serie, correlativo FROM series WHERE tipo=%s", (data.tipo,))
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
        es_proforma = (data.tipo or "").upper() == "PROFORMA"
        if es_proforma and not fecha_vencimiento:
            fecha_vencimiento = fecha_emision.date().isoformat()
        if es_proforma:
            estado_pago = "DEUDA"
            metodo_pago = ""

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

            if not es_proforma:
                cur.execute("""
                UPDATE productos SET stock = GREATEST(COALESCE(stock,0) - %s, 0)
                WHERE id = %s AND COALESCE(sucursal,%s)=%s
                """, (item.cantidad, producto_id, DEFAULT_SUCURSAL, sucursal))

        cur.execute("UPDATE series SET correlativo = correlativo + 1 WHERE id=%s", (serie_id,))

        if not es_proforma:
            cur.execute("""
            INSERT INTO caja_movimientos (
                fecha, tipo, detalle, monto, usuario, documento_tipo, documento_numero, estado_pago, metodo_pago, sucursal
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                fecha_emision,
                "INGRESO" if estado_pago == "PAGADO" else estado_pago,
                f"{data.tipo} {numero} - {data.cliente_nombre}",
                total, data.usuario_emisor, data.tipo, numero, estado_pago, metodo_pago, sucursal
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


@app.get("/documentos")
def listar_documentos(sucursal: str = DEFAULT_SUCURSAL, fecha: str = ""):
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        sucursal = norm_sucursal(sucursal)
        filtro_fecha = (fecha or "").strip()

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
            COALESCE(usuario_emisor, '') AS usuario_emisor,
            COALESCE(estado, 'EMITIDO') AS estado,
            COALESCE(estado_pago, 'PAGADO') AS estado_pago,
            COALESCE(metodo_pago, '') AS metodo_pago,
            COALESCE(monto_pagado, CASE WHEN COALESCE(estado_pago,'PAGADO')='PAGADO' THEN COALESCE(total,0) ELSE 0 END) AS monto_pagado,
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
            row["comprobantes_pago"] = cargar_comprobantes_json(row.get("comprobantes_pago_json"))
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


@app.get("/documentos/{documento_id}")
def detalle_documento(documento_id: int):
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()

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
            COALESCE(usuario_emisor, '') AS usuario_emisor,
            COALESCE(estado, 'EMITIDO') AS estado,
            COALESCE(estado_pago, 'PAGADO') AS estado_pago,
            COALESCE(metodo_pago, '') AS metodo_pago,
            COALESCE(monto_pagado, CASE WHEN COALESCE(estado_pago,'PAGADO')='PAGADO' THEN COALESCE(total,0) ELSE 0 END) AS monto_pagado,
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
        SELECT producto_id, COALESCE(cantidad, 0)
        FROM ventas_detalle
        WHERE venta_id=%s AND producto_id IS NOT NULL
        """, (documento_id,))
        detalles = cur.fetchall()

        for producto_id, cantidad in detalles:
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
        monto_pagado = data.monto_pagado
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
        RETURNING id, tipo, numero, cliente, total, usuario_emisor, COALESCE(metodo_pago, ''), COALESCE(sucursal,%s), COALESCE(monto_pagado,0), COALESCE(saldo_pago,0),
                  COALESCE(comprobante_pago,''), COALESCE(comprobante_pago_nombre,''), COALESCE(comprobante_pago_mime,''), COALESCE(comprobante_pago_tamano,0),
                  COALESCE(comprobante_pago_base64,''), COALESCE(comprobante_pago_data_url,''), COALESCE(comprobantes_pago_json,'')
        """, (
            estado_pago, metodo_pago, monto_pagado, saldo_pago, data.observacion_pago or "",
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
            monto_pagado_db, saldo_pago_db, comprobante_pago_db, comprobante_nombre_db,
            comprobante_mime_db, comprobante_tamano_db, comprobante_base64_db,
            comprobante_data_url_db, comprobantes_json_db
        ) = row

        cur.execute("""
        UPDATE caja_movimientos
        SET tipo=%s, estado_pago=%s, metodo_pago=%s
        WHERE documento_tipo=%s AND documento_numero=%s
          AND COALESCE(sucursal,%s)=%s
        """, ("INGRESO" if estado_pago == "PAGADO" else estado_pago, estado_pago, metodo_pago_db, tipo, numero, DEFAULT_SUCURSAL, sucursal_db))

        if cur.rowcount == 0:
            cur.execute("""
            INSERT INTO caja_movimientos (
                tipo, detalle, monto, usuario, documento_tipo, documento_numero, estado_pago, metodo_pago, sucursal
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                "INGRESO" if estado_pago == "PAGADO" else estado_pago,
                f"{tipo} {numero} - {cliente}",
                monto_pagado_db, usuario or "", tipo, numero, estado_pago, metodo_pago_db, sucursal_db
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
        tipo, detalle, monto, usuario, documento_tipo, documento_numero, estado_pago, metodo_pago, sucursal
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    RETURNING id
    """, (
        data.tipo, data.detalle, data.monto, data.usuario,
        data.documento_tipo, data.documento_numero, estado_pago, metodo_pago, sucursal
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
    total_ventas = float(cur.fetchone()[0] or 0)
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
        saldo_caja = float(cur.fetchone()[0] or 0)
    except Exception:
        saldo_caja = total_ventas

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
          AND fecha >= date_trunc('month', (timezone('America/Lima', now()))::date)
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
    cur.execute(f"""
        SELECT COUNT(*) FROM ventas
        WHERE COALESCE(estado_pago,'PAGADO') IN ('CREDITO','DEUDA')
          AND UPPER(COALESCE(tipo,'')) IN {tipos_venta_sql}
          AND COALESCE(sucursal,%s)=%s
    """, (DEFAULT_SUCURSAL, sucursal))
    facturas_cobrar = int(cur.fetchone()[0] or 0)
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
        "total_ventas": total_ventas,
        "saldo_caja": saldo_caja,
        "ventas_por_dia": ventas_por_dia,
        "recientes": recientes,
        "metodos_pago": metodos_pago,
        "productos_bajos": productos_bajos,
        "stock_bajo": stock_bajo,
        "facturas_cobrar": facturas_cobrar,
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
