#!/bin/sh
# Idempotent: safe to run repeatedly (docker compose run --rm bootstrap).
# AGENTS (COMPOSE_PROFILES in .env): which sandboxes to set up, hermes and/or claude.
set -eu
GW=http://openshell-gateway:8080

if [ -z "${AGENTS:-}" ]; then
  echo "COMPOSE_PROFILES is empty: set it in .env to hermes, claude or hermes,claude." >&2
  exit 1
fi

echo "Waiting for the gateway..."
until python -c "import urllib.request; urllib.request.urlopen('http://openshell-gateway:8081/readyz')" 2>/dev/null; do sleep 2; done

openshell gateway add "$GW" --name compose 2>/dev/null || true
openshell status

sandbox_exists() {
  if openshell sandbox get "$1" >/dev/null 2>&1; then
    echo "Sandbox $1 already exists."
  else
    return 1
  fi
}

setup_hermes() {
  sandbox_exists "$SANDBOX_NAME" && return
  # No provider or model settings: Hermes only knows the model relay (hermes/config.yaml).
  # shellcheck disable=SC2086
  openshell sandbox create --name "$SANDBOX_NAME" \
    --from hermes-sandbox:local \
    --policy /policy/hermes-policy.yaml \
    --detach \
    -- $HERMES_CMD </dev/null
}

setup_claude() {
  if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo "CLAUDE_CODE_OAUTH_TOKEN is empty: put the token from \`claude setup-token\` in .env." >&2
    exit 1
  fi
  # `openshell profile update` requires the current resource_version.
  profile=/providers/claude-subscription.yaml
  if openshell profile export claude-subscription -o json > /tmp/current-profile.json 2>/dev/null; then
    { cat "$profile"
      python -c 'import json, sys; print("resource_version:", json.dumps(json.load(open(sys.argv[1]))["resource_version"]))' /tmp/current-profile.json
    } > /tmp/claude-profile.yaml
    openshell profile update -f /tmp/claude-profile.yaml claude-subscription
  else
    openshell profile lint -f "$profile"
    openshell profile import -f "$profile"
  fi
  # The gateway keeps the token (read from this container's environment); the sandbox gets a placeholder.
  if openshell provider get claude-subscription >/dev/null 2>&1; then
    openshell provider update claude-subscription --credential CLAUDE_CODE_OAUTH_TOKEN
  else
    openshell provider create --name claude-subscription --type claude-subscription --credential CLAUDE_CODE_OAUTH_TOKEN
  fi
  sandbox_exists "$CLAUDE_SANDBOX_NAME" && return
  openshell sandbox create --name "$CLAUDE_SANDBOX_NAME" \
    --from claude-sandbox:local \
    --policy /policy/claude-policy.yaml \
    --provider claude-subscription \
    --detach \
    -- sleep infinity </dev/null
}

for agent in $(echo "$AGENTS" | tr ',' ' '); do
  case "$agent" in
    hermes|claude) "setup_$agent" ;;
    *) echo "Unknown agent in COMPOSE_PROFILES: $agent" >&2; exit 1 ;;
  esac
done
openshell sandbox list
