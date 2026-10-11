#!/usr/bin/env bash
set -euo pipefail
handler_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$handler_root"
printf '%s\n' 'Handler · Jev testing' 'Enter your API key privately. This test sends only three synthetic tasks.' 'Saving the key does not enable Jev for your chats or walks.' ''
if ! "$handler_root/.venv/bin/python" scripts/configure-jev.py; then
    printf '%s\n' 'Setup stopped. Press Enter to close.'
    read -r
    exit 1
fi
if "$handler_root/.venv/bin/python" scripts/jev-probe.py --run > artifacts/jev-routing-probe.json; then
    cat artifacts/jev-routing-probe.json
    printf '%s\n' '' 'Test saved. Jev remains disabled for your work.'
else
    rm -f artifacts/jev-routing-probe.json
    printf '%s\n' 'The test did not complete. Your key was not displayed.'
fi
printf '%s\n' 'Press Enter to close.'
read -r
