from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import psycopg2
import os

app = FastAPI()

# ================= CONEXION (SIMPLE Y ESTABLE) =================
def get_conn():
    return psycopg2.connect(
        os.getenv("DATABASE_URL"),
        sslmode="require"
    )


def dict_fetchall(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def dict_fetchone(cur):
    row = cur.fetchone()
    if not row:
        return None
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


# ================= MODELOS =================
class ItemVenta(BaseModel):
    id: int
    cantidad: int
    precio: float
    total: float
    producto_id: Optional[int] = None
    nombre: str = ""
    marca: str = ""
    modelo: str = ""
    serie: str = ""
    series_texto: str = ""


class Venta(BaseModel):
    tipo: str
    cliente_nombre: str
    items: List[ItemVenta]
    tipo_documento_cliente: str = ""
    numero_documento_cliente: str = ""
    direccion_cliente: str = ""
    usuario_emisor: str = ""
    observacion: str = ""
    estado_pago: str = "PAGADO"
    metodo_pago: str = ""


class Cliente(BaseModel):
    tipo_documento: str
    numero_documento: str
    nombre: str
    direccion: str


class SerieProducto(BaseModel):
    producto_id: int
    serie: str
    proveedor: str = ""
    estado: str = "DISPONIBLE"
    fecha_ingreso: str = ""
    fecha_salida: Optional[str] = None


class StockAjuste(BaseModel):
    stock: int


class CajaMovimiento(BaseModel):
    tipo: str = "INGRESO"
    detalle: str
    monto: float
    usuario: str = ""
    documento_tipo: str = "MOVIMIENTO"
    documento_numero: str = ""
    estado_pago: str = "PAGADO"
    metodo_pago: str = ""


class EstadoPagoUpdate(BaseModel):
    estado_pago: str
    metodo_pago: Optional[str] = None


class Producto(BaseModel):
    nombre: str
    categoria: str
    marca: str
    modelo: str
    precio_compra: float
    precio_venta: float
    stock: int


# ================= TEST CONEXION =================
@app.get("/")
def home():
    return {"ok": True, "app": "ERP API"}


@app.get("/test-conn")
def test_conn():
    try:
        conn = get_conn()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/init")
def init():
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            usuario TEXT UNIQUE,
            clave TEXT,
            rol TEXT
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            tipo_documento TEXT,
            numero_documento TEXT UNIQUE,
            nombre TEXT,
            direccion TEXT
        );
        """)

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
        VALUES
            ('PROFORMA','P001',1),
            ('NOTA DE VENTA','N001',1),
            ('BOLETA','B001',1),
            ('FACTURA','F001',1)
        ON CONFLICT (tipo) DO NOTHING;
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS producto_series (
            id SERIAL PRIMARY KEY,
            producto_id INT REFERENCES productos(id) ON DELETE CASCADE,
            serie TEXT UNIQUE,
            proveedor TEXT,
            estado TEXT DEFAULT 'DISPONIBLE',
            fecha_ingreso TEXT,
            fecha_salida TEXT,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

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

        for column_sql in [
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS documento_cliente TEXT",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS direccion_cliente TEXT",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS subtotal NUMERIC DEFAULT 0",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS igv NUMERIC DEFAULT 0",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS observacion TEXT",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS usuario_emisor TEXT",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'EMITIDO'",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS estado_pago TEXT DEFAULT 'PAGADO'",
            "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS metodo_pago TEXT DEFAULT ''",
        ]:
            cur.execute(column_sql)

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

        for column_sql in [
            "ALTER TABLE ventas_detalle ADD COLUMN IF NOT EXISTS descripcion TEXT",
            "ALTER TABLE ventas_detalle ADD COLUMN IF NOT EXISTS marca TEXT",
            "ALTER TABLE ventas_detalle ADD COLUMN IF NOT EXISTS modelo TEXT",
            "ALTER TABLE ventas_detalle ADD COLUMN IF NOT EXISTS series_texto TEXT",
        ]:
            cur.execute(column_sql)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS caja_movimientos (
            id SERIAL PRIMARY KEY,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tipo TEXT,
            detalle TEXT,
            monto NUMERIC,
            usuario TEXT,
            documento_tipo TEXT,
            documento_numero TEXT,
            estado_pago TEXT DEFAULT 'PAGADO',
            metodo_pago TEXT DEFAULT ''
        );
        """)

        cur.execute("ALTER TABLE caja_movimientos ADD COLUMN IF NOT EXISTS metodo_pago TEXT DEFAULT ''")

        conn.commit()
        conn.close()

        return {"ok": True, "msg": "Base completa lista"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


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
    ON CONFLICT (numero_documento)
    DO UPDATE SET tipo_documento=EXCLUDED.tipo_documento,
                  nombre=EXCLUDED.nombre,
                  direccion=EXCLUDED.direccion
    RETURNING id
    """, (data.tipo_documento, data.numero_documento,
          data.nombre, data.direccion))
    cliente_id = cur.fetchone()[0]

    conn.commit()
    conn.close()

    return {"ok": True, "id": cliente_id}


@app.get("/clientes")
def listar_clientes():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, tipo_documento, numero_documento, nombre, direccion
    FROM clientes
    ORDER BY id DESC
    """)
    data = dict_fetchall(cur)

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
    RETURNING id
    """, (data.nombre, data.categoria, data.marca,
          data.modelo, data.precio_compra,
          data.precio_venta, data.stock))
    producto_id = cur.fetchone()[0]

    conn.commit()
    conn.close()

    return {"ok": True, "id": producto_id}


@app.get("/productos")
def listar_productos():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, nombre, categoria, marca, modelo, precio_compra, precio_venta, stock
    FROM productos
    ORDER BY nombre
    """)
    data = dict_fetchall(cur)

    conn.close()

    return data


