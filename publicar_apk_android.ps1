param(
    [string]$Owner = "giomar456",
    [string]$Repo = "erp-api",
    [string]$Branch = "main",
    [string]$AndroidVersion = "1.77",
    [string]$ReleaseTag = "v1.0.72",
    [string]$RenderServiceId = "srv-d7p6tn58nd3s73e49bf0",
    [string]$GitHubToken = "",
    [string]$RenderToken = "",
    [switch]$SkipRender
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutDir = Join-Path $Root "actualizacion_android_$AndroidVersion"
$PhoneName = "GG_ERP_TELEFONO_v${AndroidVersion}_CAJA_PRODUCTOS_INSTALABLE.apk"
$DexName = "GG_ERP_TABLET_DEX_v${AndroidVersion}_CAJA_PRODUCTOS_INSTALABLE.apk"
$PhonePath = Join-Path $OutDir $PhoneName
$DexPath = Join-Path $OutDir $DexName
$Notes = "Actualizacion Android G&G ERP v${AndroidVersion}: EMITIR SUNAT B002/F002, compras producto nuevo, detalle/documento compra, fix guardar compra."

function Read-PlainSecret($label, $envName, $override = "") {
    if (-not [string]::IsNullOrWhiteSpace($override)) { return $override.Trim() }
    foreach ($scope in @("Process", "User", "Machine")) {
        $existing = [Environment]::GetEnvironmentVariable($envName, $scope)
        if (-not [string]::IsNullOrWhiteSpace($existing)) { return $existing.Trim() }
    }
    return ""
}

function Invoke-GitHubJson($method, $url, $body = $null) {
    $params = @{ Method = $method; Uri = $url; Headers = $script:GitHubHeaders }
    if ($null -ne $body) {
        $params["Body"] = ($body | ConvertTo-Json -Depth 8)
        $params["ContentType"] = "application/json"
    }
    return Invoke-RestMethod @params
}

function Get-OrCreateRelease() {
    try {
        return Invoke-GitHubJson "Get" "https://api.github.com/repos/$Owner/$Repo/releases/tags/$ReleaseTag"
    } catch {
        return Invoke-GitHubJson "Post" "https://api.github.com/repos/$Owner/$Repo/releases" @{
            tag_name = $ReleaseTag
            target_commitish = $Branch
            name = "G&G ERP $ReleaseTag Android $AndroidVersion"
            body = $Notes
            draft = $false
            prerelease = $false
        }
    }
}

function Upload-ReleaseAsset($release, $path, $assetName) {
    if (-not (Test-Path -LiteralPath $path)) { throw "No existe $path" }
    $assets = Invoke-GitHubJson "Get" $release.assets_url
    foreach ($asset in $assets) {
        if ($asset.name -eq $assetName) {
            Invoke-GitHubJson "Delete" "https://api.github.com/repos/$Owner/$Repo/releases/assets/$($asset.id)" | Out-Null
        }
    }
    $uploadBase = $release.upload_url.Split("{")[0]
    $headers = @{
        Authorization = "Bearer $script:GitHubToken"
        Accept = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
    }
    Invoke-RestMethod -Method Post -Uri "$uploadBase`?name=$([Uri]::EscapeDataString($assetName))" -Headers $headers -InFile $path -ContentType "application/octet-stream" | Out-Null
    Write-Host "GitHub asset OK: $assetName" -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $PhonePath)) { throw "Primero compila con compilar_apk_android.ps1. Falta $PhonePath" }

$script:GitHubToken = Read-PlainSecret "GitHub token" "GITHUB_TOKEN" $GitHubToken
if ([string]::IsNullOrWhiteSpace($script:GitHubToken)) { throw "GITHUB_TOKEN vacio" }
$script:GitHubHeaders = @{
    Authorization = "Bearer $script:GitHubToken"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

$release = Get-OrCreateRelease
Upload-ReleaseAsset $release $PhonePath $PhoneName
if (Test-Path -LiteralPath $DexPath) {
    Upload-ReleaseAsset $release $DexPath $DexName
}

$phoneUrl = "https://github.com/$Owner/$Repo/releases/download/$ReleaseTag/$PhoneName"
$dexUrl = "https://github.com/$Owner/$Repo/releases/download/$ReleaseTag/$DexName"

if (-not $SkipRender) {
    $script:RenderToken = Read-PlainSecret "Render token" "RENDER_API_KEY" $RenderToken
    if (-not [string]::IsNullOrWhiteSpace($script:RenderToken)) {
        $headers = @{ Authorization = "Bearer $script:RenderToken"; Accept = "application/json" }
        Invoke-RestMethod -Method Put -Headers $headers -Uri "https://api.render.com/v1/services/$RenderServiceId/env-vars/ANDROID_APP_VERSION" -Body (@{ value = $AndroidVersion } | ConvertTo-Json) -ContentType "application/json" | Out-Null
        Invoke-RestMethod -Method Put -Headers $headers -Uri "https://api.render.com/v1/services/$RenderServiceId/env-vars/ANDROID_APP_DOWNLOAD_URL" -Body (@{ value = $phoneUrl } | ConvertTo-Json) -ContentType "application/json" | Out-Null
        Invoke-RestMethod -Method Put -Headers $headers -Uri "https://api.render.com/v1/services/$RenderServiceId/env-vars/ANDROID_APP_APK_NAME" -Body (@{ value = $PhoneName } | ConvertTo-Json) -ContentType "application/json" | Out-Null
        Invoke-RestMethod -Method Put -Headers $headers -Uri "https://api.render.com/v1/services/$RenderServiceId/env-vars/ANDROID_APP_DEX_DOWNLOAD_URL" -Body (@{ value = $dexUrl } | ConvertTo-Json) -ContentType "application/json" | Out-Null
        Invoke-RestMethod -Method Put -Headers $headers -Uri "https://api.render.com/v1/services/$RenderServiceId/env-vars/ANDROID_APP_DEX_APK_NAME" -Body (@{ value = $DexName } | ConvertTo-Json) -ContentType "application/json" | Out-Null
        Invoke-RestMethod -Method Put -Headers $headers -Uri "https://api.render.com/v1/services/$RenderServiceId/env-vars/ANDROID_APP_UPDATE_NOTES" -Body (@{ value = $Notes } | ConvertTo-Json) -ContentType "application/json" | Out-Null
        Write-Host "Render env Android actualizado." -ForegroundColor Green
    }
}

Write-Host "PUBLICACION_APK_OK" -ForegroundColor Green
Write-Host "Telefono: $phoneUrl" -ForegroundColor Cyan
Write-Host "DeX: $dexUrl" -ForegroundColor Cyan