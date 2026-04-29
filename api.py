from fastapi import FastAPI, HTTPException
import psycopg2
import os

app = FastAPI()

from urllib.parse import urlparse

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

# 🔹 INICIO
@app.get("/")
def home():
    return {"msg": "API ERP CON POSTGRES OK"}

# 🔹 TEST DB
@app.get("/test-db")
def test_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1")
    result = cur.fetchone()
    conn.close()

    return {"db": "ok", "result": result}

# 🔹 CREAR TABLAS
@app.get("/init-db")
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # TABLA USUARIOS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY,
        usuario VARCHAR(50) UNIQUE,
        clave VARCHAR(50),
        rol VARCHAR(20)
    );
    """)

    # TABLA CAJA
    cur.execute("""
    CREATE TABLE IF NOT EXISTS caja (
        id SERIAL PRIMARY KEY,
        tipo VARCHAR(50),
        monto NUMERIC,
        estado_pago VARCHAR(20),
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # INSERT USUARIO ADMIN
    cur.execute("""
    INSERT INTO usuarios (usuario, clave, rol)
    VALUES ('admin', '1234', 'admin')
    ON CONFLICT (usuario) DO NOTHING;
    """)

    conn.commit()
    conn.close()

    return {"msg": "Base de datos lista"}

# 🔐 LOGIN
@app.post("/login")
def login(data: dict):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM usuarios WHERE usuario=%s AND clave=%s",
        (data["usuario"], data["clave"])
    )

    user = cur.fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Usuario incorrecto")

    return {
        "ok": True,
        "usuario": user[1],
        "rol": user[3]
    }

# 💰 REGISTRAR MOVIMIENTO DE CAJA
@app.post("/caja")
def registrar_caja(data: dict):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO caja (tipo, monto, estado_pago)
    VALUES (%s, %s, %s)
    """, (data["tipo"], data["monto"], data["estado"]))

    conn.commit()
    conn.close()

    return {"ok": True, "msg": "Movimiento registrado"}

# 📊 LISTAR CAJA
@app.get("/caja")
def listar_caja():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM caja ORDER BY id DESC")
    data = cur.fetchall()

    conn.close()

    return data
