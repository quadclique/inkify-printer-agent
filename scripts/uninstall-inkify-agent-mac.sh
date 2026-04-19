#!/bin/bash
set -e

PLIST_NAME="com.inkify.agent.plist"
PLIST_PATH="/Library/LaunchDaemons/$PLIST_NAME"
BINARY_PATH="/usr/local/bin/inkify-agent"

if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run this script with sudo."
  exit 1
fi

echo "Unloading macOS service..."
if [ -f "$PLIST_PATH" ]; then
    launchctl unload -w "$PLIST_PATH" || true
    echo "Removing plist file..."
    rm -f "$PLIST_PATH"
fi

echo "Removing application binary..."
if [ -f "$BINARY_PATH" ]; then
    rm -f "$BINARY_PATH"
fi

echo "Uninstall complete."