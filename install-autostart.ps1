# تسجيل الـ Agent عشان يشتغل تلقائيًا عند تسجيل الدخول
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$taskName = "DeviceAgent"
$script = Join-Path $PSScriptRoot "run.ps1"

if (-not (Test-Path $script)) {
    throw "مش لاقي run.ps1 في $PSScriptRoot"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $PSScriptRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Agent محلي بيتحكم من تيليجرام" `
    -Force | Out-Null

Write-Host "✅ تم تسجيل المهمة '$taskName' — هتشتغل مع كل تسجيل دخول." -ForegroundColor Green
Write-Host "للتشغيل الآن:  Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor Cyan
Write-Host "للإلغاء:        Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false" -ForegroundColor Cyan
