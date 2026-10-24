"""Print the OpenShell provider profile for the model backend in MODEL_BASE_URL.

The sandbox gets only a placeholder in MODEL_API_KEY; OpenShell substitutes the real key
as a bearer token on requests to this host, made by the sandbox's Python (Hermes).
JSON is valid YAML, so no YAML library is needed.
"""
import json
import os
import sys
import urllib.parse

url = urllib.parse.urlsplit(os.environ["MODEL_BASE_URL"])
if url.scheme not in ("http", "https") or not url.hostname:
    raise SystemExit(f"MODEL_BASE_URL must be an http(s) URL, got {os.environ['MODEL_BASE_URL']!r}")

profile = {
    "id": "hermes-model",
    "display_name": "Hermes model backend",
    "description": f"OpenAI-compatible API at {url.hostname}",
    "category": "inference",
    "inference_capable": True,
    "credentials": [{
        "name": "api_key",
        "description": "Model backend API key",
        "env_vars": ["MODEL_API_KEY"],
        "required": True,
        "auth_style": "bearer",
        "header_name": "authorization",
    }],
    "endpoints": [{
        "host": url.hostname,
        "port": url.port or (443 if url.scheme == "https" else 80),
        "protocol": "rest",
        "access": "read-write",
        "enforcement": "enforce",
    }],
    # Real path of the base image's Python (uv-managed; /usr/local/bin/python3 is a symlink).
    # Processes it starts are covered too.
    "binaries": ["/sandbox/.uv/python/**"],
}
# Given the exported current profile, carry over its resource_version: `openshell profile update` requires it.
if len(sys.argv) > 1:
    with open(sys.argv[1]) as current:
        profile["resource_version"] = json.load(current)["resource_version"]
print(json.dumps(profile, indent=2))
