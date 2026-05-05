#!/bin/bash
set -e

echo "Building Inkify Agent Executable..."
source .venv/bin/activate

# Install PyInstaller if not present
pip install pyinstaller

# Build into a single binary, cleaning previous builds
pyinstaller --name inkify-agent --onefile --clean main.py

echo "Build complete! Executable is located in the dist/ folder."