#!/bin/sh
# Starts Hermes without the sandbox runtime's markers in its environment: drops OPENSHELL_*
# variables and points the CA bundle variables at neutral copies of the same files.
for var in $(env | sed -n 's/^\(OPENSHELL_[A-Za-z0-9_]*\)=.*/\1/p'); do
  unset "$var"
done
# The source files are read-only (0444) and cp keeps that, so -f replaces the previous copy.
certs="$HOME/.cache/certs"
if [ -r "${SSL_CERT_FILE:-}" ] && mkdir -p "$certs" && cp -f "$SSL_CERT_FILE" "$certs/ca-bundle.crt"; then
  export SSL_CERT_FILE="$certs/ca-bundle.crt" REQUESTS_CA_BUNDLE="$certs/ca-bundle.crt" \
         CURL_CA_BUNDLE="$certs/ca-bundle.crt" GIT_SSL_CAINFO="$certs/ca-bundle.crt"
  if [ -r "${NODE_EXTRA_CA_CERTS:-}" ] && cp -f "$NODE_EXTRA_CA_CERTS" "$certs/ca.crt"; then
    export NODE_EXTRA_CA_CERTS="$certs/ca.crt" DENO_CERT="$certs/ca.crt"
  fi
fi
# The prebuilt dashboard chat (Ink TUI) and the image's Node; otherwise Hermes would try to build
# the TUI or fetch its own Node at launch.
export HERMES_TUI_DIR="${HERMES_TUI_DIR:-/opt/hermes-tui}" HERMES_NODE="${HERMES_NODE:-/opt/node/bin/node}"
exec /opt/hermes/.venv/bin/hermes "$@"
