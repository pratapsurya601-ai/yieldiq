"""Suggest a `sector-scope:` line for the current diff.

Used as a developer aid (paste the output into your PR body) and as a
GH Action helper that posts the suggestion as a PR comment so the
sector-isolation merge gate has something to bite on.

How the heuristic works
-----------------------
The script asks git for the changed files (vs. ``origin/main`` by
default; configurable via ``--base``) and bins each path into one of:

  * GLOBAL     - data-pipeline / analysis-service code that touches the
                 whole universe in one go (``data_pipeline/``,
                 ``backend/services/analysis/``, ``backend/services/``,
                 ``models/forecaster.py``, scoring core). Suggests ``*``.
  * SECTORAL   - a sector-specific scoring file. We look for files under
                 ``backend/services/scoring/`` and any file whose path or
                 contents mention a sector label from
                 ``scripts/sector_snapshot.json``. Suggests the matching
                 sectors.
  * NEUTRAL    - everything else (frontend, docs, tests, CI). No
                 suggestion.

The script never fails the build. It only emits a recommendation. The
authoritative gate is still ``sector_isolation_check.py``.

Output is one of:

    sector-scope: *
    sector-scope: Cement, Banks
    sector-scope: <none — no scoring/data files touched>

When run with ``--gh-comment`` (used by the workflow) it also writes a
short Markdown blurb to ``sector_scope_suggestion.md`` for posting.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "scripts" / "sector_snapshot.json"

# Path prefixes / exact files that trigger a GLOBAL (`*`) suggestion.
# These are files whose effect is universe-wide by construction.
GLOBAL_PREFIXES = (
    "data_pipeline/",
    "backend/services/analysis/",
    "backend/services/analysis_service.py",
    "backend/services/financial_valuation_service.py",
    "backend/services/ratios_service.py",
    "backend/services/financials_service.py",
    "models/forecaster.py",
    "models/growth_valuation.py",
    "models/industry_wacc.py",
    "scripts/canary_stocks_50.json",
)

# Path prefixes that are SECTORAL by convention. Files here are scanned
# for sector-label hits.
SECTORAL_PREFIXES = (
    "backend/services/scoring/",
)


def _load_sector_labels() -> list[str]:
    if not SNAPSHOT.exists():
        return []
    try:
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        return sorted((data.get("sectors") or {}).keys())
    except Exception:
        return []


def _git_changed_files(base: str) -> list[str]:
    """Return the list of paths changed vs. ``base``.

    Falls back to staged + unstaged diff if ``base`` is unreachable
    (developer running locally without origin/main fetched).
    """
    for cmd in (
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        ["git", "diff", "--name-only", base],
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--name-only", "--cached"],
    ):
        try:
            out = subprocess.check_output(
                cmd, cwd=REPO_ROOT, stderr=subprocess.DEVNULL, timeout=15
            )
            files = [
                line.strip()
                for line in out.decode("utf-8", errors="replace").splitlines()
                if line.strip()
            ]
            if files:
                return files
        except Exception:
            continue
    return []


def _is_global(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(p.startswith(prefix) or p == prefix for prefix in GLOBAL_PREFIXES)


def _is_sectoral_prefix(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(p.startswith(prefix) for prefix in SECTORAL_PREFIXES)


def _scan_for_sector_labels(path: str, labels: list[str]) -> set[str]:
    """Best-effort: look for sector labels in the path + file contents.

    Path-segment match is normalised on lowercase + word boundaries. We
    deliberately keep this loose — false positives are cheap (an extra
    sector listed) but missed sectors mean an unhelpful suggestion.
    """
    found: set[str] = set()
    p = (REPO_ROOT / path).resolve()
    haystack = path.lower()
    text = ""
    if p.exists() and p.is_file():
        try:
            text = p.read_text(encoding="utf-8", errors="replace").lower()
        except Exception:
            text = ""
    for label in labels:
        token = label.lower()
        # word-boundary match in path or contents
        if re.search(rf"\b{re.escape(token)}\b", haystack):
            found.add(label)
        elif text and re.search(rf"\b{re.escape(token)}\b", text):
            found.add(label)
    return found


def suggest(files: list[str], labels: list[str]) -> tuple[str, dict]:
    """Return (scope_line, debug_info)."""
    info = {
        "global_hits": [],
        "sectoral_hits": [],
        "matched_sectors": set(),
        "n_files": len(files),
    }
    for f in files:
        if _is_global(f):
            info["global_hits"].append(f)
            continue
        if _is_sectoral_prefix(f):
            info["sectoral_hits"].append(f)
            sectors = _scan_for_sector_labels(f, labels)
            info["matched_sectors"].update(sectors)
            continue
        # Even outside sectoral_prefix, scan content for sector labels
        # (catches PRs that touch a generic file but mention a single
        # sector heavily, e.g. validators with a sector-specific guard).
        # Restrict this fallback to backend/models Python files — docs,
        # markdown, frontend, and test fixtures often mention sector names
        # in prose without actually changing scoring behaviour, and a
        # false-positive sector list is worse than no suggestion.
        nf = f.replace("\\", "/")
        if nf.endswith(".py") and (
            nf.startswith("backend/") or nf.startswith("models/")
        ):
            sectors = _scan_for_sector_labels(f, labels)
            if sectors:
                info["sectoral_hits"].append(f)
                info["matched_sectors"].update(sectors)

    # If any file is global, the suggestion is `*` — a global change
    # always wins over any sectoral signal.
    if info["global_hits"]:
        return "sector-scope: *", info
    if info["matched_sectors"]:
        scope = ", ".join(sorted(info["matched_sectors"]))
        return f"sector-scope: {scope}", info
    return "sector-scope: <none — no scoring/data files touched>", info


def _render_comment(scope_line: str, info: dict) -> str:
    lines = [
        "### Suggested `sector-scope:` for this PR",
        "",
        "```",
        scope_line,
        "```",
        "",
        "Paste this line into the PR body (top of the template). The "
        "sector-isolation merge gate will fail until it is declared.",
        "",
        f"_Files inspected: {info['n_files']}._  ",
    ]
    if info["global_hits"]:
        lines.append("Global-scope triggers:")
        for f in info["global_hits"][:10]:
            lines.append(f"- `{f}`")
    if info["sectoral_hits"]:
        lines.append("Sectoral-scope triggers:")
        for f in info["sectoral_hits"][:10]:
            lines.append(f"- `{f}`")
    if info["matched_sectors"]:
        lines.append(
            "Sectors matched: "
            + ", ".join(sorted(info["matched_sectors"]))
        )
    lines.append("")
    lines.append("_Heuristic — see `scripts/sector_scope_suggest.py`._")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Suggest a sector-scope: line for the current diff."
    )
    p.add_argument("--base", default="origin/main",
                   help="git ref to diff against (default: origin/main)")
    p.add_argument("--files", nargs="*", default=None,
                   help="explicit file list (overrides git diff)")
    p.add_argument("--gh-comment", default=None,
                   help="write a Markdown comment for posting to the PR "
                        "(path, e.g. sector_scope_suggestion.md)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    labels = _load_sector_labels()
    if args.files:
        files = list(args.files)
    else:
        files = _git_changed_files(args.base)

    if args.verbose:
        print(f"# diff base: {args.base}", file=sys.stderr)
        print(f"# files changed: {len(files)}", file=sys.stderr)
        for f in files:
            print(f"#   {f}", file=sys.stderr)
        print(f"# sector labels: {labels}", file=sys.stderr)

    scope_line, info = suggest(files, labels)
    print(scope_line)

    if args.gh_comment:
        Path(args.gh_comment).write_text(
            _render_comment(scope_line, info), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
