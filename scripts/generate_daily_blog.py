"""Daily auto-generated blog post: top undervalued stocks.

Pulls top-N stocks by margin-of-safety from fair_value_history,
asks Groq (Llama 3.3 70B) to write a SEBI-safe educational
commentary, and APPENDS the post to ``frontend/src/lib/blog.ts``
so Vercel rebuilds and serves it as ``/blog/<slug>``.

SEBI compliance rules baked into the prompt
-------------------------------------------
* Never use buy / sell / hold / accumulate / target language.
* Never quote a "price target" or recommend an action.
* Always frame as "model output", "fair-value estimate", "factual
  observation about reported financials".
* Always include the SEBI disclaimer block in the post body.
* No personal-investment-advice language whatsoever.

The post is structured as:
  - 100-word intro (what the model surfaced today)
  - For each of the top 5 stocks: company name, sector, MoS,
    one-paragraph fundamental observation (Groq-generated)
  - Methodology footer link
  - Mandatory SEBI disclaimer

Idempotency
-----------
Skips if today's post already exists in ``BLOG_POSTS``.

Usage
-----
    DATABASE_URL=... GROQ_API_KEY=... python scripts/generate_daily_blog.py
    python scripts/generate_daily_blog.py --dry-run     # print, don't write
    python scripts/generate_daily_blog.py --top-n 7     # default 5

Schedule
--------
GH Actions cron 03:30 UTC daily (09:00 IST), commits + pushes.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import textwrap
from datetime import date
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("daily_blog")

_REPO = Path(__file__).resolve().parent.parent
BLOG_TS = _REPO / "frontend" / "src" / "lib" / "blog.ts"


# ── SEBI-safe prompt template ────────────────────────────────

_GROQ_SYSTEM = """You are a financial-data summarizer for an Indian
investing platform. You write neutral, educational commentary about
publicly-available stock fundamentals. You MUST follow these rules:

1. NEVER use the words: buy, sell, hold, accumulate, recommend, target,
   should, must, ought, advise.
2. NEVER predict future prices or returns.
3. NEVER suggest the reader take any action with their money.
4. Frame everything as "the model estimates", "the company reported",
   "publicly-disclosed financials show".
5. Output one short paragraph (60-90 words) per stock.
6. Use plain language a retail investor can understand.
7. End every paragraph with: "Numbers as reported; not investment advice."
"""

_GROQ_USER_TEMPLATE = """Today the YieldIQ DCF model surfaced these
five stocks with the largest model-implied margin of safety. Write a
short neutral commentary paragraph for EACH. Output JSON:

{{
  "intro": "100-word general framing of what 'margin of safety' means
  in our model and why these 5 surfaced today, no recommendations",
  "commentaries": [
    {{"ticker": "XXX", "paragraph": "60-90 word paragraph"}},
    ... 5 entries total
  ]
}}

Stocks for today:
{stocks_json}
"""


def _call_groq(prompt: str, system: str = _GROQ_SYSTEM) -> str | None:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        logger.error("GROQ_API_KEY not set")
        return None
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        comp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        return (comp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error("Groq call failed: %s", e)
        return None


# ── DB query for today's top-N ──────────────────────────────

def _fetch_top_undervalued(top_n: int = 5) -> list[dict[str, Any]]:
    import psycopg2
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("""
            WITH latest AS (
              SELECT DISTINCT ON (ticker)
                ticker, fair_value, price, mos_pct, verdict
              FROM fair_value_history
              ORDER BY ticker, date DESC
            )
            SELECT
              l.ticker,
              s.company_name,
              s.sector,
              l.fair_value,
              l.price,
              l.mos_pct
            FROM latest l
            JOIN stocks s ON s.ticker = l.ticker
            WHERE l.mos_pct IS NOT NULL
              AND l.mos_pct > 15  -- only model-undervalued
              AND l.mos_pct < 90  -- exclude data-quality outliers
              AND s.is_active = TRUE
              AND l.fair_value IS NOT NULL
              AND l.price IS NOT NULL
            ORDER BY l.mos_pct DESC
            LIMIT %s
        """, (top_n,))
        cols = ("ticker", "company_name", "sector", "fair_value", "price", "mos_pct")
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()
    # Coerce types
    for r in rows:
        r["fair_value"] = float(r["fair_value"]) if r["fair_value"] is not None else None
        r["price"] = float(r["price"]) if r["price"] is not None else None
        r["mos_pct"] = float(r["mos_pct"]) if r["mos_pct"] is not None else None
    return rows


# ── markdown assembly ───────────────────────────────────────

def _build_markdown(today: date, stocks: list[dict], llm_intro: str,
                    llm_commentaries: list[dict]) -> str:
    """Compose the full post body in markdown."""
    cmt_by_ticker = {c.get("ticker"): c.get("paragraph", "") for c in llm_commentaries}
    parts: list[str] = []
    parts.append(llm_intro.strip())
    parts.append("")
    parts.append("---")
    parts.append("")
    for s in stocks:
        cmt = cmt_by_ticker.get(s["ticker"], "")
        parts.append(f"## {s['company_name']} ({s['ticker']})")
        parts.append("")
        parts.append(
            f"**Sector:** {s.get('sector') or '\u2014'} "
            f"&middot; **Price:** \u20b9{s['price']:,.2f} "
            f"&middot; **Model fair value:** \u20b9{s['fair_value']:,.2f} "
            f"&middot; **Model MoS:** +{s['mos_pct']:.1f}%"
        )
        parts.append("")
        parts.append(cmt or "(commentary unavailable)")
        parts.append("")
        parts.append(
            f"[See full {s['company_name']} analysis]"
            f"(/stocks/{s['ticker']}/fair-value)"
        )
        parts.append("")
        parts.append("---")
        parts.append("")
    parts.append("## How we calculated these")
    parts.append("")
    parts.append(
        "Margin of Safety = (model fair value \u2212 current price) / current price. "
        "Fair value is a 5-year DCF discounted at WACC, with terminal growth "
        "capped at 4%. Inputs are publicly-reported financials and market prices "
        "as of " + today.isoformat() + "."
    )
    parts.append("")
    parts.append("[Read the full DCF methodology](/blog/what-is-dcf-valuation)")
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append("## Disclaimer")
    parts.append("")
    parts.append(
        "YieldIQ is a model-driven research tool. Numbers in this post are "
        "machine-generated estimates from publicly-available data. Nothing on "
        "this page is investment advice, a recommendation to buy, sell, or hold "
        "any security, or a solicitation. Past results do not guarantee future "
        "performance. Please consult a SEBI-registered investment adviser "
        "before making any investment decisions. YieldIQ is not registered as "
        "an investment adviser or research analyst with SEBI."
    )
    return "\n".join(parts)


# ── post insertion ──────────────────────────────────────────

def _build_blog_post_object(today: date, title: str,
                            description: str, content: str) -> str:
    """Render a TypeScript object literal ready to splice into BLOG_POSTS."""
    slug = f"top-undervalued-{today.isoformat()}"
    # Escape backticks + ${} in markdown
    safe = content.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    return f"""  {{
    slug: {json.dumps(slug)},
    title: {json.dumps(title)},
    description: {json.dumps(description)},
    date: {json.dumps(today.isoformat())},
    author: "YieldIQ Model",
    category: "framework",
    readTime: 4,
    content: `{safe}`,
  }},
