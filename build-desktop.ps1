param(
    [string]$Version = 'dev',
    [string]$OutputDirectory = 'dist'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$distPath = Join-Path $PSScriptRoot $OutputDirectory
$workPath = Join-Path $PSScriptRoot ("build/desktop-{0}" -f $Version)

$dictionary = Join-Path $PSScriptRoot 'apk-original/dictionary/dictionary.sqlite3'
$static = Join-Path $PSScriptRoot 'static'
$icon = Join-Path $PSScriptRoot 'assets/desktop.ico'
$trayIcon = Join-Path $PSScriptRoot 'assets/desktop-icon.png'
if (-not (Test-Path -LiteralPath $dictionary -PathType Leaf)) {
    throw '缺少 apk-original/dictionary/dictionary.sqlite3，无法制作可用的桌面包。'
}
if (-not (Test-Path -LiteralPath $trayIcon -PathType Leaf)) {
    throw '缺少 assets/desktop-icon.png，无法制作托盘图标。'
}

conda run -n Tokyo python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name FujimiShinbunBunko `
    --specpath build `
    --distpath $distPath `
    --workpath $workPath `
    --collect-data pykakasi `
    --collect-submodules edge_tts `
    --exclude-module torch `
    --exclude-module torchaudio `
    --exclude-module torchvision `
    --exclude-module scipy `
    --exclude-module onnxruntime `
    --exclude-module onnxruntime_genai `
    --exclude-module kokoro `
    --exclude-module voicevox_core `
    --hidden-import pystray._win32 `
    --icon $icon `
    --add-data "$trayIcon;assets" `
    --add-data "$static;static" `
    --add-data "$dictionary;apk-original/dictionary" `
    desktop.py
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller 构建失败。'
}

$output = Join-Path $distPath 'FujimiShinbunBunko'
$kanjiDictionary = Join-Path $output '_internal/pykakasi/data/kanwadict4.db'
if (-not (Test-Path -LiteralPath $kanjiDictionary -PathType Leaf)) {
    throw '打包后缺少 pykakasi 假名字典，桌面程序无法启动。'
}

$archive = Join-Path $PSScriptRoot ("dist/FujimiShinbunBunko-{0}-windows-x64.zip" -f $Version)
if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}
Compress-Archive -LiteralPath $output -DestinationPath $archive -CompressionLevel Optimal

Write-Host '已生成 dist/FujimiShinbunBunko/FujimiShinbunBunko.exe'
Write-Host ("已生成 {0}" -f $archive)
