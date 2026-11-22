#!/usr/bin/env python3
"""
Digest utility for Trust Fall.
Prints phase statuses from STATUS_*.md, open questions from QUESTIONS_*.md,
open blockers from BLOCKERS_*.md, and last 20 CALL_LEDGER.md lines.
"""
from pathlib import Path

def print_section(title, content):
    print("=" * 60)
    print(f" {title}")
    print("=" * 60)
    print(content.strip() if content.strip() else "(None)")
    print()

def read_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="ignore")
    return "(File not found)"

def main():
    root = Path(__file__).resolve().parent.parent
    docs = root / "docs"

    status_nikhil = read_file(docs / "STATUS_NIKHIL.md")
    status_nehaa = read_file(docs / "STATUS_NEHAA.md")
    q_nikhil = read_file(docs / "QUESTIONS_NIKHIL.md")
    q_nehaa = read_file(docs / "QUESTIONS_NEHAA.md")
    b_nikhil = read_file(docs / "BLOCKERS_NIKHIL.md")
    b_nehaa = read_file(docs / "BLOCKERS_NEHAA.md")
    ledger = read_file(docs / "CALL_LEDGER.md")

    ledger_lines = [l for l in ledger.splitlines() if l.strip() and not l.startswith("#")]
    recent_ledger = "\n".join(ledger_lines[-20:]) if ledger_lines else "(No API calls logged)"

    print_section("STATUS: NIKHIL", status_nikhil)
    print_section("STATUS: NEHAA", status_nehaa)
    print_section("OPEN QUESTIONS: NIKHIL", q_nikhil)
    print_section("OPEN QUESTIONS: NEHAA", q_nehaa)
    print_section("BLOCKERS: NIKHIL", b_nikhil)
    print_section("BLOCKERS: NEHAA", b_nehaa)
    print_section("CALL LEDGER (LAST 20 CALLS)", recent_ledger)

if __name__ == "__main__":
    main()
