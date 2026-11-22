"""
arena/reports.py
Generates incident reports data/reports/R0.md, R1.md, R2.md from round results.
Owner: Nehaa (WS-C C6)
"""
import json
from pathlib import Path

from contracts.models import Results


def _determine_stopped_by(outcome: str, round_id: str, gate_blocked: bool) -> str:
    if outcome == "blocked_by_gate" or gate_blocked:
        return "Gate"
    if outcome == "succeeded":
        return "None (Bypassed)"
    if round_id == "R2":
        return "Patch"
    return "Worker"


def generate_reports(
    results: Results,
    output_dir: str | Path = "data/reports",
    cache_hits: int = 0,
) -> list[Path]:
    """
    Generate markdown incident reports data/reports/R0.md, R1.md, R2.md from Results.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_files = []

    profile_map = {
        "R0": ("L0", "Baseline (No Defense)"),
        "R1": ("L1", "Lyzr Screening Gate"),
        "R2": ("L2", "Patched Worker & Active Gate"),
    }

    for round_res in results.rounds:
        r_id = round_res.id
        level, defense_desc = profile_map.get(r_id, ("Unknown", "Custom"))
        lines = []

        lines.append(f"# Trust Fall Incident Report — Round {r_id}")
        lines.append(f"**Defense Level:** `{level}` — {defense_desc}  ")
        lines.append(f"**Run ID:** `{results.run_id}` | **Generated:** `{results.generated_at}`\n")
        lines.append("---")

        # Summary KPIs
        lines.append("## Executive Summary\n")
        heldout_str = (
            f"{round_res.asr_heldout:.1%}"
            if round_res.asr_heldout is not None
            else "N/A"
        )
        benign_pct = (
            f"{round_res.benign.passed / round_res.benign.total:.1%}"
            if round_res.benign.total > 0
            else "100.0%"
        )

        lines.append(f"- **Attack Success Rate (Total):** `{round_res.asr:.1%}`")
        lines.append(f"- **ASR (Known Attacks):** `{round_res.asr_known:.1%}`")
        lines.append(f"- **ASR (Held-out Attacks):** `{heldout_str}`")
        lines.append(f"- **Benign Regression Pass Rate:** `{round_res.benign.passed}/{round_res.benign.total} ({benign_pct})`")
        lines.append(f"- **Gate Blocks:** `{round_res.gate_blocks}`")
        lines.append(f"- **LLM Calls:** `{round_res.llm_calls}`")
        lines.append(f"- **Lyzr Detector Calls:** `{round_res.lyzr_calls}`")
        lines.append(f"- **Cache Hits:** `{cache_hits}`\n")

        # Attack Table
        lines.append("## Attack Evaluations\n")
        lines.append("| ID | Category | OWASP | Goal | Known | Outcome | Layer Decided | Latency |")
        lines.append("|---|---|---|---|---|---|---|---|")

        for att in round_res.attacks:
            gate_blocked = bool(att.gate and att.gate.get("blocked"))
            stopped_by = _determine_stopped_by(att.outcome, r_id, gate_blocked)
            known_str = "Yes" if att.known else "**Held-out**"
            lines.append(
                f"| `{att.id}` | {att.category} | {att.owasp} | {att.goal} | {known_str} | **{att.outcome}** | {stopped_by} | {att.latency_ms}ms |"
            )

        lines.append("")

        # R2 specific: Patch History & Diff
        if r_id == "R2":
            lines.append("## Defender Patch Decisions & History\n")
            if results.patches:
                lines.append("| Version | Status | Reason | Summary | Safety Test (Demo) |")
                lines.append("|---|---|---|---|---|")
                for p in results.patches:
                    reason = p.reason or "Passed validation & regression"
                    is_demo = "Yes" if getattr(p, "demo", False) else "No"
                    lines.append(
                        f"| v{p.version} | `{p.status}` | {reason} | {p.summary} | {is_demo} |"
                    )
                lines.append("")

                # Patch details
                applied_patches = [p for p in results.patches if p.status == "applied"]
                if applied_patches and applied_patches[-1].patch:
                    active = applied_patches[-1].patch
                    lines.append("### Active Patch Specification (v%s)\n" % active.version)
                    lines.append("```json")
                    lines.append(json.dumps(active.model_dump(exclude_none=True), indent=2))
                    lines.append("```\n")
            else:
                lines.append("_No patch changes recorded in this run._\n")

        report_file = out_dir / f"{r_id}.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        generated_files.append(report_file)

    return generated_files
