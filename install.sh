#!/bin/bash

set -e  # Exit on any error

# Get absolute path to repo directory
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
VENV_DIR="${REPO_DIR}/venv"

echo "Setting up Whisper Hotkey from ${REPO_DIR}..."

# Install system dependencies
echo "Installing system dependencies..."
sudo apt install -y python3-gi gir1.2-gtk-3.0 python3-keybinder \
    gir1.2-keybinder-3.0 xdotool python3-gi-cairo gir1.2-appindicator3-0.1

# Create and activate venv
echo "Creating Python virtual environment..."
python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r "${REPO_DIR}/requirements.txt"

# Create systemd user directory if it doesn't exist
mkdir -p ~/.config/systemd/user/

# Generate systemd service file
echo "Generating systemd service file..."
cat > ~/.config/systemd/user/whisper-client.service << EOF
[Unit]
Description=Whisper Speech-to-Text Client
After=graphical-session.target

[Service]
Type=simple
Environment=PYTHONPATH=${VENV_DIR}/lib/python3.10/site-packages
ExecStart=${VENV_DIR}/bin/python ${REPO_DIR}/whisper_hotkey.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF

# Enable and start service
echo "Enabling and starting systemd service..."
systemctl --user daemon-reload
systemctl --user enable whisper-client
systemctl --user start whisper-client

echo "Setup complete! The whisper-client service should now be running."
echo "Check status with: systemctl --user status whisper-client"