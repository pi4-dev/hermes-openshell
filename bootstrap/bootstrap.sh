#!/bin/sh
# Idempotent: safe to run repeatedly (docker compose run --rm bootstrap).
set -eu
GW=http://openshell-gateway:8080

echo "Waiting for the gateway..."
until python -c "import urllib.request; urllib.request.urlopen('http://openshell-gateway:8081/readyz')" 2>/dev/null; do sleep 2; done

openshell gateway add "$GW" --name compose 2>/dev/null || true
openshell status

if openshell sandbox list | grep -qw "$SANDBOX_NAME"; then
  echo "Sandbox $SANDBOX_NAME already exists."
else
  # No provider or model settings: Hermes only knows the model relay (hermes/config.yaml).
  # shellcheck disable=SC2086
  openshell sandbox create --name "$SANDBOX_NAME" \
    --from hermes-sandbox:local \
    --policy /policy/hermes-policy.yaml \
    --detach \
    -- $HERMES_CMD </dev/null
fi
openshell sandbox list
