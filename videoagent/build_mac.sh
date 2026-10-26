#!/usr/bin/env bash
# Đóng gói VideoAgent cho macOS (chạy TRÊN MÁY MAC hoặc GitHub Actions — PyInstaller không build chéo từ Windows):
#   1) PyInstaller → dist/VideoAgent.app
#   2) hdiutil     → dist/VideoAgent-<phiên bản>-macOS-<arm64|x86_64>.dmg (kéo app vào Applications để cài)
# Bản CHƯA KÝ Apple: lần đầu mở → chuột phải VideoAgent → Mở (hoặc Cài đặt hệ thống → Quyền riêng tư & Bảo mật → Vẫn mở).
# Dữ liệu người dùng nằm ở ~/Library/Application Support/VideoAgent — KHÔNG đóng gói.
# Tuỳ chọn: ./build_mac.sh --skip-dmg  (chỉ build dist/VideoAgent.app)
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then "$PY" -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt pyinstaller

VERSION=$(python -c 'import re,pathlib; print(re.search(r"__version__\s*=\s*\"([^\"]+)\"", pathlib.Path("app/__init__.py").read_text()).group(1))')
ARCH=$(uname -m)
echo "VideoAgent $VERSION · macOS $ARCH"

# pythonnet / clr_loader (WebView2 của Windows) không dùng trên macOS — pywebview dùng WebKit (pyobjc)
pyinstaller --noconfirm --clean --windowed \
  --name VideoAgent \
  --icon assets/icon.ico \
  --osx-bundle-identifier vn.itnnv.videoagent \
  --python-option "X utf8" \
  --add-data "ui:ui" \
  --add-data "templates:templates" \
  --add-data "assets:assets" \
  --collect-all playwright \
  --collect-all edge_tts \
  --collect-all webview \
  --collect-all yt_dlp \
  --collect-all curl_cffi \
  --collect-data imageio_ffmpeg \
  main.py

PLIST="dist/VideoAgent.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 12.0" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$PLIST" 2>/dev/null || true

# ffmpeg / driver Playwright đóng gói kèm phải chạy được
find dist/VideoAgent.app -type f \( -name "ffmpeg-*" -o -name "node" \) -exec chmod +x {} + || true
# ký ad-hoc (không cần tài khoản Apple) — macOS chip M bắt buộc mọi file chạy phải có chữ ký
codesign --force --deep --sign - dist/VideoAgent.app
echo "Xong: dist/VideoAgent.app"

if [ "${1:-}" = "--skip-dmg" ]; then exit 0; fi
STAGE=build/dmg
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R dist/VideoAgent.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="dist/VideoAgent-$VERSION-macOS-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -volname "VideoAgent $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "Xong bộ cài: $DMG"
