from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import psycopg2
import os

app = FastAPI()

# ================= CONEXIÓN (SIMPLE Y ESTABLE) =================
def get_conn():
    return psycopg2.connect(
        os.getenv("DATABASE_URL"),
        sslmode="require"
    )

# ================= MODELOS =================
class ItemVenta(BaseModel):
    id: int
    cantidad: int
    precio: float
    total: float

class Venta(BaseModel):
    tipo: str
    cliente_nombre: str
    items: List[ItemVenta]

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

# ================= TEST CONEXIÓN =================
@app.get("/test-conn")
def test_conn():
    try:
        conn = get_conn()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

# ================= INIT =================
@app.get("/init")
def init():
    conn = get_conn()
    cur = conn.cursor()

    # USUARIOS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY,
        usuario TEXT UNIQUE,
        clave TEXT,
        rol TEXT
    );
    """)
    cur.execute("""
    INSERT INTO usuarios (usuario, clave, rol)
    VALUES ('admin','1234','admin')
    ON CONFLICT (usuario) DO NOTHING;
    """)

    # CLIENTES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS clientes (
        id SERIAL PRIMARY KEY,
        tipo_documento TEXT,
        numero_documento TEXT,
        nombre TEXT,
        direccion TEXT
    );
    """)

    # PRODUCTOS
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

    # SERIES
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
    VALUES ('BOLETA','B001',1),('FACTURA','F001',1)
    ON CONFLICT (tipo) DO NOTHING;
    """)

    # VENTAS
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

    # DETALLE
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

    conn.commit()
    conn.close()

    return {"ok": True}

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
    """, (data.tipo_documento, data.numero_documento,
          data.nombre, data.direccion))

    conn.commit()
    conn.close()

    return {"ok": True}

@app.get("/clientes")
def listar_clientes():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM clientes")
    data = cur.fetchall()

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
    """, (data.nombre, data.categoria, data.marca,
          data.modelo, data.precio_compra,
          data.precio_venta, data.stock))

    conn.commit()
    conn.close()

    return {"ok": True}

@app.get("/productos")
def listar_productos():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM productos")
    data = cur.fetchall()

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

# ================= VENTAS =================
@app.post("/ventas")
def crear_venta(data: Venta):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, serie, correlativo FROM series WHERE tipo=%s", (data.tipo,))
    row = cur.fetchone()

    if not row:
        return {"ok": False}

    serie_id, serie, corr = row
    numero = f"{serie}-{str(corr).zfill(6)}"

    total = sum([i.total for i in data.items])

    cur.execute("""
    INSERT INTO ventas (tipo,numero,cliente,total)
    VALUES (%s,%s,%s,%s)
    RETURNING id
    """, (data.tipo, numero, data.cliente_nombre, total))

    venta_id = cur.fetchone()[0]

    for item in data.items:
        cur.execute("""
        INSERT INTO ventas_detalle (venta_id,producto_id,cantidad,precio,total)
        VALUES (%s,%s,%s,%s,%s)
        """, (venta_id, item.id, item.cantidad, item.precio, item.total))

        cur.execute("""
        UPDATE productos SET stock = stock - %s WHERE id = %s
        """, (item.cantidad, item.id))

    cur.execute("UPDATE series SET correlativo = correlativo + 1 WHERE id=%s", (serie_id,))

    conn.commit()
    conn.close()

    return {"ok": True, "numero": numero, "total": total}
