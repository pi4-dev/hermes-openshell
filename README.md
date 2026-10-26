<!-- README-PL.md is the Polish translation of this file — keep both in sync. -->
# openshell-env

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
- Such a token is for inference only (scope `user:inference`) and does not tell Claude Code the plan. Set `CLAUDE_PLAN` in `.env` (`pro`, `max`, `team` or `enterprise`), and the bootstrap writes it into Claude's settings in the sandbox. Claude Code then shows your plan and uses its default model (for example Opus on Max) instead of showing "Claude API". The requests use the subscription either way.
- claude.ai connectors need a full login (scope `user:mcp_servers`) and are not available with this token. Claude Code logs `Missing user:mcp_servers scope (scopes=user:inference)`. MCP servers you add in the sandbox itself (`claude mcp add`) still work, with their hosts in the policy.
- `claude/settings.json` turns off auto-updates (a rebuild updates Claude Code, see Updating Claude Code), telemetry, error reports and the automatic plugin marketplace, so Claude Code needs no host besides `api.anthropic.com`.
- The Claude sandbox is not anonymized like the Hermes one: the placeholder and `OPENSHELL_SANDBOX` show that it runs in OpenShell, and its model endpoint is api.anthropic.com anyway.

### Optional upstream proxy (Squid)

The proxy is enabled by this line in `.env`, which is on in `.env.example`. Comment it out to run without Squid:
```sh
COMPOSE_FILE=docker-compose.yml:docker-compose.proxy.yml
```

- `HTTPS_PROXY` inside the sandbox does not work by design, because the supervisor rewrites the agent's proxy environment. Squid is therefore wired in as the supervisor's upstream via `[openshell.drivers.docker] https_proxy` in `openshell/gateway.proxy.toml`.
- Access goes through two independent gates. A host must be **both** in the agent's policy, `policy/hermes-policy.yaml` or `policy/claude-policy.yaml` (OpenShell, per binary), and in `squid/whitelist.txt` (Squid, per domain).
- The gateway's own traffic, the model relay and the image builds (`pip`, `git`, `npm`, the Node and Claude Code downloads) also go through Squid.
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
| `claude/` | Claude Code sandbox image: the base sandbox image (git, Node, Python, uv, build tools), the Claude Code release from `CLAUDE_RELEASE` and Claude's settings |
| `providers/claude-subscription.yaml` | OpenShell provider profile: the subscription token, only for `claude` → `api.anthropic.com` |
| `bootstrap/` | one-off setup with the OpenShell CLI: gateway registration, provider, sandboxes |
| `policy/hermes-policy.yaml` | OpenShell policy of the Hermes sandbox (filesystem, process, network) |
| `policy/claude-policy.yaml` | OpenShell policy of the Claude Code sandbox |
| `firewall.sh` | DOCKER-USER rules: containers leave only through squid (proxy only) |

## Step-by-step setup

Steps marked **(proxy)** apply only with the upstream proxy enabled. Skip them otherwise.

1. **Requirements.** Linux with Docker Engine **28.0 or later** and the compose plugin. The kernel must support Landlock (ABI 3 or later) and seccomp. Check the Docker version:
   ```sh
   docker version --format '{{.Server.Version}}'
   ```
   Older engines fail sandbox creation with `getent unable to find entry "998:998" in passwd database`, because they look up the container user on the host.

2. **Configuration.** Copy the example:
   ```sh
   cp .env.example .env
   ```
   Then fill in `.env`:
   - `COMPOSE_FILE`: keep it to use the upstream proxy, comment it out to run without it,
   - `COMPOSE_PROFILES`: `hermes`, `claude` or `hermes,claude` (see Agents above),
   - `HOST_BRIDGE_IP`: the address of the `docker0` bridge (command below),
   - for Hermes: `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`,
   - for Claude Code: `CLAUDE_CODE_OAUTH_TOKEN`, the token from `claude setup-token` (see Claude token below), and `CLAUDE_PLAN`, your plan.

   The bridge address:
   ```sh
   ip -4 addr show docker0
   ```

