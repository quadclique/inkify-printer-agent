#!/bin/bash
set -e
VERSION="1.0.0"
PACKAGE_NAME="inkify-agent_${VERSION}_amd64"

echo "📦 Building Debian Package..."
mkdir -p "$PACKAGE_NAME/DEBIAN" "$PACKAGE_NAME/opt/inkify" "$PACKAGE_NAME/etc/systemd/system"
cp dist/inkify-agent "$PACKAGE_NAME/opt/inkify/"
cp system/linux/inkify-agent.service "$PACKAGE_NAME/etc/systemd/system/"

# Replace the template variables with the root user for the system service
sed -i 's/{{USER}}/root/g' "$PACKAGE_NAME/etc/systemd/system/inkify-agent.service"
sed -i 's/{{GROUP}}/root/g' "$PACKAGE_NAME/etc/systemd/system/inkify-agent.service"
cat <<EOF > "$PACKAGE_NAME/DEBIAN/control"
Package: inkify-agent
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Maintainer: Inkify
Description: Inkify Printer Agent Background Service.
EOF

cat <<EOF > "$PACKAGE_NAME/DEBIAN/postinst"
#!/bin/bash
chmod +x /opt/inkify/inkify-agent

# Create a symlink so the user can type 'inkify-agent' anywhere in the terminal
ln -sf /opt/inkify/inkify-agent /usr/local/bin/inkify-agent

# Safely stop the service if an older version is already running before modifying variables
systemctl stop inkify-agent.service 2>/dev/null || true

systemctl daemon-reload
systemctl enable inkify-agent.service

# --no-block so dpkg doesn't hang waiting for your polling loop to finish
systemctl start inkify-agent.service --no-block

echo "Inkify Agent Installed running in the background."
exit 0
EOF
chmod +x "$PACKAGE_NAME/DEBIAN/postinst"

cat <<EOF > "$PACKAGE_NAME/DEBIAN/prerm"
#!/bin/bash
systemctl stop inkify-agent.service 2>/dev/null || true
systemctl disable inkify-agent.service 2>/dev/null || true
exit 0
EOF
chmod +x "$PACKAGE_NAME/DEBIAN/prerm"

dpkg-deb --build "$PACKAGE_NAME"