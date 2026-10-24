FROM python:3.12-slim
# The openshell package on PyPI is only the Python SDK; the CLI is a static binary from GitHub releases.
ARG OPENSHELL_CLI_VERSION=
COPY install-openshell-cli.py /tmp/
RUN python /tmp/install-openshell-cli.py /usr/local/bin && rm /tmp/install-openshell-cli.py
ENV HTTP_PROXY= HTTPS_PROXY=
COPY bootstrap.sh /
ENTRYPOINT ["/bin/sh", "/bootstrap.sh"]
