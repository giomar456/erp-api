from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import psycopg2
import os
import json
import urllib.parse
import urllib.request
import urllib.error

app = FastAPI()

# ================= CONEXION (SIMPLE Y ESTABLE) =================
DEFAULT_SUCURSAL = "computer_army"


def norm_sucursal(value: str = ""):
    value = (value or DEFAULT_SUCURSAL).strip().lower().replace(" ", "_")
    return value or DEFAULT_SUCURSAL


def get_conn():
    return psycopg2.connect(
        os.getenv("DATABASE_URL"),
        sslmode="require"
    )


def dict_fetchall(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def dict_fetchone(cur):
    row = cur.fetchone()
    if not row:
        return None
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


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
    tipo_documento_cliente: str = ""
    numero_documento_cliente: str = ""
    direccion_cliente: str = ""
    usuario_emisor: str = ""
    observacion: str = ""
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


class EstadoPagoUpdate(BaseModel):
    estado_pago: str
    metodo_pago: Optional[str] = None


class Producto(BaseModel):
    nombre: str
    categoria: str
    marca: str
    modelo: str
    precio_compra: float
    precio_venta: float
    stock: int
    imagen_url: Optional[str] = ""
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


@app.get("/init")
def init():
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
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS usuario_emisor TEXT",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'EMITIDO'",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS estado_pago TEXT DEFAULT 'PAGADO'",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS metodo_pago TEXT DEFAULT ''",
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

        conn.commit()
        conn.close()

        return {"ok": True, "msg": "Base completa lista"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ================= AUTO UPDATE =================
@app.get("/app/version")
def app_version():
    version = os.getenv("APP_VERSION", "1.0.0")
    download_url = os.getenv("APP_DOWNLOAD_URL", "")
    exe_name = os.getenv("APP_EXE_NAME", "erp_sql_pro_v20.exe")
    notes = os.getenv("APP_UPDATE_NOTES", "")
    force_update = os.getenv("APP_FORCE_UPDATE", "false").lower() in ("1", "true", "yes", "si")
    return {
        "ok": True,
        "success": True,
        "version": version,
        "url": download_url,
        "name": exe_name,
        "notes": notes,
        "force_update": force_update
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
def obtener_config_documento():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_config (
        clave TEXT PRIMARY KEY,
        valor TEXT,
        actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
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
    """, ("documento", json.dumps(data, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return {"ok": True, "success": True}


# ================= CLIENTES =================
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

    cur.execute("""
    INSERT INTO productos (nombre,categoria,marca,modelo,precio_compra,precio_venta,stock,imagen_url,sucursal)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    RETURNING id
    """, (data.nombre, data.categoria, data.marca,
          data.modelo, data.precio_compra,
          data.precio_venta, data.stock, data.imagen_url or "", sucursal))
    producto_id = cur.fetchone()[0]

    conn.commit()
    conn.close()

    return {"ok": True, "id": producto_id}


@app.get("/productos")
def listar_productos(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)

    cur.execute("""
    SELECT id, nombre, categoria, marca, modelo, precio_compra, precio_venta, stock,
           COALESCE(imagen_url, '') AS imagen_url, COALESCE(sucursal,%s) AS sucursal
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
        cur.execute("""
        UPDATE productos
        SET nombre=%s, categoria=%s, marca=%s, modelo=%s,
            precio_compra=%s, precio_venta=%s, stock=%s, imagen_url=%s
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id
        """, (
            data.nombre, data.categoria, data.marca, data.modelo,
            data.precio_compra, data.precio_venta, data.stock, data.imagen_url or "", producto_id, DEFAULT_SUCURSAL, sucursal
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

        if (data.estado or "").upper() == "DISPONIBLE":
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

        cur.execute("""
        INSERT INTO ventas (
            tipo, numero, cliente, documento_cliente, direccion_cliente,
            subtotal, igv, total, observacion, usuario_emisor, estado, estado_pago, metodo_pago, sucursal
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'EMITIDO',%s,%s,%s)
        RETURNING id
        """, (
            data.tipo, numero, data.cliente_nombre, documento_cliente,
            data.direccion_cliente, subtotal, igv, total,
            data.observacion, data.usuario_emisor, estado_pago, metodo_pago, sucursal
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

            cur.execute("""
            UPDATE productos SET stock = GREATEST(COALESCE(stock,0) - %s, 0)
            WHERE id = %s AND COALESCE(sucursal,%s)=%s
            """, (item.cantidad, producto_id, DEFAULT_SUCURSAL, sucursal))

        cur.execute("UPDATE series SET correlativo = correlativo + 1 WHERE id=%s", (serie_id,))

        cur.execute("""
        INSERT INTO caja_movimientos (
            tipo, detalle, monto, usuario, documento_tipo, documento_numero, estado_pago, metodo_pago, sucursal
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
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
def listar_documentos(sucursal: str = DEFAULT_SUCURSAL):
    conn = get_conn()
    cur = conn.cursor()
    sucursal = norm_sucursal(sucursal)

    cur.execute("""
    SELECT
        id,
        tipo,
        numero,
        cliente AS cliente_nombre,
        COALESCE(documento_cliente, '') AS documento_cliente,
        COALESCE(direccion_cliente, '') AS direccion_cliente,
        fecha AS fecha_emision,
        COALESCE(subtotal, total, 0) AS subtotal,
        COALESCE(igv, 0) AS igv,
        COALESCE(total, 0) AS total,
        COALESCE(observacion, '') AS observacion,
        COALESCE(usuario_emisor, '') AS usuario_emisor,
        COALESCE(estado, 'EMITIDO') AS estado,
        COALESCE(estado_pago, 'PAGADO') AS estado_pago,
        COALESCE(metodo_pago, '') AS metodo_pago
    FROM ventas
    WHERE COALESCE(sucursal,%s)=%s
    ORDER BY id DESC
    """, (DEFAULT_SUCURSAL, sucursal))
    data = dict_fetchall(cur)

    conn.close()
    return data


@app.get("/documentos/{documento_id}")
def detalle_documento(documento_id: int):
    conn = get_conn()
    cur = conn.cursor()

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

    conn.close()
    return data


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
        UPDATE ventas
        SET estado_pago=%s, metodo_pago=COALESCE(%s, metodo_pago, '')
        WHERE id=%s AND COALESCE(sucursal,%s)=%s
        RETURNING id, tipo, numero, cliente, total, usuario_emisor, COALESCE(metodo_pago, ''), COALESCE(sucursal,%s)
        """, (estado_pago, metodo_pago, documento_id, DEFAULT_SUCURSAL, sucursal, DEFAULT_SUCURSAL))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "msg": "Documento no encontrado"}

        venta_id, tipo, numero, cliente, total, usuario, metodo_pago_db, sucursal_db = row

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
                total, usuario or "", tipo, numero, estado_pago, metodo_pago_db, sucursal_db
            ))

        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "id": venta_id, "estado_pago": estado_pago, "metodo_pago": metodo_pago_db}
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


# ================= WOOCOMMERCE CENTRAL =================
def woo_config():
    site = (os.getenv("WC_STORE_URL") or os.getenv("WOOCOMMERCE_URL") or os.getenv("WP_URL") or "").strip().rstrip("/")
    ck = (os.getenv("WC_CONSUMER_KEY") or os.getenv("WOOCOMMERCE_CONSUMER_KEY") or "").strip()
    cs = (os.getenv("WC_CONSUMER_SECRET") or os.getenv("WOOCOMMERCE_CONSUMER_SECRET") or "").strip()
    if not site or not ck or not cs:
        return None
    return site, ck, cs


def woo_request(method, endpoint, **kwargs):
    cfg = woo_config()
    if not cfg:
        return {"ok": False, "msg": "Faltan variables WC_STORE_URL, WC_CONSUMER_KEY y WC_CONSUMER_SECRET en Render."}
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


def woo_category_for_name(name: str):
    name = str(name or "").strip()
    if not name:
        return None
    found = woo_request("get", "products/categories", params={"search": name, "per_page": 20})
    if found.get("ok"):
        for cat in found.get("data") or []:
            if str(cat.get("name", "")).strip().lower() == name.lower():
                return {"id": cat.get("id"), "name": cat.get("name")}
    created = woo_request("post", "products/categories", json={"name": name})
    if created.get("ok") and isinstance(created.get("data"), dict):
        return {"id": created["data"].get("id"), "name": created["data"].get("name")}
    return None


def woo_payload_from_erp_product(p: dict):
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
    cat = woo_category_for_name(p.get("categoria", ""))
    if cat and cat.get("id"):
        payload["categories"] = [{"id": int(cat["id"])}]
    return sku, payload


def woo_upsert_erp_product(p: dict):
    sku, payload = woo_payload_from_erp_product(p)
    found = woo_request("get", "products", params={"sku": sku, "per_page": 1})
    if not found.get("ok"):
        return found
    existing = found.get("data") or []
    if existing:
        r = woo_request("put", f"products/{existing[0]['id']}", json=payload)
        action = "actualizado"
    else:
        r = woo_request("post", "products", json=payload)
        action = "creado"
    if not r.get("ok"):
        return r
    return {"ok": True, "action": action, "data": r.get("data", {})}


def ensure_army_web(sucursal: str = DEFAULT_SUCURSAL):
    if norm_sucursal(sucursal) != DEFAULT_SUCURSAL:
        return {"ok": False, "msg": "La pagina web/WooCommerce esta habilitada solo para COMPUTER ARMY."}
    return None


@app.get("/web/woocommerce/test")
def woo_test(sucursal: str = DEFAULT_SUCURSAL):
    denied = ensure_army_web(sucursal)
    if denied:
        return denied
    r = woo_request("get", "products", params={"per_page": 1})
    if not r.get("ok"):
        return r
    return {"ok": True, "site_url": r.get("site_url"), "msg": "Conexion WooCommerce correcta"}


@app.get("/web/woocommerce/products")
def woo_products(search: str = "", sucursal: str = DEFAULT_SUCURSAL):
    denied = ensure_army_web(sucursal)
    if denied:
        return denied
    params = {"per_page": 50, "orderby": "date", "order": "desc"}
    if search:
        params["search"] = search
    r = woo_request("get", "products", params=params)
    if not r.get("ok"):
        return r
    return {"ok": True, "data": r.get("data", [])}


@app.get("/web/woocommerce/products/{producto_id}")
def woo_product(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    denied = ensure_army_web(sucursal)
    if denied:
        return denied
    r = woo_request("get", f"products/{producto_id}")
    if not r.get("ok"):
        return r
    return {"ok": True, "data": r.get("data", {})}


@app.post("/web/woocommerce/products")
def woo_create_product(data: WooProduct, sucursal: str = DEFAULT_SUCURSAL):
    denied = ensure_army_web(sucursal)
    if denied:
        return denied
    r = woo_request("post", "products", json=woo_payload_from_model(data))
    if not r.get("ok"):
        return r
    return {"ok": True, "data": r.get("data", {})}


@app.put("/web/woocommerce/products/{producto_id}")
def woo_update_product(producto_id: int, data: WooProduct, sucursal: str = DEFAULT_SUCURSAL):
    denied = ensure_army_web(sucursal)
    if denied:
        return denied
    r = woo_request("put", f"products/{producto_id}", json=woo_payload_from_model(data))
    if not r.get("ok"):
        return r
    return {"ok": True, "data": r.get("data", {})}


@app.post("/web/woocommerce/sync-product/{producto_id}")
def woo_sync_product(producto_id: int, sucursal: str = DEFAULT_SUCURSAL):
    denied = ensure_army_web(sucursal)
    if denied:
        return denied
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

    r = woo_upsert_erp_product(p)
    if not r.get("ok"):
        return r
    return {"ok": True, "msg": f"Producto {r.get('action')} en WooCommerce.", "data": r.get("data", {})}


@app.post("/web/woocommerce/sync-products")
def woo_sync_products(data: dict = None, sucursal: str = DEFAULT_SUCURSAL):
    denied = ensure_army_web(sucursal)
    if denied:
        return denied
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
        r = woo_upsert_erp_product(p)
        if r.get("ok"):
            ok += 1
        else:
            errores.append({"id": p.get("id"), "nombre": p.get("nombre"), "msg": r.get("msg", "Error WooCommerce")})
    return {"ok": True, "success": True, "total": len(productos), "sync_ok": ok, "errores": errores[:20]}


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

    cur.execute("SELECT COUNT(*) FROM clientes WHERE COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, sucursal))
    clientes = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM productos WHERE COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, sucursal))
    productos = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ventas WHERE COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, sucursal))
    documentos = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(total),0) FROM ventas WHERE COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, sucursal))
    total_ventas = float(cur.fetchone()[0] or 0)
    try:
        cur.execute("""
        SELECT COALESCE(SUM(CASE WHEN tipo='INGRESO' AND estado_pago='PAGADO' THEN monto ELSE 0 END),0)
             - COALESCE(SUM(CASE WHEN tipo='EGRESO' THEN monto ELSE 0 END),0)
        FROM caja_movimientos
        WHERE COALESCE(sucursal,%s)=%s
        """, (DEFAULT_SUCURSAL, sucursal))
        saldo_caja = float(cur.fetchone()[0] or 0)
    except Exception:
        saldo_caja = total_ventas

    cur.execute("""
        SELECT to_char(fecha::date, 'YYYY-MM-DD') AS dia, COALESCE(SUM(total), 0) AS total
        FROM ventas
        WHERE fecha >= CURRENT_DATE - INTERVAL '29 days'
          AND COALESCE(sucursal,%s)=%s
        GROUP BY fecha::date
        ORDER BY fecha::date
    """, (DEFAULT_SUCURSAL, sucursal))
    ventas_por_dia = [{"dia": r[0], "total": float(r[1] or 0)} for r in cur.fetchall()]

    cur.execute("""
        SELECT tipo, numero, COALESCE(cliente,''), COALESCE(total,0),
               COALESCE(estado_pago,'PAGADO'), COALESCE(usuario_emisor,'')
        FROM ventas
        WHERE COALESCE(sucursal,%s)=%s
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

    cur.execute("""
        SELECT COALESCE(NULLIF(metodo_pago,''),'SIN METODO') AS metodo, COALESCE(SUM(total),0) AS total
        FROM ventas
        WHERE COALESCE(estado_pago,'PAGADO')='PAGADO'
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
    cur.execute("SELECT COUNT(*) FROM ventas WHERE COALESCE(estado_pago,'PAGADO') IN ('CREDITO','DEUDA') AND COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, sucursal))
    facturas_cobrar = int(cur.fetchone()[0] or 0)
    cur.execute("SELECT COUNT(*) FROM clientes WHERE creado_en >= CURRENT_DATE AND COALESCE(sucursal,%s)=%s", (DEFAULT_SUCURSAL, sucursal))
    clientes_hoy = int(cur.fetchone()[0] or 0)

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
        "clientes_hoy": clientes_hoy,
    }
