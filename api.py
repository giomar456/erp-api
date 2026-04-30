from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import psycopg2
import os

app = FastAPI()

# ================= CONEXION (SIMPLE Y ESTABLE) =================
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


class Cliente(BaseModel):
    tipo_documento: str
    numero_documento: str
    nombre: str
    direccion: str


class Producto(BaseModel):
    nombre: str
    categoria: str
    marca: str
    modelo: str
    precio_compra: float
    precio_venta: float
    stock: int


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
            rol TEXT
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            tipo_documento TEXT,
            numero_documento TEXT UNIQUE,
            nombre TEXT,
            direccion TEXT
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS productos (
            id SERIAL PRIMARY KEY,
            nombre TEXT,
            categoria TEXT,
            marca TEXT,
            modelo TEXT,
            precio_compra NUMERIC,
            precio_venta NUMERIC,
            stock INT
        );
        """)

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
        ]:
            cur.execute(column_sql)

        conn.commit()
        conn.close()

        return {"ok": True, "msg": "Base completa lista"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ================= LOGIN =================
@app.post("/login")
def login(data: dict):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM usuarios WHERE usuario=%s AND clave=%s",
                (data["usuario"], data["clave"]))
    user = cur.fetchone()

    conn.close()

    if not user:
        return {"ok": False}

    return {"ok": True, "usuario": user[1], "rol": user[3]}


# ================= CLIENTES =================
@app.post("/clientes")
def crear_cliente(data: Cliente):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO clientes (tipo_documento,numero_documento,nombre,direccion)
    VALUES (%s,%s,%s,%s)
    ON CONFLICT (numero_documento)
    DO UPDATE SET tipo_documento=EXCLUDED.tipo_documento,
                  nombre=EXCLUDED.nombre,
                  direccion=EXCLUDED.direccion
    RETURNING id
    """, (data.tipo_documento, data.numero_documento,
          data.nombre, data.direccion))
    cliente_id = cur.fetchone()[0]

    conn.commit()
    conn.close()

    return {"ok": True, "id": cliente_id}


@app.get("/clientes")
def listar_clientes():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, tipo_documento, numero_documento, nombre, direccion
    FROM clientes
    ORDER BY id DESC
    """)
    data = dict_fetchall(cur)

    conn.close()

    return data


# ================= PRODUCTOS =================
@app.post("/productos")
def crear_producto(data: Producto):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO productos (nombre,categoria,marca,modelo,precio_compra,precio_venta,stock)
    VALUES (%s,%s,%s,%s,%s,%s,%s)
    RETURNING id
    """, (data.nombre, data.categoria, data.marca,
          data.modelo, data.precio_compra,
          data.precio_venta, data.stock))
    producto_id = cur.fetchone()[0]

    conn.commit()
    conn.close()

    return {"ok": True, "id": producto_id}


@app.get("/productos")
def listar_productos():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, nombre, categoria, marca, modelo, precio_compra, precio_venta, stock
    FROM productos
    ORDER BY nombre
    """)
    data = dict_fetchall(cur)

    conn.close()

    return data


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

        cur.execute("""
        INSERT INTO ventas (
            tipo, numero, cliente, documento_cliente, direccion_cliente,
            subtotal, igv, total, observacion, usuario_emisor, estado
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'EMITIDO')
        RETURNING id
        """, (
            data.tipo, numero, data.cliente_nombre, documento_cliente,
            data.direccion_cliente, subtotal, igv, total,
            data.observacion, data.usuario_emisor
        ))

        venta_id = cur.fetchone()[0]

        for item in data.items:
            producto_id = item.producto_id or item.id
            descripcion = item.nombre
            marca = item.marca
            modelo = item.modelo

            if not descripcion:
                cur.execute("SELECT nombre, marca, modelo FROM productos WHERE id=%s", (producto_id,))
                prod = cur.fetchone()
                if prod:
                    descripcion = prod[0] or ""
                    marca = marca or (prod[1] or "")
                    modelo = modelo or (prod[2] or "")

            cur.execute("""
            INSERT INTO ventas_detalle (
                venta_id, producto_id, descripcion, marca, modelo,
                series_texto, cantidad, precio, total
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                venta_id, producto_id, descripcion, marca, modelo,
                item.series_texto or item.serie,
                item.cantidad, item.precio, item.total
            ))

            cur.execute("""
            UPDATE productos SET stock = GREATEST(COALESCE(stock,0) - %s, 0)
            WHERE id = %s
            """, (item.cantidad, producto_id))

        cur.execute("UPDATE series SET correlativo = correlativo + 1 WHERE id=%s", (serie_id,))

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
            "total": total
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


@app.post("/documentos/emitir")
def emitir_documento(data: Venta):
    return crear_venta(data)


@app.get("/documentos")
def listar_documentos():
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
        COALESCE(subtotal, total, 0) AS subtotal,
        COALESCE(igv, 0) AS igv,
        COALESCE(total, 0) AS total,
        COALESCE(observacion, '') AS observacion,
        COALESCE(usuario_emisor, '') AS usuario_emisor,
        COALESCE(estado, 'EMITIDO') AS estado
    FROM ventas
    ORDER BY id DESC
    """)
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


@app.get("/dashboard")
def dashboard():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM clientes")
    clientes = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM productos")
    productos = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ventas")
    documentos = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(total),0) FROM ventas")
    total_ventas = float(cur.fetchone()[0] or 0)

    conn.close()
    return {
        "clientes": clientes,
        "productos": productos,
        "documentos": documentos,
        "compras": 0,
        "total_ventas": total_ventas,
        "saldo_caja": total_ventas,
    }
