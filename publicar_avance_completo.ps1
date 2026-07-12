param(
    [string]$Owner = "giomar456",
    [string]$Repo = "erp-api",
    [string]$Branch = "main",
    [string]$OracleHost = "ubuntu@64.181.176.160",
    [string]$SshKey = "$env:USERPROFILE\Downloads\ssh-key-2026-07-08.key",
    [string]$GitHubToken = "",
    [switch]$SkipDeploy
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogPath = Join-Path $Root "publicar_avance_completo.log"

function Write-Log($message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message
    Add-Content -LiteralPath $LogPath -Value $line
    Write-Host $line
}

Write-Log "=== Publicar avance SOLO Oracle Cloud (sin Render) ==="
if (-not (Test-Path $SshKey)) { throw "Falta llave SSH: $SshKey" }

# Push a GitHub si hay token / git remoto
Set-Location $Root
git add -A
$status = git status --porcelain
if ($status) {
    git commit -m "publish: avance ERP Oracle $(Get-Date -Format yyyy-MM-dd_HH:mm)" 2>$null
    Write-Log "commit local listo"
} else {
    Write-Log "sin cambios locales para commit"
}

if (-not $SkipDeploy) {
    Write-Log "Subiendo webapp + api a Oracle..."
    $tar = Join-Path $env:TEMP "erp-oracle-publish.tgz"
    if (Test-Path $tar) { Remove-Item $tar -Force }
    tar -czf $tar -C $Root api.py Dockerfile docker-compose.oracle.yml requirements-api.txt plataform_sunat_client.py plataform_sunat_server.py plataform_sunat_panel.html webapp
    scp -i $SshKey -o StrictHostKeyChecking=no $tar "${OracleHost}:/tmp/erp-oracle-publish.tgz"
    ssh -i $SshKey -o StrictHostKeyChecking=no $OracleHost @"
set -e
cd ~/erp
tar -xzf /tmp/erp-oracle-publish.tgz
docker compose -f docker-compose.oracle.yml up -d --build api
sleep 8
curl -sS 'http://127.0.0.1:8000/health?db=1'
echo
"@
    Write-Log "Deploy Oracle OK"
}

Write-Log "ERP: http://64.181.176.160:8000/erp/"
