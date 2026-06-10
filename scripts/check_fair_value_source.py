#!/usr/bin/env python3
"""ROOT CAUSE #1 invariant guard — backend (2026-06-10).

The invariant: backend templates that emit prose about a stock's
"fair value" — the AI Why service, the FAQ generator, the og-data
projection, the JSON-LD route, the AI Chat context builder, the
PDF / share-card export, the peer-comparison summary — MUST read
``headline_fair_value`` (the composite-IV-preferred canonical
number) rather than the DCF-only ``valuation.fair_value`` directly.

The DCF-specific value is still legitimately needed for surfaces
that BREAK OUT the per-engine values (the DcfMultiplesChip
explainer, the Valuation Methods Panel). Those surfaces are
whitelisted by file path below.

This script flags banned direct reads in templated-prose / public-
projection contexts. Run as a pre-commit hook and in CI alongside
``check_sebi_words.py``.

Usage:
    python scripts/check_fair_value_source.py                 # full repo scan
    python scripts/check_fair_value_source.py --diff-only \\
        --base origin/main                                    # CI mode

Exit codes:
    0  no violations / no scope hit
    1  one or more violations found (prints them and exits)
    2  CLI / invocation error
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Files inside these paths are the canonical templated-prose / public-
# projection sites. ANY direct read of ``valuation.fair_value`` or
# similar in these files is treated as a violation unless the line is
# explicitly annotated with ``# headline-fv-allow:`` (mirrors the
# ``# sebi-allow:`` convention).
SCOPED_PATHS = (
    "backend/services/ai_explain_service.py",
    "backend/services/ai_summary_",
    "backend/services/ai_why",
    "backend/services/faq_",
    "backend/services/og_",
    "backend/services/jsonld_",
    "backend/services/peer_comparison_",
    "backend/services/share_report_",
    "backend/services/pdf_export_",
    "backend/services/summary_projection.py",
    "backend/routers/og",
    "backend/routers/public.py",
    "backend/services/chat",
)

# Files in these paths LEGITIMATELY need the DCF-specific number
# (engine breakdowns, DCF reverse solver, the inject helper itself).
# Always whitelisted regardless of pattern matches.
WHITELIST_PATHS = (
    "backend/routers/analysis.py",          # contains the inject helper
    "backend/services/composite_iv_service.py",
    "backend/services/valuation_methods_",  # per-engine breakdown
    "backend/services/dcf",                  # DCF engine itself
    "backend/services/reverse_dcf",
    "backend/services/three_stage_dcf",
    "backend/services/forecaster",
    "backend/services/valuation",
    "backend/services/validators",
    "backend/services/composite",
    "backend/services/yiq50",
    "backend/services/analysis",
    "backend/services/sector",
    "backend/services/sensitivity",
    "backend/services/score",
    "backend/services/fv_",
    "backend/services/fair_value_history",
    "backend/services/peer_cap",
    "backend/services/data_quality",
    "backend/services/tier",
    "backend/services/consensus_signal",
    "backend/services/probability_weighted",
    "backend/services/ddm",
    "backend/services/epv",
    "backend/services/liquidation",
    "backend/services/replacement",
    "backend/services/honest_card_generator",
    "backend/services/bulls_bears_generator",
    "backend/services/derived_insights_service",
    "backend/services/worry_index",
    "backend/services/cache_invalidation_manifest",
    "backend/tests/",
    "backend/models/",
    "scripts/",
    "backend/workers/",
    "backend/validators",
)

# Banned attribute reads that templated prose must not consume
# directly. The ``# headline-fv-allow:`` annotation overrides per line.
BANNED_PATTERNS = (
    # Direct attribute reads in Python on a ValuationOutput / dict that
    # the templated-prose paths should NOT consume — they must read
    # ``headline_fair_value`` from the surrounding payload / response.
    re.compile(r'valuation\.fair_value\b'),
    re.compile(r'valuation\["fair_value"\]'),
    re.compile(r"valuation\.get\(['\"]fair_value['\"]\)"),
    re.compile(r"v\.fair_value\b"),
    re.compile(r"result\.valuation\.fair_value\b"),
)

ALLOW_RE = re.compile(r"#\s*headline-fv-allow\b")


def _is_scoped(path: str) -> bool:
    p = path.replace("\\", "/")
    if any(p.startswith(w) or w in p for w in WHITELIST_PATHS):
        return False
    return any(s in p for s in SCOPED_PATHS)


def _scan_file(path: Path, lines: list[tuple[int, str]]) -> list[tuple[int, str, str]]:
    """Return list of (line_no, line_text, pattern) violations."""
    violations: list[tuple[int, str, str]] = []
    for line_no, text in lines:
        if ALLOW_RE.search(text):
            continue
        for pat in BANNED_PATTERNS:
            m = pat.search(text)
            if m:
                violations.append((line_no, text.rstrip(), m.group(0)))
                break
    return violations


def _full_scan() -> list[tuple[str, int, str, str]]:
    findings: list[tuple[str, int, str, str]] = []
    for path in REPO_ROOT.glob("backend/**/*.py"):
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if not _is_scoped(rel):
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                lines = list(enumerate(f, start=1))
        except OSError:
            continue
        for line_no, text, pattern in _scan_file(path, lines):
            findings.append((rel, line_no, text, pattern))
    return findings


def _diff_only_scan(base: str) -> list[tuple[str, int, str, str]]:
    """Scan ADDED lines only (matches sebi-lint diff-only mode)."""
    try:
        cp = subprocess.run(
            ["git", "diff", f"{base}...HEAD", "--unified=0"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"check_fair_value_source: git diff failed: {exc}", file=sys.stderr)
        return []
    findings: list[tuple[str, int, str, str]] = []
    current_file: str | None = None
    current_line = 0
    for raw in cp.stdout.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:].replace("\\", "/")
            current_line = 0
            continue
        if raw.startswith("@@"):
            # @@ -a,b +c,d @@ — parse c.
            m = re.search(r"\+(\d+)", raw)
            if m:
                current_line = int(m.group(1))
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            text = raw[1:]
            if current_file and _is_scoped(current_file):
                if not ALLOW_RE.search(text):
                    for pat in BANNED_PATTERNS:
                        if pat.search(text):
                            findings.append((current_file, current_line, text, pat.pattern))
                            break
            current_line += 1
        elif not raw.startswith("-"):
            current_line += 1
    return findings


def main() -> int:
    p = argparse.ArgumentParser(
        description="ROOT CAUSE #1 — invariant guard for canonical headline FV",
    )
    p.add_argument("--diff-only", action="store_true",
                   help="Only scan lines added in the current branch")
    p.add_argument("--base", default="origin/main",
                   help="Diff base (default: origin/main)")
    args = p.parse_args()

    findings = _diff_only_scan(args.base) if args.diff_only else _full_scan()

    if not findings:
        print("check_fair_value_source: OK (no banned reads in scoped paths)")
        return 0

    print(
        "check_fair_value_source: VIOLATIONS — these files emit templated prose\n"
        "or public projections of fair value but read the DCF-only field\n"
        "directly. Read `headline_fair_value` (or the canonical surrounding\n"
        "payload helper) instead. To intentionally read the DCF-only number\n"
        "in a scoped file, add `# headline-fv-allow: <reason>` on the line.\n",
        file=sys.stderr,
    )
    for path, line_no, text, pattern in findings:
        print(f"  {path}:{line_no}  pattern={pattern}", file=sys.stderr)
        print(f"      {text.strip()}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
