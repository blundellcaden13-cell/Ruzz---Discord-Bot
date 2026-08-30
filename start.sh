#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found. Install Python 3.11+ from https://www.python.org/downloads/"
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "Creating venv..."
    python3 -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate

REQ_HASH_FILE="venv/.requirements.hash"
if command -v shasum >/dev/null 2>&1; then
    CURRENT_HASH=$(shasum -a 256 requirements.txt | awk '{print $1}')
elif command -v sha256sum >/dev/null 2>&1; then
    CURRENT_HASH=$(sha256sum requirements.txt | awk '{print $1}')
else
    CURRENT_HASH="no-hash-tool"
fi

if [ ! -f "$REQ_HASH_FILE" ] || [ "$(cat "$REQ_HASH_FILE" 2>/dev/null)" != "$CURRENT_HASH" ]; then
    echo "Installing dependencies..."
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    echo "$CURRENT_HASH" > "$REQ_HASH_FILE"
else
    echo "Dependencies up to date."
fi

python launcher.py
