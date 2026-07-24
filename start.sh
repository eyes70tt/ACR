#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "=== Starting NFC Web Manager ==="
source venv/bin/activate
cd backend
exec python3 server.py
