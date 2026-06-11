#!/usr/bin/env bash

# Builds a Debian (.deb) package for the Inkify Agent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

VERSION="${APP_VERSION:-$(cat version.txt 2>/dev/null | tr -d '[:space:]' || echo "1.0.0")}"
PACKAGE_NAME="inkify-agent_${VERSION}_amd64"
REGISTRATION_TOKEN=""

# Parse Arguments
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --token) REGISTRATION_TOKEN="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

echo "Building Inkify Agent Debian Package v${VERSION}..."

# Create package tree
rm -rf "${PACKAGE_NAME}"

mkdir -p \
    "${PACKAGE_NAME}/DEBIAN" \
    "${PACKAGE_NAME}/opt/inkify" \
    "${PACKAGE_NAME}/etc/systemd/system" \
    "${PACKAGE_NAME}/var/lib/inkify" \
    "${PACKAGE_NAME}/var/log/inkify" \
    "${PACKAGE_NAME}/etc/inkify"

# Verify binary
if [ ! -f "dist/inkify-agent" ]; then
    echo "File 'dist/inkify-agent' not found. Run scripts/build-inkify-agent.sh first."
    exit 1
fi

# Copy files
cp dist/inkify-agent "$PACKAGE_NAME/opt/inkify/"
cp system/linux/inkify-agent.service "$PACKAGE_NAME/etc/systemd/system/"
cp dist/inkify-agent "${PACKAGE_NAME}/opt/inkify/"
cp system/linux/inkify-agent.service "${PACKAGE_NAME}/etc/systemd/system/"

# Substitute service account placeholders
sed -i "s/{{USER}}/inkify/g"  "${PACKAGE_NAME}/etc/systemd/system/inkify-agent.service"
sed -i "s/{{GROUP}}/inkify/g" "${PACKAGE_NAME}/etc/systemd/system/inkify-agent.service"

# Embed registration token (optional)
if [ -n "${REGISTRATION_TOKEN}" ]; then
    echo "Embedding registration token into package..."
    cat > "${PACKAGE_NAME}/etc/inkify/inkify-registration.env" <<EOF
REGISTRATION_TOKEN=${REGISTRATION_TOKEN}
EOF
    chmod 600 "${PACKAGE_NAME}/etc/inkify/inkify-registration.env"
else
    echo "No token provided. The installed agent will require manual pairing."
fi

# DEBIAN Control File
cat > "${PACKAGE_NAME}/DEBIAN/control" <<EOF
Package: inkify-agent
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: amd64
Depends: cups
Recommends: python3-psutil
Maintainer: Inkify <support@inkify.in>
Homepage: https://inkify.in
Description: Inkify Printer Agent Background Service.
 Connects USB and network printers to the Inkify Cloud Platform.
 Runs as a systemd service and auto-discovers USB and network printers.
EOF

# DEBIAN postinst
cat > "${PACKAGE_NAME}/DEBIAN/postinst" <<'POSTINST'
#!/bin/bash
set -e

# Create dedicated service account (no login, no home dir)
if ! id -u inkify &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin inkify
    echo "Created system user: inkify"
fi

# Make inkify user a member of lp group so it can access CUPS
usermod -aG lp inkify 2>/dev/null || true

# Mark binary executable and create system symlink
chmod +x /opt/inkify/inkify-agent

# Symlink for convenience
ln -sf /opt/inkify/inkify-agent /usr/local/bin/inkify-agent

# Secure ownership on state directories
chown -R inkify:inkify /var/lib/inkify /etc/inkify /var/log/inkify
chmod 750 /var/lib/inkify /etc/inkify /var/log/inkify

# Stop any old running version before upgrading
systemctl stop inkify-agent.service 2>/dev/null || true

# Automatic Pairing (if registration env file is present)
ENV_FILE="/etc/inkify/inkify-registration.env"
if [ -f "$ENV_FILE" ]; then
    # Source the token (runs as root here — pairing writes creds to /etc/inkify/)

    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    if [ -n "${REGISTRATION_TOKEN:-}" ]; then
        echo "Inkify: Performing automatic secure pairing..."
        /opt/inkify/inkify-agent \
            --token "$REGISTRATION_TOKEN" \
            --pair-only || true
        # Delete immediately after use
        rm -f "$ENV_FILE"
    fi
fi

# Enable and Start the systemd service
systemctl daemon-reload
systemctl enable inkify-agent.service
systemctl start inkify-agent.service --no-block

echo ""
echo "Inkify Agent installed and running in the background."
echo "View logs: journalctl -u inkify-agent -f"
echo "Status: systemctl status inkify-agent"
exit 0
POSTINST
chmod +x "${PACKAGE_NAME}/DEBIAN/postinst"

# DEBIAN prerm (clean uninstall)
cat > "$PACKAGE_NAME/DEBIAN/prerm" <<'PRERM'

#!/bin/bash
systemctl stop inkify-agent.service 2>/dev/null || true
systemctl disable inkify-agent.service 2>/dev/null || true
exit 0
PRERM
chmod +x "${PACKAGE_NAME}/DEBIAN/prerm"

# DEBIAN/postrm (clean up user + dirs on purge)
cat > "${PACKAGE_NAME}/DEBIAN/postrm" <<'POSTRM'
#!/bin/bash
if [ "$1" = "purge" ]; then
    # Remove service account
    userdel inkify 2>/dev/null || true
    # Remove runtime directories (logs are kept unless explicitly purged)
    rm -rf /var/lib/inkify /etc/inkify
fi
exit 0
POSTRM
chmod +x "${PACKAGE_NAME}/DEBIAN/postrm"

# Build the (.deb) Package 
dpkg-deb --build "${PACKAGE_NAME}"
rm -rf "${PACKAGE_NAME}"  # Clean up staging dir

echo ""
echo "Build complete: ${PACKAGE_NAME}.deb"
if [ -n "${REGISTRATION_TOKEN}" ]; then
    echo "   Token embedded — package will auto-pair on install."
else
    echo "   No token embedded — user must manually paste a registration token."
fi