@app.get("/series")
def listar_series(q: str = ""):
    conn = get_conn()
    cur = conn.cursor()
    texto = f"%{(q or '').lower()}%"
    cur.execute("""
    SELECT
        ps.id,
        ps.producto_id,
        p.nombre AS producto_nombre,
        p.marca,
        p.modelo,
        ps.serie,
        ps.proveedor,
        ps.estado,
        ps.fecha_ingreso,
        ps.fecha_salida
    FROM producto_series ps
    LEFT JOIN productos p ON p.id = ps.producto_id
    WHERE %s = '%%'
       OR LOWER(COALESCE(ps.serie,'')) LIKE %s
       OR LOWER(COALESCE(ps.proveedor,'')) LIKE %s
       OR LOWER(COALESCE(ps.estado,'')) LIKE %s
       OR LOWER(COALESCE(p.nombre,'')) LIKE %s
       OR LOWER(COALESCE(p.marca,'')) LIKE %s
       OR LOWER(COALESCE(p.modelo,'')) LIKE %s
    ORDER BY ps.id DESC
    """, (texto, texto, texto, texto, texto, texto, texto))
    data = dict_fetchall(cur)
    conn.close()
    return data


@app.post("/series")
def guardar_serie_producto(data: SerieProducto):
    conn = get_conn()
    cur = conn.cursor()
    try:
        serie = (data.serie or "").strip()
        if not serie:
            conn.close()
            return {"ok": False, "msg": "La serie no puede estar vacia"}

        cur.execute("SELECT stock FROM productos WHERE id=%s", (data.producto_id,))
        producto = cur.fetchone()
        if not producto:
            conn.close()
            return {"ok": False, "msg": "Producto no encontrado"}

        cur.execute("""
        INSERT INTO producto_series (
            producto_id, serie, proveedor, estado, fecha_ingreso, fecha_salida
        )
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (serie)
        DO UPDATE SET producto_id=EXCLUDED.producto_id,
                      proveedor=EXCLUDED.proveedor,
                      estado=EXCLUDED.estado,
                      fecha_ingreso=EXCLUDED.fecha_ingreso,
                      fecha_salida=EXCLUDED.fecha_salida
        RETURNING id
        """, (
            data.producto_id, serie, data.proveedor, data.estado,
            data.fecha_ingreso, data.fecha_salida
        ))
        serie_id = cur.fetchone()[0]

        if (data.estado or "").upper() == "DISPONIBLE":
            cur.execute("""
            UPDATE productos
            SET stock = (
                SELECT COUNT(*) FROM producto_series
                WHERE producto_id=%s AND UPPER(COALESCE(estado,''))='DISPONIBLE'
            )
            WHERE id=%s
            """, (data.producto_id, data.producto_id))

        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "id": serie_id}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


@app.post("/productos/{producto_id}/ajustar-stock")
def ajustar_stock(producto_id: int, data: StockAjuste):
    conn = get_conn()
    cur = conn.cursor()
    try:
        nuevo_stock = max(0, int(data.stock))
        cur.execute("UPDATE productos SET stock=%s WHERE id=%s RETURNING id", (nuevo_stock, producto_id))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "msg": "Producto no encontrado"}
        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "id": producto_id, "stock": nuevo_stock}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


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


