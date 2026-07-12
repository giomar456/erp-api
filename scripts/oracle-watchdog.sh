#!/usr/bin/env bash
# Watchdog ERP Oracle — mantiene API/DB vivas y reinicia si el ping falla.
# No toca datos (solo health + restart de contenedores).
set -uo pipefail

ERP_DIR="${ERP_DIR:-$HOME/erp}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.oracle.yml}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
HEALTH_DB_URL="${HEALTH_DB_URL:-http://127.0.0.1:8000/health?db=1}"
LOG_FILE="${LOG_FILE:-$ERP_DIR/watchdog.log}"
MAX_LOG_LINES=400

mkdir -p "$ERP_DIR"
cd "$ERP_DIR" || exit 0

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log() { echo "[$(ts)] $*" >>"$LOG_FILE"; }

trim_log() {
  if [[ -f "$LOG_FILE" ]]; then
    local lines
    lines=$(wc -l <"$LOG_FILE" 2>/dev/null || echo 0)
    if [[ "${lines:-0}" -gt $MAX_LOG_LINES ]]; then
      tail -n 200 "$LOG_FILE" >"${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
    fi
  fi
}

ping_ok() {
  local url="$1"
  local body
  body=$(curl -sS --connect-timeout 5 --max-time 20 "$url" 2>/dev/null || true)
  echo "$body" | grep -q '"ok":true'
}

ensure_containers() {
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^erp-api-1$'; then
    log "api container missing -> compose up"
    docker compose -f "$COMPOSE_FILE" up -d >>"$LOG_FILE" 2>&1 || true
    return
  fi
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^erp-db-1$'; then
    log "db container missing -> compose up"
    docker compose -f "$COMPOSE_FILE" up -d >>"$LOG_FILE" 2>&1 || true
  fi
}

# 1) Asegurar contenedores
ensure_containers

# 2) Ping liviano (sin DB)
if ! ping_ok "$HEALTH_URL"; then
  log "PING FAIL health -> restart api"
  docker compose -f "$COMPOSE_FILE" restart api >>"$LOG_FILE" 2>&1 || docker restart erp-api-1 >>"$LOG_FILE" 2>&1 || true
  sleep 6
fi

# 3) Ping con DB
if ! ping_ok "$HEALTH_DB_URL"; then
  log "PING FAIL health?db=1 -> restart api+db"
  docker compose -f "$COMPOSE_FILE" restart api >>"$LOG_FILE" 2>&1 || true
  sleep 4
  if ! ping_ok "$HEALTH_DB_URL"; then
    docker compose -f "$COMPOSE_FILE" restart db >>"$LOG_FILE" 2>&1 || true
    sleep 8
    docker compose -f "$COMPOSE_FILE" restart api >>"$LOG_FILE" 2>&1 || true
    sleep 8
  fi
fi

# 4) Warm endpoints (mantiene workers/pool activos)
curl -sS --connect-timeout 4 --max-time 15 "$HEALTH_URL" >/dev/null 2>&1 || true
curl -sS --connect-timeout 4 --max-time 20 "$HEALTH_DB_URL" >/dev/null 2>&1 || true
curl -sS --connect-timeout 4 --max-time 15 "http://127.0.0.1:8000/" >/dev/null 2>&1 || true

if ping_ok "$HEALTH_DB_URL"; then
  : # ok
else
  log "STILL DOWN after recovery"
fi

trim_log
exit 0
