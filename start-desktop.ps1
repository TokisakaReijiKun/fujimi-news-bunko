param([int]$Port = 8428)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
conda run --no-capture-output -n Tokyo python -X utf8 desktop.py --port $Port
