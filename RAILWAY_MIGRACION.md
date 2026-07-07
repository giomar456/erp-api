# Migracion G&G ERP API: Render -> Railway

## Que hace la migracion automatica

El script `migrar_render_a_railway.ps1`:

1. Exporta todas las variables de Render a `railway_migracion_env.json`
2. Compila `my-react-app` y publica en GitHub `giomar456/erp-api`
3. Si tienes `RAILWAY_TOKEN`, copia las variables a Railway y guarda IDs en `railway_ids.json`

## Paso 1: Crear proyecto en Railway (una vez)

1. [railway.app](https://railway.app) -> **New Project**
2. **Add PostgreSQL** (o reutiliza la misma base externa de Render)
3. **Deploy from GitHub** -> repo `giomar456/erp-api`, rama `main`
4. En el servicio API -> **Settings -> Networking -> Generate Domain**
5. Copia la URL publica, por ejemplo: `https://erp-api-production.up.railway.app`

## Paso 2: Token de Railway

1. railway.app -> **Account Settings -> Tokens -> Create**
2. Agrega el token como **linea 3** en `_tokens.txt` o como variable `RAILWAY_TOKEN`

## Paso 3: Ejecutar migracion

```bat
ABRIR_MIGRAR_RAILWAY.bat
```

O en PowerShell:

```powershell
.\migrar_render_a_railway.ps1 -UseRailwayPostgresRef
```

`-UseRailwayPostgresRef` hace que `DATABASE_URL` apunte a `${{Postgres.DATABASE_URL}}` en Railway.

## Paso 4: Migrar base de datos

Si creaste Postgres nuevo en Railway, copia datos desde Render:

```bash
pg_dump "DATABASE_URL_RENDER" -Fc -f erp_backup.dump
pg_restore -d "DATABASE_URL_RAILWAY" --no-owner --no-acl erp_backup.dump
```

Si usas la misma base externa (Neon/Supabase), no hace falta migrar datos.

## Paso 5: Validar

```text
https://TU-DOMINIO.up.railway.app/health
https://TU-DOMINIO.up.railway.app/app/version
https://TU-DOMINIO.up.railway.app/erp/
```

## Publicaciones futuras

| Accion | Script |
|---|---|
| Cambios de codigo / webapp | `ABRIR_PUBLICAR_RAILWAY.bat` |
| Nueva version PC/Android | `publicar_update_pc_railway.ps1` |
| Config SUNAT | `configurar_sunat_railway.ps1` |

## Cambiar clientes PC/Android

Cuando Railway funcione, actualiza la URL en:

- `api_client.py`
- `my-react-app/src/App.jsx`
- Genera nuevo instalador PC y APK