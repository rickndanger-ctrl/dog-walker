#!/usr/bin/env bash
set -euo pipefail
app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v quickshell >/dev/null; then
  printf '%s\n' 'Handler needs Quickshell for its native desktop. The terminal interface is available with dog-walker demo.' >&2
  exit 1
fi
if quickshell ipc -p "$app_dir/native" call dogwalker open "${1:-}" >/dev/null 2>&1; then
  exit 0
fi
export DOG_WALKER_OPEN_FILE="${1:-}"
export DOG_WALKER_APP_ROOT="$app_dir"
export QT_QUICK_CONTROLS_STYLE=Basic
export QML_IMPORT_PATH="$app_dir/.runtime/qml${QML_IMPORT_PATH:+:$QML_IMPORT_PATH}"
exec quickshell -d -n -p "$app_dir/native"
