#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export PATH="$ROOT/bin:$PATH"
export PUENTE_ROOT="$TMP/bridge"
puente version | grep -q 'puente '
puente --help | grep -q 'puente'
puente init "$PUENTE_ROOT" >/dev/null
test -d "$PUENTE_ROOT/hecho"
echo 'hola mundo' | puente new alice bob prueba | tee /tmp/puente-out.txt
MSG=$(cat /tmp/puente-out.txt)
test -f "$MSG"
puente inbox bob | grep -q 'prueba'
puente done "$MSG" >/dev/null
test -f "$PUENTE_ROOT/hecho/$(basename "$MSG")"
echo "smoke ok"
