#!/usr/bin/env python3
"""
Self-verify reports/e2e_verification_audit.md tally consistency.

For each test-file section, parse the verdict column of every row in the
section's table and count PASS / WEAK / INADEQUATE / N/A symbols. Cross-check
against (a) the section's own "File verdict: ..." line and (b) the Summary
Matrix row for that filename.

Exit 0 on full consistency, 1 on any mismatch.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parent.parent / "reports" / "e2e_verification_audit.md"

PASS_SYM = "\u2705"
WEAK_SYM = "\u26a0"
INADEQ_SYM = "\u274c"

SECTION_RE = re.compile(
    r"^(?:# Section \d+|## \d+\.)\s+\u2014?\s*(?P<file>\S+\.(?:py|spec\.ts))"
)
VERDICT_LINE_RE = re.compile(r"^\*\*File verdict\*\*:\s*(?P<body>.+)$")
SUMMARY_ROW_RE = re.compile(
    r"^\|\s*(?P<file>[^|]+?)\s*\|"
    r"\s*(?P<p>\d+)\s*\|"
    r"\s*(?P<w>\d+)\s*\|"
    r"\s*(?P<i>\d+)\s*\|"
    r"\s*(?P<n>\d+)\s*\|"
    r"\s*(?P<t>\d+)\s*\|\s*$"
)
TOTAL_ROW_RE = re.compile(
    r"^\|\s*\*\*TOTAL\*\*\s*\|"
    r"\s*\*\*(?P<p>\d+)\*\*\s*\|"
    r"\s*\*\*(?P<w>\d+)\*\*\s*\|"
    r"\s*\*\*(?P<i>\d+)\*\*\s*\|"
    r"\s*\*\*(?P<n>\d+)\*\*\s*\|"
    r"\s*\*\*(?P<t>\d+)\*\*\s*\|\s*$"
)
ALL_N_TESTS_RE = re.compile(r"All\s+(\d+)\s+tests", re.IGNORECASE)


def count_symbols(line: str) -> tuple[int, int, int, int]:
    p = line.count(PASS_SYM)
    w = line.count(WEAK_SYM)
    i = line.count(INADEQ_SYM)
    n = 0
    if re.search(r"\|\s*N/A\s*\|", line) or re.search(r"\|\s*N/A\s*\u2014", line):
        bulk = ALL_N_TESTS_RE.search(line)
        n = int(bulk.group(1)) if bulk else 1
    return p, w, i, n


def parse_file_verdict(body: str) -> tuple[int, int, int, int]:
    p = w = i = n = 0
    for match in re.finditer(r"(\d+)/\d+\s*(\S)", body):
        num, sym = int(match.group(1)), match.group(2)
        if sym == PASS_SYM:
            p = num
        elif sym == WEAK_SYM:
            w = num
        elif sym == INADEQ_SYM:
            i = num
    n_match = re.search(r"(\d+)/\d+\s*N/A", body)
    if n_match:
        n = int(n_match.group(1))
    return p, w, i, n


def main() -> int:
    content = AUDIT.read_text(encoding="utf-8").splitlines()

    sections: dict[str, dict[str, tuple[int, int, int, int]]] = {}
    current_file: str | None = None
    row_tally = (0, 0, 0, 0)
    in_table = False

    for line in content:
        m = SECTION_RE.match(line)
        if m:
            if current_file is not None:
                sections.setdefault(current_file, {})["rows"] = row_tally
            current_file = os.path.basename(m.group("file").strip())
            row_tally = (0, 0, 0, 0)
            in_table = False
            continue
        if current_file is None:
            continue
        if line.startswith("| Test ") or re.match(r"^\|\s*-+", line) or line.startswith("|---"):
            in_table = True
            continue
        if in_table and line.startswith("|"):
            p, w, i, n = count_symbols(line)
            row_tally = (row_tally[0] + p, row_tally[1] + w, row_tally[2] + i, row_tally[3] + n)
            continue
        if in_table and not line.startswith("|"):
            in_table = False
        fv = VERDICT_LINE_RE.match(line)
        if fv and current_file:
            sections.setdefault(current_file, {})["file_verdict"] = parse_file_verdict(fv.group("body"))

    if current_file is not None:
        sections.setdefault(current_file, {})["rows"] = row_tally

    summary_rows: dict[str, tuple[int, int, int, int, int]] = {}
    total_row: tuple[int, int, int, int, int] | None = None
    for line in content:
        tm = TOTAL_ROW_RE.match(line)
        if tm:
            total_row = (
                int(tm.group("p")), int(tm.group("w")), int(tm.group("i")),
                int(tm.group("n")), int(tm.group("t")),
            )
            continue
        sm = SUMMARY_ROW_RE.match(line)
        if sm:
            name = sm.group("file").strip()
            if name.lower() == "file" or name.startswith("**") or name.startswith("---"):
                continue
            summary_rows[name] = (
                int(sm.group("p")), int(sm.group("w")), int(sm.group("i")),
                int(sm.group("n")), int(sm.group("t")),
            )

    ok = True
    print(f"Audit: {AUDIT}")
    print(f"Sections parsed: {len(sections)}  Summary rows parsed: {len(summary_rows)}")
    print("-" * 90)
    hdr = f"{'File':44} {'Rows(P W I N)':16} {'FileVerdict':16} {'Summary(P W I N T)':20}  OK"
    print(hdr)
    print("-" * 90)

    section_totals = [0, 0, 0, 0, 0]
    for name, data in sections.items():
        rows = data.get("rows", (0, 0, 0, 0))
        fv = data.get("file_verdict", (0, 0, 0, 0))
        sm_row = summary_rows.get(name)

        row_str = "{} {} {} {}".format(*rows)
        fv_str = "{} {} {} {}".format(*fv) if fv != (0, 0, 0, 0) else "(none)"
        sm_str = "{} {} {} {} {}".format(*sm_row) if sm_row else "(missing)"

        row_matches_sm = sm_row is not None and rows == sm_row[:4]
        fv_matches_rows = fv == rows
        this_ok = row_matches_sm and fv_matches_rows
        mark = "\u2713" if this_ok else "\u2717"
        if not this_ok:
            ok = False
        print(f"{name:44} {row_str:16} {fv_str:16} {sm_str:20}  {mark}")
        if sm_row:
            for idx in range(5):
                section_totals[idx] += sm_row[idx]

    unseen_summary = set(summary_rows.keys()) - set(sections.keys())
    for name in unseen_summary:
        sm_row = summary_rows[name]
        for idx in range(5):
            section_totals[idx] += sm_row[idx]
        print(f"{name:44} {'(no section)':16} {'(n/a)':16} {'{} {} {} {} {}'.format(*sm_row):20}  -")

    print("-" * 90)
    if total_row:
        reported_total = total_row
        computed = tuple(section_totals)
        total_ok = reported_total == computed
        mark = "\u2713" if total_ok else "\u2717"
        print(f"{'TOTAL (from Summary)':44} reported={reported_total} computed={computed}  {mark}")
        if not total_ok:
            ok = False
    else:
        print("TOTAL row NOT FOUND")
        ok = False

    print()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
