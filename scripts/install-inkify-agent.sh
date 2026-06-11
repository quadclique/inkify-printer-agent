#!/usr/bin/env bash

# Sets up a local development environment for the Inkify Agent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "Setting up Inkify Agent development environment..."

# Create virtual environment
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Created .venv"
fi
source .venv/bin/activate

# Upgrade pip silently
pip install --upgrade pip --quiet

# Install dependencies
pip install -r requirements-dev.txt --quiet
echo "Dependencies installed"

# Copy .env if not present
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Created .env from .env.example (edit API_URL if needed)"
fi

echo ""
echo "Dev environment ready."
echo "Activate:  source .venv/bin/activate"
echo "Run agent: ./scripts/run-inkify-agent.sh --token <tkn>"
echo "Run tests: pytest"
