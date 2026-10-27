from dataclasses import dataclass


@dataclass(frozen=True)
class SetupRule:
    name: str
    section: str
    phases: tuple[int, ...]
    requirements: tuple[str, ...]
    hybrid: bool = False


CATALOG = (
    SetupRule("APEX", "8.1", (1,), ("apex_entry", "apex_refinement")),
    SetupRule("LS", "8.1", (1,), ("shoulder_entry", "ls_badge")),
    SetupRule("SBR_RBS", "8.1", (1,), ("flip_entry", "flip_badge")),
    SetupRule("ERS", "8.1", (1,), ("ers_entry", "tl_alignment")),
    SetupRule("GAP_QMS", "8.1", (1,), ("gap_entry", "gap_alignment")),
    SetupRule("C_APEX", "8.2", (2, 3), ("apex_entry", "continuation")),
    SetupRule("GAP_CONTINUATION", "8.2", (2, 3), ("gap_entry", "continuation")),
    SetupRule("SBR_RBS_CONTINUATION", "8.2", (2, 3), ("flip_entry", "continuation")),
    SetupRule("QMC", "8.3", (2, 3), ("nested_qm", "continuation")),
    SetupRule("QM_TO_QM", "8.3", (1, 2, 3), ("nested_qm", "shoulder_entry")),
    SetupRule("REVERSAL_TL_QM_FAILED", "8.3", (1,), ("failed_qm", "tl_alignment")),
    SetupRule("MISS", "8.3", (1,), ("miss_entry", "ers_or_ocl")),
    SetupRule("DOUBLE_APEX", "8.3", (1,), ("double_apex", "apex_entry")),
    SetupRule("SNRC1", "8.3", (2, 3), ("fresh_av", "third_touch", "continuation")),
    SetupRule("EX1", "8.4", (1,), ("h1_ocl", "m15_shift", "micro_ocl_retest"), True),
    SetupRule("EX2", "8.4", (1,), ("h1_flip", "m3_shift", "inducement", "q3", "smt"), True),
    SetupRule("EX3", "8.4", (1,), ("h1_tl_key", "m3_tl_break", "smt"), True),
    SetupRule("EX4", "8.4", (1,), ("asia_sweep", "h1_poi", "m5_shift", "smt"), True),
)
COMMON = (
    "source_valid",
    "htf_rejection",
    "external_qm",
    "mtf_mapping",
    "badge",
    "entry_retest",
    "targets",
    "stop_buffer",
    "session",
    "q3",
    "crt_boundary",
)
RATING_ORDER = {"C": 0, "B": 1, "A": 2, "A+": 3}

# V5 plus the user's explicit EX/ERS clarifications. Hybrid filters are model-specific.
CATALOG_V5 = tuple(m for m in CATALOG if m.name not in ("ERS", "EX1", "EX2", "EX3", "EX4")) + (
    SetupRule("ERS", "8.1", (1,), ("ers_entry", "early_structure", "storyline_alignment")),
    SetupRule("EX1", "9.1", (1,), ("h1_poi", "micro_reversal", "liquidity_sweep", "smt")),
    SetupRule("EX2", "9.1", (1,), ("h1_flip", "ema9_hold")),
    SetupRule("EX3", "9.1", (1,), ("h1_poi", "session_sweep", "micro_reversal", "smt")),
    SetupRule("EX4", "9.1", (1,), ("h1_ocl_or_gap", "m5_badge")),
    SetupRule("QT_SMT", "11.2", (1, 2), ("q3", "q2_sweep", "smt", "session")),
    SetupRule("CIRCLE_FIB", "12.1", (1, 2), ("ote", "smt")),
)


def catalog(version):
    return CATALOG_V5 if version == "v5" else CATALOG


def requirements(model, version):
    common = COMMON
    if version == "v5":
        common = tuple(x for x in COMMON if x not in ("session", "q3", "crt_boundary"))
        common += ("storyline_alignment", "entry_zone_badge", "tp1_rr")
        if model.name == "ERS":
            common = tuple(x for x in common if x not in ("external_qm", "entry_retest"))
    return tuple(dict.fromkeys(common + model.requirements + ("phase",)))


def rating(optional_facts: dict[str, bool | None]) -> tuple[str, int, list[str]]:
    """Confluence coverage, never a win probability; fixed published criteria."""
    passed = [key for key, value in optional_facts.items() if value is True]
    n = len(passed)
    return (
        "A+" if n >= 3 else "A" if n == 2 else "B" if n == 1 else "C",
        round(100 * n / max(1, len(optional_facts))),
        passed,
    )
