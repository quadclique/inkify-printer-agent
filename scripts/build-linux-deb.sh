#!/bin/bash
set -e
VERSION="1.0.0"
PACKAGE_NAME="inkify-agent_${VERSION}_amd64"

echo "📦 Building Debian Package..."
mkdir -p "$PACKAGE_NAME/DEBIAN" "$PACKAGE_NAME/opt/inkify" "$PACKAGE_NAME/etc/systemd/system"
cp dist/inkify-agent "$PACKAGE_NAME/opt/inkify/"
cp system/linux/inkify-agent.service "$PACKAGE_NAME/etc/systemd/system/"

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
systemctl daemon-reload
systemctl enable inkify-agent.service
echo "Inkify Agent Installed. Open terminal and run: sudo inkify-agent"
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