<!-- README-PL.md is the Polish translation of this file — keep both in sync. -->
# hermes-openshell

[Polska wersja](README-PL.md)

The [Hermes](https://github.com/NousResearch/hermes-agent) agent (NousResearch) running in an [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox, with the gateway as Docker Compose. Optionally, all sandbox egress, model requests included, goes through Squid in a container (upstream proxy).

## Architecture

```
Hermes (sandbox) ──▶ OpenShell supervisor proxy ──▶ [Squid (whitelist)] ──▶ internet / model API
                     (per-binary policy,              optional
                      placeholder -> real API key)
```

- Hermes calls the model backend's native OpenAI-compatible API (`MODEL_BASE_URL`, `MODEL_NAME`). The API key is stored in an OpenShell provider. The sandbox sees only a placeholder in `MODEL_API_KEY`, and OpenShell replaces it with the real key on requests to the backend host.
- Bootstrap generates a provider profile (`hermes-model`) from `MODEL_BASE_URL`. It allows that one host, for the sandbox's Python only, and the provider is attached to the sandbox.
- The Hermes sandbox container is not a compose service. The gateway creates it via `docker.sock`.
- Without the upstream proxy, egress is controlled only by OpenShell (`policy/hermes-policy.yaml` plus the provider's rule, per binary).

### Optional upstream proxy (Squid)

The proxy is enabled by the `COMPOSE_FILE=docker-compose.yml:docker-compose.proxy.yml` line in `.env`, which is on in `.env.example`. Comment it out to run without Squid.

- `HTTPS_PROXY` inside the sandbox does not work by design, because the supervisor rewrites the agent's proxy environment. Squid is therefore wired in as the supervisor's upstream via `[openshell.drivers.docker] https_proxy` in `openshell/gateway.proxy.toml`.
- Access goes through two independent gates. A host must be **both** allowed by OpenShell (`policy/hermes-policy.yaml`, or the provider profile for the model backend; per binary) and in `squid/whitelist.txt` (Squid, per domain).
- The gateway's own traffic and the image builds (`pip`, `git`) also go through Squid.
- `firewall.sh` can additionally block direct container egress, so that Squid is the only way out.

| Path | Role |
|---|---|
| `docker-compose.yml` | base stack: openshell-init (JWT keys), openshell-gateway, Hermes image build, bootstrap |
| `docker-compose.proxy.yml` | optional upstream proxy: squid and proxy settings for the gateway and the builds |
| `openshell/gateway.toml` | docker driver, bridge network mode (without the proxy) |
| `openshell/gateway.proxy.toml` | the same plus the supervisor's upstream proxy (used with the proxy) |
| `squid/` | config and domain whitelist |
| `hermes/` | Hermes sandbox image and `config.yaml` (model from `MODEL_BASE_URL`/`MODEL_NAME`, key from `MODEL_API_KEY`) |
| `bootstrap/` | one-off setup with the OpenShell CLI: gateway registration, model provider profile and provider, sandbox |
| `policy/hermes-policy.yaml` | OpenShell policy (filesystem, process, network) |
| `firewall.sh` | DOCKER-USER rules: containers leave only through squid (proxy only) |

## Step-by-step setup

Steps marked **(proxy)** apply only with the upstream proxy enabled. Skip them otherwise.

1. **Requirements.** Linux with Docker Engine **28.0 or later** and the compose plugin (check with `docker version --format '{{.Server.Version}}'`). Older engines fail sandbox creation with `getent unable to find entry "998:998" in passwd database`, because they look up the container user on the host. The kernel needs seccomp and Landlock ABI 3 or later (Linux 6.2+), and Landlock must be **enabled**: `cat /sys/kernel/security/lsm` has to list `landlock`. Some kernels, such as Proxmox's, build Landlock in but leave it out of the active list. Then add it to the `lsm=` boot parameter, keeping the LSMs already listed, e.g. `lsm=landlock,lockdown,yama,integrity,apparmor`, and reboot. In an LXC container this is the host's kernel. Bootstrap checks this before it creates the sandbox.

2. **Configuration.** Run `cp .env.example .env` and fill in:
   - `COMPOSE_FILE`: keep it to use the upstream proxy, comment it out to run without it,
   - `HOST_BRIDGE_IP` (from `ip -4 addr show docker0`),
   - `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`.

3. **(proxy) IP and whitelist.** Put the same bridge IP in `https_proxy` in `openshell/gateway.proxy.toml`, because TOML does not read `.env`. Add the model backend host to `squid/whitelist.txt`.

4. **(proxy) Firewall (recommended).** Run `sudo sh firewall.sh`. The script blocks direct container egress to the internet, except for squid. It works only thanks to `supervisor_network_mode = "bridge"`. Do not run it without the proxy, because it would cut off all container egress.

5. **(proxy) Start squid and test.**
   ```
   docker compose up -d squid
   curl -x http://172.17.0.1:3128 -I https://pypi.org
   ```

6. **Build the images:** `docker compose build`. With the proxy, do this after starting squid, because `pip` and `git` in the build go through it. Base images are pulled by dockerd itself, so set any proxy in the daemon.

7. **Start the gateway.**
   ```
   docker compose up -d openshell-gateway
   curl -sf http://127.0.0.1:8081/healthz
   ```
   The port must be 8080 on both sides, because sandboxes call back to `host.openshell.internal:8080`.
   Compose first runs `openshell-init`, which writes the sandbox JWT keys to `/var/lib/openshell/tls`. The Docker driver requires them. The gateway keeps its database, keys and the extracted supervisor binary in `/var/lib/openshell` on the host and runs as root, like the `deploy/docker` setup in the OpenShell repo.

8. **Bootstrap:** `docker compose up bootstrap`. The script registers the gateway, imports the model provider profile, creates the provider with the key and creates the sandbox with the provider attached. To run it again: `docker compose run --rm bootstrap`. A rerun updates the profile and the key and leaves an existing sandbox alone. Processes that are already running (Hermes keeps a background `hermes gateway run`) keep the old key until they restart, so after a key change run `openshell sandbox stop hermes` and `openshell sandbox start hermes`.

9. **Working with Hermes.** Install the OpenShell CLI on the host, in the same version as the gateway. The `openshell` package on PyPI is only the Python SDK, and the upstream `install.sh` also sets up its own local gateway, so take the static binary from the release:
   ```
   V=0.1.5
   A=openshell-$(uname -m)-unknown-linux-musl.tar.gz
   curl -fsSLO https://github.com/NVIDIA/OpenShell/releases/download/v$V/$A
   curl -fsSLO https://github.com/NVIDIA/OpenShell/releases/download/v$V/openshell-checksums-sha256.txt
   grep " $A\$" openshell-checksums-sha256.txt | sha256sum -c
   sudo tar -xzf $A -C /usr/local/bin openshell
   ```
   Then:
   ```
   openshell gateway add http://127.0.0.1:8080 --name local
   openshell sandbox connect hermes
   hermes
   ```
   `sandbox connect` uses the host's `ssh` client. For continuous operation (Telegram, Slack, API), set `HERMES_CMD=hermes gateway run` and recreate the sandbox (`openshell sandbox delete hermes`, then the bootstrap again).

### Switching modes later

- **Proxy off:** remove squid first (`docker compose rm -sf squid`), then comment out `COMPOSE_FILE` in `.env`.
- **Proxy on:** uncomment `COMPOSE_FILE` and go through steps 3–5.

Then run `docker compose up -d openshell-gateway` (compose recreates the gateway with the other config) and recreate the sandbox so it picks up the new supervisor settings.

## Verification

- In the sandbox: `hermes -z "ping"` should get an answer from the model backend.
- `openshell policy get hermes --full` shows the provider's rule for the model backend host.
- A host outside the policy should be rejected by OpenShell.
- **(proxy)** Squid log: `docker compose exec squid tail -f /var/log/squid/access.log`. After a request from Hermes, `CONNECT <model-host>:443` should show up in it.
- **(proxy)** A host allowed by the policy but missing from the whitelist should give `TCP_DENIED` in squid.

## To check against the pinned OpenShell version

- Installing Hermes on the `openshell-community/sandboxes/base` image: `uv sync --frozen` from the `uv.lock` of the `HERMES_REF` checkout (plain pip cannot resolve hermes-agent's dependencies). The lock covers only Python 3.14, the base image's version. Pin `HERMES_REF`.
- The provider profile and the policy name the binary `/sandbox/.uv/python/**`, the real path of the base image's Python (`/usr/local/bin/python3` is a symlink to it). After changing the base image, check `readlink -f "$(command -v python3)"` in the sandbox and adjust `bootstrap/model-profile.py` and the policy.
- **(proxy)** `proxy_connect_by_hostname = true` is required, because otherwise CONNECT goes to the IP and `dstdomain` in squid does not match.
