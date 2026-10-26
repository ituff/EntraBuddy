#!/usr/bin/env bash
# 把 EntraBuddy 打包成可双击、可分发的 .app
#
# 应用代码 + Python 运行时 + PyObjC 全部打进 Contents/Resources，
# 目标机器不需要预装任何东西。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
APP="$DIST/EntraBuddy.app"
BUILD="$ROOT/.build"
VERSION="${ENTRABUDDY_VERSION:-0.1.0}"

if [ -n "${ENTRABUDDY_PYTHON:-}" ]; then
  PYTHON_BIN="$ENTRABUDDY_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [ -z "${PYTHON_BIN:-}" ] || ! "$PYTHON_BIN" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then
  echo "错误：构建需要 Python 3.9 或更高版本。" >&2
  exit 1
fi

PY_PREFIX="$("$PYTHON_BIN" -c 'import sys; print(sys.base_prefix)')"
PY_VER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "==> 构建环境：Python $PY_VER ($PY_PREFIX)"

echo "==> 清理旧产物"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"
mkdir -p "$BUILD"

echo "==> 复制应用代码"
cp "$ROOT/app.py" "$ROOT/desktop_mac.py" "$APP/Contents/Resources/app/"
cp -R "$ROOT/entrabuddy" "$APP/Contents/Resources/app/"
cp -R "$ROOT/web" "$APP/Contents/Resources/app/"
find "$APP/Contents/Resources/app" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$APP/Contents/Resources/app" -name "*.pyc" -delete 2>/dev/null || true

echo "==> 复制 Python 运行时"
PY_DEST="$APP/Contents/Resources/python"
rsync -a --exclude '__pycache__' "$PY_PREFIX/" "$PY_DEST/"
# 精简：去掉与 GUI 无关且体积可观的部分
rm -rf "$PY_DEST/lib/python$PY_VER/idlelib" \
       "$PY_DEST/lib/python$PY_VER/tkinter" \
       "$PY_DEST/lib/python$PY_VER/ensurepip" \
       "$PY_DEST/lib/python$PY_VER/test" \
       "$PY_DEST/lib/libtcl"*.dylib \
       "$PY_DEST/lib/libtk"*.dylib \
       "$PY_DEST/lib/itcl"* \
       "$PY_DEST/include" \
       "$PY_DEST/share/man" 2>/dev/null || true
find "$PY_DEST" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "==> 安装 PyObjC 到运行时"
PYOBJC_STAGE="$BUILD/pyobjc"
if [ ! -d "$PYOBJC_STAGE" ]; then
  "$PYTHON_BIN" -m pip install --quiet --no-cache-dir --target "$PYOBJC_STAGE" \
    "pyobjc-framework-Cocoa>=9.0" "pyobjc-framework-WebKit>=9.0"
fi
SITE="$PY_DEST/lib/python$PY_VER/site-packages"
mkdir -p "$SITE"
rsync -a --exclude '__pycache__' "$PYOBJC_STAGE/" "$SITE/"

echo "==> 写入启动脚本"
cat > "$APP/Contents/MacOS/EntraBuddy" <<'LAUNCHER'
#!/bin/bash
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HERE/../Resources/app"
BUNDLED_PY="$HERE/../Resources/python/bin/python3"

if [ -x "$BUNDLED_PY" ] && "$BUNDLED_PY" -c "import AppKit, WebKit" 2>/dev/null; then
  exec "$BUNDLED_PY" "$APP_DIR/desktop_mac.py"
fi

# 回退：用系统 Python（需要用户自行安装 PyObjC）
for py in "${ENTRABUDDY_PYTHON:-}" "/opt/homebrew/bin/python3" "/usr/local/bin/python3" "/usr/bin/python3"; do
  [ -x "$py" ] || continue
  if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null \
     && "$py" -c "import AppKit, WebKit" 2>/dev/null; then
    exec "$py" "$APP_DIR/desktop_mac.py"
  fi
done

osascript -e 'display dialog "EntraBuddy 内置运行时损坏或架构不匹配。\n\n如果是 Apple Silicon 以外的机型，请从源码构建：\n  git clone https://github.com/ituff/EntraBuddy.git\n  cd EntraBuddy && ./desktop/build_app.sh" with title "无法启动 EntraBuddy" buttons {"好"} default button 1 with icon caution' >/dev/null 2>&1
exit 1
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
  rm -rf "$ICONSET"; mkdir -p "$ICONSET"
  for spec in "16 16x16" "32 16x16@2x" "32 32x32" "64 32x32@2x" \
              "128 128x128" "256 128x128@2x" "256 256x256" "512 256x256@2x" \
              "512 512x512" "1024 512x512@2x"; do
    set -- $spec
    sips -z "$1" "$1" "$ICON_PNG" --out "$ICONSET/icon_$2.png" >/dev/null 2>&1
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null || true
fi

echo "==> 临时签名"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true

echo "==> 完成：$APP"
du -sh "$APP" | awk '{print "    体积：" $1}'
