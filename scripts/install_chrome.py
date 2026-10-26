"""Install a verified official Google Chrome package under a user-writable path.

Linux amd64 only. Downloads use HTTPS with normal trust validation; the binary
must match the SHA-256 in Google's HTTPS package index before extraction.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, default=Path("/workspace/tools/chrome"))
args = parser.parse_args()
if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
    raise SystemExit("Use the vendor Chrome installer on this platform")
base = "https://dl.google.com/linux/chrome/deb/"
with urllib.request.urlopen(base + "dists/stable/main/binary-amd64/Packages.gz", timeout=30) as response:
    index = gzip.decompress(response.read()).decode()
blocks = [b for b in index.split("\n\n") if b.startswith("Package: google-chrome-stable\n")]
if len(blocks) != 1:
    raise SystemExit("Unambiguous Chrome package metadata unavailable")
fields = dict(
    line.split(": ", 1) for line in blocks[0].splitlines() if ": " in line and not line.startswith(" ")
)
if not fields["Filename"].startswith("pool/main/g/google-chrome-stable/"):
    raise SystemExit("Unexpected vendor package path")
with tempfile.TemporaryDirectory(prefix="msnr-chrome-") as temporary:
    package = Path(temporary) / "chrome.deb"
    with (
        urllib.request.urlopen(base + fields["Filename"], timeout=120) as response,
        package.open("wb") as out,
    ):
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
    if hashlib.file_digest(package.open("rb"), "sha256").hexdigest() != fields["SHA256"]:
        raise SystemExit("Chrome checksum verification failed; package will not be used")
    args.directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(["dpkg-deb", "-x", str(package), str(args.directory)], check=True)
    (args.directory / "verified-package.json").write_text(
        json.dumps({k: fields[k] for k in ("Version", "Filename", "SHA256")}, indent=2)
    )
subprocess.run([str(args.directory / "opt/google/chrome/chrome"), "--version"], check=True)
