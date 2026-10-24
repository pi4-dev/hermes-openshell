#!/bin/sh
# Idempotent: safe to run repeatedly (docker compose run --rm bootstrap).
set -eu
GW=http://openshell-gateway:8080

echo "Waiting for the gateway..."
until python -c "import urllib.request; urllib.request.urlopen('$GW/healthz')" 2>/dev/null; do sleep 2; done

openshell gateway add "$GW" --name compose 2>/dev/null || true
openshell status

# The provider holds the key; the sandbox never sees it.
openshell provider create --name model --type openai \
  --credential OPENAI_API_KEY="$MODEL_API_KEY" \
  --config OPENAI_BASE_URL="$MODEL_BASE_URL" 2>/dev/null \
  || echo "provider 'model' already exists (to change the key: openshell provider update ...)"

# The upstream probe is sent by the gateway (through squid in proxy mode).
# If it fails although the backend is reachable (and squid is running): add --no-verify.
openshell inference set --provider model --model "$MODEL_NAME" --timeout 300
openshell inference get

if openshell sandbox list | grep -qw "$SANDBOX_NAME"; then
  echo "Sandbox $SANDBOX_NAME already exists."
else
  # shellcheck disable=SC2086
  openshell sandbox create --name "$SANDBOX_NAME" \
    --from hermes-sandbox:local \
    --policy /policy/hermes-policy.yaml \
    -- $HERMES_CMD </dev/null
fi
openshell sandbox list
