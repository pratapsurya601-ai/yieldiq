"""Day-71 theme codemod (PR-2 of 4): swap hardcoded gray/white classes
for design tokens across marketing route pages + landing root + root
layout.

Reuses the swap engine + safety filters from `day69_theme_codemod.py`:
 - skips semantic-ternary lines (verdict/sentiment branded branches),
 - preserves lines that already have a `dark:` sibling,
 - matches Tailwind class tokens with proper boundaries.

Scope (per PR-2 spec): only `app/(marketing)/**/*.tsx`, `app/page.tsx`,
and `app/layout.tsx`. Capped at 20 files for this PR.
"""
from __future__ import annotations

from pathlib import Path

from day69_theme_codemod import apply_swaps  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
F = ROOT / "frontend" / "src"

# Top files by hardcoded-token count from a fresh audit (Day-71).
TARGETS = [
    "app/(marketing)/screens/[slug]/ScreenClient.tsx",
    "app/(marketing)/privacy/page.tsx",
    "app/page.tsx",
    "app/(marketing)/nifty50/IndexDashboardClient.tsx",
    "app/(marketing)/pricing/page.tsx",
    "app/(marketing)/terms/page.tsx",
    "app/(marketing)/landing/page.tsx",
    "app/(marketing)/ipo/[symbol]/page.tsx",
    "app/(marketing)/ipo/page.tsx",
    "app/(marketing)/blog/[slug]/page.tsx",
    "app/(marketing)/earnings-calendar/EarningsCalendarClient.tsx",
    "app/(marketing)/blog/page.tsx",
    "app/(marketing)/features/page.tsx",
    "app/(marketing)/news/page.tsx",
    "app/(marketing)/api-docs/page.tsx",
    "app/(marketing)/status/page.tsx",
    # app/layout.tsx had 0 hits in the audit but is in-scope; include if
    # it exists so future drift is caught by the same codemod.
    "app/layout.tsx",
]


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
    if grand_total > 400:
        print("WARN: total swaps exceeds the PR-2 cap of 400.")


if __name__ == "__main__":
    main()
