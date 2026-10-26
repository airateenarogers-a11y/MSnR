"""Rebuild source traceability without modifying the authoritative source files."""

from pathlib import Path
import hashlib
import json
import re

root = Path(__file__).resolve().parents[1]
requirements = json.loads((root / "docs/requirements.json").read_text())
bindings = {
    "1": (
        ["docs/ARCHITECTURE.md", "docs/DECISIONS.md"],
        [],
        "Narrative / glossary; no numeric probability or institutional-intent claim is executed",
    ),
    "2": (
        ["src/msnr/domain.py", "src/msnr/data.py", "src/msnr/strategy/primitives.py"],
        ["tests/test_strategy.py", "tests/test_engine_pipeline.py"],
        "Implemented; primitive and representative pipeline tests",
    ),
    "3": (
        ["src/msnr/strategy/primitives.py"],
        ["tests/test_strategy.py", "tests/test_engine_pipeline.py"],
        "Implemented with user-approved junction, GAP and CC definitions",
    ),
    "4": (
        ["src/msnr/strategy/primitives.py", "src/msnr/strategy/engine.py"],
        ["tests/test_strategy.py", "tests/test_engine_pipeline.py"],
        "Implemented; full positive/negative historical corpus not validated",
    ),
    "5": (
        ["src/msnr/strategy/primitives.py", "src/msnr/strategy/engine.py"],
        ["tests/test_strategy.py", "tests/test_engine_pipeline.py"],
        "Implemented; body-close, external-reference and latest-touch tests",
    ),
    "6": (
        ["src/msnr/strategy/engine.py", "src/msnr/data.py"],
        ["tests/test_engine_pipeline.py", "tests/test_strategy.py"],
        "Implemented; advanced storyline requires verified complete level history",
    ),
    "7": (
        ["src/msnr/clock.py", "src/msnr/strategy/primitives.py", "src/msnr/strategy/engine.py"],
        ["tests/test_strategy.py", "tests/test_integrations.py"],
        "Implemented with approved NY/DST and SMT scope; real peer/feed validation pending",
    ),
    "8": (
        ["src/msnr/strategy/catalog.py", "src/msnr/strategy/engine.py", "src/msnr/strategy/primitives.py"],
        ["tests/test_strategy.py", "tests/test_engine_pipeline.py", "tests/test_bridge_and_worker.py"],
        "18 named models gated; raw-candle LS/nested-QM pipeline tested; all-model historical validation pending",
    ),
    "9": (
        ["src/msnr/risk.py", "src/msnr/execution.py", "src/msnr/worker.py", "src/msnr/analytics.py"],
        ["tests/test_execution.py", "tests/test_recovery_and_controls.py", "tests/test_bridge_and_worker.py"],
        "Implemented risk and management controls; live MT5 verification pending; human guidance remains human",
    ),
    "10": (
        ["src/msnr/strategy/engine.py", "src/msnr/store.py", "src/msnr/api.py", "docs/DECISIONS.md"],
        ["tests/test_strategy.py", "tests/test_execution.py", "tests/test_integrations.py"],
        "Conflict decisions versioned; checklist evidence and append-only journaling implemented",
    ),
}
atomic = []
for r in requirements:
    source = root / "docs/sources" / f"strategy-{r['version']}.md"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == r["source_sha256"]
    if r["version"] == "v3":
        r.update(
            status="Reference only — not executed", implementation=["docs/sources/strategy-v3.md"], tests=[]
        )
    else:
        impl, tests, status = bindings[r["section"].split(".")[0]]
        r.update(status=status, implementation=impl, tests=tests)
        if r["section"] in ("9.1", "10.1", "1.1", "1.2", "1.4"):
            r["status"] = "Narrative / human protocol; documented, not fabricated as a machine confirmation"
        for offset, line in enumerate(r["text"].splitlines()):
            stripped = line.strip()
            if not stripped or stripped.startswith(("```", "---", "###", "+", "| :")):
                continue
            # Preserve prose and table clauses verbatim. Diagrams remain in full subsection text.
            if re.match(r"^(?:[-*]|\d+\.|\||\[ \])", stripped) or len(stripped) > 70:
                atomic.append(
                    {
                        "id": r["id"] + "-L" + str(r["start_line"] + offset),
                        "parent": r["id"],
                        "source_line": r["start_line"] + offset,
                        "text": line,
                        "implementation": impl,
                        "tests": tests,
                        "status": r["status"],
                    }
                )
    for path in r["implementation"] + r["tests"]:
        assert (root / path).is_file(), path
(root / "docs/requirements.json").write_text(json.dumps(requirements, indent=2, ensure_ascii=False) + "\n")
(root / "docs/atomic-requirements.json").write_text(json.dumps(atomic, indent=2, ensure_ascii=False) + "\n")
header = """# Source compliance matrix

V4 is authoritative. `DECISIONS.md` records explicit user overrides. V3 is reference only.
Every numbered source subsection is retained with full text, line ranges and immutable source hashes in `requirements.json`.
`atomic-requirements.json` maps individual prose/list/table clauses to the same implementation and tests.
Mappings identify responsibility and existing tests; they do **not** assert that every discretionary model has been validated on real markets.
Human psychology, education and authors' performance assertions are not fabricated into automated entry evidence.

| ID | Source section | Implementation | Existing tests | Current status |
|---|---|---|---|---|
"""
rows = []
for r in requirements:
    source = f"[§{r['section']}](sources/strategy-{r['version']}.md#L{r['start_line']})"
    impl = "<br>".join(f"[{Path(p).name}](../{p})" for p in r["implementation"])
    tests = "<br>".join(f"[{Path(p).name}](../{p})" for p in r["tests"]) or "Not an executable requirement"
    rows.append(f"| {r['id']} | {source} {r['title'].replace('|', '/')} | {impl} | {tests} | {r['status']} |")
(root / "docs/COMPLIANCE_MATRIX.md").write_text(header + "\n".join(rows) + "\n")
print(
    f"Traceability: {len(requirements)} subsections, {len(atomic)} v4 source clauses; all source hashes verified."
)
