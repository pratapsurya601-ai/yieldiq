#!/usr/bin/env python3
"""
check_sebi_words.py — SEBI vocabulary lint for the Next.js frontend.

YieldIQ is NOT a SEBI-registered Investment Advisor. Any copy that crosses
from factual description into advisory / opinion text is treated as
investment advice under SEBI IA Regs 2013 and is prohibited.

This script greps every ``frontend/src/**/*.{ts,tsx,js,jsx,mdx}`` file for
the banned vocabulary defined in ``backend/services/analysis/sebi_filter.py``
and FAILS CI if any banned word appears in a string literal or JSX text
node. It is a regression backstop — the runtime LLM post-filter owns the
AI-generated path; this script owns the hand-authored frontend path.

Matching rules
==============
    * Word-boundary, case-insensitive (same as sebi_filter._BANNED_RE).
    * Only checks STRING LITERALS and JSX TEXT NODES. Code identifiers,
      type unions, and object keys are ignored — those mirror the
      backend wire format (``verdict: "undervalued"``) and renaming them
      would require a backend migration. Display text routes through a
      translation map that this script does check.
    * Comments (``//`` and ``/* ... */``) are excluded by stripping them
      before the regex pass.
    * Per-file / per-line ignore comments:
          // sebi-allow: buy   — exempt all "buy" hits on the line below
          // sebi-allow-file   — exempt the whole file (use sparingly!)

Exemptions
==========
    * ``frontend/src/types/api.ts`` — mirrors backend Pydantic enum
      literals ("undervalued"/"overvalued"/...). Type-level only; no
      user-facing strings.
    * ``frontend/src/lib/constants.ts`` — VERDICT_COLORS keys mirror
      the same wire format.
    * ``node_modules``, ``.next``, ``out``, ``dist`` — build output.

Exit code
=========
    0 on clean, 1 on any hit. Integrates into CI as a blocking check.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Force stdout to UTF-8 so Windows consoles don't crash on ≤/≥/— etc.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

# ─── Vocabulary — keep in sync with backend/services/analysis/sebi_filter.py ──
BANNED_WORDS: tuple[str, ...] = (
    "appears",
    "should",
    "concern",
    "strength",
    "weakness",
    "buy",
    "sell",
    "hold",
    "outperform",
    "underperform",
    "expensive",
    "cheap",
    "undervalued",
    "overvalued",
    "attractive",
    "poor",
    "strong",
    "weak",
    "accumulate",
    "recommend",
    "recommendation",
)

_BANNED_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in BANNED_WORDS) + r")\b",
    re.IGNORECASE,
)

# Files that mirror the backend wire format (enum literals, colour maps
# keyed on those literals). Scan is purely type-level; no user-facing DOM
# output happens from these modules directly.
EXEMPT_FILES: frozenset[str] = frozenset({
    "src/types/api.ts",
    "src/lib/constants.ts",
})

# Wire-format enum values that appear verbatim in string literals for
# code-level comparisons (``v === "undervalued"``, switch cases, object
# keys passed to APIs). These mirror the backend Pydantic enum and
# renaming them would require a backend migration — out of scope for
# this lint. When a string literal is EXACTLY one of these tokens (no
# surrounding copy), we treat it as a wire-format code point rather
# than user-facing display text.
WIRE_FORMAT_LITERALS: frozenset[str] = frozenset({
    "undervalued",
    "fairly_valued",
    "overvalued",
    "avoid",
    "data_limited",
    "unavailable",
    # Prism verdict-band keys
    "deepValue",
    "expensive",
    # Dividend sustainability wire format
    "strong",
    "moderate",
    "at_risk",
    # Prism pillar labels wire format
    "Strong",
    "Moderate",
    "Weak",
    "Positive",
    "Neutral",
    "Negative",
    # Bulk-deal wire format (BUY/SELL codes from SEBI corporate-action feed)
    "BUY",
    "SELL",
    "Buy",
    "Sell",
    # Finance column names recorded by the user's own broker transactions
    # (their transaction log, not an advisory label).
    "Buy Date",
    "Buy Price",
    "Sell Date",
    "Sell Price",
})

# Directories to skip entirely.
SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules",
    ".next",
    ".vercel",
    ".turbo",
    "out",
    "dist",
    "build",
    "coverage",
    ".git",
})

# Extensions scanned. .mdx included for the blog authoring layer.
SCANNED_EXTS: frozenset[str] = frozenset({
    ".ts", ".tsx", ".js", ".jsx", ".mdx",
})

# Strips /* ... */ and // ... comments. Deliberately simple — good enough
# for the 99% case. Literal strings containing "//" (URLs) are preserved
# because we tokenize strings before comments below.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"(^|[^:'\"])//[^\n]*")

# Extract string literals + JSX text. A bit loose — prefers false-positive
# rather than false-negative, because the cost of missing a banned word on
# a live share card is much higher than the cost of a dev needing to add an
# "sebi-allow:" comment once in a blue moon.
_STRING_LITERAL_RE = re.compile(
    r"""
    (?:                                # one of:
        "(?:[^"\\]|\\.)*"              #   double-quoted
      | '(?:[^'\\]|\\.)*'              #   single-quoted
      | `(?:[^`\\]|\\.)*`              #   template literal (no interp parse)
    )
    """,
    re.VERBOSE | re.DOTALL,
)

# JSX text — anything between > and < that isn't purely whitespace.
# Extracting perfectly from TSX requires a full parser; this regex catches
# the obvious cases which is what matters here (the 99% of share-card text).
_JSX_TEXT_RE = re.compile(r">([^<{}\n]*[A-Za-z][^<{}]*)<")

# Per-line exemption annotations.
# Accepts both line-comment (`// sebi-allow: buy`) and block/JSX-comment
# (`/* sebi-allow: buy */` or `{/* sebi-allow: buy */}`) forms.
_ALLOW_LINE_RE = re.compile(
    r"(?://|/\*)\s*sebi-allow\s*:\s*([A-Za-z0-9, _-]+?)(?:\s*\*/|$|\n)",
    re.MULTILINE,
)
_ALLOW_FILE_RE = re.compile(r"//\s*sebi-allow-file\b")


