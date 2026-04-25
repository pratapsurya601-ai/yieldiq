"""Rebaseline ``sector_snapshot.json`` after a verified intentional shift.

Guardrails
----------
1. Refuses to run without ``--reason "<why>"``. Every rebaseline must
   carry a one-line explanation that gets appended to the snapshot's
   changelog — so future readers can reconstruct why a sector baseline
   moved 20 percent on a random Tuesday.
2. Refuses to run if ``sector_isolation_check.py`` currently reports
   unexpected shifts AND ``--force`` is not passed. The typical flow is:

       a. PR changes scoring for Cement.
       b. Author adds ``sector-scope: Cement`` to PR body.
       c. Gate passes because Cement is in scope.
       d. PR merges.
       e. Author runs ``update_sector_snapshot.py --reason "PR #71 Cement
          WACC refresh — verified per-ticker triage OK"`` to lock in the
          new baseline so future PRs gate against it.

   The ``--force`` path is only for initial seeding (there is no
   baseline yet) or rare emergency rebaselines.
3. Writes atomically (tmpfile + rename) so a crashed run never leaves a
   half-written snapshot on disk that would then fail to load as JSON.

Output format
-------------
Mirrors the shape documented in SECTOR_ISOLATION.md::

    {
      "taken_at": "<iso>",
      "cache_version": <int or null>,
      "commit_sha": "<12-char git sha>",
      "changelog": [
        {"at": "<iso>", "reason": "<why>", "commit": "<sha>"},
        ...
      ],
      "sectors": {
        "Cement": {
          "tickers": ["SHREECEM.NS", ...],
          "median_fv": 5000.0,
          "median_score": 52,
          "median_mos_pct": -18.0,
          "median_iv_px_ratio": 0.85,
          "n_with_data": 3
        },
        ...
      }
    }
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import canary_diff as cd  # noqa: E402
import sector_isolation_check as sic  # noqa: E402

DEFAULT_SNAPSHOT = REPO_ROOT / "scripts" / "sector_snapshot.json"


def _cache_version() -> int | None:
    """Best-effort CACHE_VERSION read; returns None if not resolvable.

    We don't hard-fail if we can't read it — the snapshot is still
    useful. But recording it alongside sector medians helps triage
    cross-cache-version drift.
    """
    env = os.environ.get("CACHE_VERSION")
    if env and env.isdigit():
        return int(env)
    candidates = [
        REPO_ROOT / "backend" / "services" / "cache_service.py",
        REPO_ROOT / "backend" / "services" / "analysis" / "service.py",
    ]
    import re
    pat = re.compile(r"CACHE_VERSION\s*=\s*(\d+)")
    for c in candidates:
        if c.exists():
            m = pat.search(c.read_text(encoding="utf-8", errors="replace"))
            if m:
                return int(m.group(1))
    return None


def build_snapshot(
    stocks: list[dict], state: dict[str, dict]
) -> dict[str, dict]:
    return sic.aggregate_by_sector(stocks, state)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Rebaseline sector_snapshot.json after a verified intentional shift"
    )
    p.add_argument("--reason", required=True,
                   help="one-line explanation appended to the snapshot changelog (required)")
    p.add_argument("--out", default=str(DEFAULT_SNAPSHOT))
    p.add_argument("--stocks", default=str(cd.DEFAULT_STOCKS))
    p.add_argument("--state-from", default=None,
                   help="reuse a canary_diff --snapshot file (skips API fetch)")
    p.add_argument("--force", action="store_true",
                   help="allow rebaseline even if sector_isolation_check reports "
                        "unexpected shifts (initial seeding or emergency only)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    reason = args.reason.strip()
    if not reason:
        print("ERROR: --reason must be a non-empty string", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    stocks = cd.load_stocks(Path(args.stocks))

    if args.state_from:
        state = sic._load_state_from_snapshot(Path(args.state_from))
        sic._augment_scores(stocks, state)
    else:
        print(f"Fetching canary-{len(stocks)} from {cd.API_BASE}...", flush=True)
        state = cd.collect_state(
            stocks, api_base=cd.API_BASE, token=cd.AUTH_TOKEN, verbose=not args.quiet
        )
        sic._augment_scores(stocks, state)

    # Safety check: if a baseline exists and the check is currently
    # failing, block the rebaseline unless --force.
    prior: dict | None = None
    if out_path.exists():
        try:
            prior = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            prior = None
    if prior and not args.force:
        exit_code, rpt = sic.run(prior.get("sectors") or {}, stocks, state, scope=None)
        if exit_code != 0:
            unexpected = rpt["unexpected_shifts"]
            print("ERROR: refusing to rebaseline while unexpected shifts exist.",
                  file=sys.stderr)
            print("Shifts detected:", file=sys.stderr)
            for r in unexpected:
                print(f"  - {r['sector']}: {'; '.join(r.get('reasons') or [])}",
                      file=sys.stderr)
            print("", file=sys.stderr)
            print("Per the workflow, a human must first run per-ticker triage "
                  "on each shifted sector.", file=sys.stderr)
            print("If the shifts are all intentional and verified, re-run with "
                  "--force and cite the triage in --reason.", file=sys.stderr)
            return 1

    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    sha = cd._git_sha()
    sectors = build_snapshot(stocks, state)
    changelog = list((prior or {}).get("changelog") or [])
    changelog.append({"at": now, "reason": reason, "commit": sha})

    payload = {
        "taken_at": now,
        "cache_version": _cache_version(),
        "commit_sha": sha,
        "changelog": changelog,
        "sectors": sectors,
    }

    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(out_path)
    print(f"Wrote {out_path} (sectors={len(sectors)}, reason={reason!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
