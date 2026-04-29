# Quarterly Retrospective Publication — Design

_Last updated: 2026-04-29_

## The ritual

Every Indian fiscal quarter, once we have **at least 90 days of
realized outcome data** for the model's `undervalued` calls, we
publish a retrospective summarizing how those calls actually performed.

| Cron fires       | Quarter just closed | Outcome window covers   |
| ---------------- | ------------------- | ----------------------- |
| **Aug 1**        | Q1 (Apr–Jun)        | predictions + 90 days   |
| **Nov 1**        | Q2 (Jul–Sep)        | predictions + 90 days   |
| **Feb 1**        | Q3 (Oct–Dec)        | predictions + 90 days   |
| **May 1**        | Q4 (Jan–Mar)        | predictions + 90 days   |

The cadence mirrors Morningstar's quarterly fund retrospective — the
ritual that has compounded their analyst credibility for 30 years.

**First publication:** scheduled for **Aug 1, 2026** (Q1FY27
retrospective). Nothing publishes today; the `workflow_dispatch`
button on `retrospective_quarterly.yml` is for testing only.

## What's included in every artifact

- N predictions in window (filtered by margin-of-safety > 30%)
- Mean / median 90-day return
- Hit rate (positive return) and outperform rate vs Nifty 500
- Top 5 winners and bottom 5 losers, with ticker + return
- Methodology link (`/methodology/whitepaper`)
- Live numbers link (`/methodology/performance`)
- SEBI descriptive-only disclaimer

## What's NOT included

- Recommendations to buy / sell / hold
- Forecasts for next quarter
- Cherry-picked windows or filtered universes
- "Annualized" returns derived from a 90-day window (lookahead-bias trap)
- Subscriber portfolio P&L

## Editorial guidelines

### How to caption a "win"

> POWERGRID flagged at 32% MoS on 2026-04-12. 90-day return: +38.2%
> vs benchmark +6.2%. Driver: Q4 capex guide raise on 2026-05-08
> rerated the regulated-utility cohort.

A win caption should:

- name the prediction date and the MoS at flag time
- name the benchmark differential, not just the absolute return
- (optional) cite the catalyst, but never imply we predicted the catalyst

### How to caption a "miss"

> ZOMATO flagged at 41% MoS on 2026-04-19. 90-day return: -18.3%
> vs benchmark +6.2%. Driver: regulatory action on 2026-05-21 we did
> not anticipate. Lesson: our food-delivery cohort lacks a regulatory
> overhang adjustment.

A miss caption should:

- own the miss in the first sentence (no hedging)
- name the differential
- name the lesson, even if the lesson is "we don't know yet"

## Mode A vs Mode B decision tree

```
                ┌─────────────────────────────┐
                │  Cron fires (Aug/Nov/Feb/May)│
                └──────────────┬──────────────┘
                               │
                  ┌────────────▼────────────┐
                  │  is_sample == true?     │
                  └────────────┬────────────┘
                               │
                ┌──────yes─────┴────no────────┐
                │                             │
                ▼                             ▼
        Skip + warn         ┌─────────────────────────────┐
        (no publish)        │ RETROSPECTIVE_PUBLISH_MODE? │
                            └────────────┬────────────────┘
                                         │
                          ┌────review────┴────auto────┐
                          │                           │
                          ▼                           ▼
              ┌──────────────────────┐     ┌──────────────────────┐
              │ Mode A (DEFAULT)     │     │ Mode B (env-gated)   │
              │ - upload artifacts   │     │ - artifacts written  │
              │ - commit to retro/   │     │ - attempt auto-post  │
              │   branch for review  │     │   to Twitter+LinkedIn│
              │ - founder posts      │     │ - currently STUBBED  │
              │   manually           │     │   (see below)        │
              └──────────────────────┘     └──────────────────────┘
```

### Mode A — review (default)

- Workflow generates artifacts under `docs/publications/retrospective_<Q>.*`
- Workflow opens a `retro/<Q>-YYYYMMDD` branch with the artifacts
- Founder reviews on the dashboard, edits captions, posts manually to
  Twitter / LinkedIn / email
- Email send goes through the existing `scripts/send_newsletter.py`
  pipeline (founder-pick mode) or directly via SendGrid CLI

### Mode B — auto

- Set workflow_dispatch input `mode=auto` OR add
  `RETROSPECTIVE_PUBLISH_MODE=auto` to the cron environment
- Requires GitHub secrets:
  - `TWITTER_API_KEY`, `TWITTER_API_SECRET`,
    `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET`
  - `LINKEDIN_ACCESS_TOKEN` (with `w_member_social` scope)
- **Status: STUBBED in this PR.** The workflow checks for credentials
  and emits a warning if missing. Real Twitter / LinkedIn API calls
  are not yet implemented; the integration ships in a follow-up PR
  once the founder has approved the auto-post copy template.

## SEBI compliance

Every artifact carries the standard disclaimer:

> Past results are not indicative of future returns.
> SEBI: descriptive only, not advisory.
> Sample size, survivorship-bias and look-ahead-bias caveats apply.

The retrospective is **descriptive analytics about a deterministic
DCF model's outputs**, not investment advice. We do not recommend
buying or selling any of the named tickers. Misses are listed
alongside wins. The `/methodology/performance` page links the full
universe of predictions, not a curated subset.

## Local testing

```bash
# Resolve which quarter would publish if today were Aug 1, 2026:
python scripts/resolve_prev_quarter.py --as-of 2026-08-01

# Generate artifacts from a fixture (no network):
python scripts/generate_retrospective_publication.py \
    --quarter Q1FY27 \
    --fixture tests/fixtures/retrospective_sample_payload.json \
    --out-dir /tmp/retro

# Run the test suite:
pytest tests/test_retrospective_publication.py -q
```

## Files in scope

- `.github/workflows/retrospective_quarterly.yml`
- `scripts/resolve_prev_quarter.py`
- `scripts/generate_retrospective_publication.py`
- `tests/test_retrospective_publication.py`
- `tests/fixtures/retrospective_sample_payload.json`
- `docs/publications/retrospective_publication_design.md`
- Sample artifacts: `docs/publications/retrospective_Q1FY27.*`
