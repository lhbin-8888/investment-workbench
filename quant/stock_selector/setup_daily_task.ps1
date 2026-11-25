$ErrorActionPreference = "Stop"

$taskName = "Touyan_StockSelector_Daily"
$runner = Join-Path $PSScriptRoot "run_daily_update.ps1"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

if (-not (Test-Path -LiteralPath $runner)) {
  throw "Daily update runner not found: $runner"
}

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`"" `
  -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger `
  -Weekly `
  -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
  -At "16:40"

$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
  -MultipleInstances IgnoreNew

Register-ScheduledTask `
  -TaskName $taskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Update the stock selector every weekday at 16:40 and publish only when content changes." `
  -Force | Out-Null

Write-Host "Scheduled task registered: $taskName"
Write-Host "Schedule: Monday-Friday 16:40"
Write-Host "Runner: $runner"
