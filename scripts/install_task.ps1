# 一键注册 Windows 任务计划程序（每天 08:00 自动补跑 PaperFlow）
# 关键：StartWhenAvailable 确保关机错过后开机自动补跑

param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "PaperFlow_Daily_Fetch",
    [string]$RunTime = "08:00"
)

$scriptPath = Join-Path $PSScriptRoot "run_daily_fetch.ps1"
if (-not (Test-Path $scriptPath)) {
    Write-Error "找不到 run_daily_fetch.ps1: $scriptPath"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ProjectRoot `"$ProjectRoot`""

$trigger = New-ScheduledTaskTrigger -Daily -At $RunTime

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

# 若已存在则先卸载
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已卸载旧任务: $TaskName"
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "PaperFlow 2026 每日论文采集与队列导出（含关机补跑）" | Out-Null

Write-Host "✓ 已注册定时任务 '$TaskName'，每天 $RunTime 执行；开机补跑已启用。"
Write-Host "  查看任务: Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
