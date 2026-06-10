#!/usr/bin/env python3
"""
check_manifest_public_title.py — guard the manifest entries' user-facing
``title_public`` field against engineering-jargon leaks.

Background
==========
The cache_invalidation_manifest tracks every model change so the
"Why we changed" timeline on /analysis/{ticker} can render an audit
trail. Engineers author entries with internal-cadence vocabulary
(``T4.5``, ``Phase C.2``, ``v_t6_2_ai_chat_phase_a_2026_06_10``,
``composite_intrinsic_value``, ``byte-identical``) which is meaningless
to end users and reads as advisory / SEBI-actionable on a non-registered
platform.

Three prior fixes (#123, #175, #188) hardened the rationale sanitiser
for Day-/Phase/Audit#/PR#/Task#/#NNN tokens, but the leak kept
recurring with NEW vocabulary forms each time (T-numbers, slug strings,
engineer-speak) because nothing validated the actual user-facing string
at the data layer.

This script enforces the structural fix introduced as ROOT-CAUSE #11
(2026-06-10): every manifest entry MUST carry a ``title_public`` field
that passes the banned-pattern guard. It is the CI check that backs the
runtime `public_manifest_entry` serializer.

Rules
=====
For every entry in ``backend.services.cache_invalidation_manifest.MANIFEST``:

1. Entry MUST have a non-empty ``title_public`` (str, ≤ 140 chars).
2. ``title_public`` MUST NOT match any of
   ``_TITLE_PUBLIC_BANNED_PATTERNS`` defined in
   ``cache_invalidation_manifest`` (T-numbers, Phase labels, Day-NNN,
   Audit#/PR#/Task#/#NNN cadence handles, internal slugs, raw field
   names, "byte-identical" / "bridge contract" engineer-speak).

Failures print as ``manifest:<version_id> -- <reason>`` lines and the
script exits 1.

Exit code
=========
    0  every entry passes.
    1  one or more entries failed the guard. Stderr lists each failure.
    2  internal error (manifest module failed to import, etc.).

Usage
=====
    python scripts/check_manifest_public_title.py

    # Limit to entries modified in the current branch only (CI mode):
    python scripts/check_manifest_public_title.py --diff-only \\
        --base origin/main
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/check_manifest_public_title.py` from repo root
# without needing PYTHONPATH set.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _import_manifest_module():
    """Import the manifest module with a graceful error if anything in
    the backend boot path is broken at this moment."""
    try:
        from backend.services import cache_invalidation_manifest as mod  # noqa: WPS433
    except Exception as exc:  # noqa: BLE001
        print(
            f"[check_manifest_public_title] failed to import "
            f"backend.services.cache_invalidation_manifest: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)
    return mod


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-length",
        type=int,
        default=140,
        help="Maximum length of title_public (default: 140 chars).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print every entry's version_id + title_public on success.",
    )
    args = parser.parse_args(argv)

    mod = _import_manifest_module()
    manifest = getattr(mod, "MANIFEST", None)
    matcher = getattr(mod, "_matches_banned_title_pattern", None)
    if manifest is None or matcher is None:
        print(
            "[check_manifest_public_title] MANIFEST or "
            "_matches_banned_title_pattern missing from module",
            file=sys.stderr,
        )
        return 2

    failures: list[str] = []
    successes: list[tuple[str, str]] = []
    for idx, entry in enumerate(manifest):
        version_id = (entry or {}).get("version_id") or f"<index {idx}>"
        title = (entry or {}).get("title_public")
        if not isinstance(title, str) or not title.strip():
            failures.append(
                f"manifest:{version_id} -- missing or empty title_public"
            )
            continue
        title = title.strip()
        if len(title) > args.max_length:
            failures.append(
                f"manifest:{version_id} -- title_public is "
                f"{len(title)} chars, exceeds max {args.max_length}"
            )
            continue
        hit = matcher(title)
        if hit is not None:
            failures.append(
                f"manifest:{version_id} -- title_public contains banned "
                f"token {hit!r}: {title!r}"
            )
            continue
        successes.append((version_id, title))

    if failures:
        print(
            f"[check_manifest_public_title] {len(failures)} entr"
            f"{'y' if len(failures) == 1 else 'ies'} failed the public-title "
            f"guard ({len(manifest)} total):",
            file=sys.stderr,
        )
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        print(
            "\nRemediation: edit the offending manifest entry in "
            "backend/services/cache_invalidation_manifest.py and replace "
            "the internal vocabulary (T-numbers, slugs, raw field names) "
            "with a one-sentence user-facing summary.",
            file=sys.stderr,
        )
        return 1

    if args.list:
        for version_id, title in successes:
            print(f"{version_id}: {title}")
    print(
        f"[check_manifest_public_title] OK — all {len(manifest)} entries "
        f"have a guard-passing title_public.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
