"""Build the Docker runtime when the Docker build namespace has no package egress."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
os.chdir(root)
cache = root / "var/cache/pip"
os.environ.setdefault("PIP_CACHE_DIR", str(cache))
os.environ.setdefault("DOCKER_CONFIG", str(root / "var/cache/docker"))
wheels = root / "var/wheelhouse"
wheels.mkdir(parents=True, exist_ok=True)
subprocess.run(
    [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--require-hashes",
        "--only-binary=:all:",
        "-r",
        "requirements.lock",
        "--dest",
        str(wheels),
    ],
    check=True,
)
subprocess.run(
    [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheels), "."], check=True
)
with tempfile.TemporaryDirectory(prefix="docker-context-", dir=root / "var") as name:
    context = Path(name)
    shutil.copytree(wheels, context / "wheelhouse")
    for directory in ("config", "docs"):
        shutil.copytree(root / directory, context / directory)
    shutil.copy2(root / "requirements.lock", context / "requirements.lock")
    shutil.copy2(root / "deployment/Dockerfile.offline", context / "Dockerfile")
    subprocess.run(
        ["docker", "build", "--network=none", "-t", "msnr-terminal:local", str(context)], check=True
    )
