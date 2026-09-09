#!/usr/bin/env python3
"""Fail if A4S+ makes a claim it is not entitled to make.

A4S+ is a software-only prototype fed entirely by simulated data. Phrases such
as "military-grade encryption" or "clinically validated" would be false. They
*do* appear in the source, but only inside disclaimers, so a naive grep is not
enough: this checker inspects a small window of surrounding text and treats a
hit as a violation only when nothing nearby negates or qualifies it.

Usage:  python3 scripts/claim_scan.py <path> [<path> ...]
Exit:   0 = clean, 1 = violations printed to stdout.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCANNED_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".css",
    ".md",
    ".yml",
    ".yaml",
    ".sh",
    ".Dockerfile",
}

SKIP_DIRS = {
    # This checker and its wrapper necessarily contain the forbidden phrases as
    # patterns, so they exclude themselves.
    "scripts",
    "node_modules",
    ".next",
    "__pycache__",
    "artifacts",
    ".git",
    "test-results",
    "playwright-report",
}

CLAIMS = [
    r"military[-\s]grade",
    r"clinically\s+(?:validated|approved|proven)",
    r"medical[-\s]grade",
    r"FDA[-\s](?:approved|cleared)",
    r"CE[-\s]marked",
    r"unhackable",
    r"unbreakable",
    r"100%\s+(?:accurate|secure|reliable)",
    r"production[-\s]ready",
]
CLAIM_RE = re.compile("|".join(CLAIMS), re.IGNORECASE)

NEGATION_RE = re.compile(
    r"\b(?:not|never|no|none|nothing|neither|non|without|isn't|aren't|"
    r"cannot|can't|avoid|avoided|refuse|refuses|disclaim|disclaims|"
    r"unqualified|false|misleading|marketing)\b",
    re.IGNORECASE,
)

# Lines that name a capability in order to display it as *withheld*.
ALLOWLIST = {
    # The admin capability matrix needs a human-readable label for every
    # capability it reports as false; the UI strikes each one through.
    "frontend/src/app/(app)/admin/system/page.tsx": re.compile(
        r"^\s*(?:real_sensors|real_uav_control|clinical_validation|"
        r"encrypted_data_at_rest|authenticated_encryption_demo):"
    ),
}

WINDOW = 2  # lines of context inspected on each side of a hit


def iter_files(roots: list[str]):
    for root in roots:
        path = Path(root)
        if path.is_file():
            yield path
            continue
        for candidate in sorted(path.rglob("*")):
            if not candidate.is_file():
                continue
            if SKIP_DIRS & set(candidate.parts):
                continue
            if candidate.suffix in SCANNED_SUFFIXES:
                yield candidate


def main(argv: list[str]) -> int:
    violations: list[str] = []
    for path in iter_files(argv or ["."]):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        allow = ALLOWLIST.get(str(path))
        for index, line in enumerate(lines):
            if not CLAIM_RE.search(line):
                continue
            if allow is not None and allow.search(line):
                continue
            lo = max(0, index - WINDOW)
            hi = min(len(lines), index + WINDOW + 1)
            context = " ".join(lines[lo:hi])
            if NEGATION_RE.search(context):
                continue
            violations.append(f"{path}:{index + 1}: {line.strip()}")

    for violation in violations:
        print(violation)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
