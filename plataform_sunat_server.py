"""
Servidor compatible con plataform-api-sunat / Kodevo (flujo video Postman).
En Render: https://erp-api-7x3d.onrender.com/api/v1/...
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

try:
    from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
except Exception:
    load_key_and_certificates = None

router = APIRouter(tags=["plataform-sunat"])

PANEL_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plataform_sunat_panel.html")

PUBLIC_BASE = (
    os.getenv("PLATAFORM_SUNAT_PUBLIC_URL")
    or os.getenv("PUBLIC_BASE_URL")
    or os.getenv("APP_PUBLIC_URL")
    or "https://erp-api-7x3d.onrender.com"
).rstrip("/")


def _get_conn():
    import psycopg2

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL no configurado")
    if "sslmode=" in database_url.lower():
        return psycopg2.connect(database_url)
    return psycopg2.connect(database_url, sslmode=os.getenv("DB_SSLMODE", "require"))


def ensure_plataform_tables(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS plataform_empresas (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER UNIQUE NOT NULL,
            ruc TEXT UNIQUE NOT NULL,
            razon_social TEXT NOT NULL DEFAULT '',
            direccion TEXT DEFAULT '',
            ubigeo TEXT DEFAULT '150101',
            departamento TEXT DEFAULT 'LIMA',
            provincia TEXT DEFAULT 'LIMA',
            distrito TEXT DEFAULT 'LIMA',
            usuario_sol TEXT DEFAULT '',
            clave_sol TEXT DEFAULT '',
            cert_password TEXT DEFAULT '',
            cert_pfx_base64 TEXT DEFAULT '',
            entorno TEXT DEFAULT 'production',
            plan TEXT DEFAULT 'pro',
            api_key TEXT UNIQUE NOT NULL,
            api_secret_hash TEXT NOT NULL,
            activo BOOLEAN DEFAULT TRUE,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS plataform_sucursales (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL REFERENCES plataform_empresas(id) ON DELETE CASCADE,
            nombre TEXT NOT NULL,
            cod_local TEXT DEFAULT '0001',
            direccion TEXT DEFAULT '',
            ubigeo TEXT DEFAULT '150101',
            es_principal BOOLEAN DEFAULT FALSE,
            telefono TEXT DEFAULT '',
            email TEXT DEFAULT '',
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS plataform_series (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL REFERENCES plataform_empresas(id) ON DELETE CASCADE,
            sucursal_id INTEGER NOT NULL DEFAULT 1,
            tipo TEXT NOT NULL,
            serie TEXT NOT NULL,
            correlativo INTEGER NOT NULL DEFAULT 1,
            UNIQUE (empresa_id, tipo, serie)
        );
        """
    )


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(str(secret or "").encode("utf-8")).hexdigest()


def _gen_api_key() -> str:
    return "V4" + secrets.token_urlsafe(46).replace("-", "A").replace("_", "B")[:62]


def _gen_api_secret() -> str:
    return secrets.token_hex(32)


def _ok(mensaje: str, datos: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"estado": "exito", "mensaje": mensaje, "datos": datos},
    )


def _err(mensaje: str, errores: Optional[dict] = None, status: int = 400) -> JSONResponse:
    payload: dict[str, Any] = {"estado": "error", "mensaje": mensaje}
    if errores:
        payload["errores"] = errores
    return JSONResponse(status_code=status, content=payload)


