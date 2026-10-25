"""Install the Node.js and npm versions hermes-agent pins in pm/lock.json, verified by sha256.

Usage: install-node.py <pm/lock.json> <prefix>. The base image's Node is older than hermes-agent
requires; this one builds the dashboard and runs its chat (the Ink TUI).
"""
import hashlib
import io
import json
import platform
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

lock, prefix = json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2])
arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}[platform.machine()]


def fetch(package: str, artifact: str) -> bytes:
    entry = lock["packages"][package]["artifacts"][artifact]
    with urllib.request.urlopen(entry["url"], timeout=300) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise SystemExit(f"checksum mismatch for {entry['url']}")
    return data


def extract(data: bytes, target: Path) -> None:
    """Extract an archive whose files all sit under one top-level directory into target."""
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive.getmembers():
            member.name = member.name.partition("/")[2]
            if member.name:
                archive.extract(member, target, filter="tar")


extract(fetch("node", f"linux-{arch}"), prefix)
npm = prefix / "lib/node_modules/npm"
shutil.rmtree(npm)
extract(fetch("npm", "any"), npm)
print(f"installed node {lock['packages']['node']['version']} and npm {lock['packages']['npm']['version']} to {prefix}")
