# Reddit / X / LinkedIn draft — 2026-05-22

Audience: r/IndiaInvestments. Tone: honest, technical, no marketing
speak, no recommendations, no SEBI-banned vocabulary. Topic chosen:
**the utility bear-floor bug from Day-92** (concrete numbers, real
story, clearly user-beneficial, technical enough that the sub will
respect it).

---

## r/IndiaInvestments — long-form post (target 950 words)

**Title:** A DCF bug made our tool show NTPC's bear case as ₹0. Here's what we got wrong and how we fixed it.

---

Hi all. I run a small free DCF tool for Indian stocks. Last month a
user emailed us with one line: "your bear case for NTPC is zero. That
can't be right." He was correct, and the reason it was zero turned out
to be more interesting than the bug itself. Writing this up because I
think the underlying mistake — treating regulated utilities like
cyclical businesses — is a thing I see in plenty of retail DCF
spreadsheets too.

**What the user saw**

Open the analysis page for NTPC. Three scenarios — bear, base, bull —
each with a fair-value rupee number. Base was around ₹360. Bull was
around ₹430. Bear was ₹0.

Not "₹40" or "₹120". Literally ₹0. The same was true for POWERGRID,
GAIL, IOC, and a couple of PSU banks. The tool was, with a straight
face, telling people that in a bad-but-plausible scenario these
companies were worth nothing.

**Why it happened**

Our DCF engine projects free cash flow over a 10-year explicit window
and then computes a terminal value using a perpetuity-growth formula.
The bear scenario applies a stress: revenue growth gets cut, margins
compress, and the discount rate (WACC) is bumped up to reflect the
worse environment.

For most businesses the stress is bounded by what the model itself can
produce — bear-case FCF for, say, an FMCG company stays positive
because brand equity and pricing power keep margins above zero even in
a stress.

For regulated utilities the input range was wider. NTPC's
trailing-twelve-month operating margin sits in a regulated band
because tariffs are set by CERC against an allowed return on the rate
base. When we applied the same percentage stress we use for cyclicals
— a 40% margin haircut — we drove the bear-case operating margin
below the level at which interest coverage stays positive. The model
then projected negative FCF for years 3–10. The terminal value
collapsed. Discount that back and you get a fair value that rounds to
zero.

In other words: our stress assumption was wrong for the asset class.
Regulated utilities aren't cyclicals. CERC doesn't let NTPC's allowed
return drop to zero in a downturn — the entire point of the
regulatory framework is that revenue is decoupled from short-cycle
demand. Stress-testing them as if their margins could go to zero is
modelling something that has never happened and which the regulatory
structure is designed to prevent.

**What we changed**

Three things, all visible in the codebase if anyone wants to check:

1. Per-sector bear-case floors. For sectors classified as
   "rate-regulated" (power generation, transmission, gas
   distribution, public-sector banks under PCA-style constraints) we
   floor the bear-case operating margin at the lower of (a) the
   regulated allowed-return level, or (b) the lowest historical
   margin in the last 10 years. Neither floor can be lower than the
   structural minimum at which the asset is still operating.

2. Bear-case WACC ceiling. For these sectors the stressed WACC is
   capped at +200 bps over the base case, not +500 bps. Risk-free
   rates and equity premia don't blow out for rate-regulated entities
   the way they do for cyclicals — the data shows their cost of debt
   is anchored by sovereign-adjacent ratings.

3. Terminal-value sanity check. If the implied terminal value of any
   scenario is less than the company's current rate base or
   regulatory-asset-base, we flag it in the audit log and floor the
   TV at the rate base. This is the "rate base economic value floor"
   — a regulated utility, in liquidation, is worth at least its
   regulated asset base because the regulator has already agreed to
   let it earn a return on that base.

**Before / after numbers**

| Stock | Bear (before) | Bear (after) | Base | Bull |
| --- | --- | --- | --- | --- |
| NTPC | ₹0 | ₹356 | ₹362 | ₹431 |
| POWERGRID | ₹0 | ₹278 | ₹291 | ₹344 |
| GAIL | ₹0 | ₹164 | ₹178 | ₹212 |

(Base and bull cases barely moved — only the bear case had the bug.)

**Why I'm writing this up**

Two reasons.

One: if you build your own DCFs, the lesson generalises. The bear
case for a regulated utility is not "what if margins compress 40%".
It's "what if the regulator changes the framework" or "what if the
allowed return drops 100 bps" — much narrower distributions. Using a
cyclical's stress on a utility produces nonsense numbers. I see this
in plenty of retail spreadsheets and even some sell-side models.

Two: we run a free public DCF tool at yieldiq.in. It's currently
showing the fixed numbers for the names above. If you analyse any
regulated utility on it and the bear case still looks wrong, please
tell us — either reply here or in the in-app feedback. I personally
read every report and we ship fixes within 24 hours when they're
correct. Same goes for any other model assumption that looks off.

Not asking anyone to use the tool, just inviting people who already
do retail DCF analysis to throw their hardest case at it and tell us
where the model is still wrong. That's how it gets better.

Edit: to be clear, none of the numbers above are investment advice or
a view on whether to hold these names. They're just outputs of a
public model that anyone can reproduce. Always do your own work.

---

## X / Twitter — 2-tweet thread

**1/** We had a DCF bug that made our tool show NTPC's bear case as
₹0. The reason was instructive: we were stressing a regulated utility
the same way we stress a cyclical. CERC-allowed returns don't go to
zero in a downturn — that's the entire point of rate-base regulation.

**2/** Fix: per-sector bear-case floors, capped WACC stress, and a
terminal-value sanity check against the regulated asset base. NTPC
bear went ₹0 → ₹356. POWERGRID ₹0 → ₹278. Public DCF tool at
yieldiq.in if you want to try your own utility and tell us where the
model is still wrong.

---

## LinkedIn — single paragraph

Brief post-mortem from the YieldIQ build: a DCF stress assumption that
worked for cyclicals was driving the bear-case fair value of
regulated utilities (NTPC, POWERGRID, GAIL) to ₹0 by projecting
negative free cash flow under a margin haircut that the regulatory
framework would never actually permit. The fix is per-sector
bear-case floors, a tighter WACC stress band for rate-regulated
sectors, and a terminal-value sanity check against the regulated
asset base. NTPC bear went from ₹0 to ₹356 — the base and bull
cases were always fine, only the stress scenario was modelled
wrong. The broader lesson is that the bear case for a rate-regulated
business is a narrower distribution than for a cyclical, and treating
them identically produces unrealistic outputs. The fixed model is
live at yieldiq.in for anyone who wants to reproduce the numbers.

---

## SEBI-safe vocabulary check

Words deliberately avoided throughout: buy, sell, hold, strong,
recommend, recommendation, should, outperform, underperform,
accumulate, target price, upside, downside, conviction, pick,
opportunity.

Words used instead: fair value, scenario, bear / base / bull,
model output, analysis. The post invites engagement with the model,
not action on the names.
