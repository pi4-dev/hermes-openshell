#!/bin/sh
# Idempotent: safe to run repeatedly (docker compose run --rm bootstrap).
set -eu
GW=http://openshell-gateway:8080

# The sandbox runtime requires Landlock ABI 3+ in the kernel's active LSM list (this container shares
# the host kernel). Without it the sandbox only fails with "exited before supervisor became ready".
python - <<'EOF'
import ctypes, errno, sys
libc = ctypes.CDLL(None, use_errno=True)
abi = libc.syscall(444, None, 0, 1)  # landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)
err = ctypes.get_errno()
if abi >= 3:
    sys.exit(0)
if abi >= 0:
    sys.exit(f"Landlock ABI {abi} is too old: OpenShell needs ABI 3 or later (Linux 6.2+).")
if err == errno.EOPNOTSUPP:
    sys.exit("Landlock is built into the kernel but not enabled: add landlock to the lsm= kernel "
             "parameter and reboot (see README, step 1).")
if err == errno.ENOSYS:
    sys.exit("The kernel has no Landlock support: OpenShell needs Landlock ABI 3 or later (Linux 6.2+).")
print(f"warning: cannot probe Landlock ({errno.errorcode.get(err, err)}), continuing", file=sys.stderr)
EOF

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
