import base64
import mimetypes
import os

import requests

BASE_URL = os.getenv("ERP_API_URL", "https://erp-api-7x3d.onrender.com")
EMPRESA = "computer_army"

def set_empresa(empresa):
    global EMPRESA
    EMPRESA = (empresa or "computer_army").strip().lower().replace(" ", "_") or "computer_army"

def headers():
    return {}

def branch_params(extra=None):
    data = {"sucursal": EMPRESA, "empresa": EMPRESA}
    if extra:
        data.update(extra)
    return data

def branch_payload(d):
    payload = dict(d or {})
    payload.setdefault("sucursal", EMPRESA)
    payload.setdefault("empresa", EMPRESA)
    return payload

def as_list_response(resp, keys=()):
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for key in keys:
            value = resp.get(key)
            if isinstance(value, list):
                return value
        value = resp.get("data")
        if isinstance(value, list):
            return value
    return []

# ---------------- LOGIN ----------------
def validar_usuario(usuario, clave):
    try:
        r = requests.post(
            f"{BASE_URL}/login",
            json={
                "usuario": usuario,
                "clave": clave,
                "sucursal": EMPRESA,
                "empresa": EMPRESA
            }
        )
        return r.json()
    except:
        return {"ok": False}

# ---------------- CLIENTES ----------------
def guardar_cliente(d):
    try:
        return requests.post(f"{BASE_URL}/clientes", json=branch_payload(d)).json()
    except:
        return {"ok": False}

def obtener_clientes():
    try:
        return requests.get(f"{BASE_URL}/clientes", params=branch_params()).json()
    except:
        return []

def buscar_cliente_por_documento(documento):
    try:
        return requests.get(f"{BASE_URL}/clientes/{documento}", params=branch_params()).json()
    except Exception as e:
        return {"ok": False, "success": False, "found": False, "msg": str(e)}

def consultar_documento(documento):
    try:
        return requests.get(f"{BASE_URL}/consulta/documento/{documento}", params=branch_params()).json()
    except Exception as e:
        return {"ok": False, "success": False, "found": False, "msg": str(e)}

# ---------------- PRODUCTOS ----------------
def guardar_producto(d):
    try:
        return requests.post(f"{BASE_URL}/productos", json=branch_payload(d)).json()
    except:
        return {"ok": False}

def obtener_productos():
    try:
        return requests.get(f"{BASE_URL}/productos", params=branch_params()).json()
    except:
        return []


def actualizar_producto(producto_id, payload):
    try:
        return requests.put(f"{BASE_URL}/productos/{producto_id}", params=branch_params(), json=branch_payload(payload)).json()
    except:
        return {"ok": False}

def eliminar_producto(producto_id):
    try:
        return requests.delete(f"{BASE_URL}/productos/{producto_id}", params=branch_params()).json()
    except:
        return {"ok": False}

# ---------------- VENTAS ----------------
def emitir_documento(d):
    try:
        return requests.post(f"{BASE_URL}/ventas", json=branch_payload(d)).json()
    except:
        return {"ok": False}


# ---------------- DOCUMENTOS ----------------
def siguiente_numero(tipo):
    try:
        return requests.get(f"{BASE_URL}/series/{tipo}", params=branch_params()).json().get("numero", "")
    except:
        return ""

def obtener_documentos(fecha=""):
    try:
        extra = {"fecha": fecha} if fecha else None
        return requests.get(f"{BASE_URL}/documentos", params=branch_params(extra)).json()
    except:
        return []

def obtener_ultimo_documento_caja():
    try:
        return requests.get(f"{BASE_URL}/documentos/ultimo", params=branch_params()).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def obtener_detalle_documento(documento_id):
    try:
        return requests.get(f"{BASE_URL}/documentos/{documento_id}").json()
    except:
        return []

def actualizar_series_detalle_documento(detalle_id, series_texto="", usuario=""):
    try:
        return requests.put(
            f"{BASE_URL}/documentos/detalle/{detalle_id}/series",
            params=branch_params(),
            json={"series_texto": series_texto, "usuario": usuario}
        ).json()
    except:
        return {"ok": False}

def eliminar_documento(documento_id):
    try:
        return requests.delete(f"{BASE_URL}/documentos/{documento_id}", params=branch_params()).json()
    except:
        return {"ok": False}

def actualizar_documento(documento_id, payload):
    data = branch_payload(payload)
    for method, path in (
        ("put", f"{BASE_URL}/documentos/{documento_id}"),
        ("patch", f"{BASE_URL}/documentos/{documento_id}"),
        ("put", f"{BASE_URL}/documentos/{documento_id}/editar"),
        ("post", f"{BASE_URL}/documentos/{documento_id}/editar"),
    ):
        try:
            func = getattr(requests, method)
            resp = func(path, params=branch_params(), json=data).json()
            if _api_ok(resp):
                return resp
        except Exception:
            pass
    return {"ok": False, "msg": "La API no acepto la actualizacion del documento."}

