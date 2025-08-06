#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APK_TOOLS_DIR="$(cd "$SCRIPT_DIR/../for-codex-alpine-apk-tools" && pwd)"

make -C "$APK_TOOLS_DIR" CFLAGS=-Wno-error >/dev/null

# Print path to built apk binary
echo "$APK_TOOLS_DIR/src/apk"
