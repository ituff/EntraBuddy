#!/usr/bin/env bash
# 把 EntraBuddy 打包成可双击的 .app
# 壳：PyObjC + WKWebView（原生窗口），后端：Python 标准库 HTTP 服务
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
APP="$DIST/EntraBuddy.app"
BUILD="$ROOT/.build"
VERSION="0.1.0"

if [ -n "${ENTRABUDDY_PYTHON:-}" ]; then
  PYTHON_BIN="$ENTRABUDDY_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi
if ! "$PYTHON_BIN" -c "import AppKit, WebKit" >/dev/null 2>&1; then
  echo "错误：$PYTHON_BIN 缺少 PyObjC。" >&2
  echo "请先执行：$PYTHON_BIN -m pip install pyobjc-framework-Cocoa pyobjc-framework-WebKit" >&2
  exit 1
fi

echo "==> 清理旧产物"
rm -rf "$APP" "$BUILD"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$BUILD"

echo "==> 写入启动脚本"
cat > "$APP/Contents/MacOS/EntraBuddy" <<LAUNCHER
#!/bin/bash
exec "$PYTHON_BIN" "$ROOT/desktop.py"
LAUNCHER
chmod +x "$APP/Contents/MacOS/EntraBuddy"

echo "==> 生成 Info.plist"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>EntraBuddy</string>
    <key>CFBundleDisplayName</key><string>EntraBuddy</string>
    <key>CFBundleIdentifier</key><string>com.entrabuddy.app</string>
    <key>CFBundleExecutable</key><string>EntraBuddy</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>${VERSION}</string>
    <key>CFBundleVersion</key><string>${VERSION}</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSPrincipalClass</key><string>NSApplication</string>
    <key>NSAppTransportSecurity</key>
    <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST

echo "==> 生成图标"
ICON_PNG="$BUILD/icon.png"
if [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
    --default-background-color=00000000 \
    --window-size=1024,1024 --screenshot="$ICON_PNG" \
    "file://$ROOT/desktop/icon.html" >/dev/null 2>&1 || true
fi

if [ -f "$ICON_PNG" ]; then
  ICONSET="$BUILD/AppIcon.iconset"
  mkdir -p "$ICONSET"
  for spec in "16 16x16" "32 16x16@2x" "32 32x32" "64 32x32@2x" \
              "128 128x128" "256 128x128@2x" "256 256x256" "512 256x256@2x" \
              "512 512x512" "1024 512x512@2x"; do
    set -- $spec
    sips -z "$1" "$1" "$ICON_PNG" --out "$ICONSET/icon_$2.png" >/dev/null 2>&1
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null || true
fi

echo "==> 临时签名"
codesign --force --sign - "$APP" >/dev/null 2>&1 || true

echo "==> 完成：$APP"
du -sh "$APP" | awk '{print "    体积：" $1}'
