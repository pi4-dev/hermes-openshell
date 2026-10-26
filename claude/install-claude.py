"""Install the native Claude Code build, verified by sha256 like the official install.sh.

Usage: install-claude.py <latest|stable|VERSION> <target> [channel dir]. A channel is read from
the channel dir when it holds that file (the Dockerfile ADDs them), otherwise downloaded. The
checksum comes from the release manifest at downloads.claude.ai; the base image's Claude Code is older.
"""
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request

BASE = "https://downloads.claude.ai/claude-code-releases"
wanted, target, channels = sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None
arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}[platform.machine()]


def fetch(url):
    return urllib.request.urlopen(url, timeout=300)


version = wanted
if wanted in ("latest", "stable"):
    channel = os.path.join(channels, wanted) if channels else None
    with open(channel, "rb") if channel and os.path.exists(channel) else fetch(f"{BASE}/{wanted}") as f:
        version = f.read().decode().strip()
if not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?", version):
    raise SystemExit(f"not a Claude Code version: {version!r}")
checksum = json.load(fetch(f"{BASE}/{version}/manifest.json"))["platforms"][f"linux-{arch}"]["checksum"]

digest, partial = hashlib.sha256(), target + ".download"
with fetch(f"{BASE}/{version}/linux-{arch}/claude") as response, open(partial, "wb") as out:
    while chunk := response.read(1 << 20):
        digest.update(chunk)
        out.write(chunk)
if digest.hexdigest() != checksum:
    os.remove(partial)
    raise SystemExit(f"checksum mismatch for Claude Code {version}")
os.chmod(partial, 0o755)
shutil.move(partial, target)
print(subprocess.run([target, "--version"], capture_output=True, text=True, check=True).stdout.strip())
