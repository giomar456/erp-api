from fastapi import FastAPI, HTTPException
import psycopg2
import os

app = FastAPI()

def get_conn():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

# 🔹 RUTA PRINCIPAL (NO BORRAR)
@app.get("/")
def home():
    return {"msg": "API ERP CON POSTGRES OK"}

# 🔹 LOGIN (AGREGAS ESTO)
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

    return {"ok": True, "usuario": user[1], "rol": user[3]}
