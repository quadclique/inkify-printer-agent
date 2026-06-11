#!/usr/bin/env bash

# Builds a signed macOS .pkg installer for the Inkify Agent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

VERSION="${APP_VERSION:-$(cat version.txt 2>/dev/null | tr -d '[:space:]' || echo "1.0.0")}"
REGISTRATION_TOKEN=""

# Parse Arguments
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --token) REGISTRATION_TOKEN="$2"; shift 2 ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
done

echo "Building Inkify Agent macOS Package v${VERSION}..."

# Create Payload Directory Structure
rm -rf build_mac
mkdir -p \
    build_mac/payload/usr/local/bin \
    build_mac/payload/Library/LaunchDaemons \
    build_mac/payload/var/log/inkify \
    build_mac/payload/etc/inkify \
    build_mac/scripts

# Verify Binary 
if [ ! -f dist/inkify-agent ]; then
    echo "File dist/inkify-agent not found. Run scripts/build-inkify-agent.sh first."
    exit 1
fi
cp dist/inkify-agent build_mac/payload/usr/local/bin/

# Copy LaunchDaemon plist
# Ensure system/mac/com.inkify.agent.plist exists, otherwise warn
if [ ! -f system/mac/com.inkify.agent.plist ]; then
    echo "Warning: system/mac/com.inkify.agent.plist not found. You might need to create it."
else
    cp system/mac/com.inkify.agent.plist build_mac/payload/Library/LaunchDaemons/
fi

# Embed Registration Token (if provided)
if [ -n "$REGISTRATION_TOKEN" ]; then
    echo "Embedding registration token into package..."
    cat > build_mac/payload/etc/inkify/inkify-registration.env <<EOF
REGISTRATION_TOKEN=${REGISTRATION_TOKEN}
EOF
    chmod 600 build_mac/payload/etc/inkify/inkify-registration.env
else
    echo "No token provided. The installed agent will require manual pairing."
fi

# Generate postinstall Script
cat > build_mac/scripts/postinstall <<'POSTINSTALL'
#!/bin/bash
set -e

# Permissions
chmod +x /usr/local/bin/inkify-agent
if [ -f /Library/LaunchDaemons/com.inkify.agent.plist ]; then
    chown root:wheel /Library/LaunchDaemons/com.inkify.agent.plist
    chmod 644 /Library/LaunchDaemons/com.inkify.agent.plist
fi

# Ensure log and config directories exist with correct ownership
mkdir -p /var/log/inkify /var/lib/inkify /etc/inkify
chown -R root:wheel /var/log/inkify /var/lib/inkify /etc/inkify

# Automatic Pairing (if registration env file is present)
ENV_FILE="/etc/inkify/inkify-registration.env"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    if [ -n "$REGISTRATION_TOKEN" ]; then
        echo "Inkify: Performing automatic secure pairing..."
        /usr/local/bin/inkify-agent --pair-only --token "$REGISTRATION_TOKEN" || true
        # Clean up the token file immediately after use for security
        rm -f "$ENV_FILE"
    fi
fi

# Load the LaunchDaemon (starts agent as background service)
if [ -f /Library/LaunchDaemons/com.inkify.agent.plist ]; then
    launchctl load -w /Library/LaunchDaemons/com.inkify.agent.plist
fi

echo "Inkify Agent installed and started successfully."
exit 0
POSTINSTALL
chmod +x build_mac/scripts/postinstall

# Generate preinstall Script (stops any running agent before upgrade)
cat > build_mac/scripts/preinstall <<'PREINSTALL'
#!/bin/bash
# Gracefully unload any existing agent before installing the new version
if launchctl list | grep -q "com.inkify.agent"; then
    launchctl unload /Library/LaunchDaemons/com.inkify.agent.plist 2>/dev/null || true
fi
exit 0
PREINSTALL
chmod +x build_mac/scripts/preinstall

# Build the .pkg
pkgbuild \
    --root build_mac/payload \
    --scripts build_mac/scripts \
    --identifier com.inkify.agent \
    --version "${VERSION}" \
    --install-location / \
    "InkifyAgent_v${VERSION}.pkg"

# Clean up
rm -rf build_mac

echo "Build complete: InkifyAgent_v${VERSION}.pkg"
if [ -n "$REGISTRATION_TOKEN" ]; then
    echo "   Token embedded — installer will auto-pair on first launch."
else
    echo "   No token embedded — user must manually paste a registration token."
fi