ARG BASE_IMAGE=ghcr.io/nvidia/openshell-community/sandboxes/base:latest
FROM ${BASE_IMAGE}

ARG HERMES_REF=main
USER root
RUN python3 -m venv /opt/hermes/.venv \
 && /opt/hermes/.venv/bin/pip install --no-cache-dir \
      "hermes-agent @ git+https://github.com/NousResearch/hermes-agent.git@${HERMES_REF}" \
 && ln -sf /opt/hermes/.venv/bin/hermes /usr/local/bin/hermes

COPY --chown=sandbox:sandbox config.yaml /sandbox/.hermes/config.yaml
ENV HERMES_HOME=/sandbox/.hermes

# The proxy from build args must not stay in the image — inside the sandbox OpenShell sets the proxy.
ENV HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy=

USER sandbox
WORKDIR /sandbox
