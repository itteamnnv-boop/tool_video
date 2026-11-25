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

# Dựng từ VideoAgent.spec (1 nguồn duy nhất: thư viện collect_all, hiddenimports, icon, UTF-8…). KHÔNG truyền tham số
# PyInstaller ở đây — chạy kiểu "pyinstaller ... main.py" sẽ ghi đè spec và làm rơi thư viện (VD claude-agent-sdk).
& .venv\Scripts\pyinstaller --noconfirm --clean VideoAgent.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller lỗi" }
Write-Host "Xong: dist\VideoAgent\VideoAgent.exe"

# Tự kiểm bản build: nạp mọi thư viện + claude.exe đi kèm SDK + ffmpeg. Thiếu → dừng, không ra bộ cài hỏng.
$check = Join-Path $env:TEMP "videoagent_selfcheck.txt"
Remove-Item $check -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "dist\VideoAgent\VideoAgent.exe" -ArgumentList "--selfcheck", "`"$check`"" -Wait -PassThru
if (Test-Path $check) { Get-Content $check -Encoding utf8 | Write-Host }
if ($p.ExitCode -ne 0 -or -not (Test-Path $check)) { throw "Tự kiểm bản build lỗi (xem danh sách FAIL ở trên)" }
Write-Host "Tự kiểm: OK"
if ($SkipInstaller) { return }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Chưa có Inno Setup 6 — cài: winget install JRSoftware.InnoSetup" }
& $iscc "/DAppVersion=$version" installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup lỗi" }
Write-Host "Xong bộ cài: dist\installer\VideoAgent-Setup-$version.exe"