"""


def _slug_already_exists(slug: str) -> bool:
    if not BLOG_TS.exists():
        return False
    body = BLOG_TS.read_text(encoding="utf-8")
    return f'slug: "{slug}"' in body or f"slug: '{slug}'" in body


def _splice_into_blog_ts(post_object: str) -> bool:
    """Insert the new post immediately after `BLOG_POSTS = [`. Idempotent."""
    body = BLOG_TS.read_text(encoding="utf-8")
    marker = "export const BLOG_POSTS: BlogPost[] = ["
    idx = body.find(marker)
    if idx < 0:
        logger.error("Couldn't locate BLOG_POSTS marker in blog.ts")
        return False
    insert_pos = idx + len(marker)
    new_body = body[:insert_pos] + "\n" + post_object + body[insert_pos:]
    BLOG_TS.write_text(new_body, encoding="utf-8")
    return True


# ── main ────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = date.today()
    slug = f"top-undervalued-{today.isoformat()}"
    if _slug_already_exists(slug):
        logger.info("post for %s already exists, skipping", today)
        return 0

    stocks = _fetch_top_undervalued(top_n=args.top_n)
    if not stocks:
        logger.warning("no qualifying stocks today, skipping")
        return 0
    logger.info("top %d candidates: %s", len(stocks),
                ", ".join(s["ticker"] for s in stocks))

    prompt = _GROQ_USER_TEMPLATE.format(
        stocks_json=json.dumps(stocks, indent=2, default=str)
    )
    raw = _call_groq(prompt)
    if not raw:
        logger.error("Groq returned nothing — aborting")
        return 1

    try:
        llm = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("Groq response wasn't valid JSON: %s\n%s", e, raw[:400])
        return 1

    intro = llm.get("intro", "").strip()
    commentaries = llm.get("commentaries", [])
    if not intro or not commentaries:
        logger.error("Groq response missing intro/commentaries")
        return 1

    # SEBI safety check — reject any forbidden words sneaking through
    forbidden = re.compile(
        r"\b(buy|sell|hold|accumulate|recommend|target price|should buy|"
        r"should sell|advise|advice to)\b",
        re.IGNORECASE,
    )
    full_text = intro + " " + " ".join(c.get("paragraph", "") for c in commentaries)
    bad_hit = forbidden.search(full_text)
    if bad_hit:
        logger.error(
            "SEBI-safety check failed — found forbidden phrase: %r. "
            "Aborting and not publishing.", bad_hit.group(0)
        )
        return 2

    md = _build_markdown(today, stocks, intro, commentaries)
    title = (
        f"{len(stocks)} Stocks With the Largest Model Margin of Safety \u2014 "
        f"{today.strftime('%d %B %Y')}"
    )
    description = textwrap.shorten(
        intro.replace("\n", " "), width=160, placeholder="\u2026"
    )

    post_object = _build_blog_post_object(today, title, description, md)

    if args.dry_run:
        print("=== Would insert into blog.ts ===")
        print(post_object[:1500])
        return 0

    ok = _splice_into_blog_ts(post_object)
    if not ok:
        return 1
    logger.info("blog post written: /blog/%s", slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
