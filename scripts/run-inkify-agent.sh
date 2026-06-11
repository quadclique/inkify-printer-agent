#!/usr/bin/env bash

# Runs the Inkify Agent from source.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Starting Inkify Agent..."
cd "$PROJECT_ROOT"

# Activate virtualenv
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Virtual environment not found. Please run install.sh first."
    exit 1
fi

export ENVIRONMENT="${ENVIRONMENT:-development}"
export AGENT_LOG_LEVEL="${AGENT_LOG_LEVEL:-DEBUG}"

python main.py "$@"