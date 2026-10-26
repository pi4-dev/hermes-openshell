# Claude Code sandbox: the base image brings git, Node, Python with uv and build tools; Claude Code
# itself is replaced with the release in CLAUDE_RELEASE (.env). To update: docker compose build
# claude-image, then recreate the sandbox.
FROM ghcr.io/nvidia/openshell-community/sandboxes/base:latest

USER root
# Toolchains for your projects go here: the sandbox cannot install system packages at runtime.
# RUN apt-get update && apt-get install -y --no-install-recommends golang-go && rm -rf /var/lib/apt/lists/*

# Claude Code: latest, stable or a version such as 2.1.310. It stays at /usr/local/bin/claude,
# the path in providers/claude-subscription.yaml, owned by root, so the agent cannot replace it.
# The channel files name the current releases, and a new release invalidates the build cache.
ARG CLAUDE_RELEASE=latest
ADD https://downloads.claude.ai/claude-code-releases/latest https://downloads.claude.ai/claude-code-releases/stable /tmp/claude-release/
COPY install-claude.py /tmp/
RUN python3 /tmp/install-claude.py "$CLAUDE_RELEASE" /usr/local/bin/claude /tmp/claude-release \
 && rm -rf /tmp/install-claude.py /tmp/claude-release

# claude.json: the token comes from the provider, so skip the first-run login screen.
# settings.json: no auto-updates (updates come with a rebuild), telemetry, error reports or
# automatic plugin marketplace, which the policy would block anyway, and no checks for a per-user
# install (~/.local/bin/claude). OpenShell does not pass the image's ENV to sandbox processes, so
# these go in Claude's settings.
COPY --chown=sandbox:sandbox claude.json /sandbox/.claude.json
COPY --chown=sandbox:sandbox settings.json /sandbox/.claude/settings.json

USER sandbox
WORKDIR /sandbox
