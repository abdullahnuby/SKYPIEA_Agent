$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "إنشاء البيئة الافتراضية..." -ForegroundColor Cyan
    py -m venv .venv
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "تثبيت المتطلبات..." -ForegroundColor Cyan
& $python -m pip install --upgrade pip --quiet
& $python -m pip install -r requirements.txt --quiet

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "تم إنشاء .env — عدّله وحط التوكن والمفتاح، وبعدها شغّل: .\run.ps1" -ForegroundColor Yellow
    exit 0
}

Write-Host "تشغيل الـ Agent..." -ForegroundColor Green
& $python -m agent.main
