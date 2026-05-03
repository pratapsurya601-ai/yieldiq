"""CACHE_VERSION-bump auto-check.

Used by both:

* ``.github/workflows/cache_version_check.yml`` (PR gate)
* a local pre-push hook (``--require-bump``)

Logic
-----

A PR (or push) **must** include a ``CACHE_VERSION`` change in
``backend/services/cache_service.py`` whenever its diff touches any of
the following analysis-output-affecting paths:

* ``backend/services/``
* ``backend/routers/``
* ``backend/validators/``
* ``backend/models/``
* ``models/forecaster.py``
* ``models/industry_wacc.py``
* ``data_pipeline/sources/``

…unless the PR body declares one of:

* ``cache-version: skip``
* ``cache-version: not-needed`` (with a free-form rationale)

If neither a bump nor a skip declaration is present, exit 1 with a
message that tells the author exactly what to do. Otherwise exit 0.

This file is intentionally dependency-light: stdlib only, no pytest, no
GitHub-API client. The workflow feeds it a ``--diff-file`` (the unified
diff of the PR vs. base) and a ``--pr-body-file``. The local pre-push
hook can do the same with ``git diff origin/main...HEAD`` piped to a
temp file.

Background: PR #134 and PR #136 (2026-04-27) both shipped backend
changes that needed a CACHE_VERSION bump but didn't get one on merge,
so production served stale cached values until PR #137 retroactively
bumped. This script makes that class of mistake un-mergeable.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path
from typing import Iterable


# ---- Trigger paths ---------------------------------------------------------
# A diff that touches any path matching one of these prefixes/exact-files
# requires a CACHE_VERSION bump (or an explicit skip declaration).
TRIGGER_PREFIXES: tuple[str, ...] = (
    "backend/services/",
    "backend/routers/",
    "backend/validators/",
    "backend/models/",
    "data_pipeline/sources/",
)
TRIGGER_EXACT: tuple[str, ...] = (
    "models/forecaster.py",
    "models/industry_wacc.py",
)

# The file that, when changed, counts as "the bump landed".
CACHE_FILE = "backend/services/cache_service.py"

# Path-glob patterns that are exempt from the bump check even when they
# fall under a TRIGGER_PREFIX. Matched via fnmatch on POSIX-style paths.
#
# The "pure-additive" rule below (handled separately in
# diff_requires_bump): files that don't exist in the base branch (i.e.
# only have a `+++ b/<path>` and a `--- /dev/null` header) cannot
# invalidate any existing cached payload by definition.
EXEMPT_PATTERNS: tuple[str, ...] = (
    "**/scaffolds/**",
    "**/*_scaffold.py",
)

# Path prefixes / exact files that genuinely affect analysis output —
# the narrow whitelist for the "outside this is exempt" rule. Anything
# outside these can't change cached fair-value/score payloads, so an
# exempt-pattern PR (or a PR that only touches non-analysis backend
# code) doesn't need a CACHE_VERSION bump.
#
# These mirror the GLOBAL_PREFIXES list in sector_scope_suggest.py.
ANALYSIS_PATHS: tuple[str, ...] = (
    "backend/services/analysis/",
    "backend/services/analysis_service.py",
    "backend/services/financial_valuation_service.py",
    "backend/services/ratios_service.py",
    "backend/services/financials_service.py",
    "backend/services/cache_service.py",
)


def _path_in_analysis(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(p == ap or p.startswith(ap) for ap in ANALYSIS_PATHS if ap.endswith("/")) or any(
        p == ap for ap in ANALYSIS_PATHS if not ap.endswith("/")
    )

# Regex: matches the CACHE_VERSION literal-assignment line in a unified diff.
# We want to see at least one *added* line (``+CACHE_VERSION = N``) and the
# value to differ from the *removed* line. In practice any ``+CACHE_VERSION =``
# alongside a ``-CACHE_VERSION =`` is sufficient; bumping it to the same
# integer is a no-op nobody bothers with.
_CACHE_ADD_RE = re.compile(r"^\+CACHE_VERSION\s*=\s*(\d+)", re.MULTILINE)
_CACHE_DEL_RE = re.compile(r"^-CACHE_VERSION\s*=\s*(\d+)", re.MULTILINE)

# Skip-declaration tokens. Matched case-insensitively at any line position so
# authors can wrap them in code-fences / blockquotes / list items without
# tripping the gate (same lesson as the sector-isolation parser fix).
_SKIP_RE = re.compile(
    r"cache-version\s*:\s*(skip|not-needed)\b",
    re.IGNORECASE,
)


# ---- Diff parsing ----------------------------------------------------------
def _changed_paths(diff_text: str) -> set[str]:
    """Extract changed file paths from a unified diff.

    Looks for ``diff --git a/<path> b/<path>`` headers and ``+++ b/<path>``
    lines. Returns POSIX-style paths (no leading ``a/``/``b/``).
    """
    paths: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            # `diff --git a/foo b/foo`
            parts = line.split()
            if len(parts) >= 4:
                a = parts[2]
                b = parts[3]
                if a.startswith("a/"):
                    paths.add(a[2:])
                if b.startswith("b/"):
                    paths.add(b[2:])
        elif line.startswith("+++ b/"):
            paths.add(line[len("+++ b/"):].strip())
        elif line.startswith("--- a/"):
            paths.add(line[len("--- a/"):].strip())
    # /dev/null shows up for added/deleted files; drop it.
    paths.discard("/dev/null")
    return paths


def _path_triggers(path: str) -> bool:
    if path in TRIGGER_EXACT:
        return True
    return any(path.startswith(p) for p in TRIGGER_PREFIXES)


def _path_matches_exempt(path: str) -> bool:
    """Match POSIX-style ``path`` against EXEMPT_PATTERNS via fnmatch."""
    p = path.replace("\\", "/")
    for pat in EXEMPT_PATTERNS:
        if fnmatch.fnmatch(p, pat):
            return True
    return False


def _new_files_in_diff(diff_text: str) -> set[str]:
    """Return the set of files added (didn't exist in base branch).

    Detection signals (any one is sufficient):
      * ``new file mode <octal>`` line in the file's diff header
      * ``--- /dev/null`` pre-image followed by ``+++ b/<path>`` post-image

    We sweep file-section by file-section using ``diff --git`` headers
    as boundaries.
    """
    new_files: set[str] = set()
    cur_b: str | None = None
    saw_dev_null_pre = False
    saw_new_file_marker = False

    def _flush() -> None:
        if cur_b and (saw_dev_null_pre or saw_new_file_marker):
            new_files.add(cur_b)

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            _flush()
            cur_b = None
            saw_dev_null_pre = False
            saw_new_file_marker = False
            # Try to capture path from the header itself for completeness.
            parts = line.split()
            if len(parts) >= 4 and parts[3].startswith("b/"):
                cur_b = parts[3][2:]
        elif line.startswith("new file mode"):
            saw_new_file_marker = True
        elif line.startswith("--- "):
            if line[4:].strip() == "/dev/null":
                saw_dev_null_pre = True
        elif line.startswith("+++ b/"):
            cur_b = line[len("+++ b/"):].strip()
    _flush()
    return new_files


def diff_touches_trigger(diff_text: str) -> tuple[bool, list[str]]:
    """Return (touched, [matching paths]).

    Adds an exemption layer for the parallel-PR friction case:

      * Brand-new files (no pre-image in base branch) cannot invalidate
        any existing cached payload by definition — exempt.
      * Files matching EXEMPT_PATTERNS (scaffolds) — exempt.
      * Files OUTSIDE ``backend/services/analysis/`` AND not in
        TRIGGER_EXACT — exempt. Only the analysis subdirectory writes
        to analysis_cache; other backend trees can't invalidate cached
        fair-value payloads even if they share a TRIGGER_PREFIX root.

    A path is "matched" (gate fires for it) only when it satisfies a
    TRIGGER and survives all three exemption layers.
    """
    new_files = _new_files_in_diff(diff_text)
    matched: list[str] = []
    for p in sorted(_changed_paths(diff_text)):
        if not _path_triggers(p):
            continue
        if p in new_files:
            continue
        if _path_matches_exempt(p):
            continue
        # TRIGGER_EXACT entries (forecaster.py, industry_wacc.py)
        # always count — they're explicitly listed for a reason.
        if p in TRIGGER_EXACT:
            matched.append(p)
            continue
        # For TRIGGER_PREFIX matches, narrow to the analysis area.
        if _path_in_analysis(p):
            matched.append(p)
            continue
        # Otherwise: trigger-prefix hit but outside analysis area —
        # exempt. Routers / validators / models that don't write to
        # analysis_cache can't invalidate cached fair-value payloads.
    return (bool(matched), matched)


def diff_has_cache_bump(diff_text: str) -> bool:
    """True if the diff bumps CACHE_VERSION in cache_service.py.

    We require:
      * at least one ``+CACHE_VERSION = N`` added line
      * AND a corresponding ``-CACHE_VERSION = M`` removed line with M != N

    (A bare ``+CACHE_VERSION = N`` with no removed line implies the file
    is brand-new, which we still accept — covers an unlikely refactor
    that splits cache_service.py.)
    """
    if CACHE_FILE not in _changed_paths(diff_text):
        return False
    added = _CACHE_ADD_RE.findall(diff_text)
    if not added:
        return False
    removed = _CACHE_DEL_RE.findall(diff_text)
    if not removed:
        # File added from scratch — accept.
        return True
    # Any added value differing from any removed value counts as a bump.
    return any(a != r for a in added for r in removed)


def body_has_skip_declaration(body: str | None) -> bool:
    if not body:
        return False
    return bool(_SKIP_RE.search(body))


# ---- CLI -------------------------------------------------------------------
ERROR_MESSAGE = """\
CACHE_VERSION-bump check FAILED.

This PR touches analysis-affecting code:
{matched}

…but does NOT bump CACHE_VERSION in backend/services/cache_service.py,
and the PR body does NOT declare a skip.

Pick one:

  (A) BUMP. Edit backend/services/cache_service.py and increment
      CACHE_VERSION by 1. Add a one-line comment after the literal that
      explains WHAT cached payloads need to recompute and WHY (see
      existing comment history in that file for the format).

  (B) SKIP. If your change genuinely cannot affect any cached analysis
      output (e.g. logging, observability, error sanitization, frontend
      wiring, schema additions that don't touch fair_value / MoS /
      verdict / score / red_flags / strengths), add a line to your PR
      description like:

          cache-version: not-needed - logging-only, no payload change

      The skip token is parsed case-insensitively and tolerates
      Markdown decorations (backticks, list bullets, blockquotes).

See docs/cache_version_discipline.md for the full rationale and
examples from history.
"""


def _read(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--diff-file",
        required=True,
        help="Path to unified diff of PR vs. base (e.g. `git diff origin/main...HEAD`).",
    )
    ap.add_argument(
        "--pr-body-file",
        default=None,
        help="Path to a file containing the PR body (for skip-declaration parsing).",
    )
    ap.add_argument(
        "--require-bump",
        action="store_true",
        help="Local pre-push mode: identical to PR mode, just here for clarity.",
    )
    args = ap.parse_args(argv)

    diff = _read(args.diff_file)
    body = _read(args.pr_body_file)

    touched, matched = diff_touches_trigger(diff)
    if not touched:
        print("[cache-version] No analysis-affecting paths touched. OK.")
        return 0

    if diff_has_cache_bump(diff):
        print(
            "[cache-version] Trigger paths touched AND CACHE_VERSION bumped. OK.\n"
            "  matched: " + ", ".join(matched)
        )
        return 0

    if body_has_skip_declaration(body):
        print(
            "[cache-version] Trigger paths touched, no bump, but PR body declares "
            "`cache-version: skip|not-needed`. OK.\n"
            "  matched: " + ", ".join(matched)
        )
        return 0

    sys.stderr.write(ERROR_MESSAGE.format(matched="\n".join(f"  - {m}" for m in matched)))
    return 1


# ---- Helpers exported for tests --------------------------------------------
__all__ = [
    "diff_touches_trigger",
    "diff_has_cache_bump",
    "body_has_skip_declaration",
    "TRIGGER_PREFIXES",
    "TRIGGER_EXACT",
    "CACHE_FILE",
]


def _iter_paths(diff_text: str) -> Iterable[str]:  # pragma: no cover - convenience
    return _changed_paths(diff_text)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
