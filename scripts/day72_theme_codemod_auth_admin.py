"""Day-72 theme codemod (PR-4 of 4): swap hardcoded gray/white classes
for design tokens across auth + legal + terms/privacy surfaces.

Reuses the swap logic from `day69_theme_codemod` (PR-1).
"""
from __future__ import annotations

from pathlib import Path

from day69_theme_codemod import apply_swaps

ROOT = Path(__file__).resolve().parents[1]
F = ROOT / "frontend" / "src"

# In-scope files (auth + legal + (marketing)/terms + (marketing)/privacy).
# No `frontend/src/app/admin` or `(auth)/` directory exists; admin under
# `(app)/admin` was already handled by PR-1.
TARGETS = [
    "app/auth/login/page.tsx",
    "app/auth/callback/page.tsx",
    "app/auth/signup/page.tsx",
    "app/auth/reset-password/page.tsx",
    "app/auth/forgot-password/page.tsx",
    "app/legal/sla/page.tsx",
    "app/(marketing)/terms/page.tsx",
    "app/(marketing)/privacy/page.tsx",
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


if __name__ == "__main__":
    main()
