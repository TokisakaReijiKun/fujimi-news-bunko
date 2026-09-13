param([int]$Port = 8427)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
conda run --no-capture-output -n Tokyo python -X utf8 server.py --port $Port
