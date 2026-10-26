# Đóng gói VideoAgent:
#   1) PyInstaller (onedir) → dist\VideoAgent\VideoAgent.exe
#   2) Inno Setup → dist\installer\VideoAgent-Setup-<phiên bản>.exe (bộ cài cho máy khác)
# Dữ liệu người dùng (profile trình duyệt, tài khoản, cài đặt, token) nằm ở %APPDATA%\VideoAgent — KHÔNG đóng gói:
# máy cài mới phải đăng nhập lại các tài khoản trình duyệt (Muse, ChatGPT, Grok, Gemini…) và Facebook.
# Tuỳ chọn: .\build.ps1 -SkipInstaller  (chỉ build thư mục dist\VideoAgent)
param([switch]$SkipInstaller)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) { python -m venv .venv }
& .venv\Scripts\pip install -q -r requirements.txt pyinstaller

$version = (Select-String -Path "app\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$parts = ($version.Split(".") + @("0", "0", "0", "0"))[0..3] -join ", "
New-Item -ItemType Directory -Force build | Out-Null
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts), prodvers=($parts)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'ITNNV'),
      StringStruct('FileDescription', 'VideoAgent'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', 'VideoAgent'),
      StringStruct('OriginalFilename', 'VideoAgent.exe'),
      StringStruct('ProductName', 'VideoAgent'),
      StringStruct('ProductVersion', '$version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Encoding utf8 build\version_info.txt

& .venv\Scripts\pyinstaller --noconfirm --clean --windowed `
    --name VideoAgent `
    --icon assets\icon.ico `
    --version-file build\version_info.txt `
    --python-option "X utf8" `
    --add-data "ui;ui" `
    --add-data "templates;templates" `
    --add-data "assets;assets" `
    --collect-all playwright `
    --collect-all edge_tts `
    --collect-all webview `
    --collect-all pythonnet `
    --collect-all clr_loader `
    --collect-all yt_dlp `
    --collect-all curl_cffi `
    --collect-data imageio_ffmpeg `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller lỗi" }
Write-Host "Xong: dist\VideoAgent\VideoAgent.exe"
if ($SkipInstaller) { return }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Chưa có Inno Setup 6 — cài: winget install JRSoftware.InnoSetup" }
& $iscc "/DAppVersion=$version" installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup lỗi" }
Write-Host "Xong bộ cài: dist\installer\VideoAgent-Setup-$version.exe"
