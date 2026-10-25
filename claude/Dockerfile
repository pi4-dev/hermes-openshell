# Claude Code sandbox: the base image already contains Claude Code (/usr/local/bin/claude), git,
# Node, Python with uv, and build tools. A newer Claude Code comes with a newer base image:
# docker compose build --pull claude-image, then recreate the sandbox.
FROM ghcr.io/nvidia/openshell-community/sandboxes/base:latest

# Toolchains for your projects go here: the sandbox cannot install system packages at runtime.
# USER root
# RUN apt-get update && apt-get install -y --no-install-recommends golang-go && rm -rf /var/lib/apt/lists/*

# claude.json: the token comes from the provider, so skip the first-run login screen.
# settings.json: no auto-updates, telemetry, error reports or automatic plugin marketplace, which
# the policy would block anyway, and no checks for a per-user install (~/.local/bin/claude).
# OpenShell does not pass the image's ENV to sandbox processes, so these go in Claude's settings.
COPY --chown=sandbox:sandbox claude.json /sandbox/.claude.json
COPY --chown=sandbox:sandbox settings.json /sandbox/.claude/settings.json

USER sandbox
WORKDIR /sandbox
