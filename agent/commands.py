"""أوامر PowerShell مشتركة بين المهارات والموديل."""

from __future__ import annotations

DISK_CMD = (
    "Get-PSDrive -PSProvider FileSystem | "
    "Select-Object Name,"
    "@{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}},"
    "@{n='UsedGB';e={[math]::Round($_.Used/1GB,1)}} | "
    "Format-Table -AutoSize"
)

RAM_CMD = (
    "$os=Get-CimInstance Win32_OperatingSystem; "
    "'RAM كلية: {0:N1} GB | مستخدمة: {1:N1} GB | متاحة: {2:N1} GB' -f "
    "($os.TotalVisibleMemorySize/1MB), "
    "(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/1MB), "
    "($os.FreePhysicalMemory/1MB)"
)

PROCS_CMD = (
    "Get-Process | Sort-Object CPU -Descending | Select-Object -First 8 "
    "Name,CPU,@{n='RAM_MB';e={[math]::Round($_.WorkingSet64/1MB)}} | "
    "Format-Table -AutoSize"
)

BATTERY_CMD = (
    "Get-CimInstance Win32_Battery | "
    "Select-Object EstimatedChargeRemaining,BatteryStatus | Format-List"
)

IP_CMD = (
    "Get-NetIPAddress -AddressFamily IPv4 | "
    "Where-Object {$_.IPAddress -ne '127.0.0.1'} | "
    "Select-Object IPAddress,InterfaceAlias | Format-Table -AutoSize"
)

LOCK_CMD = 'rundll32.exe user32.dll,LockWorkStation; "تم قفل الجهاز"'
