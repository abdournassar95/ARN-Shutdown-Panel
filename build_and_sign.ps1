# ==============================================================================
# Shutdown Panel — Build & Digital Signing Pipeline (Inno Setup Edition)
# Developer: Abdou Ragab Nassar (عبده رجب نصار)
# Company: ARN Technology
# Copyright (c) 2026 ARN Technology. All Rights Reserved.
# ==============================================================================

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  ARN Technology - Shutdown Panel Build & Sign Pipeline" -ForegroundColor Yellow
Write-Host "  Developer: Abdou Ragab Nassar (عبده رجب نصار)" -ForegroundColor Green
Write-Host "  Version:   2.0.1 (Production Release)" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Clean previous build folders & temporary files
Write-Host "`n>>> [1/7] Cleaning previous build folders & cache..." -ForegroundColor Cyan
Get-Process -Name "ShutdownPanel*", "ShutdownPanelClient*", "ShutdownPanel_Setup*" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

@(".\build", ".\dist") | ForEach-Object {
    if (Test-Path $_) {
        Remove-Item -Path $_ -Recurse -Force -ErrorAction SilentlyContinue | Out-Null
        Write-Host "  Cleaned: $_" -ForegroundColor DarkGray
    }
}
Get-ChildItem -Path "." -Filter "__pycache__" -Recurse -Directory -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue | Out-Null
Write-Host "  Build environment clean completed." -ForegroundColor Green

# 2. Check and Sync ARN Technology Digital Certificate
Write-Host "`n>>> [2/7] Checking ARN Technology Digital Certificate..." -ForegroundColor Cyan
if (-not (Test-Path "cert")) {
    New-Item -ItemType Directory -Force -Path "cert" | Out-Null
}

$cert = Get-ChildItem -Path "Cert:\CurrentUser\My" | Where-Object { $_.Subject -match "CN=ARN Technology" -and $_.NotAfter -gt (Get-Date) } | Select-Object -First 1

if (-not $cert) {
    Write-Host "  Generating self-signed Code Signing Certificate for ARN Technology..." -ForegroundColor Yellow
    $cert = New-SelfSignedCertificate -Subject "CN=ARN Technology, O=ARN Technology, C=EG" -Type CodeSigningCert -CertStoreLocation "Cert:\CurrentUser\My" -NotAfter (Get-Date).AddYears(10) -FriendlyName "ARN Technology Code Signing Certificate" -KeyAlgorithm RSA -KeyLength 3072 -KeyUsage DigitalSignature
}

Write-Host "  Active Certificate Thumbprint: $($cert.Thumbprint)" -ForegroundColor Green

# Export to local cert directory and workspace ARN_Cert
$localCer = "cert\ARN_Technology_Root.cer"
Export-Certificate -Cert $cert -FilePath $localCer -Type CERT -Force | Out-Null
Write-Host "  Exported root certificate to $localCer" -ForegroundColor Green

if (Test-Path "e:\مشاريعي\ARN_Cert") {
    Copy-Item -Force $localCer "e:\مشاريعي\ARN_Cert\ARN_Technology_Root.cer" -ErrorAction SilentlyContinue
}

# Auto-register certificate in developer's local user TrustedPublisher store (Rule 7)
try {
    $pubStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("TrustedPublisher", "CurrentUser")
    $pubStore.Open("ReadWrite")
    if (-not $pubStore.Certificates.Contains($cert)) {
        $pubStore.Add($cert)
        Write-Host "  Registered certificate in CurrentUser TrustedPublisher Store." -ForegroundColor Green
    } else {
        Write-Host "  Certificate already verified in TrustedPublisher Store." -ForegroundColor Green
    }
    $pubStore.Close()
} catch {
    Write-Warning "Could not register in CurrentUser store directly: $_"
}

# 3. Choose Python executable
$pythonExe = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python.exe" }
Write-Host "`n>>> [3/7] Using Python: $pythonExe" -ForegroundColor Cyan

# 4. Compile Host Server (ShutdownPanel.exe)
Write-Host "`n>>> [4/7] Compiling Host Server (ShutdownPanel.exe)..." -ForegroundColor Cyan
& $pythonExe -m PyInstaller --clean --noconfirm "ShutdownPanel.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed for ShutdownPanel.exe!"
}

$serverExe = "dist\ShutdownPanel.exe"
if (-not (Test-Path $serverExe)) {
    throw "Build artifact not found: $serverExe"
}
Write-Host "  Host Server compiled: $serverExe" -ForegroundColor Green

# 5. Compile Desktop Client (ShutdownPanelClient.exe)
Write-Host "`n>>> [5/7] Compiling Desktop Client (ShutdownPanelClient.exe)..." -ForegroundColor Cyan
& $pythonExe -m PyInstaller --clean --noconfirm "ShutdownPanelClient.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed for ShutdownPanelClient.exe!"
}

