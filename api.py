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
    
@app.get("/init-db")
def init_db():
    
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY,
        usuario VARCHAR(50),
        clave VARCHAR(50),
        rol VARCHAR(20)
    );
    """)

    cur.execute("""
    INSERT INTO usuarios (usuario, clave, rol)
    VALUES ('admin', '1234', 'admin')
    ON CONFLICT DO NOTHING;
    """)

    conn.commit()
    conn.close()

    return {"msg": "Base de datos lista"}    
