$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

$python = "C:\windows\py.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

& $python -3 -m quant.stock_selector.daily_update
exit $LASTEXITCODE
