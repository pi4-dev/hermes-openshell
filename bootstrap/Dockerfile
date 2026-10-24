FROM python:3.12-slim
ARG OPENSHELL_CLI_VERSION=
RUN pip install --no-cache-dir "openshell${OPENSHELL_CLI_VERSION:+==$OPENSHELL_CLI_VERSION}"
ENV HTTP_PROXY= HTTPS_PROXY=
COPY bootstrap.sh /bootstrap.sh
ENTRYPOINT ["/bin/sh", "/bootstrap.sh"]
