#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "=========================================="
echo "  Installing Inkify Printer Agent"
echo "=========================================="

# 1. Ensure the script is run with sudo/root privileges
if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run this script with sudo."
  exit 1
fi

# 2. Identify the absolute paths and the target user
# We get the directory where the script is located, then go up one level to the project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# If run via sudo, $SUDO_USER is the actual human user. Otherwise, fallback to root.
TARGET_USER="${SUDO_USER:-root}"
TARGET_GROUP=$(id -g -n "$TARGET_USER")

echo "Project Root: $PROJECT_ROOT"
echo "Installing for User: $TARGET_USER"

# 3. Setup Python Virtual Environment
echo "Setting up Python virtual environment..."
sudo -u "$TARGET_USER" python3 -m venv "$PROJECT_ROOT/.venv"

# 4. Install Requirements
echo "Installing dependencies..."
sudo -u "$TARGET_USER" "$PROJECT_ROOT/.venv/bin/pip" install --upgrade pip
if [ -f "$PROJECT_ROOT/requirements.txt" ]; then
    sudo -u "$TARGET_USER" "$PROJECT_ROOT/.venv/bin/pip" install -r "$PROJECT_ROOT/requirements.txt"
else
    echo "Warning: No requirements.txt found. Skipping pip install."
fi

# 5. Configure systemd service
SERVICE_NAME="inkify-agent.service"
TEMPLATE_FILE="$PROJECT_ROOT/system/linux/$SERVICE_NAME"
SYSTEMD_DIR="/etc/systemd/system"
TARGET_SERVICE_FILE="$SYSTEMD_DIR/$SERVICE_NAME"

echo "Configuring systemd service..."

if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "Error: Service template not found at $TEMPLATE_FILE"
    exit 1
fi

# Copy the template to a temporary file
TMP_SERVICE="/tmp/$SERVICE_NAME"
cp "$TEMPLATE_FILE" "$TMP_SERVICE"

# Inject the dynamic variables using sed
sed -i "s|{{USER}}|$TARGET_USER|g" "$TMP_SERVICE"
sed -i "s|{{GROUP}}|$TARGET_GROUP|g" "$TMP_SERVICE"
sed -i "s|{{WORKING_DIR}}|$PROJECT_ROOT|g" "$TMP_SERVICE"

# Move to the systemd directory and set permissions
mv "$TMP_SERVICE" "$TARGET_SERVICE_FILE"
chmod 644 "$TARGET_SERVICE_FILE"

# 6. Enable and Start the Service
echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling service to start on boot..."
systemctl enable "$SERVICE_NAME"

echo "Starting the service..."
systemctl restart "$SERVICE_NAME"

echo "=========================================="
echo "  Installation Complete! 🚀"
echo "=========================================="
echo "To check the agent status, run: sudo systemctl status $SERVICE_NAME"
echo "To view live logs, run: journalctl -u $SERVICE_NAME -f"