from fastapi import FastAPI
import psycopg2
import os

app = FastAPI()

def get_conn():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

@app.get("/")
def home():
    return {"msg": "API ERP CON POSTGRES OK"}
