# Multilingual AI Summaries — Design (Phase 0)

**Status:** Phase 0 (review-gated, dark-launched). Backend infrastructure
landed; feature flag `MULTILINGUAL_SUMMARIES_ENABLED` defaults OFF.
Native-speaker review of the samples in
`docs/multilingual_samples_for_review.md` MUST pass before the flag
is flipped. UI toggle ships in a later PR.

## 1. Rationale

YieldIQ's primary growth opportunity is tier-2/3 city retail investors
who consume financial information in Hindi, Tamil, and Marathi more
naturally than English. A Hindi-language summary on the analysis page
materially lowers the comprehension barrier for the largest pool of
new Indian retail investors.

The launch list is deliberately constrained to three languages
(hi, ta, mr) because:

- **Hindi** — largest single-language audience in India.
- **Tamil** — financial literacy in Tamil Nadu is high; Tamil
  financial press has well-established terminology; the
  community is sensitive to translation quality.
- **Marathi** — Mumbai-Pune retail-investor heartland.

Telugu, Kannada, and Bengali are scoped to **Phase 4**, after the
review loop established here is proven.

## 2. Risk register (front and centre)

| Risk | Severity | Mitigation in this PR |
| --- | --- | --- |
| **Mistranslation of financial terms** producing misleading content | High | Per-language system prompt enforces formal register and explicit canonical terms (`उचित मूल्य`, `நியாயமான மதிப்பு`, `योग्य मूल्य`). Native-speaker review of 5 samples is a hard gate before flag-flip. |
| **Regulatory framing** (SEBI banned vocabulary leaking through translation) | High | English summary is generated under existing SEBI filter first; translation pipeline preserves numbers and structure rather than re-deriving content. Phase 1 will extend banned-word lists to per-language transliterations. |
| **Hinglish / Tanglish bleed** lowering perceived quality | Med | Prompts explicitly forbid Hinglish; reviewers check this in checklist. |
| **Hindi vs Marathi script collision** (both Devanagari) | Med | Marathi prompt is distinct vocabulary; tests assert Marathi-distinct tokens (e.g. "आहे") in mr output to detect silent fallback to Hindi. |
| **Disclaimer omitted by LLM** | Low | `translate_ai_summary` defensively appends the disclaimer if the model output doesn't already contain it — guarantee holds unconditionally. |
| **Cost blow-up** | Low | 4× Groq calls per cold compute. Cached at the analysis-cache tier with the existing English summary, so warm reads are free. |
| **Liability for AI-translated financial content** | Med | Each non-English summary carries an in-string disclaimer in the target language stating the English version is authoritative and that errors are possible. Reviewer must confirm placement and wording before flag-flip. |

**Fallback behaviour:** If translation fails or Groq is unavailable,
`ai_summary_translations` is left as `null` and the existing English
`ai_summary` is unaffected. The frontend renders English in that case.

## 3. Architecture

```
AnalysisService.analyze(ticker)
  └── generate_narrative_summary  (English, SEBI-filtered)
        └── result.ai_summary  ← unchanged
  └── get_ai_summary_translations  (NEW, gated)
        ├── checks MULTILINGUAL_SUMMARIES_ENABLED env var
        ├── for each of {hi, ta, mr}:
        │     translate_ai_summary(english, language=lang)
        │     ├── system prompt = LANGUAGE_PROMPTS[lang]
        │     ├── Groq call with English summary as input
        │     └── disclaimer appended if missing
        └── result.ai_summary_translations  ← {hi: ..., ta: ..., mr: ...}
```

Key properties:

- **Additive** — `ai_summary_translations` is a new optional field on
  `AnalysisResponse`; existing `ai_summary` is untouched. Old clients
  see no change.
- **Cached together** — translations live inside the
  `analysis_cache.payload` JSON alongside the English summary. **No
  CACHE_VERSION bump required** because the field is optional and
  defaults to None for pre-existing payloads.
- **Feature-flagged off** — until `MULTILINGUAL_SUMMARIES_ENABLED=true`
  is set in Railway env, the translation path is short-circuited and
  no Groq calls are made for translation.
- **No prod-cache backfill from this PR** — when the flag is flipped,
  cold reads will populate translations naturally; warm reads stay
  English-only until the next cold compute. This is intentional.

## 4. Cost analysis

Per cold analysis compute:

- Existing: 1 Groq call for English summary (~140-180 tokens).
- New (when flag on): 1 Groq call for English + 3 for translations,
  each ~400 tokens output. **Net 4×** Groq cost on cold computes.
- Warm reads (the 99th-percentile case): **zero** additional cost.

At current Groq pricing for `llama-3.3-70b-versatile` and current cold-
compute volume, this is well within budget. Phase 3 will revisit
caching strategy if cold-compute volume grows materially.

## 5. Phase rollout plan

### Phase 0 — this PR (review-gated scaffolding)

- [x] `LANGUAGE_PROMPTS` for hi/ta/mr with formal financial register.
- [x] `translate_ai_summary` + `get_ai_summary_translations` on
      `NarrativeMixin`.
- [x] Additive `ai_summary_translations` field on `AnalysisResponse`
      and frontend type.
- [x] `MULTILINGUAL_SUMMARIES_ENABLED` env-var feature flag (default
      off).
- [x] Tests with mocked Groq covering script + disclaimer guarantees.
- [x] `scripts/generate_multilingual_samples.py` produces 5 sample
      stocks × 4 languages → `docs/multilingual_samples_for_review.md`.
- [ ] Frontend language toggle UI — **not in this PR**.

### Phase 1 — native-speaker review (next 2 weeks)

- Re-run `scripts/generate_multilingual_samples.py` with a real
  `GROQ_API_KEY` to refresh `docs/multilingual_samples_for_review.md`
  with actual model output.
- Engage one native speaker per language (hi, ta, mr).
- Reviewer fills in the per-stock checklist:
  register, terminology, Hinglish bleed, factual integrity, disclaimer.
- Iterate on `LANGUAGE_PROMPTS` in follow-up PRs based on feedback.
- Exit criterion: reviewer signs off on **all 5 stocks for all 3
  languages**.

### Phase 2 — canary 50

- With the iterated prompts, generate translations for the 50 canary
  stocks (offline, into a `docs/multilingual_canary_50.md` artefact).
- Second round of reviewer sampling (10 random stocks × 3 languages).
- Exit criterion: ≤ 1 corrective edit per stock on the sampled set.

### Phase 3 — flip the flag

- Set `MULTILINGUAL_SUMMARIES_ENABLED=true` in Railway env vars.
- Ship the frontend language toggle component (separate PR).
- Monitor Sentry for translation-call failures and user feedback for
  quality complaints.
- Add per-language banned-word lists to `sebi_filter` for hardened
  policy enforcement.

### Phase 4 — additional languages

- Telugu, Kannada, Bengali — repeat the Phase 1–3 cycle per language.
- No infrastructure changes expected — extension point is purely
  adding entries to `LANGUAGE_PROMPTS` and `DISCLAIMERS`.

## 6. What this PR explicitly does NOT do

- Does not bump `CACHE_VERSION`.
- Does not backfill `analysis_cache` or any other prod table.
- Does not write to `model_predictions_history`.
- Does not ship the frontend language toggle UI.
- Does not enable the feature flag in any environment.
- Does not add per-language SEBI banned-word lists (Phase 3 work).
