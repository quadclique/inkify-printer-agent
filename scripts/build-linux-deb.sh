#!/bin/bash
# build-linux-deb.sh — Builds a .deb package for the Inkify Agent.
#
# Usage:
#   ./scripts/build-linux-deb.sh                    # Generic package (manual pairing)
#   ./scripts/build-linux-deb.sh --token tkn_abc123 # Auto-pairs on first install
#
set -e

VERSION="${APP_VERSION:-$(cat version.txt 2>/dev/null || echo "1.0.0")}"
PACKAGE_NAME="inkify-agent_${VERSION}_amd64"
REGISTRATION_TOKEN=""

# --- Parse Arguments ---
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --token) REGISTRATION_TOKEN="$2"; shift ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

echo "📦 Building Inkify Agent Debian Package v${VERSION}..."
rm -rf "$PACKAGE_NAME"

mkdir -p \
    "$PACKAGE_NAME/DEBIAN" \
    "$PACKAGE_NAME/opt/inkify" \
    "$PACKAGE_NAME/etc/systemd/system" \
    "$PACKAGE_NAME/var/lib/inkify" \
    "$PACKAGE_NAME/var/log/inkify" \
    "$PACKAGE_NAME/etc/inkify"

# --- Copy Files ---
if [ ! -f dist/inkify-agent ]; then
    echo "❌ Error: dist/inkify-agent not found. Run build-inkify-agent.sh first."
    exit 1
fi
cp dist/inkify-agent "$PACKAGE_NAME/opt/inkify/"
cp system/linux/inkify-agent.service "$PACKAGE_NAME/etc/systemd/system/"

# Replace service user/group template placeholders with dedicated service account
sed -i 's/{{USER}}/inkify/g' "$PACKAGE_NAME/etc/systemd/system/inkify-agent.service"
sed -i 's/{{GROUP}}/inkify/g' "$PACKAGE_NAME/etc/systemd/system/inkify-agent.service"

# --- Embed Registration Token (if provided) ---
if [ -n "$REGISTRATION_TOKEN" ]; then
    echo "🔑 Embedding registration token into package..."
    cat > "$PACKAGE_NAME/etc/inkify/inkify-registration.env" <<EOF
REGISTRATION_TOKEN=${REGISTRATION_TOKEN}
EOF
    chmod 600 "$PACKAGE_NAME/etc/inkify/inkify-registration.env"
else
    echo "⚠️  No token provided. The installed agent will require manual pairing."
fi

# --- DEBIAN Control File ---
cat <<EOF > "$PACKAGE_NAME/DEBIAN/control"
Package: inkify-agent
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: cups
Maintainer: Inkify <support@inkify.in>
Description: Inkify Printer Agent Background Service.
 Connects local printers to the Inkify Cloud Platform.
 Runs as a systemd service and auto-discovers USB and network printers.
EOF

# --- DEBIAN postinst ---
cat > "$PACKAGE_NAME/DEBIAN/postinst" <<'POSTINST'
#!/bin/bash
set -e

# Create dedicated system user (no login shell, no home dir)
if ! id -u inkify &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin inkify
fi

# Make inkify user a member of lp group so it can access CUPS
usermod -aG lp inkify 2>/dev/null || true

chmod +x /opt/inkify/inkify-agent

# Symlink for convenience
ln -sf /opt/inkify/inkify-agent /usr/local/bin/inkify-agent

# Secure ownership on state directories
chown -R inkify:inkify /var/lib/inkify /etc/inkify /var/log/inkify
chmod 750 /var/lib/inkify /etc/inkify /var/log/inkify

# Stop any old running version before upgrading
systemctl stop inkify-agent.service 2>/dev/null || true

# --- Automatic Pairing (if registration env file is present) ---
ENV_FILE="/etc/inkify/inkify-registration.env"
if [ -f "$ENV_FILE" ]; then
    # Source the token (runs as root here — pairing writes creds to /etc/inkify/)
    set -a; source "$ENV_FILE"; set +a
    if [ -n "$REGISTRATION_TOKEN" ]; then
        echo "Inkify: Performing automatic secure pairing..."
        /opt/inkify/inkify-agent --pair-only --token "$REGISTRATION_TOKEN" || true
        # Delete immediately after use
        rm -f "$ENV_FILE"
    fi
fi

# --- Start systemd Service ---
systemctl daemon-reload
systemctl enable inkify-agent.service
systemctl start inkify-agent.service --no-block

echo "Inkify Agent installed and running in the background."
exit 0
POSTINST
chmod +x "$PACKAGE_NAME/DEBIAN/postinst"

# --- DEBIAN prerm (clean uninstall) ---
cat > "$PACKAGE_NAME/DEBIAN/prerm" <<'PRERM'
#!/bin/bash
systemctl stop inkify-agent.service 2>/dev/null || true
systemctl disable inkify-agent.service 2>/dev/null || true
exit 0
PRERM
chmod +x "$PACKAGE_NAME/DEBIAN/prerm"

# --- Build .deb ---
dpkg-deb --build "$PACKAGE_NAME"

echo "✅ Build complete: ${PACKAGE_NAME}.deb"
if [ -n "$REGISTRATION_TOKEN" ]; then
    echo "   Token embedded — package will auto-pair on install."
else
    echo "   No token embedded — user must manually paste a registration token."
fi