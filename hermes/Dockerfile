ARG BASE_IMAGE=ghcr.io/nvidia/openshell-community/sandboxes/base:latest
FROM ${BASE_IMAGE}

# Branch, tag or commit of NousResearch/hermes-agent.
ARG HERMES_REF=main
# hermes-agent installs only with uv from its uv.lock: [tool.uv] override-dependencies resolve
# conflicts that pip cannot (browser-harness pins pillow==12.3.0, hermes-agent needs Pillow==13.0.0).
# Same uv version as pm/lock.json in hermes-agent.
ARG UV_VERSION=0.13.5
USER root
# The lock covers Python 3.14 only, which is the base image's python3; uv must not download another one.
RUN python3 -m venv /tmp/uv \
 && /tmp/uv/bin/pip install --no-cache-dir "uv==${UV_VERSION}" \
 && git init -q /opt/hermes \
 && git -C /opt/hermes fetch -q --depth 1 https://github.com/NousResearch/hermes-agent.git "${HERMES_REF}" \
 && git -C /opt/hermes checkout -q FETCH_HEAD \
 && cd /opt/hermes \
 && UV_NO_CACHE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    /tmp/uv/bin/uv sync --frozen --no-dev --compile-bytecode \
 && rm -rf /opt/hermes/.git /tmp/uv

# Web dashboard and its embedded chat (the Ink TUI), prebuilt: /opt/hermes is read-only in the
# sandbox, so Hermes must not try to build them at launch. They need the Node and npm versions
# hermes-agent pins (pm/lock.json; the base image's Node is too old), installed to /opt/node, which
# also runs the chat. Native modules compile against its headers (npm_config_nodedir), so node-gyp
# downloads nothing.
COPY install-node.py /tmp/
RUN /opt/hermes/.venv/bin/python /tmp/install-node.py /opt/hermes/pm/lock.json /opt/node \
 && cd /opt/hermes \
 && export PATH="/opt/node/bin:$PATH" npm_config_install_links=false npm_config_nodedir=/opt/node \
 && node scripts/build/node-deps.mjs --source /opt/hermes --workspace ui-tui --workspace web \
 && node scripts/build/tui.mjs --source /opt/hermes --out /opt/hermes-tui \
 && node scripts/build/web.mjs --source /opt/hermes --icons /opt/hermes --out /opt/hermes/hermes_cli/web_dist \
 && find /opt/hermes -name node_modules -type d -prune -exec rm -rf {} + \
 && rm -rf /tmp/install-node.py /root/.npm

# `hermes` starts Hermes without the sandbox runtime's markers in its environment.
COPY --chmod=755 hermes-launcher.sh /usr/local/bin/hermes
# Points only at the model relay, under a model alias; no comments, Hermes can read this file.
COPY --chown=sandbox:sandbox config.yaml /sandbox/.hermes/config.yaml
ENV HERMES_HOME=/sandbox/.hermes

# The proxy from build args must not stay in the image — inside the sandbox OpenShell sets the proxy.
ENV HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy=

USER sandbox
WORKDIR /sandbox