def dashboard():
    try:
        return requests.get(f"{BASE_URL}/dashboard", params=branch_params()).json()
    except:
        return {}


# ---------------- CONFIGURACION CENTRAL ----------------
def obtener_config_documento():
    try:
        return requests.get(f"{BASE_URL}/config/documento", params=branch_params()).json()
    except:
        return {"ok": False, "data": {}}

def guardar_config_documento(d):
    try:
        return requests.post(f"{BASE_URL}/config/documento", json=branch_payload(d)).json()
    except:
        return {"ok": False}

def obtener_config_web():
    try:
        return requests.get(f"{BASE_URL}/web/config", params=branch_params()).json()
    except:
        return {"ok": False, "data": {}}

def guardar_config_web(d):
    try:
        return requests.post(f"{BASE_URL}/web/config", params=branch_params(), json=branch_payload(d)).json()
    except:
        return {"ok": False}

# ---------------- USUARIOS ----------------
def obtener_usuarios():
    try:
        return requests.get(f"{BASE_URL}/usuarios", params=branch_params()).json()
    except:
        return []

def perfil_usuario(usuario):
    try:
        return requests.get(f"{BASE_URL}/usuarios/perfil", params={"usuario": usuario}).json()
    except:
        return {"ok": False, "found": False}

def guardar_usuario(d):
    try:
        return requests.post(f"{BASE_URL}/usuarios", json=branch_payload(d)).json()
    except:
        return {"ok": False}

def actualizar_foto_usuario(usuario_id, foto_url):
    try:
        return requests.put(f"{BASE_URL}/usuarios/{usuario_id}/foto", json={"foto_url": foto_url}).json()
    except:
        return {"ok": False}


# ---------------- CAJA ----------------
def obtener_caja():
    try:
        return requests.get(f"{BASE_URL}/caja", params=branch_params()).json()
    except:
        return []

def guardar_mov_caja(d):
    try:
        return requests.post(f"{BASE_URL}/caja", json=branch_payload(d)).json()
    except:
        return {"ok": False}

# ---------------- COMPRAS / PROVEEDORES ----------------
def obtener_compras():
    try:
        return as_list_response(requests.get(f"{BASE_URL}/compras", params=branch_params()).json(), ("compras", "items"))
    except:
        return []

def guardar_compra(d):
    try:
        return requests.post(f"{BASE_URL}/compras", json=branch_payload(d)).json()
    except:
        return {"ok": False}

def obtener_proveedores():
    try:
        return as_list_response(requests.get(f"{BASE_URL}/proveedores", params=branch_params()).json(), ("proveedores", "items"))
    except:
        return []

def guardar_proveedor(d):
    try:
        return requests.post(f"{BASE_URL}/proveedores", json=branch_payload(d)).json()
    except:
        return {"ok": False}

# ---------------- INVENTARIO / SERIES ----------------
def obtener_series(q=""):
    try:
        return requests.get(f"{BASE_URL}/series", params=branch_params({"q": q})).json()
    except:
        return []

def obtener_series_producto(producto_id):
    try:
        return requests.get(f"{BASE_URL}/productos/{int(producto_id)}/series", params=branch_params()).json()
    except Exception:
        return []

def guardar_serie(d):
    try:
        return requests.post(f"{BASE_URL}/series", json=branch_payload(d)).json()
    except:
        return {"ok": False}

def actualizar_serie(serie_id, d):
    try:
        return requests.put(f"{BASE_URL}/series/{serie_id}", params=branch_params(), json=branch_payload(d)).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def eliminar_serie(serie_id):
    try:
        return requests.delete(f"{BASE_URL}/series/{serie_id}", params=branch_params()).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def ajustar_stock_producto(producto_id, nuevo_stock):
    try:
        return requests.post(f"{BASE_URL}/productos/{producto_id}/ajustar-stock", params=branch_params(), json={"stock": int(nuevo_stock)}).json()
    except:
        return {"ok": False}


def transferir_stock(producto_id, cantidad, sucursal_destino, usuario="", nota=""):
    try:
        return requests.post(
            f"{BASE_URL}/stock/transferir",
            json={
                "producto_id": int(producto_id),
                "cantidad": int(cantidad),
                "sucursal_origen": EMPRESA,
                "sucursal_destino": sucursal_destino,
                "usuario": usuario,
                "nota": nota
            }
        ).json()
    except:
        return {"ok": False}


