# Đóng gói VideoAgent thành thư mục dist\VideoAgent (PyInstaller, onedir).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) { python -m venv .venv }
& .venv\Scripts\pip install -q -r requirements.txt pyinstaller

& .venv\Scripts\pyinstaller --noconfirm --clean --windowed `
    --name VideoAgent `
    --add-data "ui;ui" `
    --add-data "templates;templates" `
    --add-data "assets;assets" `
    --collect-all playwright `
    --collect-all edge_tts `
    --collect-all webview `
    --collect-data imageio_ffmpeg `
    main.py

Write-Host "Xong: dist\VideoAgent\VideoAgent.exe"
