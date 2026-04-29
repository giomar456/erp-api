from fastapi import FastAPI
import psycopg2
import os

app = FastAPI()

def get_conn():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

@app.get("/")
def home():
    return {"msg": "API ERP CON POSTGRES OK"}

@app.get("/test-db")
def test_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1")
    result = cur.fetchone()
    conn.close()

    return {"db": "ok", "result": result}
