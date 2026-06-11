#!/usr/bin/env bash

# Builds the Inkify Agent into a single self-contained binary using PyInstaller.

set -euo pipefail

# Always force the script to run from the project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Use version from APP_VERSION env var, otherwise read from version.txt
VERSION="${APP_VERSION:-$(cat version.txt 2>/dev/null | tr -d '[:space:]' || echo "1.0.0")}"

# Ensure version.txt exists so PyInstaller --add-data doesn't fail
if [ ! -f "version.txt" ]; then
    echo "$VERSION" > version.txt
fi

echo "Building Inkify Agent v${VERSION}..."

# Activate virtual environment if present
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "   Using .venv"
elif [ -d "venv" ]; then
    source venv/bin/activate
    echo "   Using venv"
else
  echo "Warning: No virtual environment found. Make sure all the dependencies are installed."
fi

# Ensure PyInstaller is available
pip install pyinstaller --quiet

# Cleaning previous builds
rm -rf build/ dist/ inkify-agent.spec

echo "Building Inkify Agent Executable..."
# Build into a single binary
# Using `python -m PyInstaller` ensures we use the active environment's PyInstaller
python -m PyInstaller \
    --name inkify-agent \
    --onefile \
    --clean \
    --strip \
    --add-data "version.txt:." \
    main.py

echo "Binary built Completed: dist/inkify-agent"
echo "Size: $(du -sh dist/inkify-agent | cut -f1)"