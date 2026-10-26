<!-- README-PL.md is the Polish translation of this file — keep both in sync. -->
# hermes-openshell

[Polska wersja](README-PL.md)

The [Hermes](https://github.com/NousResearch/hermes-agent) agent (NousResearch), [Claude Code](https://code.claude.com/docs) on a Claude subscription, or both, each in its own [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox, with the gateway as Docker Compose. Optionally, all sandbox egress, model requests included, goes through Squid in a container (upstream proxy).

## Architecture

```
Hermes (sandbox) ──▶ OpenShell supervisor proxy ──▶ [Squid (whitelist)] ──▶ internet
                     (per-binary policy)      │          optional
                                              └──▶ model-relay ──▶ [Squid] ──▶ model API
                                                   (key, endpoint, model name)

Claude Code (sandbox) ──▶ OpenShell supervisor proxy ──▶ [Squid] ──▶ api.anthropic.com
                          (adds the subscription token)
```

- Hermes knows only the model relay (`http://host.docker.internal:8082/v1`), the model alias `assistant` and a dummy key. The `model-relay` service holds `MODEL_BASE_URL`, `MODEL_API_KEY` and `MODEL_NAME`. It adds the key, swaps the alias for the real model and answers `/v1/models` itself. It removes model names, provider fields, SSE comments and non-JSON error pages from responses and forwards only inference calls. It names no server software and answers everything else with the same empty 404; health and metrics are on a separate port (see Model relay: health and metrics).
- The sandbox gets no model settings and no OpenShell provider. `hermes` in the image is a launcher that drops the `OPENSHELL_*` variables and points the CA bundle variables at neutral copies. `hermes/config.yaml` has no comments, because Hermes can read it.
- Still visible inside the sandbox, because it is the OpenShell runtime itself: PID 1 `/.openshell/runtime/openshell-sandbox` in `/proc`, the mounts under `/.openshell` and `/run/openshell-supervisor-ca`, and the TLS CA `OpenShell Sandbox CA` on intercepted HTTPS connections. A curious agent can still work out that it runs in OpenShell, but not the model endpoint or the key.
- The sandbox containers are not compose services. The gateway creates them via `docker.sock`.
- Without the upstream proxy, egress is controlled only by the OpenShell policies (`policy/hermes-policy.yaml`, `policy/claude-policy.yaml`, per binary).

### Agents: Hermes, Claude Code or both

`COMPOSE_PROFILES` in `.env` chooses the agents. Compose builds and starts only their services, and the bootstrap creates their sandboxes:

| `COMPOSE_PROFILES` | Sandboxes | Services |
|---|---|---|
| `hermes` | `hermes` | model-relay, Hermes image |
| `claude` | `claude` | Claude Code image |
| `hermes,claude` | `hermes` and `claude`, side by side | all of the above |

The agents share only the gateway. Each has its own sandbox, policy and model access, and files pass between them only through you (see the examples under Working with Claude Code).

- Claude Code runs on a Claude subscription (Pro, Max, Team or Enterprise) with a token from `claude setup-token`, not on an API key. The bootstrap stores the token in the gateway as the `claude-subscription` provider (`providers/claude-subscription.yaml`). In the sandbox, `CLAUDE_CODE_OAUTH_TOKEN` holds only a placeholder. The supervisor puts the real token into the `Authorization` header of requests that `/usr/local/bin/claude` sends to `api.anthropic.com`, and nowhere else. Only Claude Code and the processes it starts may connect to that host, and the real token never enters the sandbox.
- `claude/settings.json` turns off auto-updates, telemetry, error reports and the automatic plugin marketplace, so Claude Code needs no host besides `api.anthropic.com`.
- The Claude sandbox is not anonymized like the Hermes one: the placeholder and `OPENSHELL_SANDBOX` show that it runs in OpenShell, and its model endpoint is api.anthropic.com anyway.

### Optional upstream proxy (Squid)

The proxy is enabled by the `COMPOSE_FILE=docker-compose.yml:docker-compose.proxy.yml` line in `.env`, which is on in `.env.example`. Comment it out to run without Squid.

- `HTTPS_PROXY` inside the sandbox does not work by design, because the supervisor rewrites the agent's proxy environment. Squid is therefore wired in as the supervisor's upstream via `[openshell.drivers.docker] https_proxy` in `openshell/gateway.proxy.toml`.
- Access goes through two independent gates. A host must be **both** in the agent's policy, `policy/hermes-policy.yaml` or `policy/claude-policy.yaml` (OpenShell, per binary), and in `squid/whitelist.txt` (Squid, per domain).
- The gateway's own traffic, the model relay and the image builds (`pip`, `git`, `npm`, the Node download) also go through Squid.
- `firewall.sh` can additionally block direct container egress, so that Squid is the only way out.

| Path | Role |
|---|---|
| `docker-compose.yml` | base stack: openshell-init (JWT keys), openshell-gateway, bootstrap; per agent: model-relay and the Hermes image (`hermes`), the Claude Code image (`claude`) |
| `docker-compose.proxy.yml` | optional upstream proxy: squid and proxy settings for the gateway and the builds |
| `openshell/gateway.toml` | docker driver, bridge network mode (without the proxy) |
| `openshell/gateway.proxy.toml` | the same plus the supervisor's upstream proxy (used with the proxy) |
| `squid/` | config and domain whitelist |
| `model-relay/` | OpenAI-compatible relay holding the model key, endpoint and name; the only model endpoint Hermes knows; `/health` and `/metrics` on a separate port |
| `hermes/` | Hermes sandbox image with the prebuilt web dashboard, `config.yaml` (relay and model alias only) and the `hermes` launcher |
| `claude/` | Claude Code sandbox image: the base sandbox image (Claude Code, git, Node, Python, uv, build tools) and Claude's settings |
| `providers/claude-subscription.yaml` | OpenShell provider profile: the subscription token, only for `claude` → `api.anthropic.com` |
| `bootstrap/` | one-off setup with the OpenShell CLI: gateway registration, provider, sandboxes |
| `policy/hermes-policy.yaml` | OpenShell policy of the Hermes sandbox (filesystem, process, network) |
| `policy/claude-policy.yaml` | OpenShell policy of the Claude Code sandbox |
| `firewall.sh` | DOCKER-USER rules: containers leave only through squid (proxy only) |

## Step-by-step setup

Steps marked **(proxy)** apply only with the upstream proxy enabled. Skip them otherwise.

1. **Requirements.** Linux with Docker Engine **28.0 or later** and the compose plugin (check with `docker version --format '{{.Server.Version}}'`). Older engines fail sandbox creation with `getent unable to find entry "998:998" in passwd database`, because they look up the container user on the host. The kernel must support Landlock (ABI 3 or later) and seccomp.

2. **Configuration.** Run `cp .env.example .env` and fill in:
   - `COMPOSE_FILE`: keep it to use the upstream proxy, comment it out to run without it,
   - `COMPOSE_PROFILES`: `hermes`, `claude` or `hermes,claude` (see Agents above),
   - `HOST_BRIDGE_IP` (from `ip -4 addr show docker0`),
   - for Hermes: `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`,
   - for Claude Code: `CLAUDE_CODE_OAUTH_TOKEN`, the token from `claude setup-token` (see Claude token below).

3. **(proxy) IP and whitelist.** Put the same bridge IP in `https_proxy` in `openshell/gateway.proxy.toml`, because TOML does not read `.env`. Add the model backend host to `squid/whitelist.txt` (Hermes). `api.anthropic.com` (Claude Code) is already there.

4. **(proxy) Firewall (recommended).** Run `sudo sh firewall.sh`. The script blocks direct container egress to the internet, except for squid. It works only thanks to `supervisor_network_mode = "bridge"`. Do not run it without the proxy, because it would cut off all container egress.

5. **(proxy) Start squid and test.**
   ```
   docker compose up -d squid
   curl -x http://172.17.0.1:3128 -I https://pypi.org
   ```

6. **Build the images:** `docker compose build` builds those of the chosen agents. With the proxy, do this after starting squid, because `pip`, `git` and `npm` in the build go through it. Base images are pulled by dockerd itself, so set any proxy in the daemon.

7. **Start the gateway.**
   ```
   docker compose up -d openshell-gateway
   curl -sf http://127.0.0.1:8081/healthz
   ```
   The port must be 8080 on both sides, because sandboxes call back to `host.openshell.internal:8080`.
   Compose first runs `openshell-init`, which writes the sandbox JWT keys to `/var/lib/openshell/tls`. The Docker driver requires them. The gateway keeps its database, keys and the extracted supervisor binary in `/var/lib/openshell` on the host and runs as root, like the `deploy/docker` setup in the OpenShell repo.

8. **Bootstrap:** `docker compose up bootstrap`. It also starts the model relay for Hermes and waits until it is healthy. The script registers the gateway and creates the sandboxes of the chosen agents with their policies; for Claude Code it first stores the token in the gateway. To run it again: `docker compose run --rm bootstrap`; a rerun leaves existing sandboxes alone but updates the Claude token, so after a new `claude setup-token` change `.env` and rerun it. The running sandbox uses the new token for new processes within seconds. To change the model, the key or the endpoint, edit `.env` and run `docker compose up -d model-relay`; the sandbox needs no change. If the model's context window is not 131072 tokens, set `context_length` in `hermes/config.yaml` and rebuild the image.

9. **Working with the agents.** Install the OpenShell CLI on the host, in the same version as the gateway. The `openshell` package on PyPI is only the Python SDK, and the upstream `install.sh` also sets up its own local gateway, so take the static binary from the release:
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
   openshell sandbox exec --tty claude -- claude
   ```
   `sandbox exec` starts a new process in the sandbox. For a shell, use `openshell sandbox exec --tty hermes -- /bin/bash -l`. `openshell sandbox connect hermes` does not open a shell. It attaches to the sandbox's main process (`HERMES_CMD`) and replays its recent output. With the default `sleep infinity` it shows nothing, so it only looks like it hangs. `Ctrl-C` disconnects and leaves the main process running. For continuous operation (Telegram, Slack, API), set `HERMES_CMD=hermes gateway run` and recreate the sandbox (`openshell sandbox delete hermes`, then the bootstrap again). `sandbox connect` then shows the output of that gateway. It needs the host's `ssh` client. For Claude Code, see the examples under Working with Claude Code.

### Claude token

`CLAUDE_CODE_OAUTH_TOKEN` is a long-lived token from `claude setup-token`, valid for a year. It needs a Claude subscription (Pro, Max, Team or Enterprise). Create it on any machine where you can log in with that account, but not in the OpenShell sandbox: its policy does not let the login through, and the real token is meant never to be there.

- **Your computer, with a browser and Claude Code:** run `claude setup-token`. The browser opens, and after you log in the terminal prints the token (`sk-ant-oat01-…`).
- **The Docker host over SSH, without a browser:** install Claude Code (`curl -fsSL https://claude.ai/install.sh | bash`) and run `claude setup-token`. It prints a link: open it on any device, log in and paste the code you get back into the terminal.
- **Without installing anything on the host:** use a throwaway container from the base sandbox image, which already contains Claude Code. It is an ordinary container with normal network access, not a sandbox, and the login works as over SSH:
  ```
  docker run --rm -it --entrypoint claude ghcr.io/nvidia/openshell-community/sandboxes/base:latest setup-token
  ```
  With `firewall.sh` in place (proxy mode), containers cannot reach the internet directly, so use one of the first two options.

Then put the token in `.env` as `CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-…` and run the bootstrap (`docker compose run --rm bootstrap` if it has run before). Treat the token like a password; `.env` is in `.gitignore`. When the token expires, Claude reports `401 OAuth access token is invalid`: create a new one the same way, replace it in `.env` and run the bootstrap again. The running sandbox picks it up without being recreated.

### Web dashboard

The image contains Hermes's web dashboard, including its chat. The sandbox has no network of its own, so the dashboard listens on `127.0.0.1:9119` inside it and `openshell forward` tunnels that port to the host:

1. Run the dashboard as the sandbox's main process: set `HERMES_CMD=hermes dashboard --skip-build --no-open` in `.env` and recreate the sandbox (`openshell sandbox delete hermes`, then `docker compose up bootstrap`). Without `--skip-build`, Hermes tries to rebuild the dashboard at launch, which cannot work in the sandbox.
2. On the host: `openshell forward start 9119 hermes -d`, then open http://127.0.0.1:9119/. `openshell forward stop 9119 hermes` ends the tunnel.
3. From another machine, go through SSH: `ssh -L 9119:127.0.0.1:9119 user@docker-host`, then open http://127.0.0.1:9119/ there.

On a loopback bind the dashboard has no login and gives full control over Hermes (config, keys, sessions), so do not forward it to `0.0.0.0` or another interface.

### Model relay: health and metrics

On its API port (8082) the relay answers the sandboxes only with `/v1/models` and the inference calls. Everything else, `/health` and `/metrics` included, gets the same empty 404, and no response names the server software. Health and metrics are on a separate port, `MODEL_RELAY_OPS_ADDR` in `.env` (`127.0.0.1:9082` by default), which the sandbox policies do not allow:

- `GET /health` returns `{"status": "ok"}`. Compose uses it as the container's healthcheck (`docker compose ps model-relay` shows `healthy`), and the bootstrap waits for it.
- `GET /metrics` returns Prometheus metrics. Their labels name no model or backend:

| Metric | Type | Labels, meaning |
|---|---|---|
| `model_relay_requests_total` | counter | `path` (API path, or `other` for everything else), `code` |
| `model_relay_request_duration_seconds` | histogram | `path`; the whole request, streaming included |
| `model_relay_time_to_first_byte_seconds` | histogram | `path`; until the backend's response headers |
| `model_relay_tokens_total` | counter | `type` (`input`, `output`), as reported by the backend |
| `model_relay_in_flight_requests` | gauge | requests being forwarded |
| `process_start_time_seconds` | gauge | relay start time |

A Prometheus on the same host scrapes it like this:
```yaml
scrape_configs:
  - job_name: model-relay
    static_configs:
      - targets: ["127.0.0.1:9082"]
```
From a Prometheus container on the compose network `osnet`, the target is `model-relay:9000`. For one on another machine, set `MODEL_RELAY_OPS_ADDR` to the host's LAN address and run `docker compose up -d model-relay`.

Example Grafana queries:
- tokens per minute: `sum by (type) (rate(model_relay_tokens_total[5m])) * 60`
- p95 time to first byte: `histogram_quantile(0.95, sum by (le) (rate(model_relay_time_to_first_byte_seconds_bucket[5m])))`
- failed inference calls: `sum by (code) (rate(model_relay_requests_total{path!="other",code!~"2.."}[5m]))`
- requests outside the API, for example an agent probing the relay: `increase(model_relay_requests_total{path="other"}[1h])`

Tokens are counted when the backend reports usage: in every non-streamed response, and in streams only if the backend includes it.

### Working with Claude Code

`openshell sandbox exec --tty claude -- claude` starts Claude Code interactively in the sandbox. The subscription is already set up, so there is no login. The first start in a folder asks whether you trust it, and `claude --continue` resumes the last session in that folder (sessions stay in the sandbox).

The sandbox shares no folder with the host. Code goes in and out with `openshell sandbox upload` and `download`, through git, or through the output of `sandbox exec`. `upload` puts a directory *inside* the target directory, so upload to `/sandbox` or `/tmp`. For commits made in the sandbox, set a git identity once:
```
openshell sandbox exec claude -- git config --global user.name "Claude (sandbox)"
openshell sandbox exec claude -- git config --global user.email claude@sandbox.invalid
```

**Copy a project in and back.** From a git work tree, the upload follows `.gitignore` and skips `.git`, so `.env` files, `node_modules` and the history stay on the host:
```
openshell sandbox upload claude ./myapp /sandbox                # -> /sandbox/myapp
openshell sandbox exec --tty --workdir /sandbox/myapp claude -- claude
openshell sandbox download claude /sandbox/myapp ./myapp-claude
```

**With git history: a bundle in, patches out.** Claude works on a clone and commits; you review its commits and apply them on the host:
```
git -C ~/src/myapp bundle create /tmp/myapp.bundle --all
openshell sandbox upload claude /tmp/myapp.bundle /tmp
openshell sandbox exec --workdir /sandbox claude -- git clone /tmp/myapp.bundle myapp
openshell sandbox exec --tty --workdir /sandbox/myapp claude -- claude   # "add input validation with tests, then commit"
openshell sandbox exec --workdir /sandbox/myapp claude -- git format-patch origin/HEAD --stdout > claude.patch
git -C ~/src/myapp am < claude.patch
```
A public repository can also be cloned straight from GitHub: `openshell sandbox exec --workdir /sandbox claude -- git clone https://github.com/<owner>/<repo>.git`. The sandbox has no GitHub credentials, so pushing stays on the host.

**Headless, for scripts.** `claude -p` runs one task and prints the result. Without permissions it only reads, so allow what the task needs:
```
# Questions about the code
openshell sandbox exec --workdir /sandbox/myapp claude -- claude -p "Explain the architecture in 10 bullet points"
# File edits, and only the test command
openshell sandbox exec --workdir /sandbox/myapp claude -- claude -p "Make the failing tests pass" \
  --permission-mode acceptEdits --allowedTools "Bash(npm test:*)"
# No permission prompts at all
openshell sandbox exec --workdir /sandbox/myapp claude -- claude -p "Upgrade the dependencies and fix the build" \
  --dangerously-skip-permissions
openshell sandbox exec --workdir /sandbox/myapp claude -- git diff > upgrade.patch
```
With `--dangerously-skip-permissions`, interactively too, Claude runs anything without asking, but only inside the sandbox: the OpenShell policy still decides which hosts it reaches and which files it sees, and the token never leaves the supervisor.

**Claude and Hermes side by side** (`COMPOSE_PROFILES=hermes,claude`). For example, Claude writes a change and Hermes reviews it:
```
openshell sandbox exec --workdir /sandbox/myapp claude -- git format-patch origin/HEAD --stdout > change.patch
openshell sandbox upload hermes change.patch /tmp
openshell sandbox exec hermes -- hermes -z "Review /tmp/change.patch: bugs, missing tests, risky changes"
```

**More Claude sandboxes**, for example one per project, all on the same subscription. Run this in the repository directory, because `--policy` is a local file:
```
openshell sandbox create --name claude-api --from claude-sandbox:local \
  --policy policy/claude-policy.yaml --provider claude-subscription --detach -- sleep infinity
openshell sandbox exec --tty claude-api -- claude
```

**What a project needs.**
- Tools: the image has git, Node 22, Python 3 with uv, gcc and make. Add others in `claude/Dockerfile`, then run `docker compose build claude-image`, `openshell sandbox delete claude` and the bootstrap again. Deleting the sandbox deletes its files, so download what you need first.
- Network: the policy lets git reach GitHub and lets npm and PyPI install packages. Add the hosts your project needs to `policy/claude-policy.yaml` (with the proxy, to `squid/whitelist.txt` too) and apply them to the running sandbox with `openshell policy set claude --policy policy/claude-policy.yaml --wait`. Claude's own web fetches come from `/usr/local/bin/claude`, so name that binary for such hosts.
- A dev server that Claude starts on `127.0.0.1:5173` in the sandbox is reachable from the host after `openshell forward start 5173 claude -d`, at http://127.0.0.1:5173/.

### Switching modes later

- **Proxy off:** remove squid first (`docker compose rm -sf squid`), then comment out `COMPOSE_FILE` in `.env`.
- **Proxy on:** uncomment `COMPOSE_FILE` and go through steps 3–5.

Then run `docker compose up -d openshell-gateway` (compose recreates the gateway with the other config) and recreate the sandboxes so they pick up the new supervisor settings.

## Verification

- `openshell sandbox exec hermes -- hermes -z "ping"` should get an answer from the model backend.
- `docker compose logs model-relay` shows the request (`POST /v1/chat/completions`). `openshell policy get hermes --full` shows the `model` rule for `host.docker.internal:8082`. `curl -s http://127.0.0.1:9082/health` returns `{"status": "ok"}`, and `curl -s http://127.0.0.1:9082/metrics | grep model_relay_requests_total` counts the request.
- `openshell sandbox exec claude -- claude -p "reply with OK"` should get an answer from Claude. `openshell sandbox exec claude -- printenv CLAUDE_CODE_OAUTH_TOKEN` prints only the placeholder (`openshell:resolve:env:…`), and `openshell logs claude | grep anthropic` shows `ALLOWED /usr/local/bin/claude(0) -> api.anthropic.com:443 [policy:_provider_claude_subscription …]`. `401 OAuth access token is invalid` means a wrong or expired token: create a new one with `claude setup-token`, put it in `.env` and rerun the bootstrap.
- A host outside the policy should be rejected by OpenShell.
- **(proxy)** Squid log: `docker compose exec squid tail -f /var/log/squid/access.log`. After a request from Hermes, the relay's `CONNECT <model-host>:443` should show up in it, and after one from Claude Code, `CONNECT api.anthropic.com:443`.
- **(proxy)** A host allowed by the policy but missing from the whitelist should give `TCP_DENIED` in squid.

## To check against the pinned OpenShell version

- Installing Hermes on the `openshell-community/sandboxes/base` image: `uv sync --frozen` from the `uv.lock` of the `HERMES_REF` checkout (plain pip cannot resolve hermes-agent's dependencies). The lock covers only Python 3.14, the base image's version. Pin `HERMES_REF`.
- The policy names the binary `/sandbox/.uv/python/**`, the real path of the base image's Python (`/usr/local/bin/python3` is a symlink to it). After changing the base image, check `readlink -f "$(command -v python3)"` in the sandbox and adjust the policy.
- Claude Code comes from the base sandbox image (`openshell sandbox exec claude -- claude --version`); `docker compose build --pull claude-image` takes a newer one when there is one. `providers/claude-subscription.yaml` names its real path, `/usr/local/bin/claude`. After a base image change, check `readlink -f "$(command -v claude)"` in the sandbox. If a new Claude Code version needs another host, `openshell logs claude` shows it as `DENIED`.
- **(proxy)** `proxy_connect_by_hostname = true` is required, because otherwise CONNECT goes to the IP and `dstdomain` in squid does not match.
