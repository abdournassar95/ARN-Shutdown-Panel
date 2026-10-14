# UTF-8
param()

$SourceDir = $PSScriptRoot + "\dist"
$DestDir = "C:\Program Files\ARN Technology\Shutdown Panel"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " ARN Technology - Shutdown Panel Updater" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Kill any running instances
Write-Host "1. Closing any running instances..." -ForegroundColor Yellow
Get-Process -Name 'ShutdownPanel*' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

# 2. Check destination
if (-not (Test-Path -Path $DestDir)) {
    Write-Host "Error: Installation directory not found: $DestDir" -ForegroundColor Red
    Start-Sleep -Seconds 3
    exit 1
}

# 3. Copy files
try {
    Write-Host "2. Copying updated files to Program Files..." -ForegroundColor Yellow
    Copy-Item -Path "$SourceDir\ShutdownPanel.exe" -Destination "$DestDir\ShutdownPanel.exe" -Force
    Unblock-File -Path "$DestDir\ShutdownPanel.exe" -ErrorAction SilentlyContinue
    Write-Host "   - Copied ShutdownPanel.exe successfully." -ForegroundColor Green
    
    if (Test-Path "$SourceDir\ShutdownPanelClient.exe") {
        Copy-Item -Path "$SourceDir\ShutdownPanelClient.exe" -Destination "$DestDir\ShutdownPanelClient.exe" -Force
        Unblock-File -Path "$DestDir\ShutdownPanelClient.exe" -ErrorAction SilentlyContinue
        Write-Host "   - Copied ShutdownPanelClient.exe successfully." -ForegroundColor Green
    }
    
    Write-Host "`nAll files updated successfully!" -ForegroundColor Cyan
    Start-Sleep -Seconds 1
} catch {
    Write-Host "Failed to copy files: $_" -ForegroundColor Red
    Start-Sleep -Seconds 3
    exit 1
}
