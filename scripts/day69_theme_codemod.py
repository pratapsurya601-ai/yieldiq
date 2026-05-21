"""Day-69 theme codemod (PR-1 of 4): swap hardcoded gray/white classes
for design tokens across (app)/ and (stocks)/ route pages.

Safety rules:
 1. Only modifies file paths in TARGETS (top 30 by occurrence count).
 2. Skips a line if it contains a semantic-color sibling on the same
    line (amber/red/green/blue/emerald/violet/pink/rose/orange/yellow/
    cyan/teal/slate) — meaning the gray is the neutral branch of a
    ternary tied to a verdict/status/sentiment and must stay branded.
 3. Skips a line where the class already has a `dark:` variant for the
    same prefix (already migrated).
 4. Only matches within className-style string contexts; we operate
    inside double-quoted/backtick attribute strings only by virtue of
    class-shaped tokens (no false positives in JSX text — those don't
    use class names like `bg-white`).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
F = ROOT / "frontend" / "src"

# Top-30 in-scope files by hardcoded-token count (Day-69 audit).
TARGETS = [
    "app/(stocks)/stocks/[ticker]/fair-value/page.tsx",
    "app/(app)/admin/story-dcf/page.tsx",
    "app/(stocks)/stocks/[ticker]/reverse-dcf/ReverseDCFClient.tsx",
    "app/(stocks)/stocks/[ticker]/dupont/page.tsx",
    "app/(stocks)/stocks/[ticker]/risk-analysis/page.tsx",
    "app/(stocks)/prism/compare/[slug]/CompareClient.tsx",
    "app/(app)/portfolio/page.tsx",
    "app/(app)/portfolio/tax-report/page.tsx",
    "app/(stocks)/stocks/[ticker]/technicals/TechnicalsClient.tsx",
    "app/(app)/admin/realty/page.tsx",
    "app/(app)/concall/page.tsx",
    "app/(stocks)/compare/[slug]/CompareClient.tsx",
    "app/(app)/admin/insurance/page.tsx",
    "app/(app)/compare/page.tsx",
    "app/(stocks)/hex/compare/[slug]/CompareClient.tsx",
    "app/(app)/portfolio/analyze/page.tsx",
    "app/(stocks)/prism/[ticker]/page.tsx",
    "app/(stocks)/hex/[ticker]/page.tsx",
    "app/(app)/report/[ticker]/page.tsx",
    "app/(app)/admin/page.tsx",
    "app/(app)/admin/outliers/page.tsx",
    "app/(app)/search/page.tsx",
    "app/(stocks)/stocks/[ticker]/news/page.tsx",
    "app/(app)/discover/page.tsx",
    "app/(app)/portfolio/import/page.tsx",
    "app/(app)/discover/screener/page.tsx",
    "app/(stocks)/stocks/StocksIndexClient.tsx",
    "app/(stocks)/stocks/[ticker]/fair-value/sensitivity/page.tsx",
    "app/(app)/account/page.tsx",
    "app/(app)/portfolio/upload/page.tsx",
]

# Token map. Order matters where one token is a prefix of another —
# longer/more-specific must come first.
SWAPS = [
    # gray text: 900/800/700 -> ink; 600/500/400 -> caption
    ("text-gray-900", "text-ink"),
    ("text-gray-800", "text-ink"),
    ("text-gray-700", "text-ink"),
    ("text-gray-600", "text-caption"),
    ("text-gray-500", "text-caption"),
    ("text-gray-400", "text-caption"),
    # borders
    ("border-gray-200", "border-border"),
    ("border-gray-300", "border-border"),
    # surfaces
    ("bg-white", "bg-bg dark:bg-surface"),
    ("bg-gray-50", "bg-bg dark:bg-surface"),
    ("bg-gray-100", "bg-surface"),
]

SEMANTIC_HUES = (
    "amber",
    "rose",
    "orange",
    "yellow",
    "emerald",
    "violet",
    "pink",
    "cyan",
    "teal",
    "lime",
    "fuchsia",
    "indigo",
    "sky",
    "purple",
)

# A line is a "semantic ternary line" if it has both `?` ... `:` and
# at least one semantic-hue Tailwind class. In that case we leave any
# gray-* / bg-white on the same line alone (it's the neutral branch).
_TERNARY = re.compile(r"\?.*:")
_HUE_CLASS = re.compile(
    r"(?:bg|text|border|ring|from|to|via|fill|stroke)-(?:"
    + "|".join(SEMANTIC_HUES)
    + r")-(?:50|100|200|300|400|500|600|700|800|900|950)"
)
# Also treat `green` and `red` as semantic when paired with `?:` ternary.
_SEM_RG = re.compile(
    r"(?:bg|text|border|ring|from|to|via|fill|stroke)-(?:green|red|blue|slate)-(?:50|100|200|300|400|500|600|700|800|900|950)"
)

# Class-token boundary helpers. Tailwind class tokens are bounded by
# whitespace or one of `"' `${}[]<>(),. The token may legitimately be
# followed by `:` only in the case of a variant prefix to a different
# class (e.g. `bg-white hover:bg-blue-50`) — we don't want to match
# `hover:bg-white` as `bg-white`. Use a negative lookbehind for `:`.
_PRE = r"(?<![\w:-])"
_POST = r"(?![\w-])"


def is_semantic_ternary_line(line: str) -> bool:
    if not _TERNARY.search(line):
        return False
    if _HUE_CLASS.search(line):
        return True
    # green/red/blue/slate are semantic only when paired with another
    # branded color on the same ternary (verdict bg/text combos).
    if _SEM_RG.search(line):
        return True
    return False


def has_dark_sibling(line: str, token: str) -> bool:
    """True if the line already has a `dark:` variant of `token` or
    a `dark:bg-surface` / `dark:bg-bg` token suggesting prior migration."""
    if "dark:" not in line:
        return False
    if token.startswith("bg-"):
        return ("dark:bg-surface" in line) or ("dark:bg-bg" in line) or ("dark:" + token in line)
    if token.startswith("text-"):
        return ("dark:text-ink" in line) or ("dark:text-caption" in line) or ("dark:" + token in line)
    if token.startswith("border-"):
        return ("dark:border-border" in line) or ("dark:" + token in line)
    return False


def apply_swaps(text: str) -> tuple[str, int]:
    out_lines = []
    total = 0
    for line in text.splitlines(keepends=True):
        if is_semantic_ternary_line(line):
            out_lines.append(line)
            continue
        new = line
        for old, new_tok in SWAPS:
            if old not in new:
                continue
            if has_dark_sibling(new, old):
                continue
            pat = re.compile(_PRE + re.escape(old) + _POST)
            new, n = pat.subn(new_tok, new)
            total += n
        out_lines.append(new)
    return "".join(out_lines), total


def main() -> None:
    grand_total = 0
    changed_files = 0
    per_file: list[tuple[str, int]] = []
    for rel in TARGETS:
        p = F / rel
        if not p.exists():
            print(f"MISSING: {rel}")
            continue
        src = p.read_text(encoding="utf-8")
        new, n = apply_swaps(src)
        if n > 0 and new != src:
            p.write_text(new, encoding="utf-8")
            changed_files += 1
            grand_total += n
        per_file.append((rel, n))
    per_file.sort(key=lambda x: -x[1])
    for rel, n in per_file:
        print(f"  {n:4d}  {rel}")
    print(f"\nFiles changed: {changed_files}")
    print(f"Total swaps:   {grand_total}")


if __name__ == "__main__":
    main()
