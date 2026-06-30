param(
    [string]$Owner = "giomar456",
    [string]$Repo = "erp-api",
    [string]$Branch = "main",
    [string]$RenderServiceId = "srv-d7p6tn58nd3s73e49bf0",
    [string]$GitHubToken = "",
    [string]$RenderToken = "",
    [switch]$SkipRender
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogPath = Join-Path $Root "publicar_avance_completo.log"

function Write-Log($message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message
    Add-Content -LiteralPath $LogPath -Value $line
}

function Read-PlainSecret($label, $envName, $override = "") {
    if (-not [string]::IsNullOrWhiteSpace($override)) { return (($override -replace '[\x00-\x1F\x7F]', '').Trim()) }
    foreach ($scope in @("Process", "User", "Machine")) {
        $existing = [Environment]::GetEnvironmentVariable($envName, $scope)
        if (-not [string]::IsNullOrWhiteSpace($existing)) { return (($existing -replace '[\x00-\x1F\x7F]', '').Trim()) }
    }
    if ([Environment]::UserInteractive) {
        $secure = Read-Host "$label" -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { return (($plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)) -replace '[\x00-\x1F\x7F]', '').Trim() }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    }
    return ""
}

function Invoke-GitHubJson($method, $url, $body = $null) {
    Write-Log "$method $url"
    $params = @{
        Method = $method
        Uri = $url
        Headers = $script:GitHubHeaders
    }
    if ($null -ne $body) {
        $params["Body"] = ($body | ConvertTo-Json -Depth 8)
        $params["ContentType"] = "application/json"
    }
    return Invoke-RestMethod @params
}

function Get-GitHubContentSha($path) {
    $encodedPath = [Uri]::EscapeDataString($path).Replace("%2F", "/")
    try {
        $meta = Invoke-GitHubJson "Get" "https://api.github.com/repos/$Owner/$Repo/contents/$encodedPath`?ref=$Branch"
        return $meta.sha
    } catch {
        return $null
    }
}

function Put-GitHubFile($path, $message) {
    $local = Join-Path $Root $path
    if (-not (Test-Path -LiteralPath $local)) {
        Write-Host "No existe $path, se omite." -ForegroundColor Yellow
        return
    }
    $encodedPath = [Uri]::EscapeDataString($path).Replace("%2F", "/")
    $content = [Convert]::ToBase64String([IO.File]::ReadAllBytes($local))
    $sha = Get-GitHubContentSha $path
    $body = @{
        message = $message
        content = $content
        branch = $Branch
    }
    if ($sha) { $body["sha"] = $sha }
    Invoke-GitHubJson "Put" "https://api.github.com/repos/$Owner/$Repo/contents/$encodedPath" $body | Out-Null
    Write-Host "GitHub OK: $path" -ForegroundColor Green
}

Set-Content -LiteralPath $LogPath -Value ("Inicio publicacion completa {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))

$script:GitHubToken = Read-PlainSecret "GitHub token" "GITHUB_TOKEN" $GitHubToken
if ([string]::IsNullOrWhiteSpace($script:GitHubToken)) { throw "Token GitHub vacio. Define GITHUB_TOKEN o pasa -GitHubToken." }
$script:GitHubHeaders = @{
    Authorization = "Bearer $script:GitHubToken"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

Write-Host "Compilando frontend..." -ForegroundColor Cyan
Push-Location (Join-Path $Root "my-react-app")
npm run build | Out-Host
Pop-Location

$dist = Join-Path $Root "my-react-app\dist"
$web = Join-Path $Root "webapp"
Copy-Item -Force (Join-Path $dist "index.html") (Join-Path $web "index.html")
if (Test-Path (Join-Path $web "assets")) { Remove-Item -Recurse -Force (Join-Path $web "assets") }
Copy-Item -Recurse -Force (Join-Path $dist "assets") (Join-Path $web "assets")
Write-Host "webapp sincronizado desde dist" -ForegroundColor Green

$commitMsg = "ERP: permisos series, auditoria mercaderia, garantias, compras, DNI/RUC y web"
Write-Host "Subiendo a GitHub ($Owner/$Repo)..." -ForegroundColor Cyan
Put-GitHubFile "api.py" $commitMsg
Put-GitHubFile "requirements-api.txt" $commitMsg
if (Test-Path (Join-Path $Root "Dockerfile")) { Put-GitHubFile "Dockerfile" $commitMsg }
Put-GitHubFile "my-react-app/src/App.jsx" $commitMsg

Get-ChildItem -Path (Join-Path $Root "webapp") -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($Root.Length + 1).Replace("\", "/")
    Put-GitHubFile $rel $commitMsg
}

if (-not $SkipRender) {
    $script:RenderToken = Read-PlainSecret "Render token" "RENDER_API_KEY" $RenderToken
    if ([string]::IsNullOrWhiteSpace($script:RenderToken)) {
        Write-Host "Render token vacio. GitHub subido, pero sin deploy automatico." -ForegroundColor Yellow
    } else {
        $renderHeaders = @{ Authorization = "Bearer $script:RenderToken"; Accept = "application/json" }
        Invoke-RestMethod -Method Post -Headers $renderHeaders -Uri "https://api.render.com/v1/services/$RenderServiceId/deploys" -Body (@{ clearCache = "clear" } | ConvertTo-Json) -ContentType "application/json" | Out-Null
        Write-Host "Render deploy iniciado. Espera 2-3 min." -ForegroundColor Cyan
    }
}

Write-Host "Publicacion completa." -ForegroundColor Green
Write-Log "PUBLICACION_OK"
Write-Host "Log: $LogPath" -ForegroundColor Yellow