3. **(proxy) IP and whitelist.** Put the same bridge IP in `https_proxy` in `openshell/gateway.proxy.toml`, because TOML does not read `.env`. Add the model backend host to `squid/whitelist.txt` (Hermes). `api.anthropic.com` (Claude Code) is already there.

4. **(proxy) Firewall (recommended).** The script blocks direct container egress to the internet, except for squid. It works only thanks to `supervisor_network_mode = "bridge"`. Do not run it without the proxy, because it would cut off all container egress.
   ```sh
   sudo sh firewall.sh
   ```

5. **(proxy) Start squid and test.**
   ```sh
   docker compose up -d squid
   curl -x http://172.17.0.1:3128 -I https://pypi.org
   ```

6. **Build the images** of the chosen agents:
   ```sh
   docker compose build
   ```
   With the proxy, do this after starting squid, because `pip`, `git`, `npm` and the Claude Code download in the build go through it. Base images and the Claude Code release check (`ADD` in `claude/Dockerfile`) are fetched by dockerd itself, so set any proxy in the daemon.

7. **Start the gateway.**
   ```sh
   docker compose up -d openshell-gateway
   curl -sf http://127.0.0.1:8081/healthz
   ```
   The port must be 8080 on both sides, because sandboxes call back to `host.openshell.internal:8080`.
   Compose first runs `openshell-init`, which writes the sandbox JWT keys to `/var/lib/openshell/tls`. The Docker driver requires them. The gateway keeps its database, keys and the extracted supervisor binary in `/var/lib/openshell` on the host and runs as root, like the `deploy/docker` setup in the OpenShell repo.

8. **Bootstrap.** The script registers the gateway and creates the sandboxes of the chosen agents with their policies; for Claude Code it first stores the token in the gateway. It also starts the model relay for Hermes and waits until it is healthy.
   ```sh
   docker compose up bootstrap
   ```
   To run it again, for example after changing the Claude token or plan in `.env`:
   ```sh
   docker compose run --rm bootstrap
   ```
   A rerun leaves existing sandboxes alone but updates the Claude token and plan. The running sandbox uses the new token for new processes within seconds.

   To change the Hermes model, key or endpoint, edit `.env` and restart only the relay; the sandbox needs no change:
   ```sh
   docker compose up -d model-relay
   ```
   If the model's context window is not 131072 tokens, set `context_length` in `hermes/config.yaml` and rebuild the image.

9. **Working with the agents.** Install the OpenShell CLI on the host, in the same version as the gateway. The `openshell` package on PyPI is only the Python SDK, and the upstream `install.sh` also sets up its own local gateway, so take the static binary from the release:
   ```
   V=0.1.5
   A=openshell-$(uname -m)-unknown-linux-musl.tar.gz
   curl -fsSLO https://github.com/NVIDIA/OpenShell/releases/download/v$V/$A
   curl -fsSLO https://github.com/NVIDIA/OpenShell/releases/download/v$V/openshell-checksums-sha256.txt
   grep " $A\$" openshell-checksums-sha256.txt | sha256sum -c
   sudo tar -xzf $A -C /usr/local/bin openshell
   ```
   Then register the gateway and start an agent:
   ```sh
   openshell gateway add http://127.0.0.1:8080 --name local
   openshell sandbox exec --tty hermes -- hermes
   openshell sandbox exec --tty claude -- claude
   ```
   `sandbox exec` starts a new process in the sandbox. A shell:
   ```sh
   openshell sandbox exec --tty hermes -- /bin/bash -l
   ```
   For continuous operation (Telegram, Slack, API), set this in `.env`:
   ```sh
   HERMES_CMD=hermes gateway run
   ```
   Then recreate the sandbox and follow the output of that gateway:
   ```sh
   openshell sandbox delete hermes
   docker compose run --rm bootstrap
   openshell sandbox connect hermes
   ```
   `sandbox connect` does not open a shell. It attaches to the sandbox's main process (`HERMES_CMD`) and replays its recent output, and it needs the host's `ssh` client. With the default `sleep infinity` it shows nothing, so it only looks like it hangs. `Ctrl-C` disconnects and leaves the main process running. For Claude Code, see the examples under Working with Claude Code.

### Claude token

