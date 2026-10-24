<!-- README-PL.md is the Polish translation of this file — keep both in sync. -->
# hermes-openshell

[Polska wersja](README-PL.md)

The [Hermes](https://github.com/NousResearch/hermes-agent) agent (NousResearch) running in an [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox, with the gateway as Docker Compose. Optionally, all sandbox egress, model requests included, goes through Squid in a container (upstream proxy).

## Architecture

```
Hermes (sandbox) ──▶ OpenShell supervisor proxy ──▶ [Squid (whitelist)] ──▶ internet
                     (per-binary policy)      │          optional
                                              └──▶ model-relay ──▶ [Squid] ──▶ model API
                                                   (key, endpoint, model name)
```

- Hermes knows only the model relay (`http://host.docker.internal:8082/v1`), the model alias `assistant` and a dummy key. The `model-relay` service holds `MODEL_BASE_URL`, `MODEL_API_KEY` and `MODEL_NAME`. It adds the key, swaps the alias for the real model and answers `/v1/models` itself. It removes model names, provider fields and SSE comments from responses and forwards only inference calls.
- The sandbox gets no model settings and no OpenShell provider. `hermes` in the image is a launcher that drops the `OPENSHELL_*` variables and points the CA bundle variables at neutral copies. `hermes/config.yaml` has no comments, because Hermes can read it.
- Still visible inside the sandbox, because it is the OpenShell runtime itself: PID 1 `/.openshell/runtime/openshell-sandbox` in `/proc`, the mounts under `/.openshell` and `/run/openshell-supervisor-ca`, and the TLS CA `OpenShell Sandbox CA` on intercepted HTTPS connections. A curious agent can still work out that it runs in OpenShell, but not the model endpoint or the key.
- The Hermes sandbox container is not a compose service. The gateway creates it via `docker.sock`.
- Without the upstream proxy, egress is controlled only by the OpenShell policy (`policy/hermes-policy.yaml`, per binary).

### Optional upstream proxy (Squid)

The proxy is enabled by the `COMPOSE_FILE=docker-compose.yml:docker-compose.proxy.yml` line in `.env`, which is on in `.env.example`. Comment it out to run without Squid.

- `HTTPS_PROXY` inside the sandbox does not work by design, because the supervisor rewrites the agent's proxy environment. Squid is therefore wired in as the supervisor's upstream via `[openshell.drivers.docker] https_proxy` in `openshell/gateway.proxy.toml`.
- Access goes through two independent gates. A host must be **both** in `policy/hermes-policy.yaml` (OpenShell, per binary) and in `squid/whitelist.txt` (Squid, per domain).
- The gateway's own traffic, the model relay and the image builds (`pip`, `git`) also go through Squid.
- `firewall.sh` can additionally block direct container egress, so that Squid is the only way out.

| Path | Role |
|---|---|
| `docker-compose.yml` | base stack: openshell-init (JWT keys), openshell-gateway, model-relay, Hermes image build, bootstrap |
| `docker-compose.proxy.yml` | optional upstream proxy: squid and proxy settings for the gateway and the builds |
| `openshell/gateway.toml` | docker driver, bridge network mode (without the proxy) |
| `openshell/gateway.proxy.toml` | the same plus the supervisor's upstream proxy (used with the proxy) |
| `squid/` | config and domain whitelist |
| `model-relay/` | OpenAI-compatible relay holding the model key, endpoint and name; the only model endpoint Hermes knows |
| `hermes/` | Hermes sandbox image, `config.yaml` (relay and model alias only) and the `hermes` launcher |
| `bootstrap/` | one-off setup with the OpenShell CLI: gateway registration, sandbox |
| `policy/hermes-policy.yaml` | OpenShell policy (filesystem, process, network) |
| `firewall.sh` | DOCKER-USER rules: containers leave only through squid (proxy only) |

## Step-by-step setup

Steps marked **(proxy)** apply only with the upstream proxy enabled. Skip them otherwise.

1. **Requirements.** Linux with Docker Engine **28.0 or later** and the compose plugin (check with `docker version --format '{{.Server.Version}}'`). Older engines fail sandbox creation with `getent unable to find entry "998:998" in passwd database`, because they look up the container user on the host. The kernel must support Landlock (ABI 3 or later) and seccomp.

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
   docker compose up -d openshell-gateway model-relay
   curl -sf http://127.0.0.1:8081/healthz
   ```
   The port must be 8080 on both sides, because sandboxes call back to `host.openshell.internal:8080`.
   Compose first runs `openshell-init`, which writes the sandbox JWT keys to `/var/lib/openshell/tls`. The Docker driver requires them. The gateway keeps its database, keys and the extracted supervisor binary in `/var/lib/openshell` on the host and runs as root, like the `deploy/docker` setup in the OpenShell repo.

8. **Bootstrap:** `docker compose up bootstrap`. The script registers the gateway and creates the sandbox with the policy. To run it again: `docker compose run --rm bootstrap`; a rerun leaves an existing sandbox alone. To change the model, the key or the endpoint, edit `.env` and run `docker compose up -d model-relay`; the sandbox needs no change. If the model's context window is not 131072 tokens, set `context_length` in `hermes/config.yaml` and rebuild the image.

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
   openshell sandbox exec --tty hermes -- hermes
   ```
   `sandbox exec` starts a new process in the sandbox. For a shell, use `openshell sandbox exec --tty hermes -- /bin/bash -l`. `openshell sandbox connect hermes` does not open a shell. It attaches to the sandbox's main process (`HERMES_CMD`) and replays its recent output. With the default `sleep infinity` it shows nothing, so it only looks like it hangs. `Ctrl-C` disconnects and leaves the main process running. For continuous operation (Telegram, Slack, API), set `HERMES_CMD=hermes gateway run` and recreate the sandbox (`openshell sandbox delete hermes`, then the bootstrap again). `sandbox connect` then shows the output of that gateway. It needs the host's `ssh` client.

### Switching modes later

- **Proxy off:** remove squid first (`docker compose rm -sf squid`), then comment out `COMPOSE_FILE` in `.env`.
- **Proxy on:** uncomment `COMPOSE_FILE` and go through steps 3–5.

Then run `docker compose up -d openshell-gateway` (compose recreates the gateway with the other config) and recreate the sandbox so it picks up the new supervisor settings.

## Verification

- `openshell sandbox exec hermes -- hermes -z "ping"` should get an answer from the model backend.
- `docker compose logs model-relay` shows the request (`POST /v1/chat/completions`). `openshell policy get hermes --full` shows the `model` rule for `host.docker.internal:8082`.
- A host outside the policy should be rejected by OpenShell.
- **(proxy)** Squid log: `docker compose exec squid tail -f /var/log/squid/access.log`. After a request from Hermes, the relay's `CONNECT <model-host>:443` should show up in it.
- **(proxy)** A host allowed by the policy but missing from the whitelist should give `TCP_DENIED` in squid.

## To check against the pinned OpenShell version

- Installing Hermes on the `openshell-community/sandboxes/base` image: `uv sync --frozen` from the `uv.lock` of the `HERMES_REF` checkout (plain pip cannot resolve hermes-agent's dependencies). The lock covers only Python 3.14, the base image's version. Pin `HERMES_REF`.
- The policy names the binary `/sandbox/.uv/python/**`, the real path of the base image's Python (`/usr/local/bin/python3` is a symlink to it). After changing the base image, check `readlink -f "$(command -v python3)"` in the sandbox and adjust the policy.
- **(proxy)** `proxy_connect_by_hostname = true` is required, because otherwise CONNECT goes to the IP and `dstdomain` in squid does not match.