$clientExe = "dist\ShutdownPanelClient.exe"
if (-not (Test-Path $clientExe)) {
    throw "Build artifact not found: $clientExe"
}
Write-Host "  Remote Client compiled: $clientExe" -ForegroundColor Green

# Helper function for RFC-3161 Timestamped Digital Signing (Rule 7)
function Sign-Executable {
    param (
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        $Certificate
    )

    $tsServers = @(
        "http://timestamp.digicert.com",
        "http://timestamp.sectigo.com",
        "http://tsa.starfieldtech.com"
    )

    $signed = $false
    foreach ($server in $tsServers) {
        try {
            Write-Host "    Attempting timestamp server: $server ..." -ForegroundColor DarkGray
            $sig = Set-AuthenticodeSignature -Certificate $Certificate -FilePath $FilePath -TimestampServer $server -HashAlgorithm SHA256 -ErrorAction Stop
            if ($sig.Status -eq "Valid" -and $sig.TimeStamperCertificate -ne $null) {
                Write-Host "    Successfully signed with RFC-3161 timestamp ($server)." -ForegroundColor Green
                $signed = $true
                break
            }
        } catch {
            Write-Warning "    Timestamp server $server returned: $_"
        }
    }

    if (-not $signed) {
        Write-Warning "    All timestamp servers failed, signing without timestamp..."
        Set-AuthenticodeSignature -Certificate $Certificate -FilePath $FilePath -HashAlgorithm SHA256 | Out-Null
    }

    Unblock-File -Path $FilePath -ErrorAction SilentlyContinue
}

# 6. Digitally Sign Internal Executables
Write-Host "`n>>> [6/7] Digitally signing internal executables..." -ForegroundColor Cyan
@($serverExe, $clientExe) | ForEach-Object {
    $target = $_
    Write-Host "  Signing $target ..." -ForegroundColor Yellow
    Sign-Executable -FilePath $target -Certificate $cert
}

# 7. Compile and Sign Unified Setup Installer
Write-Host "`n>>> [7/7] Compiling unified installer with Inno Setup..." -ForegroundColor Cyan

$isccCandidates = @(
    "C:\Program Files\Inno Setup 7\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Antigravity IDE\resources\app\node_modules\innosetup\bin\ISCC.exe"
)

$isccPath = $null
foreach ($p in $isccCandidates) {
    if (Test-Path $p) {
        $isccPath = $p
        break
    }
}

if (-not $isccPath) {
    $whichIscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($whichIscc) {
        $isccPath = $whichIscc.Source
    }
}

if (-not $isccPath) {
    throw "Inno Setup compiler (ISCC.exe) not found!"
}

Write-Host "  Using Inno Setup compiler: $isccPath" -ForegroundColor DarkGray
& $isccPath "installer.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed!"
}

$setupExe = "dist\ShutdownPanel_Setup_v2.0.1.exe"
if (-not (Test-Path $setupExe)) {
    throw "Installer file not found at $setupExe!"
}

Write-Host "  Signing final setup installer: $setupExe ..." -ForegroundColor Yellow
Sign-Executable -FilePath $setupExe -Certificate $cert

# Distribute to releases directory e:\اصداراتي if present (Rule 7)
$releasesDir = "e:\اصداراتي"
if (Test-Path $releasesDir) {
    $destSetup = Join-Path $releasesDir (Split-Path $setupExe -Leaf)
    Copy-Item -Path $setupExe -Destination $destSetup -Force
    Unblock-File -Path $destSetup -ErrorAction SilentlyContinue
    Write-Host "  Copied signed installer to releases directory: $destSetup" -ForegroundColor Green
}


$serverSizeMB = [math]::Round((Get-Item $serverExe).Length / 1MB, 2)
$clientSizeMB = [math]::Round((Get-Item $clientExe).Length / 1MB, 2)
$setupSizeMB = [math]::Round((Get-Item $setupExe).Length / 1MB, 2)

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "  SHUTDOWN PANEL - PRODUCTION BUILD & SIGN COMPLETE! 🎉" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  1. Host Server:     $serverExe ($serverSizeMB MB)" -ForegroundColor Yellow
Write-Host "  2. Remote Client:   $clientExe ($clientSizeMB MB)" -ForegroundColor Yellow
Write-Host "  3. Setup Installer: $setupExe ($setupSizeMB MB)" -ForegroundColor Cyan
Write-Host "  4. Digital Cert:    $localCer (Thumbprint: $($cert.Thumbprint))" -ForegroundColor White
Write-Host "  5. Target System:   Windows 10 / 11 (64-bit)" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Green
