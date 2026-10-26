import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


def test_downloadable_launcher_matches_reviewed_sources(tmp_path):
    for folder in ("deployment", "scripts"):
        (tmp_path / folder).mkdir()
    for name in (
        "deployment/windows-release.json",
        "deployment/windows-bootstrap.ps1",
        "scripts/build_windows_launcher.py",
    ):
        shutil.copyfile(name, tmp_path / name)
    subprocess.run([sys.executable, str(tmp_path / "scripts/build_windows_launcher.py")], check=True)
    assert (tmp_path / "Install-MSnR.cmd").read_bytes() == Path("Install-MSnR.cmd").read_bytes()


def test_download_is_pinned_and_contains_no_placeholder_or_live_enablement():
    release = json.loads(Path("deployment/windows-release.json").read_text())
    assert re.fullmatch(r"[0-9a-f]{40}", release["commit"])
    assert re.fullmatch(r"[0-9a-f]{64}", release["sha256"])
    payload = Path("Install-MSnR.cmd").read_bytes()
    assert payload.count(b"\r\n") == payload.count(b"\n")
    assert b"__SOURCE_COMMIT__" not in payload and b"__SOURCE_SHA256__" not in payload
    assert release["commit"].encode() in payload and release["sha256"].encode() in payload
    assert b"EXPLICITLY_AUTHORIZED" not in payload
    assert b"-ExecutionPolicy Bypass" not in payload