def _strip_comments(src: str) -> str:
    """Remove block comments AND line comments (keeping line-count intact).
    Line comments are stripped AFTER sebi-allow extraction upstream."""
    def _block_replace(m: re.Match) -> str:
        # Preserve newlines so downstream line numbers stay correct.
        return "\n" * m.group(0).count("\n")

    out = _BLOCK_COMMENT_RE.sub(_block_replace, src)
    # Remove // line comments. We do a naive pass that preserves quoted
    # strings by first masking them out.
    lines: list[str] = []
    for raw in out.split("\n"):
        # Find the first // not inside a string.
        in_single = False
        in_double = False
        in_back = False
        cut = None
        i = 0
        while i < len(raw):
            ch = raw[i]
            if ch == "\\" and i + 1 < len(raw):
                i += 2
                continue
            if not in_double and not in_back and ch == "'":
                in_single = not in_single
            elif not in_single and not in_back and ch == '"':
                in_double = not in_double
            elif not in_single and not in_double and ch == "`":
                in_back = not in_back
            elif not in_single and not in_double and not in_back:
                if ch == "/" and i + 1 < len(raw) and raw[i + 1] == "/":
                    cut = i
                    break
            i += 1
        lines.append(raw if cut is None else raw[:cut])
    return "\n".join(lines)


