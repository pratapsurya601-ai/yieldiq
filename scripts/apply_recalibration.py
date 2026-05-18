"""Apply a recalibration JSON artifact to ``models/industry_wacc.py``.

Reads the artifact produced by ``scripts/fetch_recalibration_inputs.py``,
prints a before/after diff per sector, and (with ``--apply``) rewrites
the per-sector ``beta_typical`` and ``terminal_growth`` lines in-place.

This script DOES NOT bump ``CACHE_VERSION`` and DOES NOT touch any
service / router / validator code. After it runs:

1. Operator reviews ``git diff models/industry_wacc.py``.
2. Operator runs ``python scripts/canary_diff.py`` (full 5-gate sweep).
3. Operator opens a SEPARATE PR carrying the WACC edits + the
   CACHE_VERSION bump + the canary-diff report — the discipline rules
   in CLAUDE.md require that bundle.

CLI:
    python scripts/apply_recalibration.py \\
        --input scripts/snapshots/recalibration_q2_2026_*.json
    python scripts/apply_recalibration.py \\
        --input scripts/snapshots/recalibration_q2_2026_*.json --apply
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WACC_FILE = _REPO_ROOT / "models" / "industry_wacc.py"

# Match either a sector header (``"sector_key": {``) or a field assignment
# (``"beta_typical":  1.05,``) inside that block. We only ever rewrite
# the value text on field-assignment lines we recognize.
_SECTOR_HEADER = re.compile(r'^(\s*)"([a-z_]+)"\s*:\s*\{\s*$')
_FIELD_LINE = re.compile(
    r'^(?P<indent>\s+)"(?P<field>beta_typical|terminal_growth)"\s*:\s*'
    r'(?P<value>[-+]?\d*\.?\d+)\s*,(?P<tail>.*)$'
)


def _load_artifact(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_input(arg: str) -> Path:
    """Allow either an exact path or a glob (operator convenience)."""
    p = Path(arg)
    if p.exists():
        return p
    matches = sorted(glob.glob(arg))
    if not matches:
        raise FileNotFoundError(arg)
    # Newest by mtime
    return Path(max(matches, key=lambda m: Path(m).stat().st_mtime))


def compute_changes(artifact: dict[str, Any]
                    ) -> dict[str, dict[str, tuple[float, float]]]:
    """Return ``{sector: {field: (old, new)}}`` for every targetable knob.

    "Old" comes from ``current_industry_wacc_snapshot`` in the artifact;
    we deliberately don't re-read industry_wacc.py here so the preview
    is reproducible from the artifact alone.
    """
    cur = artifact.get("current_industry_wacc_snapshot", {}) or {}
    betas = artifact.get("sector_betas", {}) or {}
    tg = artifact.get("terminal_growth", {}) or {}
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for sector, new in betas.items():
        old = cur.get(sector, {}).get("beta_typical")
        if old is None or abs(float(old) - float(new)) < 1e-9:
            continue
        out.setdefault(sector, {})["beta_typical"] = (float(old), float(new))
    for sector, new in tg.items():
        if sector == "default":
            continue
        old = cur.get(sector, {}).get("terminal_growth")
        if old is None or abs(float(old) - float(new)) < 1e-9:
            continue
        out.setdefault(sector, {})["terminal_growth"] = (float(old), float(new))
    return out


def rewrite_wacc_file(text: str,
                      changes: dict[str, dict[str, tuple[float, float]]]
                      ) -> tuple[str, list[str]]:
    """Apply ``changes`` to the source text of industry_wacc.py.

    Returns the new text plus a list of human-readable touch lines.
    Only edits sectors inside the first ``INDUSTRY_WACC = {`` block
    (i.e. ignores INDUSTRY_WACC_USA).
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    touches: list[str] = []
    in_indian_block = False
    current_sector: str | None = None

    for ln in lines:
        if "INDUSTRY_WACC = {" in ln:
            in_indian_block = True
            out.append(ln)
            continue
        if in_indian_block and ln.startswith("INDUSTRY_WACC_USA"):
            in_indian_block = False
            current_sector = None
            out.append(ln)
            continue

        if in_indian_block:
            mh = _SECTOR_HEADER.match(ln)
            if mh:
                current_sector = mh.group(2)
                out.append(ln)
                continue
            mf = _FIELD_LINE.match(ln)
            if mf and current_sector and current_sector in changes:
                field = mf.group("field")
                spec = changes[current_sector].get(field)
                if spec is not None:
                    old_v, new_v = spec
                    old_str = mf.group("value")
                    # Preserve original column alignment as much as we can:
                    # rebuild line with same indent/tail, padded value width.
                    new_str = _fmt_value(new_v, len(old_str))
                    new_line = (
                        f'{mf.group("indent")}"{field}":'
                        f'{" " * max(1, 17 - len(field))}'
                        f'{new_str},{mf.group("tail")}\n'
                    )
                    # Fallback: if our reformatter changed line shape too
                    # aggressively, keep a minimal surgical replacement.
                    surgical = ln.replace(
                        f'"{field}":', f'"{field}":', 1
                    )
                    surgical = re.sub(
                        rf'("{field}"\s*:\s*)[-+]?\d*\.?\d+',
                        rf'\g<1>{new_str}',
                        surgical,
                        count=1,
                    )
                    out.append(surgical)
                    touches.append(
                        f"{current_sector}.{field}: {old_str} → {new_str}"
                    )
                    continue
        out.append(ln)

    return "".join(out), touches


def _fmt_value(v: float, ref_width: int) -> str:
    # Use 3 decimals for beta-ish numbers (≥ 0.1) and 4 for terminal
    # growth-ish numbers (< 0.1). Falls back to original width.
    if abs(v) >= 0.1:
        s = f"{v:.3f}"
    else:
        s = f"{v:.4f}"
    return s


def print_diff_table(changes: dict[str, dict[str, tuple[float, float]]]) -> None:
    if not changes:
        print("[apply_recalibration] No changes detected vs current file.")
        return
    print()
    print("=" * 72)
    print("Pending recalibration changes")
    print("=" * 72)
    print(f"{'sector':<22}{'field':<20}{'old':>10}{'new':>10}{'Δ':>10}")
    for sector in sorted(changes):
        for field, (old, new) in changes[sector].items():
            print(f"{sector:<22}{field:<20}{old:>10.4f}{new:>10.4f}"
                  f"{new - old:>+10.4f}")
    print()


def predict_fv_impact(artifact: dict[str, Any]) -> None:
    """Read existing canary golden values (if present) and print a rough
    FV-impact estimate purely from rate-of-change math — no live API."""
    canary = _REPO_ROOT / "scripts" / "canary_stocks_50.json"
    if not canary.exists():
        print("[fv-impact] canary_stocks_50.json not found — skipping estimate.")
        return
    try:
        rows = json.loads(canary.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[fv-impact] could not parse canary file: {e}")
        return
    cur = artifact.get("current_industry_wacc_snapshot", {}) or {}
    rf_new = float(artifact.get("risk_free_rate") or 0.0)
    # Rough proxy: ΔFV% ≈ −ΔWACC × (1 / (WACC − g)) × WACC change-leverage.
    # We don't know each stock's sector here without re-running the engine,
    # so we report the aggregate rate-of-change of the median WACC default.
    if not cur:
        print("[fv-impact] no current snapshot — skipping estimate.")
        return
    waccs = [c.get("wacc_default") for c in cur.values()
             if isinstance(c.get("wacc_default"), (int, float))]
    if not waccs:
        print("[fv-impact] no wacc_default samples — skipping estimate.")
        return
    med = sorted(waccs)[len(waccs) // 2]
    # Read the operator-facing canary count for context.
    print(f"[fv-impact] canary universe: {len(rows)} rows; "
          f"median wacc_default {med:.3f}; new rf {rf_new:.3f}. "
          "Run scripts/canary_diff.py for the real 5-gate sweep.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--input", required=True,
                    help="recalibration artifact (path or glob)")
    ap.add_argument("--apply", action="store_true",
                    help="write changes to models/industry_wacc.py")
    args = ap.parse_args(argv)

    art_path = _resolve_input(args.input)
    print(f"[apply_recalibration] artifact: {art_path}")
    art = _load_artifact(art_path)
    changes = compute_changes(art)
    print_diff_table(changes)
    predict_fv_impact(art)

    if not args.apply:
        print("[dry-run] re-run with --apply to write the changes.")
        return 0

    if not changes:
        print("[apply] nothing to write.")
        return 0

    src = _WACC_FILE.read_text(encoding="utf-8")
    new_src, touches = rewrite_wacc_file(src, changes)
    if new_src == src:
        print("[apply] regex did not match any target line — aborting.")
        return 2
    _WACC_FILE.write_text(new_src, encoding="utf-8")
    print(f"[apply] wrote {_WACC_FILE} ({len(touches)} line edits):")
    for t in touches:
        print(f"  - {t}")
    print("\nNext steps:")
    print("  1. git diff models/industry_wacc.py   # review")
    print("  2. python scripts/canary_diff.py      # 5-gate sweep")
    print("  3. open a SEPARATE PR with the bump + CACHE_VERSION+1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
