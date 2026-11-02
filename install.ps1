# Atlas server installer — Windows laptop with the RTX 2060.
#
# Run in PowerShell, in this folder:
#     Set-ExecutionPolicy -Scope Process Bypass
#     .\install.ps1
#
# This makes THIS machine the model server. The MacBook connects to it over
# your local network. Nothing is exposed to the internet.
#
# What it does:
#   1. downloads a portable Ollama into .\vendor\ollama (no system install)
#   2. starts it bound to 0.0.0.0 on port 11434
#   3. pulls a model that fits in 6 GB of VRAM
#   4. opens the firewall for the private network only
#   5. prints the LAN address to paste into the MacBook's .env

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Model = if ($env:ATLAS_MODEL) { $env:ATLAS_MODEL } else { "qwen2.5:7b" }
$Vendor = Join-Path $PSScriptRoot "vendor\ollama"
$Exe    = Join-Path $Vendor "ollama.exe"

Write-Host "`n=== 1/5 portable ollama ===" -ForegroundColor Cyan
if (-not (Test-Path $Exe)) {
    New-Item -ItemType Directory -Force -Path $Vendor | Out-Null
    $zip = Join-Path $PSScriptRoot "vendor\ollama-windows-amd64.zip"
    Write-Host "downloading (~1.6 GB, one time)…"
    Invoke-WebRequest -Uri "https://ollama.com/download/ollama-windows-amd64.zip" -OutFile $zip
    Write-Host "extracting…"
    Expand-Archive -Path $zip -DestinationPath $Vendor -Force
    Remove-Item $zip
} else {
    Write-Host "already present"
}

Write-Host "`n=== 2/5 start server on 0.0.0.0:11434 ===" -ForegroundColor Cyan
# Persist for future sessions. Local network only — never port-forward this.
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")
$env:OLLAMA_HOST = "0.0.0.0:11434"

$running = Get-Process ollama -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "ollama already running — restarting it to apply OLLAMA_HOST"
    $running | Stop-Process -Force
    Start-Sleep -Seconds 2
}
Start-Process -FilePath $Exe -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 5

Write-Host "`n=== 3/5 model ($Model) ===" -ForegroundColor Cyan
& $Exe pull $Model

Write-Host "`n=== 4/5 firewall (private network only) ===" -ForegroundColor Cyan
$rule = "Atlas Ollama (LAN)"
if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $rule -Direction Inbound -LocalPort 11434 `
        -Protocol TCP -Action Allow -Profile Private | Out-Null
    Write-Host "rule created"
} else {
    Write-Host "rule already exists"
}

Write-Host "`n=== 5/5 address for the MacBook ===" -ForegroundColor Cyan
$ip = (Get-NetIPAddress -AddressFamily IPv4 |
       Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
       Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "  Put this in ~/dev/atlas/.env on the MacBook:" -ForegroundColor Yellow
Write-Host "  ATLAS_BASE_URL=http://${ip}:11434/v1"
Write-Host "  ATLAS_MODEL=$Model"
Write-Host ""
Write-Host "Test from the MacBook:  curl http://${ip}:11434/api/version"
Write-Host ""
Write-Host "Keep this machine awake while you use Atlas:" -ForegroundColor DarkGray
Write-Host "  powercfg /change standby-timeout-ac 0"
