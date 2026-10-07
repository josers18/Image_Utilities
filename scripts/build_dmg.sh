#!/usr/bin/env bash
set -euo pipefail

# Packages Image Utilities into a drag-to-Applications .dmg installer for macOS.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$ROOT_DIR/dist"
STAGING_DIR="$DIST_DIR/dmg_staging"
APP_BUNDLE="$ROOT_DIR/Image Utilities.app"
DMG_OUTPUT="$DIST_DIR/Image_Utilities.dmg"

echo "Building Image Utilities .dmg package..."

mkdir -p "$DIST_DIR"
rm -rf "$STAGING_DIR" "$DMG_OUTPUT"
mkdir -p "$STAGING_DIR"

# Ensure the native .app binary is compiled
if [ ! -f "$APP_BUNDLE/Contents/MacOS/Image Utilities" ]; then
  echo "Compiling native Swift launcher..."
  mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"
  swiftc -O "$ROOT_DIR/mac/main.swift" -o "$APP_BUNDLE/Contents/MacOS/Image Utilities"
fi

# Copy App to staging
echo "Copying application bundle..."
cp -R "$APP_BUNDLE" "$STAGING_DIR/"

# Create /Applications symlink
echo "Creating /Applications drag-and-drop link..."
ln -s /Applications "$STAGING_DIR/Applications"

# Build compressed DMG
echo "Generating DMG archive with hdiutil..."
hdiutil create \
  -volname "Image Utilities" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_OUTPUT"

# Cleanup staging
rm -rf "$STAGING_DIR"

SIZE=$(du -h "$DMG_OUTPUT" | cut -f1)
echo "✓ Successfully built: $DMG_OUTPUT ($SIZE)"
