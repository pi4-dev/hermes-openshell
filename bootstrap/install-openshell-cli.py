"""Install the static OpenShell CLI from GitHub releases, verified against the release checksums.

The openshell package on PyPI is only the Python SDK and has no CLI.
OPENSHELL_CLI_VERSION: release version such as 0.1.5; empty = latest release.
"""
import hashlib
import io
import os
import platform
import sys
import tarfile
import urllib.request

version = os.environ.get("OPENSHELL_CLI_VERSION", "").strip().removeprefix("v")
base = "https://github.com/NVIDIA/OpenShell/releases/" + (f"download/v{version}" if version else "latest/download")
arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}[platform.machine()]
asset = f"openshell-{arch}-unknown-linux-musl.tar.gz"
target = sys.argv[1] if len(sys.argv) > 1 else "/usr/local/bin"


def fetch(name: str) -> bytes:
    with urllib.request.urlopen(f"{base}/{name}", timeout=300) as response:
        return response.read()


checksums = {}
for line in fetch("openshell-checksums-sha256.txt").decode().splitlines():
    if line.strip():
        digest, name = line.split(maxsplit=1)
        checksums[name.lstrip("*")] = digest

archive = fetch(asset)
if hashlib.sha256(archive).hexdigest() != checksums.get(asset):
    raise SystemExit(f"checksum mismatch for {asset}")

with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
    binary = tar.extractfile("openshell").read()
path = os.path.join(target, "openshell")
with open(path, "wb") as out:
    out.write(binary)
os.chmod(path, 0o755)
print(f"installed {asset} from {base} to {path}")