def _clean_ruc(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _validate_cert(pfx_bytes: bytes, password: str) -> tuple[bool, str]:
    if not pfx_bytes:
        return False, "Falta certificado digital."
    if not password:
        return False, "Falta contrasena del certificado."
    if not load_key_and_certificates:
        return True, "OK"
    try:
        load_key_and_certificates(pfx_bytes, password.encode("utf-8"))
        return True, "OK"
    except Exception as exc:
        return False, f"Certificado PFX invalido: {exc}"


def _empresa_por_key(cur, api_key: str, api_secret: str) -> Optional[dict]:
    cur.execute(
        """
        SELECT *
        FROM plataform_empresas
        WHERE api_key = %s AND api_secret_hash = %s AND activo = TRUE
        """,
        (api_key.strip(), _hash_secret(api_secret)),
    )
    cols = [c[0] for c in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def _require_auth(
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    x_api_secret: Optional[str] = Header(None, alias="X-Api-Secret"),
) -> dict:
    key = str(x_api_key or "").strip()
    secret = str(x_api_secret or "").strip()
    if not key or not secret:
        raise HTTPException(
            status_code=401,
            detail={"estado": "error", "mensaje": "Las cabeceras X-Api-Key y X-Api-Secret son requeridas."},
        )
    conn = _get_conn()
    cur = conn.cursor()
    try:
        ensure_plataform_tables(cur)
        conn.commit()
        empresa = _empresa_por_key(cur, key, secret)
        if not empresa:
            raise HTTPException(
                status_code=401,
                detail={"estado": "error", "mensaje": "Credenciales de API inválidas."},
            )
        return empresa
    finally:
        conn.close()


@router.get("/panel", include_in_schema=False)
def panel_redirect_api():
    if os.path.isfile(PANEL_HTML):
        return FileResponse(PANEL_HTML, media_type="text/html")
    return _err("Panel web no disponible en este deploy.", status=404)


def sunat_panel_page():
    if os.path.isfile(PANEL_HTML):
        return FileResponse(PANEL_HTML, media_type="text/html")
    return JSONResponse(
        status_code=404,
        content={"estado": "error", "mensaje": "Panel SUNAT no publicado en este deploy."},
    )


@router.get("/system/info")
def system_info():
    return {
        "estado": "exito",
        "mensaje": "Plataform API SUNAT en Render",
        "datos": {
            "servidor": PUBLIC_BASE,
            "base_url": f"{PUBLIC_BASE}/api/v1",
            "proveedor": "G&G ERP Render",
            "panel_web": f"{PUBLIC_BASE}/sunat-panel",
            "endpoints": [
                "GET /sunat-panel (tablero web)",
                "POST /registro",
                "POST /empresa/credenciales/regenerar",
                "GET /empresa",
                "POST /sucursales",
                "POST /series",
            ],
        },
    }


@router.post("/registro")
async def registro_empresa(
    ruc: str = Form(""),
    razon_social: str = Form(""),
    direccion: str = Form(""),
    ubigeo: str = Form("150101"),
    sol_user: str = Form(""),
    sol_pass: str = Form(""),
    contrasena_certificado: str = Form(""),
    contrasena: str = Form(""),
    departamento: str = Form("LIMA"),
    provincia: str = Form("LIMA"),
    distrito: str = Form("LIMA"),
    plan: str = Form("pro"),
    entorno: str = Form("production"),
    certificado: UploadFile = File(None),
):
    ruc_clean = _clean_ruc(ruc)
    if len(ruc_clean) != 11:
        return _err("Error de validación", {"ruc": ["El RUC debe tener 11 dígitos."]}, 422)

    cert_password = (contrasena_certificado or contrasena or "").strip()
    cert_bytes = b""
    if certificado and certificado.filename:
        cert_bytes = await certificado.read()
    if not cert_bytes:
        return _err("Error de validación", {"certificado": ["El certificado es obligatorio."]}, 422)

    ok_cert, cert_msg = _validate_cert(cert_bytes, cert_password)
    if not ok_cert:
        return _err("Error de validación", {"certificado": [cert_msg]}, 422)

    if not str(sol_user or "").strip() or not str(sol_pass or "").strip():
        return _err("Error de validación", {"sol_user": ["Usuario y clave SOL son obligatorios."]}, 422)

    conn = _get_conn()
    cur = conn.cursor()
    try:
        ensure_plataform_tables(cur)
        cur.execute("SELECT id FROM plataform_empresas WHERE ruc = %s", (ruc_clean,))
        if cur.fetchone():
            return _err("Error de validación", {"ruc": ["El campo ruc ya ha sido registrado."]}, 422)

        cur.execute("SELECT COALESCE(MAX(tenant_id), 0) + 1 FROM plataform_empresas")
        tenant_id = int(cur.fetchone()[0])
        api_key = _gen_api_key()
        api_secret = _gen_api_secret()
        cert_b64 = base64.b64encode(cert_bytes).decode("ascii")

        cur.execute(
            """
            INSERT INTO plataform_empresas (
                tenant_id, ruc, razon_social, direccion, ubigeo, departamento, provincia, distrito,
                usuario_sol, clave_sol, cert_password, cert_pfx_base64, entorno, plan,
                api_key, api_secret_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                tenant_id,
                ruc_clean,
                str(razon_social or "").strip(),
                str(direccion or "").strip(),
                str(ubigeo or "150101").strip(),
                str(departamento or "LIMA").strip(),
                str(provincia or "LIMA").strip(),
                str(distrito or "LIMA").strip(),
                str(sol_user or "").strip(),
                str(sol_pass or "").strip(),
                cert_password,
                cert_b64,
                str(entorno or "production").strip().lower(),
                str(plan or "pro").strip(),
                api_key,
                _hash_secret(api_secret),
            ),
        )
        empresa_id = int(cur.fetchone()[0])
        cur.execute(
            """
            INSERT INTO plataform_sucursales (empresa_id, nombre, cod_local, direccion, ubigeo, es_principal)
            VALUES (%s, %s, '0001', %s, %s, TRUE)
            """,
            (
                empresa_id,
                str(razon_social or "Sucursal Principal").strip()[:120],
                str(direccion or "").strip(),
                str(ubigeo or "150101").strip(),
            ),
        )
        conn.commit()

        datos = {
            "tenant_id": tenant_id,
            "id": empresa_id,
            "ruc": ruc_clean,
            "razon_social": str(razon_social or "").strip(),
            "entorno": str(entorno or "production").strip().lower(),
            "api_key": api_key,
            "api_secret": api_secret,
            "base_url": f"{PUBLIC_BASE}/api/v1",
            "aviso": "Guarda api_secret ahora: solo se muestra una vez.",
        }
        return _ok("Creado exitosamente", datos, 201)
    except Exception as exc:
        conn.rollback()
        return _err(f"Error al registrar empresa: {exc}", status=500)
    finally:
        conn.close()


@router.post("/empresa/credenciales/regenerar")
async def regenerar_credenciales(
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    x_api_secret: Optional[str] = Header(None, alias="X-Api-Secret"),
):
    key = str(x_api_key or "").strip()
    secret = str(x_api_secret or "").strip()
    if not key or not secret:
        return _err("Las cabeceras X-Api-Key y X-Api-Secret son requeridas.", status=401)

    conn = _get_conn()
    cur = conn.cursor()
    try:
        ensure_plataform_tables(cur)
        conn.commit()
        old = _empresa_por_key(cur, key, secret)
        if not old:
            return _err("Credenciales de API inválidas.", status=401)

        new_key = _gen_api_key()
        new_secret = _gen_api_secret()
        cur.execute(
            """
            UPDATE plataform_empresas
            SET api_key = %s, api_secret_hash = %s, actualizado = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (new_key, _hash_secret(new_secret), old["id"]),
        )
        conn.commit()
        datos = {
            "api_key": new_key,
            "api_secret": new_secret,
            "nueva_api_key": new_key,
            "nueva_api_secret": new_secret,
            "ruc": old.get("ruc"),
            "tenant_id": old.get("tenant_id"),
            "aviso": "Guarda el nuevo api_secret ahora: solo se muestra una vez.",
        }
        return _ok("Credenciales regeneradas", datos, 200)
    except Exception as exc:
        conn.rollback()
        return _err(str(exc), status=500)
    finally:
        conn.close()


@router.get("/empresa")
def get_empresa(empresa: dict = Depends(_require_auth)):
    datos = {
        "tenant_id": empresa.get("tenant_id"),
        "id": empresa.get("id"),
        "ruc": empresa.get("ruc"),
        "razon_social": empresa.get("razon_social"),
        "direccion": empresa.get("direccion"),
        "ubigeo": empresa.get("ubigeo"),
        "departamento": empresa.get("departamento"),
        "provincia": empresa.get("provincia"),
        "distrito": empresa.get("distrito"),
        "usuario_sol": empresa.get("usuario_sol"),
        "entorno": empresa.get("entorno"),
        "plan": empresa.get("plan"),
        "base_url": f"{PUBLIC_BASE}/api/v1",
    }
    return _ok("Empresa encontrada", datos)


@router.post("/sucursales")
async def crear_sucursal(request: Request, empresa: dict = Depends(_require_auth)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO plataform_sucursales (
                empresa_id, nombre, cod_local, direccion, ubigeo, es_principal, telefono, email
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                empresa["id"],
                str(body.get("nombre") or "Sucursal Principal").strip(),
                str(body.get("cod_local") or "0001").strip(),
                str(body.get("direccion") or empresa.get("direccion") or "").strip(),
                str(body.get("ubigeo") or empresa.get("ubigeo") or "150101").strip(),
                bool(body.get("es_principal", True)),
                str(body.get("telefono") or "").strip(),
                str(body.get("email") or "").strip(),
            ),
        )
        suc_id = int(cur.fetchone()[0])
        conn.commit()
        body_out = dict(body)
        body_out["id"] = suc_id
        body_out["empresa_id"] = empresa["id"]
        return _ok("Sucursal creada", body_out, 201)
    except Exception as exc:
        conn.rollback()
        return _err(str(exc), status=500)
    finally:
        conn.close()


@router.post("/series")
async def crear_series(request: Request, empresa: dict = Depends(_require_auth)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    series = body.get("series") if isinstance(body, dict) else None
    if not isinstance(series, list) or not series:
        return _err("Error de validación", {"series": ["Debe enviar al menos una serie."]}, 422)

    conn = _get_conn()
    cur = conn.cursor()
    creadas = []
    try:
        for item in series:
            if not isinstance(item, dict):
                continue
            tipo = str(item.get("tipo") or "").strip().lower()
            serie = str(item.get("serie") or "").strip().upper()
            sucursal_id = int(item.get("sucursal_id") or 1)
            correlativo = max(1, int(item.get("correlativo_inicial") or 1))
            if not tipo or not serie:
                continue
            cur.execute(
                """
                INSERT INTO plataform_series (empresa_id, sucursal_id, tipo, serie, correlativo)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (empresa_id, tipo, serie)
                DO UPDATE SET correlativo = EXCLUDED.correlativo, sucursal_id = EXCLUDED.sucursal_id
                RETURNING id
                """,
                (empresa["id"], sucursal_id, tipo, serie, correlativo),
            )
            creadas.append({"id": int(cur.fetchone()[0]), "tipo": tipo, "serie": serie, "sucursal_id": sucursal_id})
        conn.commit()
        return _ok("Series configuradas", {"series": creadas}, 201)
    except Exception as exc:
        conn.rollback()
        return _err(str(exc), status=500)
    finally:
        conn.close()