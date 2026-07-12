# G&G ERP — Produccion SOLO Oracle Cloud

## URL unica
- API / ERP: **http://64.181.176.160:8000**
- Web caja: **http://64.181.176.160:8000/erp/**
- Health: **http://64.181.176.160:8000/health?db=1**
- SUNAT panel: **http://64.181.176.160:8000/sunat-panel**

## Infra
| Pieza | Detalle |
|-------|---------|
| Cloud | Oracle Always Free (Sao Paulo) |
| VM | `gg-erp-api` / `64.181.176.160` |
| API | Docker `erp-api-1` |
| DB | Docker Postgres `erp-db-1` (volumen `erp_pgdata`) |
| Render | **NO usar** (suspendido) |
| Railway | **NO usar** |

## Optimizacion (1GB RAM)
- Postgres: shared_buffers 64MB, max_connections 40, mem_limit 320M
- API: 1 worker, concurrency 15, pool 1-5, cache productos 300s, mem_limit 420M

## Deploy
```powershell
.\publicar_avance_completo.ps1
```

## SSH
```powershell
ssh -i $env:USERPROFILE\Downloads\ssh-key-2026-07-08.key ubuntu@64.181.176.160
cd ~/erp
docker compose -f docker-compose.oracle.yml ps
docker compose -f docker-compose.oracle.yml logs -f --tail 100 api
```
