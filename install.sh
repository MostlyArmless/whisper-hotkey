#!/bin/bash
set -e  # Exit on any error

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/whisper-hotkey"
AUTOSTART_DIR="$HOME/.config/autostart"

echo "Installing required system packages..."
# Only use sudo for apt commands
sudo apt update
sudo apt install -y \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-3.0 \
    gir1.2-keybinder-3.0 \
    xdotool \
    libgirepository1.0-dev \
    pkg-config \
    libcairo2-dev \
    python3-dev \
    python3-venv \
    dbus-x11

echo "Creating installation directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$AUTOSTART_DIR"

echo "Creating launcher script..."
cat > "$INSTALL_DIR/launcher.sh" << 'EOL'
#!/bin/bash

# Check if already running
if pgrep -f "python.*whisper_hotkey.py" > /dev/null; then
    exit 0
fi

# Directory where the script is installed
INSTALL_DIR="$HOME/.local/share/whisper-hotkey"
VENV_DIR="$INSTALL_DIR/venv"
SCRIPT="$INSTALL_DIR/whisper_hotkey.py"

# Ensure virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    # Create venv without pip to ensure we use system-wide packages
    python3 -m venv "$VENV_DIR" --system-site-packages
    source "$VENV_DIR/bin/activate"
    # Install dependencies while allowing system-wide access
    pip install --ignore-installed -r "$INSTALL_DIR/requirements.txt"
else
    source "$VENV_DIR/bin/activate"
fi

# Run the script
exec python "$SCRIPT"
EOL

chmod +x "$INSTALL_DIR/launcher.sh"

echo "Creating desktop entry..."
cat > "$AUTOSTART_DIR/whisper-hotkey.desktop" << EOL
[Desktop Entry]
Type=Application
Name=Whisper Hotkey
Exec=$INSTALL_DIR/launcher.sh
Icon=audio-input-microphone
Categories=Utility;
X-GNOME-Autostart-enabled=true
EOL

echo "Setting up symlinks for python files..."
ln -sf "$SCRIPT_DIR/whisper_hotkey.py" "$INSTALL_DIR/whisper_hotkey.py"
ln -sf "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/requirements.txt"

echo "Setting up keyboard shortcut..."
# Ensure dbus session is available
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    eval `dbus-launch --sh-syntax`
fi

gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/whisper-hotkey/']"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/whisper-hotkey/ name "Whisper Hotkey"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/whisper-hotkey/ command "$INSTALL_DIR/launcher.sh"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/whisper-hotkey/ binding "XF86Favorites"

echo "Installation complete! The app will:"
echo "1. Start automatically on login"
echo "2. Can be started manually with the Favorites key"
echo "3. Use the Favorites key to toggle recording once running"
echo ""
echo "You can start it now by pressing the Favorites key or running:"
echo "$INSTALL_DIR/launcher.sh"
echo ""
echo "To debug keyboard binding, run: xev | grep keycode"
echo "Then press the Favorites key to see if it's detected"