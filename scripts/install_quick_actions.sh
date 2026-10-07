#!/usr/bin/env bash
set -euo pipefail

# Installs macOS Finder Quick Actions (Services) for Image Utilities.
# Users can right-click any image in Finder -> Quick Actions -> Remove Background or Upscale 4x.

SERVICES_DIR="$HOME/Library/Services"
mkdir -p "$SERVICES_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Installing macOS Finder Quick Actions for Image Utilities..."

# Helper to create a service workflow
create_quick_action() {
  local title="$1"
  local task="$2"
  local workflow_path="$SERVICES_DIR/$title.workflow"
  local contents_dir="$workflow_path/Contents"

  mkdir -p "$contents_dir"

  cat > "$contents_dir/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>NSIconName</key>
    <string>NSActionTemplate</string>
    <key>NSServices</key>
    <array>
        <dict>
            <key>NSBackgroundColorName</key>
            <string>background</string>
            <key>NSIconName</key>
            <string>NSActionTemplate</string>
            <key>NSMenuItem</key>
            <dict>
                <key>default</key>
                <string>$title</string>
            </dict>
            <key>NSMessage</key>
            <string>runWorkflowAsService</string>
            <key>NSRequiredContext</key>
            <dict>
                <key>NSApplicationIdentifier</key>
                <string>com.apple.finder</string>
            </dict>
            <key>NSSendFileTypes</key>
            <array>
                <string>public.image</string>
            </array>
        </dict>
    </array>
</dict>
</plist>
EOF

  cat > "$contents_dir/document.wflow" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>AMApplicationBuild</key>
    <string>523</string>
    <key>AMApplicationVersion</key>
    <string>2.10</string>
    <key>AMDocumentVersion</key>
    <string>2</string>
    <key>actions</key>
    <array>
        <dict>
            <key>action</key>
            <dict>
                <key>AMAccepts</key>
                <dict>
                    <key>Container</key>
                    <string>List</string>
                    <key>Types</key>
                    <array>
                        <string>com.apple.cocoa.path</string>
                    </array>
                </dict>
                <key>AMActionVersion</key>
                <string>2.0.3</string>
                <key>AMParameterProperties</key>
                <dict>
                    <key>COMMAND_STRING</key>
                    <dict/>
                </dict>
                <key>AMProvides</key>
                <dict>
                    <key>Container</key>
                    <string>List</string>
                    <key>Types</key>
                    <array>
                        <string>com.apple.cocoa.path</string>
                    </array>
                </dict>
                <key>ActionBundlePath</key>
                <string>/System/Library/Automator/Run Shell Script.action</string>
                <key>ActionName</key>
                <string>Run Shell Script</string>
                <key>ActionParameters</key>
                <dict>
                    <key>COMMAND_STRING</key>
                    <string>
ROOT="$ROOT_DIR"
URL_FILE="\$ROOT/var/app.url"

# Ensure server is running
if [ ! -f "\$URL_FILE" ]; then
  open -a "\$ROOT/Image Utilities.app" 2>/dev/null || (cd "\$ROOT" &amp;&amp; ./run.sh &amp;)
  sleep 2
fi

SERVER_URL=\$(cat "\$URL_FILE" 2>/dev/null || echo "http://127.0.0.1:8765")
JSON_PAYLOAD=\$(python3 -c "import sys, json; print(json.dumps({'paths': sys.argv[1:]}))" "\$@")

curl -s -X POST "\$SERVER_URL/api/open" \\
  -H "Content-Type: application/json" \\
  -d "\$JSON_PAYLOAD" &gt;/dev/null 2&gt;&amp;1 || true
</string>
                    <key>CheckedForUserDefaultShell</key>
                    <true/>
                    <key>inputMethod</key>
                    <integer>1</integer>
                    <key>shell</key>
                    <string>/bin/bash</string>
                    <key>source</key>
                    <string></string>
                </dict>
            </dict>
        </dict>
    </array>
</dict>
</plist>
EOF

  echo "✓ Created $title in $SERVICES_DIR"
}

create_quick_action "Remove Background with Image Utilities" "cutout"
create_quick_action "Upscale 4x with Image Utilities" "upscale"

echo ""
echo "🎉 Quick Actions installed! In Finder, right-click any image -> Quick Actions to use them."