def iniciar_inventario_conteo(categoria, usuario=""):
    try:
        return requests.post(
            f"{BASE_URL}/inventario/conteos",
            json=branch_payload({"categoria": categoria, "usuario": usuario})
        ).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def obtener_inventario_conteo(conteo_id):
    try:
        return requests.get(f"{BASE_URL}/inventario/conteos/{int(conteo_id)}", params=branch_params()).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def escanear_inventario_conteo(conteo_id, serie, usuario=""):
    try:
        return requests.post(
            f"{BASE_URL}/inventario/conteos/{int(conteo_id)}/scan",
            params=branch_params(),
            json={"serie": serie, "usuario": usuario}
        ).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def cerrar_inventario_conteo(conteo_id):
    try:
        return requests.post(f"{BASE_URL}/inventario/conteos/{int(conteo_id)}/cerrar", params=branch_params()).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def _api_ok(resp):
    if not isinstance(resp, dict):
        return False
    if resp.get("ok") is True or resp.get("success") is True:
        return True
    return resp.get("data") not in (None, False)


def _observacion_con_comprobante(observacion_pago="", comprobante_pago=""):
    comprobante_pago = str(comprobante_pago or "").strip()
    if not comprobante_pago:
        return observacion_pago
    base = str(observacion_pago or "").strip()
    detalle = f"Comprobante: {comprobante_pago.split('/')[-1].split(chr(92))[-1]}"
    return f"{base} | {detalle}" if base else detalle


def _comprobante_pago_payload(path):
    if not path or not os.path.isfile(path):
        return {}
    size = os.path.getsize(path)
    if size > 15 * 1024 * 1024:
        raise ValueError("Comprobante mayor a 15 MB.")
    mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return {
        "comprobante_pago_nombre": os.path.basename(path),
        "comprobante_pago_mime": mime_type,
        "comprobante_pago_tamano": size,
        "comprobante_pago_base64": encoded,
        "comprobante_pago_data_url": f"data:{mime_type};base64,{encoded}",
    }


def actualizar_estado_pago_documento(documento_id, estado_pago, metodo_pago="", monto_pagado=None, observacion_pago="", comprobante_pago="", comprobante_pago_payload=None, pagos_detalle=None):
    try:
        payload = {"estado_pago": estado_pago, "metodo_pago": metodo_pago, "observacion_pago": observacion_pago}
        if monto_pagado is not None:
            payload["monto_pagado"] = float(monto_pagado)
        if pagos_detalle:
            payload["pagos_detalle"] = pagos_detalle
        if isinstance(comprobante_pago_payload, dict) and comprobante_pago_payload.get("comprobantes_pago"):
            payload.update(comprobante_pago_payload)
            if comprobante_pago:
                payload["comprobante_pago"] = comprobante_pago
        elif comprobante_pago:
            payload["comprobante_pago"] = comprobante_pago
            payload.update(comprobante_pago_payload if isinstance(comprobante_pago_payload, dict) else _comprobante_pago_payload(comprobante_pago))
        resp = requests.put(
            f"{BASE_URL}/documentos/{documento_id}/estado-pago",
            params=branch_params(),
            json=payload
        ).json()
        if _api_ok(resp) or not comprobante_pago:
            return resp
        payload = {"estado_pago": estado_pago, "metodo_pago": metodo_pago, "observacion_pago": _observacion_con_comprobante(observacion_pago, comprobante_pago)}
        if monto_pagado is not None:
            payload["monto_pagado"] = float(monto_pagado)
        if pagos_detalle:
            payload["pagos_detalle"] = pagos_detalle
        return requests.put(
            f"{BASE_URL}/documentos/{documento_id}/estado-pago",
            params=branch_params(),
            json=payload
        ).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def actualizar_estado_sunat(documento_id, sunat_estado="PROCESO", sunat_modo="MANUAL"):
    try:
        return requests.put(
            f"{BASE_URL}/documentos/{documento_id}/sunat",
            params=branch_params(),
            json={"sunat_estado": sunat_estado, "sunat_modo": sunat_modo}
        ).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def obtener_sunat_config():
    try:
        return requests.get(f"{BASE_URL}/sunat/config", params=branch_params()).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def guardar_sunat_config(payload):
    try:
        return requests.post(f"{BASE_URL}/sunat/config", params=branch_params(), json=payload or {}).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def enviar_documento_sunat(documento_id, regenerar=True, permitir_sin_firma=False):
    try:
        return requests.post(
            f"{BASE_URL}/sunat/documentos/{documento_id}/enviar",
            params=branch_params(),
            json={"regenerar": bool(regenerar), "permitir_sin_firma": bool(permitir_sin_firma)},
            timeout=90,
        ).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def obtener_estado_documento_sunat(documento_id):
    try:
        return requests.get(
            f"{BASE_URL}/sunat/documentos/{documento_id}/estado",
            params=branch_params(),
            timeout=30,
        ).json()
    except Exception as e:
        return {"ok": False, "msg": str(e)}

