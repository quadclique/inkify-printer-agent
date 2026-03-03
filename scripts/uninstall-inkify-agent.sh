#!/bin/bash
set -e

SERVICE_NAME="inkify-agent.service"

if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run this script with sudo."
  exit 1
fi

echo "Stopping service..."
systemctl stop "$SERVICE_NAME" || true

echo "Disabling service..."
systemctl disable "$SERVICE_NAME" || true

echo "Removing systemd file..."
rm -f "/etc/systemd/system/$SERVICE_NAME"

echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Uninstall complete. (Note: The Python virtual environment and logs were kept intact)."