from fastapi import FastAPI
import psycopg2
import os
from urllib.parse import urlparse

app = FastAPI()

def get_conn():
    url = os.getenv("DATABASE_URL")
    result = urlparse(url)
    return psycopg2.connect(
        dbname=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
        sslmode="require"
    )

# LOGIN
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

# CLIENTES
@app.post("/clientes")
def crear_cliente(data: dict):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clientes (
        id SERIAL PRIMARY KEY,
        tipo_documento TEXT,
        numero_documento TEXT,
        nombre TEXT,
        direccion TEXT
    )
    """)

    cur.execute("""
    INSERT INTO clientes (tipo_documento, numero_documento, nombre, direccion)
    VALUES (%s,%s,%s,%s)
    """, (data["tipo_documento"], data["numero_documento"],
          data["nombre"], data["direccion"]))

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
    return [{"id": x[0], "tipo_documento": x[1], "numero_documento": x[2], "nombre": x[3], "direccion": x[4]} for x in data]

# PRODUCTOS
@app.post("/productos")
def crear_producto(data: dict):
    conn = get_conn()
    cur = conn.cursor()

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
    )
    """)

    cur.execute("""
    INSERT INTO productos (nombre,categoria,marca,modelo,precio_compra,precio_venta,stock)
    VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (data["nombre"], data["categoria"], data["marca"],
          data["modelo"], data["precio_compra"],
          data["precio_venta"], data["stock"]))

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
    return [{"id": x[0], "nombre": x[1], "categoria": x[2], "marca": x[3],
             "modelo": x[4], "precio_venta": float(x[6]), "stock": x[7]} for x in data]

# VENTAS
@app.post("/ventas")
def crear_venta(data: dict):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ventas (
        id SERIAL PRIMARY KEY,
        cliente TEXT,
        total NUMERIC
    )
    """)

    total = sum([i["total"] for i in data["items"]])

    cur.execute("INSERT INTO ventas (cliente,total) VALUES (%s,%s)",
                (data["cliente_nombre"], total))

    conn.commit()
    conn.close()

    return {"ok": True, "numero": "000001", "total": total}

# DASHBOARD
@app.get("/dashboard")
def dashboard():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM clientes")
    clientes = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM productos")
    productos = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM ventas")
    ventas = cur.fetchone()[0]

    conn.close()

    return {
        "clientes": clientes,
        "productos": productos,
        "documentos": ventas,
        "compras": 0,
        "total_ventas": 0,
        "saldo_caja": 0
    }
