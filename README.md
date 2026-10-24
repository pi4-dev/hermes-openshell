<!-- README-PL.md is the Polish translation of this file — keep both in sync. -->
# hermes-openshell

[Polska wersja](README-PL.md)

The [Hermes](https://github.com/NousResearch/hermes-agent) agent (NousResearch) running in an [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox, with the gateway as Docker Compose. Optionally, all sandbox egress, model requests included, goes through Squid in a container (upstream proxy).

## Architecture

```
Hermes (sandbox) ──▶ OpenShell supervisor proxy ──▶ [Squid (whitelist)] ──▶ internet / model API
                     (per-binary policy,              optional
                      inference.local + key outside the sandbox)
```

- Hermes sends requests only to `https://inference.local/v1`. OpenShell swaps in the model and injects the real key, which the sandbox never sees.
- The Hermes sandbox container is not a compose service. The gateway creates it via `docker.sock`.
- Without the upstream proxy, egress is controlled only by the OpenShell policy (`policy/hermes-policy.yaml`, per binary).

### Optional upstream proxy (Squid)

The proxy is enabled by the `COMPOSE_FILE=docker-compose.yml:docker-compose.proxy.yml` line in `.env`, which is on in `.env.example`. Comment it out to run without Squid.

- `HTTPS_PROXY` inside the sandbox does not work by design, because the supervisor rewrites the agent's proxy environment. Squid is therefore wired in as the supervisor's upstream via `[openshell.drivers.docker] https_proxy` in `openshell/gateway.proxy.toml`.
- Access goes through two independent gates. A host must be **both** in `policy/hermes-policy.yaml` (OpenShell, per binary) and in `squid/whitelist.txt` (Squid, per domain).
- The gateway's own traffic and the image builds (`pip`, `git`) also go through Squid.
- `firewall.sh` can additionally block direct container egress, so that Squid is the only way out.

| Path | Role |
|---|---|
| `docker-compose.yml` | base stack: openshell-init (JWT keys), openshell-gateway, Hermes image build, bootstrap |
| `docker-compose.proxy.yml` | optional upstream proxy: squid and proxy settings for the gateway and the builds |
| `openshell/gateway.toml` | docker driver, bridge network mode (without the proxy) |
| `openshell/gateway.proxy.toml` | the same plus the supervisor's upstream proxy (used with the proxy) |
| `squid/` | config and domain whitelist |
| `hermes/` | Hermes sandbox image and `config.yaml` (model -> inference.local) |
| `bootstrap/` | one-off setup: gateway registration, provider, inference routing, sandbox |
| `policy/hermes-policy.yaml` | OpenShell policy (filesystem, process, network) |
| `firewall.sh` | DOCKER-USER rules: containers leave only through squid (proxy only) |

## Step-by-step setup

Steps marked **(proxy)** apply only with the upstream proxy enabled. Skip them otherwise.

1. **Requirements.** Linux with Docker Engine and the compose plugin. The kernel must support Landlock and seccomp.

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
   curl -sf http://127.0.0.1:8080/healthz
   ```
   The port must be 8080 on both sides, because sandboxes call back to `host.openshell.internal:8080`.
   Compose first runs `openshell-init`, which writes the sandbox JWT keys to `/var/lib/openshell/tls`. The Docker driver requires them. The gateway keeps its database, keys and the extracted supervisor binary in `/var/lib/openshell` on the host and runs as root, like the `deploy/docker` setup in the OpenShell repo.

8. **Bootstrap:** `docker compose up bootstrap`. The script registers the gateway, creates the provider, sets up inference routing and creates the sandbox. To run it again: `docker compose run --rm bootstrap`.

9. **Working with Hermes** (CLI on the host, same version as the gateway: `uv tool install openshell`):
   ```
   openshell gateway add http://127.0.0.1:8080 --name local
   openshell sandbox connect hermes
   hermes
   ```
   For continuous operation (Telegram, Slack, API), set `HERMES_CMD=hermes gateway run` and recreate the sandbox.

### Switching modes later

- **Proxy off:** remove squid first (`docker compose rm -sf squid`), then comment out `COMPOSE_FILE` in `.env`.
- **Proxy on:** uncomment `COMPOSE_FILE` and go through steps 3–5.

Then run `docker compose up -d openshell-gateway` (compose recreates the gateway with the other config) and recreate the sandbox so it picks up the new supervisor settings.

## Verification

- In the sandbox: `curl https://inference.local/v1/models` should get a response from the model backend.
- A host outside the policy should be rejected by OpenShell.
- **(proxy)** Squid log: `docker compose exec squid tail -f /var/log/squid/access.log`. After the request to `inference.local`, `CONNECT <model-host>:443` should show up in it.
- **(proxy)** A host allowed by the policy but missing from the whitelist should give `TCP_DENIED` in squid.

## To check against the pinned OpenShell version

- Installing Hermes on the `openshell-community/sandboxes/base` image: `uv sync --frozen` from the `uv.lock` of the `HERMES_REF` checkout (plain pip cannot resolve hermes-agent's dependencies). The lock covers only Python 3.14, the base image's version. Pin `HERMES_REF`.
- `CERTIFICATE_VERIFY_FAILED` error with `inference.local`: set `SSL_CERT_FILE=/etc/openshell-tls/ca-bundle.pem` in the sandbox.
- **(proxy)** `proxy_connect_by_hostname = true` is required, because otherwise CONNECT goes to the IP and `dstdomain` in squid does not match.