def _scan_file(path: Path, repo_root: Path) -> list[tuple[int, str, str]]:
    """Return list of (line_no, banned_word, excerpt) hits. Empty = clean."""
    rel = path.relative_to(repo_root).as_posix()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    if _ALLOW_FILE_RE.search(text):
        return []

    stripped = _strip_comments(text)

    hits: list[tuple[int, str, str]] = []
    # Track per-line allow lists. An annotation applies to the SAME
    # line it's on (trailing comment) AND to the next line (preceding
    # comment), so either placement works for devs.
    allow_by_line: dict[int, set[str]] = {}
    for m in _ALLOW_LINE_RE.finditer(text):
        ln_same = text.count("\n", 0, m.start()) + 1
        words = {w.strip().lower() for w in m.group(1).split(",") if w.strip()}
        allow_by_line.setdefault(ln_same, set()).update(words)
        allow_by_line.setdefault(ln_same + 1, set()).update(words)

    # 1) Check string literals.
    for m in _STRING_LITERAL_RE.finditer(stripped):
        literal = m.group(0)
        inner = literal[1:-1]  # drop surrounding quote
        # Template literals may embed ${...} interpolations that contain
        # wire-format identifiers (`deal_type === "BUY"`). Only the STATIC
        # text portions render to the DOM; strip the interpolations before
        # scanning so we don't false-fail on a legitimate conditional.
        if literal.startswith("`"):
            inner_scan = re.sub(r"\$\{[^{}]*\}", "", inner, flags=re.DOTALL)
        else:
            inner_scan = inner
        # Skip wire-format enum literals — code-level comparisons mirror
        # the backend Pydantic enum. These never render to the DOM
        # (display text routes through a translation map that IS scanned).
        if inner in WIRE_FORMAT_LITERALS:
            continue
        hit = _BANNED_RE.search(inner_scan)
        if not hit:
            continue
        ln = stripped.count("\n", 0, m.start()) + 1
        word = hit.group(0).lower()
        if word in allow_by_line.get(ln, set()):
            continue
        excerpt = literal if len(literal) < 120 else literal[:117] + "..."
        hits.append((ln, hit.group(0), excerpt))

    # 2) Check JSX text nodes.
    for m in _JSX_TEXT_RE.finditer(stripped):
        body = m.group(1)
        hit = _BANNED_RE.search(body)
        if not hit:
            continue
        ln = stripped.count("\n", 0, m.start()) + 1
        word = hit.group(0).lower()
        if word in allow_by_line.get(ln, set()):
            continue
        excerpt = body.strip()
        if len(excerpt) > 120:
            excerpt = excerpt[:117] + "..."
        hits.append((ln, hit.group(0), f"[jsx] {excerpt}"))

    # Sort + dedupe (same line, same word).
    seen: set[tuple[int, str]] = set()
    ordered: list[tuple[int, str, str]] = []
    for ln, word, excerpt in sorted(hits, key=lambda x: x[0]):
        key = (ln, word.lower())
        if key in seen:
            continue
        seen.add(key)
        ordered.append((ln, word, excerpt))
    return ordered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=None,
        help="Path to the frontend root (defaults to frontend/ next to this script's repo).",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    frontend_root = Path(args.root).resolve() if args.root else repo_root / "frontend"
    if not frontend_root.is_dir():
        print(f"[check_sebi_words] frontend dir not found: {frontend_root}", file=sys.stderr)
        return 2

    src_root = frontend_root / "src"
    if not src_root.is_dir():
        print(f"[check_sebi_words] src dir not found: {src_root}", file=sys.stderr)
        return 2

    total_hits = 0
    files_with_hits = 0

    for dirpath, dirnames, filenames in os.walk(src_root):
        # In-place prune skipped directories.
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if Path(fname).suffix not in SCANNED_EXTS:
                continue
            path = Path(dirpath) / fname
            rel = path.relative_to(frontend_root).as_posix()
            if rel in EXEMPT_FILES:
                continue
            hits = _scan_file(path, frontend_root)
            if not hits:
                continue
            files_with_hits += 1
            for ln, word, excerpt in hits:
                total_hits += 1
                print(f"{rel}:{ln}: banned='{word}' :: {excerpt}")

    if total_hits:
        print(
            f"\n[check_sebi_words] FAIL — {total_hits} banned-vocabulary hit(s) "
            f"across {files_with_hits} file(s).",
            file=sys.stderr,
        )
        print(
            "  Rewrite to descriptive, non-advisory copy. See "
            "backend/services/analysis/sebi_filter.py for the canonical "
            "banned-word list and rename conventions.",
            file=sys.stderr,
        )
        return 1

    print("[check_sebi_words] OK — no banned vocabulary in user-facing frontend strings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
