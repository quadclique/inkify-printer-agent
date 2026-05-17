#!/bin/bash
set -e
VERSION="1.0.0"

echo "🍏 Building Mac Package..."
mkdir -p build_mac/payload/usr/local/bin build_mac/payload/Library/LaunchDaemons build_mac/scripts
cp dist/inkify-agent build_mac/payload/usr/local/bin/
cp system/mac/com.inkify.agent.plist build_mac/payload/Library/LaunchDaemons/

cat <<EOF > build_mac/scripts/postinstall
#!/bin/bash
chmod +x /usr/local/bin/inkify-agent
chown root:wheel /Library/LaunchDaemons/com.inkify.agent.plist
chmod 644 /Library/LaunchDaemons/com.inkify.agent.plist
launchctl load -w /Library/LaunchDaemons/com.inkify.agent.plist
exit 0
EOF
chmod +x build_mac/scripts/postinstall

pkgbuild --root build_mac/payload --scripts build_mac/scripts --identifier com.inkify.agent --version "$VERSION" "InkifyAgent_v${VERSION}.pkg"