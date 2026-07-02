"""
Cliente para la API de facturación electrónica SUNAT (plataform-api-sunat / Kodevo / apigo).

Basado en la colección Postman de yorchavez9:
https://github.com/yorchavez9/Api-de-facturacion-electronica-sunat-Peru
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

DEFAULT_BASE_URL = os.getenv(
    "PLATAFORM_SUNAT_BASE_URL",
    os.getenv("KODEVO_BASE_URL", "https://apisunatv2.kodevo.es/api/v1"),
)
FALLBACK_BASE_URLS = [
    b
    for b in [
        DEFAULT_BASE_URL,
        "https://apisunatv2.kodevo.es/api/v1",
        os.getenv("KODEVO_ALT_BASE_URL", "https://apigo.apuuraydev.com/api/v1"),
        "https://api.kodevo.es/sunat-api/api/v1",
    ]
    if b
]


def _headers(api_key: str, api_secret: str) -> Dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
        "X-Api-Secret": api_secret,
    }


def _request(
    method: str,
    path: str,
    *,
    api_key: str = "",
    api_secret: str = "",
    json_body: Optional[dict] = None,
    data: Optional[dict] = None,
    files: Optional[dict] = None,
    base_url: str = "",
    timeout: int = 120,
) -> Tuple[int, Any, str]:
    bases = list(dict.fromkeys([base_url or DEFAULT_BASE_URL, *FALLBACK_BASE_URLS]))
    last_status = 0
    last_body: Any = {"error": "sin respuesta"}
    last_base = bases[0] if bases else ""

    headers = {"Accept": "application/json"}
    if api_key and api_secret:
        headers.update(_headers(api_key, api_secret))
    if files:
        headers.pop("Content-Type", None)

    for base in bases:
        last_base = base.rstrip("/")
        url = f"{last_base}/{path.lstrip('/')}"
        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                json=json_body,
                data=data,
                files=files,
                timeout=timeout,
                verify=False,
            )
            last_status = resp.status_code
            try:
                last_body = resp.json()
            except Exception:
                last_body = resp.text
            if resp.status_code not in (404, 502, 503):
                return resp.status_code, last_body, last_base
        except Exception as exc:
            last_body = {"error": str(exc), "base_url": last_base}
    return last_status, last_body, last_base


def parse_numero_documento(numero: str) -> Tuple[str, int]:
    text = str(numero or "").strip().upper()
    if "-" in text:
        serie, corr = text.split("-", 1)
        serie = serie.strip()
        corr_digits = re.sub(r"[^0-9]", "", corr)
        return serie, max(1, int(corr_digits or "1"))
    return text, 1


def _fecha_emision(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value or "").strip()
    if not text:
        return datetime.utcnow().date().isoformat()
    return text[:10]


def _cliente_tipo_doc(documento_cliente: str) -> Tuple[str, str]:
    text = str(documento_cliente or "").strip()
    upper = text.upper()
    number = re.sub(r"[^0-9]", "", text)
    if "RUC" in upper or len(number) == 11:
        return "6", number
    if "DNI" in upper or len(number) == 8:
        return "1", number
    if not number or number in ("-", "0"):
        return "0", "99999999"
    return "0", number or "99999999"


def erp_doc_to_payload(doc: dict, detalle: List[dict]) -> dict:
    serie, correlativo = parse_numero_documento(doc.get("numero"))
    tipo_doc, num_doc = _cliente_tipo_doc(doc.get("documento_cliente"))
    items = []
    for idx, item in enumerate(detalle, start=1):
        cantidad = max(1, int(item.get("cantidad") or 1))
        line_total = round(float(item.get("total") or 0), 2)
        if line_total <= 0:
            line_total = round(float(item.get("precio") or 0) * cantidad, 2)
        unit = round(line_total / cantidad, 2) if cantidad else round(float(item.get("precio") or 0), 2)
        descripcion = str(item.get("descripcion") or "PRODUCTO").strip()[:500]
        if item.get("series_texto"):
            descripcion = f"{descripcion} S/N: {item.get('series_texto')}"[:500]
        codigo = str(item.get("producto_id") or f"P{idx:03d}")
        items.append(
            {
                "codigo": codigo,
                "descripcion": descripcion,
                "unidad": "NIU",
                "cantidad": cantidad,
                "precio_unitario": unit,
                "tip_afe_igv": "10",
            }
        )
    if not items:
        raise ValueError("El documento no tiene items para enviar a la plataforma SUNAT.")

    payload = {
        "serie": serie,
        "correlativo": correlativo,
        "fecha_emision": _fecha_emision(doc.get("fecha")),
        "tipo_moneda": "PEN",
        "forma_pago": "Contado",
        "cliente": {
            "tipo_doc": tipo_doc,
            "num_doc": num_doc,
            "razon_social": str(doc.get("cliente") or "CLIENTE GENERAL").strip()[:200],
        },
        "items": items,
        "enviar_automatico": True,
    }
    direccion = str(doc.get("direccion_cliente") or "").strip()
    if direccion:
        payload["cliente"]["direccion"] = direccion[:250]
    if str(doc.get("tipo") or "").upper() == "FACTURA":
        payload["tipo_operacion"] = "0101"
    return payload


def _extraer_datos(body: Any) -> dict:
    if not isinstance(body, dict):
        return {}
    datos = body.get("datos")
    return datos if isinstance(datos, dict) else body


def _mapear_estado_sunat(body: Any) -> str:
    datos = _extraer_datos(body)
    for key in ("sunat_status", "estado_sunat", "sunat_estado", "status"):
        value = str(datos.get(key) or body.get(key) or "").strip().lower() if isinstance(body, dict) else ""
        if not value and isinstance(datos, dict):
            value = str(datos.get(key) or "").strip().lower()
        if value in ("aceptado", "accepted", "exito", "ok", "success"):
            return "ACEPTADO"
        if value in ("rechazado", "rejected", "error", "fallido", "failed"):
            return "RECHAZADO"
        if value in ("pendiente", "proceso", "enviado", "processing", "queued"):
            return "PROCESO"
    estado = str(body.get("estado") or "").strip().lower() if isinstance(body, dict) else ""
    if estado == "exito":
        return "PROCESO"
    if estado == "error":
        return "RECHAZADO"
    return "PROCESO"


def crear_documento(
    *,
    api_key: str,
    api_secret: str,
    doc_tipo: str,
    payload: dict,
    base_url: str = "",
) -> Tuple[int, Any, str]:
    tipo = str(doc_tipo or "").strip().upper()
    path = "facturas" if tipo == "FACTURA" else "boletas"
    return _request(
        "POST",
        f"/{path}",
        api_key=api_key,
        api_secret=api_secret,
        json_body=payload,
        base_url=base_url,
    )


def enviar_documento_plataform(
    *,
    api_key: str,
    api_secret: str,
    doc_tipo: str,
    documento_id: int,
    base_url: str = "",
) -> Tuple[int, Any, str]:
    tipo = str(doc_tipo or "").strip().upper()
    path = "facturas" if tipo == "FACTURA" else "boletas"
    return _request(
        "POST",
        f"/{path}/{int(documento_id)}/enviar",
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
    )


def asegurar_serie(
    *,
    api_key: str,
    api_secret: str,
    doc_tipo: str,
    serie: str,
    correlativo: int,
    sucursal_id: int = 1,
    base_url: str = "",
) -> Tuple[int, Any, str]:
    tipo_map = {"BOLETA": "boleta", "FACTURA": "factura"}
    tipo_serie = tipo_map.get(str(doc_tipo or "").upper(), "boleta")
    payload = {
        "series": [
            {
                "tipo": tipo_serie,
                "serie": serie,
                "sucursal_id": int(sucursal_id or 1),
                "correlativo_inicial": max(1, int(correlativo or 1)),
            }
        ]
    }
    return _request(
        "POST",
        "/series",
        api_key=api_key,
        api_secret=api_secret,
        json_body=payload,
        base_url=base_url,
    )


def registrar_empresa(
    *,
    ruc: str,
    razon_social: str,
    direccion: str,
    ubigeo: str,
    sol_user: str,
    sol_pass: str,
    cert_path: str,
    cert_password: str,
    entorno: str = "beta",
    client_id: str = "",
    client_secret: str = "",
    departamento: str = "LIMA",
    provincia: str = "LIMA",
    distrito: str = "LIMA",
    base_url: str = "",
) -> Tuple[int, Any, str]:
    data = {
        "ruc": ruc,
        "razon_social": razon_social,
        "direccion": direccion,
        "ubigeo": ubigeo,
        "sol_user": sol_user,
        "sol_pass": sol_pass,
        "contrasena": cert_password,
        "contrasena_certificado": cert_password,
        "tax_regime": "general",
        "departamento": departamento,
        "provincia": provincia,
        "distrito": distrito,
        "plan": "pro",
        "entorno": entorno,
    }
    if client_id:
        data["client_id"] = client_id
    if client_secret:
        data["client_secret"] = client_secret
    with open(cert_path, "rb") as cert_file:
        files = {"certificado": (os.path.basename(cert_path), cert_file, "application/x-pkcs12")}
        return _request("POST", "/registro", data=data, files=files, base_url=base_url)


def emitir_documento_erp(
    *,
    api_key: str,
    api_secret: str,
    doc: dict,
    detalle: List[dict],
    base_url: str = "",
    sucursal_id: int = 1,
    sincronizar_serie: bool = True,
) -> Dict[str, Any]:
    payload = erp_doc_to_payload(doc, detalle)
    serie = payload.get("serie")
    correlativo = int(payload.get("correlativo") or 1)
    doc_tipo = str(doc.get("tipo") or "BOLETA").upper()

    result: Dict[str, Any] = {
        "ok": False,
        "proveedor": "plataform",
        "http_status": 0,
        "base_url": base_url or DEFAULT_BASE_URL,
        "crear": None,
        "enviar": None,
        "plataform_id": None,
        "sunat_estado": "RECHAZADO",
        "numero_plataform": None,
        "payload": payload,
    }

    if sincronizar_serie and serie:
        sync_status, sync_body, used_base = asegurar_serie(
            api_key=api_key,
            api_secret=api_secret,
            doc_tipo=doc_tipo,
            serie=str(serie),
            correlativo=correlativo,
            sucursal_id=sucursal_id,
            base_url=base_url,
        )
        result["sync_serie"] = {"http_status": sync_status, "body": sync_body, "base_url": used_base}

    status, body, used_base = crear_documento(
        api_key=api_key,
        api_secret=api_secret,
        doc_tipo=doc_tipo,
        payload=payload,
        base_url=base_url,
    )
    result["http_status"] = status
    result["base_url"] = used_base
    result["crear"] = body

    if status >= 400:
        result["sunat_estado"] = "RECHAZADO"
        result["msg"] = _mensaje_error(body)
        return result

    datos = _extraer_datos(body)
    plataform_id = datos.get("id") or datos.get("boleta_id") or datos.get("factura_id")
    if plataform_id is None and isinstance(body, dict):
        plataform_id = body.get("id")
    result["plataform_id"] = plataform_id

    numero_plataform = datos.get("numero") or datos.get("numero_completo")
    if not numero_plataform:
        corr = datos.get("correlativo")
        if serie and corr:
            numero_plataform = f"{serie}-{str(corr).zfill(6)}"
    result["numero_plataform"] = numero_plataform

    estado = _mapear_estado_sunat(body)
    sunat_status = str(datos.get("sunat_status") or datos.get("estado_sunat") or "").strip().lower()
    if sunat_status:
        estado = _mapear_estado_sunat({"sunat_status": sunat_status})

    if estado == "PROCESO" and plataform_id and not sunat_status:
        send_status, send_body, _ = enviar_documento_plataform(
            api_key=api_key,
            api_secret=api_secret,
            doc_tipo=doc_tipo,
            documento_id=int(plataform_id),
            base_url=used_base,
        )
        result["enviar"] = {"http_status": send_status, "body": send_body}
        if send_status < 400:
            estado = _mapear_estado_sunat(send_body)
            datos_envio = _extraer_datos(send_body)
            sunat_status = str(datos_envio.get("sunat_status") or datos_envio.get("estado_sunat") or "").strip().lower()
            if sunat_status:
                estado = _mapear_estado_sunat({"sunat_status": sunat_status})

    result["sunat_estado"] = estado
    result["ok"] = estado in ("ACEPTADO", "PROCESO")
    result["msg"] = _mensaje_error(body) if estado == "RECHAZADO" else "Documento enviado via plataform SUNAT."
    return result


def _mensaje_error(body: Any) -> str:
    if isinstance(body, dict):
        return str(body.get("mensaje") or body.get("message") or body.get("error") or body.get("detail") or body)
    return str(body or "Error desconocido")


if __name__ == "__main__":
    import urllib3

    urllib3.disable_warnings()
    sample = emitir_documento_erp(
        api_key=os.getenv("PLATAFORM_SUNAT_API_KEY", os.getenv("KODEVO_API_KEY", "")),
        api_secret=os.getenv("PLATAFORM_SUNAT_API_SECRET", os.getenv("KODEVO_API_SECRET", "")),
        doc={
            "tipo": "BOLETA",
            "numero": "B002-000001",
            "cliente": "CLIENTE PRUEBA PLATAFORM",
            "documento_cliente": "12345678",
            "fecha": "2026-07-01",
        },
        detalle=[
            {
                "descripcion": "PRODUCTO PRUEBA",
                "cantidad": 1,
                "precio": 10,
                "total": 10,
                "producto_id": 1,
            }
        ],
        base_url=os.getenv("PLATAFORM_SUNAT_BASE_URL", DEFAULT_BASE_URL),
    )
    print(json.dumps(sample, ensure_ascii=False, indent=2))