`CLAUDE_CODE_OAUTH_TOKEN` is a long-lived token from `claude setup-token`, valid for a year. It needs a Claude subscription (Pro, Max, Team or Enterprise). Create it on any machine where you can log in with that account, but not in the OpenShell sandbox: its policy does not let the login through, and the real token is meant never to be there.

- **Your computer, with a browser and Claude Code:** the browser opens, and after you log in the terminal prints the token (`sk-ant-oat01-…`).
  ```sh
  claude setup-token
  ```
- **The Docker host over SSH, without a browser:** install Claude Code and run the same command. It prints a link: open it on any device, log in and paste the code you get back into the terminal.
  ```sh
  curl -fsSL https://claude.ai/install.sh | bash
  claude setup-token
  ```
- **Without installing anything on the host:** use a throwaway container from the base sandbox image, which already contains Claude Code. It is an ordinary container with normal network access, not a sandbox, and the login works as over SSH:
  ```sh
  docker run --rm -it --entrypoint claude ghcr.io/nvidia/openshell-community/sandboxes/base:latest setup-token
  ```
  With `firewall.sh` in place (proxy mode), containers cannot reach the internet directly, so use one of the first two options.

Then put the token and your plan in `.env`:
```sh
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-…
CLAUDE_PLAN=max    # or pro, team, enterprise
```
Run the bootstrap (step 8), or, if it has already run:
```sh
docker compose run --rm bootstrap
```
Treat the token like a password; `.env` is in `.gitignore`. A `CLAUDE_CODE_OAUTH_TOKEN` exported in your shell takes precedence over `.env` for `docker compose`, so remove it there:
```sh
unset CLAUDE_CODE_OAUTH_TOKEN
```
When the token expires, Claude reports `401 OAuth access token is invalid`: create a new one the same way, replace it in `.env` and run the bootstrap again. The running sandbox picks it up without being recreated.

### Web dashboard

The image contains Hermes's web dashboard, including its chat. The sandbox has no network of its own, so the dashboard listens on `127.0.0.1:9119` inside it and `openshell forward` tunnels that port to the host:

1. Run the dashboard as the sandbox's main process. Without `--skip-build`, Hermes tries to rebuild the dashboard at launch, which cannot work in the sandbox. In `.env`:
   ```sh
   HERMES_CMD=hermes dashboard --skip-build --no-open
   ```
   Then recreate the sandbox:
   ```sh
   openshell sandbox delete hermes
   docker compose run --rm bootstrap
   ```
2. On the host, open the tunnel, then open http://127.0.0.1:9119/:
   ```sh
   openshell forward start 9119 hermes -d
   ```
   To end the tunnel:
   ```sh
   openshell forward stop 9119 hermes
   ```
3. From another machine, go through SSH, then open http://127.0.0.1:9119/ there:
   ```sh
   ssh -L 9119:127.0.0.1:9119 user@docker-host
   ```

On a loopback bind the dashboard has no login and gives full control over Hermes (config, keys, sessions), so do not forward it to `0.0.0.0` or another interface.

### Model relay: health and metrics

On its API port (8082) the relay answers the sandboxes only with `/v1/models` and the inference calls. Everything else, `/health` and `/metrics` included, gets the same empty 404, and no response names the server software. Health and metrics are on a separate port, `MODEL_RELAY_OPS_ADDR` in `.env` (`127.0.0.1:9082` by default), which the sandbox policies do not allow:

- `GET /health` returns `{"status": "ok"}`. Compose uses it as the container's healthcheck, and the bootstrap waits for it. The status column then shows `healthy`:
  ```sh
  docker compose ps model-relay
  ```
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
From a Prometheus container on the compose network `osnet`, the target is `model-relay:9000`. For one on another machine, set `MODEL_RELAY_OPS_ADDR` to the host's LAN address and recreate the relay:
```sh
docker compose up -d model-relay
```

