param(
    [string]$AndroidVersion = "1.77"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $Root "my-react-app"
$AndroidDir = Join-Path $AppDir "android"
$OutDir = Join-Path $Root "actualizacion_android_$AndroidVersion"
$PhoneName = "GG_ERP_TELEFONO_v${AndroidVersion}_CAJA_PRODUCTOS_INSTALABLE.apk"
$DexName = "GG_ERP_TABLET_DEX_v${AndroidVersion}_CAJA_PRODUCTOS_INSTALABLE.apk"
$LogPath = Join-Path $Root "compilar_apk_android.log"

function Write-Log($message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message
    Add-Content -LiteralPath $LogPath -Value $line
    Write-Host $message
}

function Find-ApkSigner {
    $sdk = Join-Path $env:LOCALAPPDATA "Android\Sdk\build-tools"
    if (-not (Test-Path -LiteralPath $sdk)) { return $null }
    $latest = Get-ChildItem -LiteralPath $sdk -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $latest) { return $null }
    $tool = Join-Path $latest.FullName "apksigner.bat"
    if (Test-Path -LiteralPath $tool) { return $tool }
    return $null
}

function Sign-Apk($inputApk, $outputApk) {
    $debugKs = Join-Path $env:USERPROFILE ".android\debug.keystore"
    $apksigner = Find-ApkSigner
    if (-not (Test-Path -LiteralPath $debugKs) -or -not $apksigner) {
        Copy-Item -Force -LiteralPath $inputApk -Destination $outputApk
        Write-Log "AVISO: APK sin firma debug, se copio tal cual: $outputApk"
        return
    }
    & $apksigner sign --ks $debugKs --ks-pass pass:android --key-pass pass:android --out $outputApk $inputApk
    if ($LASTEXITCODE -ne 0) {
        Copy-Item -Force -LiteralPath $inputApk -Destination $outputApk
        Write-Log "AVISO: fallo apksigner, se copio unsigned: $outputApk"
        return
    }
    Write-Log "APK firmado: $outputApk"
}

function Ensure-JavaHome {
    if ($env:JAVA_HOME -and (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME "bin\java.exe"))) {
        return
    }
    $candidates = @(
        "C:\Program Files\Android\Android Studio\jbr",
        "C:\Program Files\Android\Android Studio1\jbr",
        "$env:LOCALAPPDATA\Programs\Android\Android Studio\jbr"
    )
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $path "bin\java.exe")) {
            $env:JAVA_HOME = $path
            $env:PATH = "$path\bin;$env:PATH"
            Write-Log "JAVA_HOME=$path"
            return
        }
    }
    throw "JAVA_HOME no configurado. Instala Android Studio o define JAVA_HOME."
}

Set-Content -LiteralPath $LogPath -Value ("Inicio compilacion Android v$AndroidVersion {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Ensure-JavaHome

Push-Location $AppDir
try {
    Write-Log "1/4 npm run build"
    npm run build | Out-Host

    Write-Log "2/4 npx cap sync android"
    npx cap sync android | Out-Host
}
finally {
    Pop-Location
}

Push-Location $AndroidDir
try {
    Write-Log "3/4 gradlew assemblePhoneRelease assembleDexRelease"
    .\gradlew.bat assemblePhoneRelease assembleDexRelease --no-daemon | Out-Host
}
finally {
    Pop-Location
}

$phoneSrc = Join-Path $AndroidDir "app\build\outputs\apk\phone\release\app-phone-release-unsigned.apk"
$dexSrc = Join-Path $AndroidDir "app\build\outputs\apk\dex\release\app-dex-release-unsigned.apk"
if (-not (Test-Path -LiteralPath $phoneSrc)) { throw "No se genero phone APK en $phoneSrc" }
if (-not (Test-Path -LiteralPath $dexSrc)) { throw "No se genero dex APK en $dexSrc" }

$phoneDst = Join-Path $OutDir $PhoneName
$dexDst = Join-Path $OutDir $DexName
Write-Log "4/4 firmar y copiar APKs"
Sign-Apk $phoneSrc $phoneDst
Sign-Apk $dexSrc $dexDst

$notes = @"
G&G ERP Android v$AndroidVersion

- Boton EMITIR SUNAT legal B002/F002 en ventas (giomar, jean, mily).
- Compras: crear producto nuevo al ingresar mercaderia.
- Compras registradas: ver productos, series y abrir documento de compra.
- Correccion al guardar compra (error interno).
- Mejoras web recientes empaquetadas en APK telefono y tablet DeX.
"@
$notesPath = Join-Path $OutDir "release_notes_android_v$AndroidVersion.txt"
Set-Content -LiteralPath $notesPath -Value $notes -Encoding UTF8

Write-Log "LISTO: $OutDir"
Write-Log "Telefono: $phoneDst"
Write-Log "DeX: $dexDst"
Write-Log "COMPILACION_APK_OK"