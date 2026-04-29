"""scripts/generate_retrospective_publication.py

Quarterly retrospective publication generator.

Pulls the public retrospective payload from the live API and writes
three artifacts under ``docs/publications/``:

  * ``retrospective_<quarter>.md``           — long-form publication
  * ``retrospective_<quarter>.twitter.md``   — 4-tweet thread
  * ``retrospective_<quarter>.linkedin.md``  — single LinkedIn post

The script never posts anything to a live network. Auto-posting is
gated behind ``RETROSPECTIVE_PUBLISH_MODE=auto`` and is currently
stubbed (no real Twitter / LinkedIn API integration ships in this PR;
see docs/publications/retrospective_publication_design.md).

Usage::

    python scripts/generate_retrospective_publication.py \\
        --quarter Q1FY27 --window 90 \\
        --api-base https://api.yieldiq.in

    # Read mock JSON from disk instead of hitting the network:
    python scripts/generate_retrospective_publication.py \\
        --quarter Q1FY27 --fixture tests/fixtures/retro_sample.json

Exit codes:
  0  artifacts written successfully
  2  bad arguments
  3  retrospective payload reports ``is_sample=true`` and
     ``--allow-sample`` was not passed; nothing written.
  4  network / API failure.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("retro_publish")

DISCLAIMER = (
    "Past results are not indicative of future returns. "
    "SEBI: descriptive only, not advisory. "
    "Sample size, survivorship-bias and look-ahead-bias caveats apply."
)

PERFORMANCE_URL = "https://yieldiq.in/methodology/performance"
WHITEPAPER_URL = "https://yieldiq.in/methodology/whitepaper"

TWITTER_LIMIT = 280
LINKEDIN_LIMIT = 3000


# ─────────────────────────────────────────────────────────────────
# Data fetch
# ─────────────────────────────────────────────────────────────────
def fetch_retrospective(api_base: str, quarter: str, window: int,
                        timeout: int = 30) -> dict[str, Any]:
    url = (f"{api_base.rstrip('/')}/api/v1/public/retrospective"
           f"?period={quarter}&window={window}")
    logger.info("GET %s", url)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────
# Renderers
# ─────────────────────────────────────────────────────────────────
def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.1f}%"


def _fmt_rate(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:.1f}%"


def render_markdown(payload: dict[str, Any]) -> str:
    p = payload
    period = p["period"]
    label = period.get("label", "?")
    start = period.get("start", "?")
    end = period.get("end", "?")
    bench = p.get("benchmark", {}) or {}
    bench_t = bench.get("ticker", "NIFTY500.NS")
    bench_r = bench.get("return_pct")

    winners = p.get("winners", []) or []
    losers = p.get("losers", []) or []

    lines = [
        f"# YieldIQ {label} Performance Retrospective",
        "",
        f"_Window: {start} → {end} ({p.get('window_days', 90)}-day outcomes)_",
        "",
        "## What this is",
        "",
        "Every quarter, once we have at least 90 days of realized prices, "
        "we publish how the model's `undervalued` calls actually performed. "
        "We publish this regardless of the result. Misses are listed alongside "
        "wins.",
        "",
        "## Headline numbers",
        "",
        f"- Predictions in window (MoS > {p.get('mos_threshold', 30):.0f}%): "
        f"**{p.get('n_predictions', 0)}**",
        f"- Mean 90-day return: **{_fmt_pct(p.get('mean_return'))}**",
        f"- Median 90-day return: **{_fmt_pct(p.get('median_return'))}**",
        f"- Hit rate (positive return): **{_fmt_rate(p.get('hit_rate'))}**",
        f"- Outperform rate vs `{bench_t}`: "
        f"**{_fmt_rate(p.get('outperform_rate'))}**",
        f"- Benchmark return: **{_fmt_pct(bench_r)}**",
        "",
        "## Top 5 winners",
        "",
        "| Ticker | 90-day return |",
        "| --- | ---: |",
    ]
    for w in winners[:5]:
        lines.append(f"| {w.get('ticker', '?')} | {_fmt_pct(w.get('return_pct'))} |")

    lines += [
        "",
        "## Bottom 5 losers",
        "",
        "We publish the misses too. Cherry-picking would defeat the point.",
        "",
        "| Ticker | 90-day return |",
        "| --- | ---: |",
    ]
    for l in losers[:5]:
        lines.append(f"| {l.get('ticker', '?')} | {_fmt_pct(l.get('return_pct'))} |")

    lines += [
        "",
        "## Methodology and full numbers",
        "",
        f"- Methodology whitepaper: <{WHITEPAPER_URL}>",
        f"- Live retrospective dashboard: <{PERFORMANCE_URL}>",
        "",
        "## Disclaimer",
        "",
        DISCLAIMER,
    ]
    return "\n".join(lines) + "\n"


def render_twitter_thread(payload: dict[str, Any]) -> str:
    """Render a 4-tweet thread.

    Each tweet must be <= 280 chars. We fail loudly if any tweet
    exceeds that.
    """
    p = payload
    label = p["period"].get("label", "?")
    n = p.get("n_predictions", 0)
    mean_r = _fmt_pct(p.get("mean_return"))
    med_r = _fmt_pct(p.get("median_return"))
    out_rate = _fmt_rate(p.get("outperform_rate"))
    winners = p.get("winners", [])[:5]
    losers = p.get("losers", [])[:5]

    def _line(items: list[dict[str, Any]]) -> str:
        return ", ".join(
            f"{x.get('ticker', '?').replace('.NS', '')} {_fmt_pct(x.get('return_pct'))}"
            for x in items
        )

    t1 = (
        f"{label} retrospective: of {n} stocks our model called "
        f"undervalued (>30% MoS), {out_rate} outperformed Nifty 500 "
        f"over 90 days. Mean: {mean_r}. Median: {med_r}."
    )
    t2 = f"Top 5 winners ({label}): {_line(winners)}"
    t3 = (
        f"Bottom 5 losers ({label}): {_line(losers)}. "
        f"Yes — we publish the misses too."
    )
    t4 = (
        f"Methodology: {WHITEPAPER_URL}\n"
        f"Full numbers: {PERFORMANCE_URL}\n"
        f"SEBI: descriptive only, not advisory."
    )

    tweets = [t1, t2, t3, t4]
    over = [(i, len(t)) for i, t in enumerate(tweets, 1) if len(t) > TWITTER_LIMIT]
    if over:
        raise ValueError(
            f"Tweet(s) exceed {TWITTER_LIMIT} chars: {over}"
        )

    body = []
    for i, t in enumerate(tweets, 1):
        body.append(f"## Tweet {i}/4 ({len(t)} chars)\n\n{t}\n")
    return "\n".join(body)


def render_linkedin(payload: dict[str, Any]) -> str:
    p = payload
    label = p["period"].get("label", "?")
    n = p.get("n_predictions", 0)
    mean_r = _fmt_pct(p.get("mean_return"))
    med_r = _fmt_pct(p.get("median_return"))
    out_rate = _fmt_rate(p.get("outperform_rate"))
    hit_rate = _fmt_rate(p.get("hit_rate"))
    winners = p.get("winners", [])[:3]
    losers = p.get("losers", [])[:3]

    def _short(items: list[dict[str, Any]]) -> str:
        return ", ".join(
            f"{x.get('ticker', '?').replace('.NS', '')} ({_fmt_pct(x.get('return_pct'))})"
            for x in items
        )

    body = (
        f"{label} retrospective — how YieldIQ's model actually did.\n\n"
        f"This quarter, our DCF model flagged {n} Indian stocks as "
        f"\"undervalued\" (margin of safety > 30%). Ninety days later, "
        f"{out_rate} of those calls outperformed the Nifty 500. "
        f"Mean return: {mean_r}. Median: {med_r}. Hit rate "
        f"(positive return): {hit_rate}.\n\n"
        f"Top wins: {_short(winners)}.\n"
        f"Misses we own: {_short(losers)}.\n\n"
        f"Why publish the misses? Because survivorship bias is the "
        f"oldest trick in this industry, and we'd rather lose your "
        f"trust honestly than keep it dishonestly. Our biggest lesson "
        f"this quarter is the same one every quarter: a wide margin of "
        f"safety doesn't protect you from the macro tape, but it does "
        f"keep the median honest.\n\n"
        f"Full numbers, ticker-by-ticker: {PERFORMANCE_URL}\n"
        f"Methodology whitepaper: {WHITEPAPER_URL}\n\n"
        f"{DISCLAIMER}"
    )
    if len(body) > LINKEDIN_LIMIT:
        raise ValueError(
            f"LinkedIn body exceeds {LINKEDIN_LIMIT} chars: {len(body)}"
        )
    return body


def render_email(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (subject, body) for the subscriber email digest."""
    p = payload
    label = p["period"].get("label", "?")
    n = p.get("n_predictions", 0)
    mean_r = _fmt_pct(p.get("mean_return"))
    out_rate = _fmt_rate(p.get("outperform_rate"))
    winners = p.get("winners", [])[:3]
    losers = p.get("losers", [])[:3]

    def _ln(items: list[dict[str, Any]]) -> str:
        return "\n".join(
            f"  - {x.get('ticker', '?')}: {_fmt_pct(x.get('return_pct'))}"
            for x in items
        )

    subject = f"YieldIQ {label} Retrospective — How our model did"
    body = (
        f"Hi there,\n\n"
        f"This quarter, our model called {n} stocks \"undervalued\" "
        f"(>30% margin of safety).\n"
        f"Ninety days later: {out_rate} beat Nifty 500. Mean return: "
        f"{mean_r}.\n\n"
        f"Top 3 wins:\n{_ln(winners)}\n\n"
        f"Top 3 misses:\n{_ln(losers)}\n\n"
        f"Full numbers, methodology, and the misses we'd love to "
        f"learn from:\n  {PERFORMANCE_URL}\n\n"
        f"We publish this every quarter. Past results aren't future "
        f"returns.\n\n"
        f"— The YieldIQ team\n\n"
        f"---\n{DISCLAIMER}\n"
    )
    return subject, body


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────
def write_artifacts(payload: dict[str, Any], quarter: str,
                    out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"retrospective_{quarter}.md"
    tw_path = out_dir / f"retrospective_{quarter}.twitter.md"
    li_path = out_dir / f"retrospective_{quarter}.linkedin.md"
    em_path = out_dir / f"retrospective_{quarter}.email.txt"

    md_path.write_text(render_markdown(payload), encoding="utf-8")
    tw_path.write_text(render_twitter_thread(payload), encoding="utf-8")
    li_path.write_text(render_linkedin(payload), encoding="utf-8")
    subject, body = render_email(payload)
    em_path.write_text(f"Subject: {subject}\n\n{body}", encoding="utf-8")

    return {"markdown": md_path, "twitter": tw_path,
            "linkedin": li_path, "email": em_path}


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quarter", required=True, help="e.g. Q1FY27")
    p.add_argument("--window", type=int, default=90)
    p.add_argument("--api-base", default=os.environ.get(
        "RETRO_API_BASE", "https://yieldiq-production.up.railway.app"))
    p.add_argument("--fixture", help="Read JSON payload from this path "
                   "instead of hitting the API (for tests / dry runs).")
    p.add_argument("--out-dir", default="docs/publications")
    p.add_argument("--allow-sample", action="store_true",
                   help="Generate artifacts even when payload reports "
                        "is_sample=true. Default: refuse and exit 3.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if args.fixture:
        payload = load_fixture(Path(args.fixture))
    else:
        try:
            payload = fetch_retrospective(args.api_base, args.quarter,
                                          args.window)
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError) as exc:
            logger.error("retrospective fetch failed: %s", exc)
            return 4

    if payload.get("is_sample") and not args.allow_sample:
        logger.warning(
            "retrospective payload reports is_sample=true — refusing "
            "to publish placeholder data. Pass --allow-sample to "
            "override (only for previews / tests)."
        )
        return 3

    out_dir = Path(args.out_dir)
    paths = write_artifacts(payload, args.quarter, out_dir)
    for kind, path in paths.items():
        logger.info("wrote %s artifact: %s", kind, path)

    mode = os.environ.get("RETROSPECTIVE_PUBLISH_MODE", "review").lower()
    if mode == "auto":
        # Auto-post is intentionally stubbed in this PR. Adding real
        # Twitter / LinkedIn API calls is gated on credentials review.
        logger.info(
            "RETROSPECTIVE_PUBLISH_MODE=auto requested but live posting "
            "is stubbed. See docs/publications/"
            "retrospective_publication_design.md for setup steps."
        )
    else:
        logger.info("Mode A (review): artifacts written for human review.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
