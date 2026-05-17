#!/bin/bash
set -e

# Always force the script to run from the project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "Building Inkify Agent Executable..."
if [ -d ".venv" ]; then
  source .venv/bin/activate
else
  echo "Warning: .venv not found. Make sure dependencies are installed globally or in your current environment."
fi

# Install PyInstaller if not present
pip install pyinstaller

# Build into a single binary, cleaning previous builds
pyinstaller --name inkify-agent --onefile --clean main.py

echo "Build complete! Executable is located in the dist/ folder."