# ================= VENTAS / DOCUMENTOS =================
@app.post("/ventas")
def crear_venta(data: Venta):
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("SELECT id, serie, correlativo FROM series WHERE tipo=%s", (data.tipo,))
        row = cur.fetchone()

        if not row:
            conn.close()
            return {"ok": False, "msg": f"No existe serie para {data.tipo}"}

        serie_id, serie, corr = row
        numero = f"{serie}-{str(corr).zfill(6)}"
        total = round(sum([float(i.total) for i in data.items]), 2)
        subtotal = total
        igv = 0
        documento_cliente = data.numero_documento_cliente or ""
        if data.tipo_documento_cliente and documento_cliente:
            documento_cliente = f"{data.tipo_documento_cliente}: {documento_cliente}"

        estado_pago = (data.estado_pago or "PAGADO").upper()
        if estado_pago not in ("PAGADO", "CREDITO", "DEUDA"):
            estado_pago = "PAGADO"
        metodo_pago = (data.metodo_pago or "").upper()

        cur.execute("""
        INSERT INTO ventas (
            tipo, numero, cliente, documento_cliente, direccion_cliente,
            subtotal, igv, total, observacion, usuario_emisor, estado, estado_pago, metodo_pago
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'EMITIDO',%s,%s)
        RETURNING id
        """, (
            data.tipo, numero, data.cliente_nombre, documento_cliente,
            data.direccion_cliente, subtotal, igv, total,
            data.observacion, data.usuario_emisor, estado_pago, metodo_pago
        ))

        venta_id = cur.fetchone()[0]

        for item in data.items:
            producto_id = item.producto_id or item.id
            descripcion = item.nombre
            marca = item.marca
            modelo = item.modelo

            if not descripcion:
                cur.execute("SELECT nombre, marca, modelo FROM productos WHERE id=%s", (producto_id,))
                prod = cur.fetchone()
                if prod:
                    descripcion = prod[0] or ""
                    marca = marca or (prod[1] or "")
                    modelo = modelo or (prod[2] or "")

            cur.execute("""
            INSERT INTO ventas_detalle (
                venta_id, producto_id, descripcion, marca, modelo,
                series_texto, cantidad, precio, total
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                venta_id, producto_id, descripcion, marca, modelo,
                item.series_texto or item.serie,
                item.cantidad, item.precio, item.total
            ))

            cur.execute("""
            UPDATE productos SET stock = GREATEST(COALESCE(stock,0) - %s, 0)
            WHERE id = %s
            """, (item.cantidad, producto_id))

        cur.execute("UPDATE series SET correlativo = correlativo + 1 WHERE id=%s", (serie_id,))

        cur.execute("""
        INSERT INTO caja_movimientos (
            tipo, detalle, monto, usuario, documento_tipo, documento_numero, estado_pago, metodo_pago
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            "INGRESO" if estado_pago == "PAGADO" else estado_pago,
            f"{data.tipo} {numero} - {data.cliente_nombre}",
            total, data.usuario_emisor, data.tipo, numero, estado_pago, metodo_pago
        ))

        conn.commit()
        conn.close()

        return {
            "ok": True,
            "success": True,
            "data": {"id": venta_id, "numero": numero, "total": total},
            "id": venta_id,
            "numero": numero,
            "subtotal": subtotal,
            "igv": igv,
            "total": total,
            "estado_pago": estado_pago,
            "metodo_pago": metodo_pago
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


@app.post("/documentos/emitir")
def emitir_documento(data: Venta):
    return crear_venta(data)


@app.get("/documentos")
def listar_documentos():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT
        id,
        tipo,
        numero,
        cliente AS cliente_nombre,
        COALESCE(documento_cliente, '') AS documento_cliente,
        COALESCE(direccion_cliente, '') AS direccion_cliente,
        fecha AS fecha_emision,
        COALESCE(subtotal, total, 0) AS subtotal,
        COALESCE(igv, 0) AS igv,
        COALESCE(total, 0) AS total,
        COALESCE(observacion, '') AS observacion,
        COALESCE(usuario_emisor, '') AS usuario_emisor,
        COALESCE(estado, 'EMITIDO') AS estado,
        COALESCE(estado_pago, 'PAGADO') AS estado_pago,
        COALESCE(metodo_pago, '') AS metodo_pago
    FROM ventas
    ORDER BY id DESC
    """)
    data = dict_fetchall(cur)

    conn.close()
    return data


@app.get("/documentos/{documento_id}")
def detalle_documento(documento_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT
        vd.id,
        vd.venta_id AS documento_id,
        vd.producto_id,
        COALESCE(vd.descripcion, p.nombre, '') AS descripcion,
        COALESCE(vd.marca, p.marca, '') AS marca,
        COALESCE(vd.modelo, p.modelo, '') AS modelo,
        COALESCE(vd.series_texto, '') AS series_texto,
        vd.cantidad,
        vd.precio AS precio_unitario,
        vd.total
    FROM ventas_detalle vd
    LEFT JOIN productos p ON p.id = vd.producto_id
    WHERE vd.venta_id = %s
    ORDER BY vd.id
    """, (documento_id,))
    data = dict_fetchall(cur)

    conn.close()
    return data


