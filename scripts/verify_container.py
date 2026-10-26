"""Check the built Linux image with a disposable database and transient credential."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import uuid

import httpx


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    (root / "var").mkdir(exist_ok=True)
    os.environ.setdefault("DOCKER_CONFIG", str(root / "var/cache/docker"))
    name = "msnr-verification-" + uuid.uuid4().hex[:8]
    token = secrets.token_urlsafe(32)
    fd, secretpath = tempfile.mkstemp(prefix="container-test-", dir=root / "var")
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as secret:
        secret.write("MSNR_OPERATOR_TOKEN=" + token + "\n")

    def docker(*args):
        return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout.strip()

    try:
        docker(
            "run",
            "--detach",
            "--name",
            name,
            "--env-file",
            secretpath,
            "--publish",
            "127.0.0.1::8000",
            "msnr-terminal:local",
        )
        port = docker("port", name, "8000/tcp").rsplit(":", 1)[1]
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            for _ in range(60):
                try:
                    health = client.get("/health", timeout=2)
                    if health.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.25)
            else:
                raise RuntimeError("Health endpoint unavailable: " + docker("logs", name)[-2000:])
            status = client.get("/api/status", headers={"Authorization": "Bearer " + token})
            assert status.status_code == 200, status.status_code
            assert status.json()["mode"] == "paper"
            denied = client.get("/api/status")
            assert denied.status_code == 401
            assert docker("exec", name, "id", "-u") == "10001"
            # Repeated one-shot workers must release their leases and wait without a broker.
            docker("exec", name, "msnr", "worker", "--once")
            docker("exec", name, "msnr", "worker", "--once")
            doctor = json.loads(docker("exec", name, "msnr", "doctor"))
            assert doctor["journal_integrity"]
            result = {
                "validated_at": datetime.now(timezone.utc).isoformat(),
                "image_id": docker("image", "inspect", "--format", "{{.Id}}", "msnr-terminal:local"),
                "health": health.json(),
                "authenticated_status": status.status_code,
                "unauthenticated_status": denied.status_code,
                "mode": status.json()["mode"],
                "container_uid": 10001,
                "worker": doctor["worker"],
                "journal_integrity": doctor["journal_integrity"],
                "scope": "Disposable Linux container; no broker or Discord credentials",
            }
            Path("artifacts").mkdir(exist_ok=True)
            Path("artifacts/container-validation.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
    finally:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True)
        Path(secretpath).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
