#!/bin/sh
# Idempotent: safe to run repeatedly (docker compose run --rm bootstrap).
set -eu
GW=http://openshell-gateway:8080

echo "Waiting for the gateway..."
until python -c "import urllib.request; urllib.request.urlopen('http://openshell-gateway:8081/readyz')" 2>/dev/null; do sleep 2; done

openshell gateway add "$GW" --name compose 2>/dev/null || true
openshell status

# Provider profile for the model backend (host from MODEL_BASE_URL). The sandbox gets only a
# placeholder in MODEL_API_KEY; OpenShell substitutes the real key on requests to that host.
if openshell profile export hermes-model -o json > /tmp/current-profile.json 2>/dev/null; then
  python /model-profile.py /tmp/current-profile.json > /tmp/model-profile.yaml
  openshell profile update -f /tmp/model-profile.yaml hermes-model
else
  python /model-profile.py > /tmp/model-profile.yaml
  openshell profile lint -f /tmp/model-profile.yaml
  openshell profile import -f /tmp/model-profile.yaml
fi

# The provider holds the key, read from MODEL_API_KEY in this container's environment.
if openshell provider get model >/dev/null 2>&1; then
  openshell provider update model --credential MODEL_API_KEY
else
  openshell provider create --name model --type hermes-model --credential MODEL_API_KEY
fi

if openshell sandbox list | grep -qw "$SANDBOX_NAME"; then
  echo "Sandbox $SANDBOX_NAME already exists."
else
  # Hermes reads MODEL_BASE_URL and MODEL_NAME (hermes/config.yaml) and the placeholder in MODEL_API_KEY.
  # shellcheck disable=SC2086
  openshell sandbox create --name "$SANDBOX_NAME" \
    --from hermes-sandbox:local \
    --policy /policy/hermes-policy.yaml \
    --provider model \
    --env MODEL_BASE_URL="$MODEL_BASE_URL" \
    --env MODEL_NAME="$MODEL_NAME" \
    --detach \
    -- $HERMES_CMD </dev/null
fi
openshell sandbox list