# ---------------- PAGINA WEB / WOOCOMMERCE ----------------
def woo_test():
    try:
        return requests.get(f"{BASE_URL}/web/woocommerce/test", params=branch_params()).json()
    except:
        return {"ok": False}

def woo_productos(search=""):
    try:
        return requests.get(f"{BASE_URL}/web/woocommerce/products", params=branch_params({"search": search})).json()
    except:
        return {"ok": False, "data": []}

def woo_producto(producto_id):
    try:
        return requests.get(f"{BASE_URL}/web/woocommerce/products/{producto_id}", params=branch_params()).json()
    except:
        return {"ok": False}

def woo_guardar_producto(producto_id, payload):
    try:
        if producto_id:
            return requests.put(f"{BASE_URL}/web/woocommerce/products/{producto_id}", params=branch_params(), json=payload).json()
        return requests.post(f"{BASE_URL}/web/woocommerce/products", params=branch_params(), json=payload).json()
    except:
        return {"ok": False}

def woo_sincronizar_producto_erp(producto_id):
    try:
        return requests.post(f"{BASE_URL}/web/woocommerce/sync-product/{producto_id}", params=branch_params()).json()
    except:
        return {"ok": False}

def woo_sincronizar_productos_erp(only_with_stock=False):
    try:
        return requests.post(
            f"{BASE_URL}/web/woocommerce/sync-products",
            params=branch_params(),
            json={"only_with_stock": bool(only_with_stock)}
        ).json()
    except:
        return {"ok": False}

def woo_sincronizar_imagenes_web():
    try:
        return requests.post(f"{BASE_URL}/web/woocommerce/sync-images", params=branch_params()).json()
    except:
        return {"ok": False}

def woo_importar_productos_web(search="", only_with_stock=False):
    try:
        return requests.post(
            f"{BASE_URL}/web/woocommerce/import-products",
            params=branch_params(),
            json={"search": search, "only_with_stock": bool(only_with_stock)}
        ).json()
    except:
        return {"ok": False}

# ---------------- GARANTIAS ----------------
def obtener_garantias(q=""):
    try:
        return requests.get(f"{BASE_URL}/garantias", params=branch_params({"q": q})).json()
    except:
        return []

def guardar_garantia(d):
    try:
        garantia_id = d.get("id")
        if garantia_id:
            return requests.put(f"{BASE_URL}/garantias/{garantia_id}", params=branch_params(), json=branch_payload(d)).json()
        return requests.post(f"{BASE_URL}/garantias", json=branch_payload(d)).json()
    except:
        return {"ok": False}

# ---------------- AUDITORIA CENTRAL ----------------
def registrar_auditoria(d):
    try:
        return requests.post(f"{BASE_URL}/auditoria", json=d).json()
    except:
        return {"ok": False}

def obtener_auditoria(q="", limit=1000):
    try:
        return requests.get(f"{BASE_URL}/auditoria", params={"q": q, "limit": limit}).json()
    except:
        return []

# ---------------- SUCURSALES CENTRALES ----------------
def obtener_sucursales():
    try:
        return requests.get(f"{BASE_URL}/sucursales").json()
    except:
        return []

def guardar_sucursal(codigo, nombre, usuario="Giomar"):
    try:
        return requests.post(
            f"{BASE_URL}/sucursales",
            json={"codigo": codigo, "nombre": nombre, "usuario": usuario}
        ).json()
    except:
        return {"ok": False}

def eliminar_sucursal(codigo, usuario="Giomar"):
    try:
        return requests.delete(f"{BASE_URL}/sucursales/{codigo}", params={"usuario": usuario}).json()
    except:
        return {"ok": False}

def obtener_permisos_sucursal(codigo=None):
    try:
        sucursal = codigo or EMPRESA
        return requests.get(f"{BASE_URL}/sucursales/{sucursal}/permisos").json()
    except:
        return {"ok": False, "permisos": {}}

def guardar_permisos_sucursal(codigo, permisos, usuario="Giomar"):
    try:
        return requests.post(
            f"{BASE_URL}/sucursales/{codigo}/permisos",
            json={"usuario": usuario, "permisos": permisos}
        ).json()
    except:
        return {"ok": False}
