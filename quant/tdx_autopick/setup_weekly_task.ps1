# 注册「通达信周线选股」计划任务（每天 15:30 触发周线选股器）
# ============================================================
# 本文件在【本机】用 PowerShell（建议管理员）运行一次即可；之后每天自动跑。
# 周线选股器 weekly_picker.py 零网络依赖，读本地日线聚合周线，写入「AI周线」板块。
# 用 pythonw.exe 静默运行（不弹黑窗）；异常写入 weekly_YYYYMMDD.log 便于排查。
# 删除任务：schtasks /delete /tn "通达信周线选股" /f
# ============================================================
$ErrorActionPreference = "Stop"

$py     = "C:\Users\73873\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
$script = "D:\投研工作台\quant\tdx_autopick\weekly_picker.py"
$wd     = "D:\投研工作台\quant\tdx_autopick"

if (-not (Test-Path $script)) {
    Write-Host "[ERROR] Cannot find $script"
    exit 1
}

# 先删旧版（若已存在），避免重复注册
$old = Get-ScheduledTask -TaskName "通达信周线选股" -ErrorAction SilentlyContinue
if ($old) {
    Unregister-ScheduledTask -TaskName "通达信周线选股" -Confirm:$false
    Write-Host "[清理] 已删除旧版 通达信周线选股"
}

$action   = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $wd
$trigger  = New-ScheduledTaskTrigger -Daily -At "15:30"
$settings = New-ScheduledTaskSettingsSet `
               -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
               -StartWhenAvailable `
               -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName "通达信周线选股" `
    -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "OK 计划任务 通达信周线选股 已注册（每天 15:30 静默跑周线选股器，写入 AI周线）"
