#!/usr/bin/env bash

# Uninstalls the Inkify Agent from a macOS system.

set -euo pipefail

PLIST_NAME="com.inkify.agent.plist"
PLIST_PATH="/Library/LaunchDaemons/$PLIST_NAME"
BINARY_PATH="/usr/local/bin/inkify-agent"

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run this script with sudo."
    exit 1
fi

echo "Uninstalling Inkify Agent..."

echo "Unloading macOS service..."

# Stop and unload the LaunchDaemon
if [ -f "$PLIST_PATH" ]; then
    echo "Stopping service..."
    launchctl unload -w "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
fi

# Remove binary
if [ -f "$BINARY_PATH" ]; then
    echo "Removing application binary..."
    rm -f "$BINARY_PATH"
fi

echo ""
read -r -p "Remove Inkify logs and data directories? [y/N]: " CONFIRM
if [[ "${CONFIRM,,}" == "y" ]]; then
    rm -rf /var/lib/inkify /var/log/inkify /etc/inkify
    echo "Data directories removed."
else
    echo "Data directories preserved at /var/lib/inkify, /var/log/inkify, /etc/inkify"
fi

echo ""
echo "Uninstall complete."