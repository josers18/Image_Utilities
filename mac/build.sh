#!/bin/bash
# Rebuild the double-clickable Mac app next to this repo.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
APP="$ROOT/Image Utilities.app"
ICONSET="$(mktemp -d /tmp/image-utilities-icon.XXXXXX)"
trap 'rm -rf "$ICONSET"' EXIT

"$ROOT/.venv/bin/python" - "$ICONSET/AppIcon.iconset" <<'PY'
import sys
from pathlib import Path
from PIL import Image, ImageDraw

out = Path(sys.argv[1])
out.mkdir(parents=True)

def draw(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    radius = size * 0.223
    pen.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=(26, 24, 22, 255))
    margin = size * (6 / 32)
    edge = size * (20 / 32)
    stroke = max(2, round(size * (2 / 32)))
    pen.rounded_rectangle(
        (margin, margin, margin + edge, margin + edge),
        radius=size * (2 / 32),
        outline=(226, 181, 106, 255),
        width=stroke,
    )
    fill_at = size * (11 / 32)
    fill = size * (10 / 32)
    pen.rounded_rectangle(
        (fill_at, fill_at, fill_at + fill, fill_at + fill),
        radius=max(1, size * (1 / 32)),
        fill=(226, 181, 106, 255),
    )
    return image

sizes = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}
for name, size in sizes.items():
    draw(size).save(out / name)
PY

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
iconutil -c icns "$ICONSET/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
printf 'APPL????' > "$APP/Contents/PkgInfo"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>launch</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>local.jose.image-utilities</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Image Utilities</string>
  <key>CFBundleDisplayName</key>
  <string>Image Utilities</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>14.0</string>
  <key>LSMultipleInstancesProhibited</key>
  <true/>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key>
      <string>Image</string>
      <key>CFBundleTypeRole</key>
      <string>Viewer</string>
      <key>LSHandlerRank</key>
      <string>Alternate</string>
      <key>LSItemContentTypes</key>
      <array>
        <string>public.image</string>
      </array>
      <key>CFBundleTypeExtensions</key>
      <array>
        <string>jpg</string>
        <string>jpeg</string>
        <string>png</string>
        <string>webp</string>
        <string>tif</string>
        <string>tiff</string>
        <string>heic</string>
        <string>gif</string>
        <string>bmp</string>
        <string>avif</string>
      </array>
    </dict>
  </array>
</dict>
</plist>
PLIST

swiftc -swift-version 5 -O -framework AppKit -o "$APP/Contents/MacOS/launch" "$ROOT/mac/main.swift"
chmod +x "$APP/Contents/MacOS/launch"
codesign --force --sign - --identifier local.jose.image-utilities "$APP"
lsregister="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [[ -x "$lsregister" ]]; then
  "$lsregister" -f "$APP"
fi
echo "Built $APP"
