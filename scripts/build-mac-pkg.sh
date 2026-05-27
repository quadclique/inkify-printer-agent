#!/bin/bash
# build-mac-pkg.sh — Builds a signed macOS .pkg installer for the Inkify Agent.
#
# Usage:
#   ./scripts/build-mac-pkg.sh                    # Generic installer (user must paste token)
#   ./scripts/build-mac-pkg.sh --token tkn_abc123 # Token pre-filled for automatic pairing
#
set -e

VERSION="${APP_VERSION:-$(cat version.txt 2>/dev/null || echo "1.0.0")}"
REGISTRATION_TOKEN=""

# --- Parse Arguments ---
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --token) REGISTRATION_TOKEN="$2"; shift ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

echo "🍏 Building Inkify Agent macOS Package v${VERSION}..."

# --- Create Payload Directory Structure ---
rm -rf build_mac
mkdir -p \
    build_mac/payload/usr/local/bin \
    build_mac/payload/Library/LaunchDaemons \
    build_mac/payload/var/log/inkify \
    build_mac/payload/etc/inkify \
    build_mac/scripts

# --- Copy Binary ---
if [ ! -f dist/inkify-agent ]; then
    echo "❌ Error: dist/inkify-agent not found. Run build-inkify-agent.sh first."
    exit 1
fi
cp dist/inkify-agent build_mac/payload/usr/local/bin/

# --- Copy LaunchDaemon plist ---
cp system/mac/com.inkify.agent.plist build_mac/payload/Library/LaunchDaemons/

# --- Embed Registration Token (if provided) ---
if [ -n "$REGISTRATION_TOKEN" ]; then
    echo "🔑 Embedding registration token into package..."
    cat > build_mac/payload/etc/inkify/inkify-registration.env <<EOF
REGISTRATION_TOKEN=${REGISTRATION_TOKEN}
EOF
    chmod 600 build_mac/payload/etc/inkify/inkify-registration.env
else
    echo "⚠️  No token provided. The installed agent will require manual pairing."
fi

# --- Generate postinstall Script ---
cat > build_mac/scripts/postinstall <<'POSTINSTALL'
#!/bin/bash
set -e

# Fix permissions
chmod +x /usr/local/bin/inkify-agent
chown root:wheel /Library/LaunchDaemons/com.inkify.agent.plist
chmod 644 /Library/LaunchDaemons/com.inkify.agent.plist

# Ensure log and config directories exist with correct ownership
mkdir -p /var/log/inkify /var/lib/inkify /etc/inkify
chown -R root:wheel /var/log/inkify /var/lib/inkify /etc/inkify

# --- Automatic Pairing (if registration env file is present) ---
ENV_FILE="/etc/inkify/inkify-registration.env"
if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
    if [ -n "$REGISTRATION_TOKEN" ]; then
        echo "Inkify: Performing automatic secure pairing..."
        /usr/local/bin/inkify-agent --pair-only --token "$REGISTRATION_TOKEN" || true
        # Clean up the token file immediately after use for security
        rm -f "$ENV_FILE"
    fi
fi

# --- Load the LaunchDaemon (starts agent as background service) ---
launchctl load -w /Library/LaunchDaemons/com.inkify.agent.plist

echo "Inkify Agent installed and started successfully."
exit 0
POSTINSTALL
chmod +x build_mac/scripts/postinstall

# --- Generate preinstall Script (stops any running agent before upgrade) ---
cat > build_mac/scripts/preinstall <<'PREINSTALL'
#!/bin/bash
# Gracefully unload any existing agent before installing the new version
if launchctl list | grep -q "com.inkify.agent"; then
    launchctl unload /Library/LaunchDaemons/com.inkify.agent.plist 2>/dev/null || true
fi
exit 0
PREINSTALL
chmod +x build_mac/scripts/preinstall

# --- Build the .pkg ---
echo "📦 Packaging..."
pkgbuild \
    --root build_mac/payload \
    --scripts build_mac/scripts \
    --identifier com.inkify.agent \
    --version "$VERSION" \
    --install-location / \
    "InkifyAgent_v${VERSION}.pkg"

echo "✅ Build complete: InkifyAgent_v${VERSION}.pkg"
if [ -n "$REGISTRATION_TOKEN" ]; then
    echo "   Token embedded — installer will auto-pair on first launch."
else
    echo "   No token embedded — user must manually paste a registration token."
fi