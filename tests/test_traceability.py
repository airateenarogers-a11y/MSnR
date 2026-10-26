from pathlib import Path
import hashlib
import json
import re


def test_every_source_section_and_hash_is_preserved():
    root = Path(__file__).resolve().parents[1]
    requirements = json.loads((root / "docs/requirements.json").read_text())
    for version in ("v3", "v4"):
        raw = (root / "docs/sources" / f"strategy-{version}.md").read_bytes()
        actual = set(re.findall(r"^### (\d+\.\d+) ", raw.decode(), re.MULTILINE))
        mapped = {r["section"] for r in requirements if r["version"] == version}
        assert actual == mapped
        assert all(
            r["source_sha256"] == hashlib.sha256(raw).hexdigest()
            for r in requirements
            if r["version"] == version
        )
    for requirement in requirements:
        assert requirement["implementation"]
        assert all((root / path).is_file() for path in requirement["implementation"] + requirement["tests"])
