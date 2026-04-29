"""Unit tests for the quarterly retrospective publication ritual.

Covers:
  * scripts/resolve_prev_quarter.py — date-to-quarter resolver
  * scripts/generate_retrospective_publication.py — artifact generation,
    Twitter / LinkedIn length budgets, is_sample guard
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import resolve_prev_quarter as rpq  # noqa: E402
from scripts import generate_retrospective_publication as grp  # noqa: E402


FIXTURE = (
    Path(__file__).parent / "fixtures" / "retrospective_sample_payload.json"
)


# ─────────────────────────────────────────────────────────────────
# Quarter resolver
# ─────────────────────────────────────────────────────────────────
class TestResolveQuarter:
    def test_aug_1_2026_returns_q1fy27(self):
        info = rpq.resolve_prev_quarter(date(2026, 8, 1))
        assert info.label == "Q1FY27"
        assert info.start == "2026-04-01"
        assert info.end == "2026-06-30"

    def test_nov_1_2026_returns_q2fy27(self):
        info = rpq.resolve_prev_quarter(date(2026, 11, 1))
        assert info.label == "Q2FY27"
        assert info.start == "2026-07-01"
        assert info.end == "2026-09-30"

    def test_feb_1_2027_returns_q3fy27(self):
        info = rpq.resolve_prev_quarter(date(2027, 2, 1))
        assert info.label == "Q3FY27"
        assert info.start == "2026-10-01"
        assert info.end == "2026-12-31"

    def test_may_1_2027_returns_q4fy27(self):
        info = rpq.resolve_prev_quarter(date(2027, 5, 1))
        assert info.label == "Q4FY27"
        assert info.start == "2027-01-01"
        assert info.end == "2027-03-31"


# ─────────────────────────────────────────────────────────────────
# Artifact generation
# ─────────────────────────────────────────────────────────────────
@pytest.fixture
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class TestArtifactGeneration:
    def test_all_three_artifacts_written(self, payload, tmp_path):
        paths = grp.write_artifacts(payload, "Q1FY27", tmp_path)
        assert paths["markdown"].exists()
        assert paths["twitter"].exists()
        assert paths["linkedin"].exists()
        assert paths["email"].exists()

    def test_markdown_contains_disclaimer_and_winners(self, payload, tmp_path):
        paths = grp.write_artifacts(payload, "Q1FY27", tmp_path)
        md = paths["markdown"].read_text(encoding="utf-8")
        assert "SEBI: descriptive only" in md
        assert "POWERGRID.NS" in md
        assert "ZOMATO.NS" in md
        assert "Q1FY27" in md

    def test_twitter_thread_has_4_tweets_each_under_280(self, payload):
        rendered = grp.render_twitter_thread(payload)
        # Each tweet block is preceded by '## Tweet i/4'.
        assert rendered.count("## Tweet ") == 4
        # Pull the four tweet bodies and verify length.
        sections = rendered.split("## Tweet ")[1:]
        assert len(sections) == 4
        for sec in sections:
            # First line is the header e.g. "1/4 (123 chars)\n"; rest
            # is the actual tweet body until the next blank line / EOF.
            header, _, rest = sec.partition("\n\n")
            tweet_body = rest.strip()
            assert len(tweet_body) <= 280, (
                f"Tweet exceeds 280 chars ({len(tweet_body)}): "
                f"{tweet_body[:50]}..."
            )

    def test_linkedin_under_3000_chars(self, payload):
        body = grp.render_linkedin(payload)
        assert len(body) <= 3000
        assert "SEBI" in body
        assert "Q1FY27" in body

    def test_email_subject_includes_quarter(self, payload):
        subject, body = grp.render_email(payload)
        assert "Q1FY27" in subject
        assert "Retrospective" in subject
        assert "ZOMATO" in body  # misses included
        assert "Past results" in body

    def test_is_sample_guard(self, payload, tmp_path, monkeypatch):
        sample_path = tmp_path / "sample.json"
        sample = dict(payload)
        sample["is_sample"] = True
        sample_path.write_text(json.dumps(sample), encoding="utf-8")

        out_dir = tmp_path / "out"
        rc = grp.main([
            "--quarter", "Q1FY27",
            "--fixture", str(sample_path),
            "--out-dir", str(out_dir),
        ])
        assert rc == 3, "expected exit 3 when is_sample=true and not overridden"
        assert not out_dir.exists() or not any(out_dir.iterdir())

    def test_is_sample_allow_override(self, payload, tmp_path):
        sample_path = tmp_path / "sample.json"
        sample = dict(payload)
        sample["is_sample"] = True
        sample_path.write_text(json.dumps(sample), encoding="utf-8")

        out_dir = tmp_path / "out"
        rc = grp.main([
            "--quarter", "Q1FY27",
            "--fixture", str(sample_path),
            "--out-dir", str(out_dir),
            "--allow-sample",
        ])
        assert rc == 0
        assert (out_dir / "retrospective_Q1FY27.md").exists()