@app.put("/documentos/{documento_id}/estado-pago")
def actualizar_estado_pago_documento(documento_id: int, data: EstadoPagoUpdate):
    conn = get_conn()
    cur = conn.cursor()
    try:
        estado_pago = (data.estado_pago or "PAGADO").upper()
        if estado_pago not in ("PAGADO", "CREDITO", "DEUDA"):
            estado_pago = "PAGADO"

        metodo_pago = data.metodo_pago.upper() if data.metodo_pago else None

        cur.execute("""
        UPDATE ventas
        SET estado_pago=%s, metodo_pago=COALESCE(%s, metodo_pago, '')
        WHERE id=%s
        RETURNING id, tipo, numero, cliente, total, usuario_emisor, COALESCE(metodo_pago, '')
        """, (estado_pago, metodo_pago, documento_id))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"ok": False, "msg": "Documento no encontrado"}

        venta_id, tipo, numero, cliente, total, usuario, metodo_pago_db = row

        cur.execute("""
        UPDATE caja_movimientos
        SET tipo=%s, estado_pago=%s, metodo_pago=%s
        WHERE documento_tipo=%s AND documento_numero=%s
        """, ("INGRESO" if estado_pago == "PAGADO" else estado_pago, estado_pago, metodo_pago_db, tipo, numero))

        if cur.rowcount == 0:
            cur.execute("""
            INSERT INTO caja_movimientos (
                tipo, detalle, monto, usuario, documento_tipo, documento_numero, estado_pago, metodo_pago
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                "INGRESO" if estado_pago == "PAGADO" else estado_pago,
                f"{tipo} {numero} - {cliente}",
                total, usuario or "", tipo, numero, estado_pago, metodo_pago_db
            ))

        conn.commit()
        conn.close()
        return {"ok": True, "success": True, "id": venta_id, "estado_pago": estado_pago, "metodo_pago": metodo_pago_db}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"ok": False, "msg": str(e)}


@app.get("/caja")
def listar_caja():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, fecha, tipo, detalle, monto, usuario,
           COALESCE(documento_tipo, '') AS documento_tipo,
           COALESCE(documento_numero, '') AS documento_numero,
           COALESCE(estado_pago, 'PAGADO') AS estado_pago,
           COALESCE(metodo_pago, '') AS metodo_pago
    FROM caja_movimientos
    ORDER BY id DESC
    """)
    data = dict_fetchall(cur)
    conn.close()
    return data


@app.post("/caja")
def registrar_caja(data: CajaMovimiento):
    conn = get_conn()
    cur = conn.cursor()
    estado_pago = (data.estado_pago or "PAGADO").upper()
    if estado_pago not in ("PAGADO", "CREDITO", "DEUDA"):
        estado_pago = "PAGADO"
    metodo_pago = (data.metodo_pago or "").upper()
    cur.execute("""
    INSERT INTO caja_movimientos (
        tipo, detalle, monto, usuario, documento_tipo, documento_numero, estado_pago, metodo_pago
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    RETURNING id
    """, (
        data.tipo, data.detalle, data.monto, data.usuario,
        data.documento_tipo, data.documento_numero, estado_pago, metodo_pago
    ))
    movimiento_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return {"ok": True, "id": movimiento_id}


@app.get("/dashboard")
def dashboard():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM clientes")
    clientes = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM productos")
    productos = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ventas")
    documentos = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(total),0) FROM ventas")
    total_ventas = float(cur.fetchone()[0] or 0)
    try:
        cur.execute("""
        SELECT COALESCE(SUM(CASE WHEN tipo='INGRESO' AND estado_pago='PAGADO' THEN monto ELSE 0 END),0)
             - COALESCE(SUM(CASE WHEN tipo='EGRESO' THEN monto ELSE 0 END),0)
        FROM caja_movimientos
        """)
        saldo_caja = float(cur.fetchone()[0] or 0)
    except Exception:
        saldo_caja = total_ventas

    conn.close()
    return {
        "clientes": clientes,
        "productos": productos,
        "documentos": documentos,
        "compras": 0,
        "total_ventas": total_ventas,
        "saldo_caja": saldo_caja,
    }
