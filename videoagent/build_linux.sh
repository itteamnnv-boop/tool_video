#!/usr/bin/env bash
# Đóng gói VideoAgent cho Ubuntu / Debian (chạy TRÊN MÁY LINUX hoặc GitHub Actions — PyInstaller không build chéo):
#   1) PyInstaller → dist/VideoAgent/ (cửa sổ app dùng Qt WebEngine — đóng gói kèm, không cần GTK / WebKit của máy)
#   2) dpkg-deb    → dist/videoagent_<phiên bản>_<amd64|arm64>.deb
# Cài: sudo apt install ./videoagent_*.deb  → menu ứng dụng có "VideoAgent", hoặc gõ lệnh: videoagent
# Gỡ:  sudo apt remove videoagent
# Dữ liệu người dùng nằm ở ~/.config/VideoAgent — KHÔNG đóng gói, gỡ app không xoá.
# Build trên Ubuntu cũ nhất muốn hỗ trợ (glibc) — bản build trên 22.04 chạy được trên 22.04 / 24.04.
# Tuỳ chọn: ./build_linux.sh --skip-deb  (chỉ build dist/VideoAgent)
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then "$PY" -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt pyinstaller

VERSION=$(python -c 'import re,pathlib; print(re.search(r"__version__\s*=\s*\"([^\"]+)\"", pathlib.Path("app/__init__.py").read_text()).group(1))')
ARCH=$(dpkg --print-architecture)
echo "VideoAgent $VERSION · Linux $ARCH"

# pythonnet / clr_loader (WebView2 của Windows) không dùng trên Linux — pywebview dùng Qt (qtpy → PyQt6)
pyinstaller --noconfirm --clean --windowed \
  --name VideoAgent \
  --python-option "X utf8" \
  --add-data "ui:ui" \
  --add-data "templates:templates" \
  --add-data "assets:assets" \
  --collect-all playwright \
  --collect-all edge_tts \
  --collect-all webview \
  --collect-all yt_dlp \
  --collect-all curl_cffi \
  --collect-all qtpy \
  --collect-data imageio_ffmpeg \
  --hidden-import PyQt6.QtWebEngineWidgets \
  --hidden-import PyQt6.QtWebEngineCore \
  --hidden-import PyQt6.QtWebChannel \
  --hidden-import PyQt6.QtNetwork \
  --hidden-import PyQt6.QtSvg \
  main.py

# ffmpeg / driver Playwright đóng gói kèm phải chạy được
find dist/VideoAgent -type f \( -name "ffmpeg-*" -o -name "node" \) -exec chmod +x {} + || true
echo "Xong: dist/VideoAgent"

if [ "${1:-}" = "--skip-deb" ]; then exit 0; fi
echo "== Tạo .deb"
PKG=build/deb/videoagent
rm -rf build/deb && mkdir -p "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/usr/share/applications" \
  "$PKG/usr/share/icons/hicolor/256x256/apps"
cp -a dist/VideoAgent "$PKG/opt/videoagent"
ln -s /opt/videoagent/VideoAgent "$PKG/usr/bin/videoagent"
python - "$PKG/usr/share/icons/hicolor/256x256/apps/videoagent.png" <<'EOF'
import sys
from PIL import Image
with Image.open("assets/logo.png") as im:
    im = im.convert("RGBA")
    im.thumbnail((256, 256))
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    canvas.paste(im, ((256 - im.width) // 2, (256 - im.height) // 2))
    canvas.save(sys.argv[1])
EOF
cat > "$PKG/usr/share/applications/videoagent.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VideoAgent
Comment=Tạo video ngắn bằng AI
Exec=/opt/videoagent/VideoAgent
Icon=videoagent
Terminal=false
Categories=AudioVideo;Video;
StartupWMClass=VideoAgent
EOF
SIZE=$(du -sk "$PKG" | cut -f1)
# thư viện hệ thống Qt WebEngine (Chromium) + xcb cần — Qt / Python đã đóng gói kèm
cat > "$PKG/DEBIAN/control" <<EOF
Package: videoagent
Version: $VERSION
Section: video
Priority: optional
Architecture: $ARCH
Maintainer: VideoAgent <noreply@videoagent.local>
Installed-Size: $SIZE
Depends: libc6 (>= 2.35), libnss3, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-image0,
 libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-shape0, libxcb-xinerama0, libxcb-xkb1, libxcomposite1,
 libxdamage1, libxrandr2, libxtst6, libegl1, libgl1, libfontconfig1, libdbus-1-3, libasound2 | libasound2t64,
 xdg-utils
Recommends: google-chrome-stable | chromium | chromium-browser, nodejs
Description: VideoAgent - tạo video ngắn bằng AI
 Ứng dụng tạo ảnh, video, hậu kỳ và đăng bài bằng AI (Canvas, Studio, Muse).
 Dữ liệu người dùng lưu ở ~/.config/VideoAgent.
EOF
cat > "$PKG/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true
exit 0
EOF
cp "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"
DEB="dist/videoagent_${VERSION}_${ARCH}.deb"
rm -f "$DEB"
dpkg-deb --build --root-owner-group -Zxz "$PKG" "$DEB"
dpkg-deb --info "$DEB" | head -20
echo "Xong bộ cài: $DEB"
