"""Day-37: bulk-patch dark: variants into the 5 remaining empty-state
components (WatchlistEmpty was patched manually as the template)."""
from pathlib import Path

# Same find→replace pattern for all 5 files
PATCHES = [
    # Icon container
    ("bg-blue-50 flex items-center justify-center mb-4",
     "bg-blue-50 dark:bg-blue-950/40 flex items-center justify-center mb-4"),
    # Icon glyph
    ('className="h-8 w-8 text-blue-500" fill="none"',
     'className="h-8 w-8 text-blue-500 dark:text-blue-300" fill="none"'),
    # Title
    ('text-lg font-semibold text-gray-900 mb-1',
     'text-lg font-semibold text-gray-900 dark:text-ink mb-1'),
    # Body paragraph
    ('text-sm text-gray-500 mb-6 max-w-xs',
     'text-sm text-gray-500 dark:text-caption mb-6 max-w-xs'),
    # Secondary caption
    ('text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-3',
     'text-[10px] font-bold text-gray-500 dark:text-caption uppercase tracking-widest mb-3'),
    # Link below CTA
    ('mt-3 text-xs text-blue-600 hover:text-blue-700 hover:underline font-medium',
     'mt-3 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 hover:underline font-medium'),
    # CTA button background variant (gray-100 secondary)
    ('"bg-gray-100 text-gray-700 text-sm font-semibold"',
     '"bg-gray-100 dark:bg-bg text-gray-700 dark:text-ink text-sm font-semibold"'),
    ('"hover:bg-gray-200 active:bg-gray-300 active:scale-[0.97] transition"',
     '"hover:bg-gray-200 dark:hover:bg-border active:bg-gray-300 active:scale-[0.97] transition"'),
]

FILES = [
    "frontend/src/components/empty-states/HomeEmpty.tsx",
    "frontend/src/components/empty-states/AlertsEmpty.tsx",
    "frontend/src/components/empty-states/CompareEmpty.tsx",
    "frontend/src/components/empty-states/ConcallEmpty.tsx",
    "frontend/src/components/empty-states/PortfolioEmpty.tsx",
]

ROOT = Path(__file__).resolve().parents[1]


def patch_file(path: Path) -> tuple[int, list[str]]:
    src = path.read_text(encoding="utf-8")
    original = src
    matched = []
    for old, new in PATCHES:
        if old in src:
            src = src.replace(old, new)
            matched.append(old[:50] + "...")
    # Idempotency: skip if already dark-patched
    if "Day-37" not in src and matched:
        src = src.replace(
            "export default function",
            "// Day-37 (2026-05-20): dark variants added — see\n"
            "// docs/design/week2-ux-audit-2026-05-20.md\nexport default function",
            1,
        )
    if src != original:
        path.write_text(src, encoding="utf-8")
    return len(matched), matched


def main() -> int:
    total_files = 0
    total_patches = 0
    for rel in FILES:
        p = ROOT / rel
        if not p.exists():
            print(f"SKIP (missing): {rel}")
            continue
        n, _ = patch_file(p)
        total_files += 1 if n > 0 else 0
        total_patches += n
        print(f"{rel}: {n} patches")
    print(f"\nDONE: {total_patches} patches across {total_files} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
