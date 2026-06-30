param(
    [string]$Owner = "giomar456",
    [string]$Repo = "erp-api",
    [string]$Branch = "main",
    [string]$RenderServiceId = "srv-d7p6tn58nd3s73e49bf0",
    [string]$GitHubToken = "",
    [string]$RenderToken = "",
    [switch]$SkipRender,
    [switch]$ForceRender
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

function Publish-SingleCommit($paths, $message) {
    $ref = Invoke-GitHubJson "Get" "https://api.github.com/repos/$Owner/$Repo/git/ref/heads/$Branch"
    $baseCommit = $ref.object.sha
    $commitMeta = Invoke-GitHubJson "Get" "https://api.github.com/repos/$Owner/$Repo/git/commits/$baseCommit"
    $baseTree = $commitMeta.tree.sha
    $treeItems = @()
    foreach ($path in ($paths | Sort-Object)) {
        $local = Join-Path $Root ($path -replace "/", [IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path -LiteralPath $local)) {
            Write-Host "No existe $path, se omite." -ForegroundColor Yellow
            continue
        }
        $blob = Invoke-GitHubJson "Post" "https://api.github.com/repos/$Owner/$Repo/git/blobs" @{
            content = [Convert]::ToBase64String([IO.File]::ReadAllBytes($local))
            encoding = "base64"
        }
        $treeItems += @{
            path = $path
            mode = "100644"
            type = "blob"
            sha = $blob.sha
        }
        Write-Host "BLOB $path" -ForegroundColor DarkGray
    }
    if (-not $treeItems.Count) { throw "No hay archivos para publicar." }
    $newTree = Invoke-GitHubJson "Post" "https://api.github.com/repos/$Owner/$Repo/git/trees" @{
        base_tree = $baseTree
        tree = $treeItems
    }
    $newCommit = Invoke-GitHubJson "Post" "https://api.github.com/repos/$Owner/$Repo/git/commits" @{
        message = $message
        tree = $newTree.sha
        parents = @($baseCommit)
    }
    Invoke-GitHubJson "Patch" "https://api.github.com/repos/$Owner/$Repo/git/refs/heads/$Branch" @{
        sha = $newCommit.sha
        force = $false
    } | Out-Null
    Write-Host "COMMIT_UNICO $($newCommit.sha.Substring(0, 12))" -ForegroundColor Green
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

$commitMsg = "ERP: boton EMITIR SUNAT B002/F002 visible junto a Procesar, un solo deploy"
Write-Host "Subiendo a GitHub ($Owner/$Repo) en UN solo commit..." -ForegroundColor Cyan
$uploadPaths = @(
    "api.py",
    "requirements-api.txt",
    "my-react-app/src/App.jsx",
    "publicar_avance_completo.ps1",
    "ABRIR_PUBLICAR_AVANCE.bat"
)
if (Test-Path (Join-Path $Root "Dockerfile")) { $uploadPaths += "Dockerfile" }
Get-ChildItem -Path (Join-Path $Root "webapp") -Recurse -File | ForEach-Object {
    $uploadPaths += $_.FullName.Substring($Root.Length + 1).Replace("\", "/")
}
Publish-SingleCommit $uploadPaths $commitMsg

if ($ForceRender -and -not $SkipRender) {
    $script:RenderToken = Read-PlainSecret "Render token" "RENDER_API_KEY" $RenderToken
    if ([string]::IsNullOrWhiteSpace($script:RenderToken)) {
        Write-Host "Render token vacio. GitHub subido; Render usara auto-deploy del push." -ForegroundColor Yellow
    } else {
        $renderHeaders = @{ Authorization = "Bearer $script:RenderToken"; Accept = "application/json" }
        Invoke-RestMethod -Method Post -Headers $renderHeaders -Uri "https://api.render.com/v1/services/$RenderServiceId/deploys" -Body (@{ clearCache = "clear" } | ConvertTo-Json) -ContentType "application/json" | Out-Null
        Write-Host "Render deploy manual iniciado. Espera 2-3 min." -ForegroundColor Cyan
    }
} else {
    Write-Host "Un solo deploy: Render auto-deploy por el push (sin deploy manual extra)." -ForegroundColor Cyan
}

Write-Host "Publicacion completa." -ForegroundColor Green
Write-Log "PUBLICACION_OK"
Write-Host "Log: $LogPath" -ForegroundColor Yellow