Example Grafana queries:
```
# Tokens per minute
sum by (type) (rate(model_relay_tokens_total[5m])) * 60
# p95 time to first byte
histogram_quantile(0.95, sum by (le) (rate(model_relay_time_to_first_byte_seconds_bucket[5m])))
# Failed inference calls
sum by (code) (rate(model_relay_requests_total{path!="other",code!~"2.."}[5m]))
# Requests outside the API, for example an agent probing the relay
increase(model_relay_requests_total{path="other"}[1h])
```

Tokens are counted when the backend reports usage: in every non-streamed response, and in streams only if the backend includes it.

### Working with Claude Code

Start Claude Code interactively in the sandbox. The subscription is already set up, so there is no login. The first start in a folder asks whether you trust it.
```sh
openshell sandbox exec --tty claude -- claude
```
Sessions stay in the sandbox. To resume the last one in a folder:
```sh
openshell sandbox exec --tty --workdir /sandbox/myapp claude -- claude --continue
```

The sandbox shares no folder with the host. Code goes in and out with `openshell sandbox upload` and `download`, through git, or through the output of `sandbox exec`. `upload` puts a directory *inside* the target directory, so upload to `/sandbox` or `/tmp`. For commits made in the sandbox, set a git identity once:
```sh
openshell sandbox exec claude -- git config --global user.name "Claude (sandbox)"
openshell sandbox exec claude -- git config --global user.email claude@sandbox.invalid
```

**Copy a project in and back.** From a git work tree, the upload follows `.gitignore` and skips `.git`, so `.env` files, `node_modules` and the history stay on the host:
```sh
openshell sandbox upload claude ./myapp /sandbox                # -> /sandbox/myapp
openshell sandbox exec --tty --workdir /sandbox/myapp claude -- claude
openshell sandbox download claude /sandbox/myapp ./myapp-claude
```

**With git history: a bundle in, patches out.** Claude works on a clone and commits; you review its commits and apply them on the host:
```sh
git -C ~/src/myapp bundle create /tmp/myapp.bundle --all
openshell sandbox upload claude /tmp/myapp.bundle /tmp
openshell sandbox exec --workdir /sandbox claude -- git clone /tmp/myapp.bundle myapp
openshell sandbox exec --tty --workdir /sandbox/myapp claude -- claude   # "add input validation with tests, then commit"
openshell sandbox exec --workdir /sandbox/myapp claude -- git format-patch origin/HEAD --stdout > claude.patch
git -C ~/src/myapp am < claude.patch
```
A public repository can also be cloned straight from GitHub. The sandbox has no GitHub credentials, so pushing stays on the host.
```sh
openshell sandbox exec --workdir /sandbox claude -- git clone https://github.com/<owner>/<repo>.git
```

**Headless, for scripts.** With `-p`, Claude Code runs one task and prints the result. Without permissions it only reads, so allow what the task needs:
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
```sh
openshell sandbox exec --workdir /sandbox/myapp claude -- git format-patch origin/HEAD --stdout > change.patch
openshell sandbox upload hermes change.patch /tmp
openshell sandbox exec hermes -- hermes -z "Review /tmp/change.patch: bugs, missing tests, risky changes"
```

**Updating Claude Code.** The image installs the release named by `CLAUDE_RELEASE` in `.env`: `latest` (the default), `stable` (about a week behind, with fewer regressions) or a fixed version such as `2.1.310`. Building the image installs a new release when there is one; otherwise the build comes from the cache. A sandbox keeps the image it was created from, so recreate it, after downloading what you need from it:
```sh
docker compose build claude-image
openshell sandbox download claude /sandbox/myapp ./myapp-backup
openshell sandbox delete claude
docker compose run --rm bootstrap
openshell sandbox exec claude -- claude --version
```
Newer models come with newer Claude Code releases (`/model`). The auto-updater stays off on purpose. Only `/usr/local/bin/claude` may send the token to api.anthropic.com, and it is owned by root, so the agent cannot replace it. An auto-update would install Claude Code into the sandbox's home directory, which the agent can write to.

**More Claude sandboxes**, for example one per project, all on the same subscription. Run this in the repository directory, because `--policy` is a local file:
```sh
openshell sandbox create --name claude-api --from claude-sandbox:local \
  --policy policy/claude-policy.yaml --provider claude-subscription --detach -- sleep infinity
openshell sandbox exec --tty claude-api -- claude
```

