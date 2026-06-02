#!/bin/bash

# ── Go to the folder this script lives in ──────────────────────────────────────
cd "$(dirname "$0")"

echo "=============================="
echo "  Pawffinated – First Time Setup"
echo "=============================="

# ── Install Homebrew if missing ────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for Apple Silicon
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi

eval "$(/opt/homebrew/bin/brew shellenv)"

# ── Install Python if missing ──────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "Installing Python..."
    brew install python@3.11
fi

# ── Install Python dependencies ────────────────────────────────────────────────
echo "Installing required packages..."
pip3 install PyQt6 psycopg2-binary python-dotenv

# ── Create the desktop launcher (.command file on Desktop) ────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCHER="$HOME/Desktop/Pawffinated.command"

cat > "$LAUNCHER" << EOF
#!/bin/bash
cd "$SCRIPT_DIR"
eval "\$(/opt/homebrew/bin/brew shellenv)"
python3 "$SCRIPT_DIR/Login.py"
EOF

chmod +x "$LAUNCHER"

# ── Give it a coffee cup icon using AppleScript ───────────────────────────────
ICON_PATH="$SCRIPT_DIR/app_logo.png"
if [ -f "$ICON_PATH" ]; then
osascript << APPLESCRIPT
use framework "Foundation"
use framework "AppKit"

set iconPath to "$ICON_PATH"
set launcherPath to "$LAUNCHER"

set theImage to current application's NSImage's alloc()'s initWithContentsOfFile:iconPath
current application's NSWorkspace's sharedWorkspace()'s setIcon:theImage forFile:launcherPath options:0
APPLESCRIPT
fi

echo ""
echo "✅ Done! A 'Pawffinated' icon has been placed on the Desktop."
echo "   Double-click it anytime to open the app."
echo ""
read -p "Press Enter to close this window..."