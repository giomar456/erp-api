"""
Restaura respaldo ERP en Oracle (o local) desde carpeta respaldo_oracle_*.
Uso:
  python _restaurar_oracle.py --backup respaldo_oracle_20260706_120000
  python _restaurar_oracle.py --backup respaldo_oracle_20260706_120000 --sql-only
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def find_pg_tool(name):
    for c in [name, rf"C:\Program Files\PostgreSQL\18\bin\{name}.exe",
              rf"C:\Program Files\PostgreSQL\16\bin\{name}.exe"]:
        try:
            subprocess.run([c, "--version"], capture_output=True, check=True, timeout=8)
            return c
        except Exception:
            continue
    return None


def restore_sql(database_url, sql_path):
    psql = find_pg_tool("psql")
    if not psql:
        return False, "psql no encontrado"
    proc = subprocess.run([psql, database_url, "-f", sql_path], capture_output=True, timeout=1800)
    if proc.returncode != 0:
        return False, proc.stderr.decode("utf-8", errors="replace")[:3000]
    return True, "SQL restaurado"


def restore_json(database_url, json_path):
    try:
        import psycopg2
    except ImportError:
        return False, "Instala psycopg2: pip install psycopg2-binary"
    with open(json_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    tablas = payload.get("tablas") or {}
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor()
    restored = 0
    for table, rows in tablas.items():
        if not isinstance(rows, list) or not rows:
            continue
        cols = list(rows[0].keys())
        placeholders = ", ".join(["%s"] * len(cols))
        col_sql = ", ".join(cols)
        for row in rows:
            values = [row.get(c) for c in cols]
            cur.execute(
                f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                values,
            )
        restored += len(rows)
    conn.commit()
    release = conn.close
    release()
    return True, f"JSON restaurado ({restored} filas procesadas)"


def write_env_file(backup_dir, out_path):
    env_src = os.path.join(backup_dir, "render_env.json")
    if not os.path.isfile(env_src):
        return False
    with open(env_src, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    lines = []
    skip = {"DATABASE_URL"}
    for key, value in sorted(data.items()):
        if key in skip:
            continue
        safe = str(value).replace("\n", "\\n")
        lines.append(f"{key}={safe}")
    lines.append("POSTGRES_PASSWORD=erp_oracle_2026")
    lines.append("PUBLIC_BASE_URL=http://TU_IP_ORACLE:8000")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True, help="Carpeta respaldo_oracle_YYYYMMDD_HHMMSS")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--sql-only", action="store_true")
    parser.add_argument("--write-env-only", action="store_true", help="Solo genera .env.oracle desde render_env.json")
    args = parser.parse_args()

    backup_dir = args.backup if os.path.isabs(args.backup) else os.path.join(ROOT, args.backup)
    if not os.path.isdir(backup_dir):
        print(f"No existe carpeta: {backup_dir}")
        sys.exit(1)

    if args.write_env_only:
        env_out = os.path.join(ROOT, ".env.oracle")
        if write_env_file(backup_dir, env_out):
            print(f"Plantilla env: {env_out}")
            return
        print("No se pudo generar .env.oracle")
        sys.exit(1)

    database_url = args.database_url
    if not database_url:
        print("Define DATABASE_URL o usa docker-compose en Oracle.")
        sys.exit(1)

    sql_path = os.path.join(backup_dir, "base_datos.sql")
    json_path = os.path.join(backup_dir, "base_datos.json")

    if os.path.isfile(sql_path):
        print("Restaurando SQL...")
        ok, msg = restore_sql(database_url, sql_path)
        print(msg)
        if not ok and not args.sql_only:
            print("Intentando JSON...")
        elif ok:
            env_out = os.path.join(ROOT, ".env.oracle")
            if write_env_file(backup_dir, env_out):
                print(f"Plantilla env: {env_out}")
            print("Restauracion SQL completada.")
            return

    if os.path.isfile(json_path) and not args.sql_only:
        print("Restaurando JSON...")
        ok, msg = restore_json(database_url, json_path)
        print(msg)
        if ok:
            env_out = os.path.join(ROOT, ".env.oracle")
            if write_env_file(backup_dir, env_out):
                print(f"Plantilla env: {env_out}")
            return
    print("No se pudo restaurar.")
    sys.exit(1)


if __name__ == "__main__":
    main()