**What a project needs.**
- Tools: the image has git, Node 22, Python 3 with uv, gcc and make. Add others in `claude/Dockerfile`, then rebuild the image and recreate the sandbox. Deleting the sandbox deletes its files, so download what you need first.
  ```sh
  docker compose build claude-image
  openshell sandbox delete claude
  docker compose run --rm bootstrap
  ```
- Network: the policy lets git reach GitHub and lets npm and PyPI install packages. Add the hosts your project needs to `policy/claude-policy.yaml` (with the proxy, to `squid/whitelist.txt` too) and apply them to the running sandbox. Claude's own web fetches come from `/usr/local/bin/claude`, so name that binary for such hosts.
  ```sh
  openshell policy set claude --policy policy/claude-policy.yaml --wait
  ```
- A dev server that Claude starts on `127.0.0.1:5173` in the sandbox is reachable from the host at http://127.0.0.1:5173/ after:
  ```sh
  openshell forward start 5173 claude -d
  ```

### Switching modes later

- **Proxy off:** remove squid first, then comment out `COMPOSE_FILE` in `.env`.
  ```sh
  docker compose rm -sf squid
  ```
- **Proxy on:** uncomment `COMPOSE_FILE` and go through steps 3–5.

Then recreate the gateway with the other config, and the sandboxes so they pick up the new supervisor settings (download what you need from them first):
```sh
docker compose up -d openshell-gateway
openshell sandbox delete hermes    # and/or claude
docker compose run --rm bootstrap
```

## Verification

**Hermes:**
```sh
openshell sandbox exec hermes -- hermes -z "ping"          # an answer from the model backend
docker compose logs model-relay                              # the request: POST /v1/chat/completions
openshell policy get hermes --full                           # the model rule for host.docker.internal:8082
curl -s http://127.0.0.1:9082/health                         # {"status": "ok"}
curl -s http://127.0.0.1:9082/metrics | grep model_relay_requests_total    # counts the request
```

**Claude Code:**
```sh
openshell sandbox exec claude -- claude -p "reply with OK"           # an answer from Claude
openshell sandbox exec claude -- printenv CLAUDE_CODE_OAUTH_TOKEN    # only the placeholder: openshell:resolve:env:…
openshell logs claude | grep anthropic
```
The log should show `ALLOWED /usr/local/bin/claude(0) -> api.anthropic.com:443 [policy:_provider_claude_subscription …]`. `401 OAuth access token is invalid` means a wrong or expired token: create a new one (see Claude token), put it in `.env` and rerun the bootstrap.

A host outside the policy should be rejected by OpenShell.

**(proxy) Squid log:**
```sh
docker compose exec squid tail -f /var/log/squid/access.log
```
After a request from Hermes, the relay's `CONNECT <model-host>:443` should show up in it, and after one from Claude Code, `CONNECT api.anthropic.com:443`. A host allowed by the policy but missing from the whitelist should give `TCP_DENIED`.

## To check against the pinned OpenShell version

- Installing Hermes on the `openshell-community/sandboxes/base` image: `uv sync --frozen` from the `uv.lock` of the `HERMES_REF` checkout (plain pip cannot resolve hermes-agent's dependencies). The lock covers only Python 3.14, the base image's version. Pin `HERMES_REF`.
- The policy names the binary `/sandbox/.uv/python/**`, the real path of the base image's Python (`/usr/local/bin/python3` is a symlink to it). After changing the base image, check the path and adjust the policy:
  ```sh
  openshell sandbox exec hermes -- sh -c 'readlink -f "$(command -v python3)"'
  ```
- `claude/install-claude.py` installs the native Claude Code build from downloads.claude.ai to `/usr/local/bin/claude`, the path named in `providers/claude-subscription.yaml`, and checks its sha256 against the release manifest, like the official `install.sh`. If a new Claude Code version needs another host, the sandbox log shows it as `DENIED`:
  ```sh
  openshell logs claude | grep DENIED
  ```
- **(proxy)** `proxy_connect_by_hostname = true` is required, because otherwise CONNECT goes to the IP and `dstdomain` in squid does not match.
