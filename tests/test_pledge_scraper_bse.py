"""Test BSE pledge scraper HTML parsing.

The scraper is a black box around BeautifulSoup table extraction. We
inject a synthetic BSE response via the ``_http_get`` test seam so the
test runs offline and remains deterministic regardless of BSE
anti-bot behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


_BSE_FIXTURE_HTML = """
<html><body>
<table id="ContentPlaceHolder1_gvData">
  <tr>
    <th>Filing Date</th>
    <th>Promoter Name</th>
    <th>Pledged Shares</th>
    <th>% of Promoter Holding</th>
    <th>% of Total Capital</th>
  </tr>
  <tr>
    <td>31-Jan-2026</td>
    <td>Reliance Capital Limited Promoter Group</td>
    <td>4,400,000,000</td>
    <td>80.00</td>
    <td>17.58</td>
  </tr>
  <tr>
    <td>31-Oct-2025</td>
    <td>Reliance Capital Limited Promoter Group</td>
    <td>3,575,000,000</td>
    <td>65.00</td>
    <td>14.28</td>
  </tr>
</table>
</body></html>
"""


def test_bse_parser_extracts_pledge_rows():
    from backend.services.promoter_pledge_service import _parse_bse_pledge_html

    rows = _parse_bse_pledge_html(
        _BSE_FIXTURE_HTML,
        ticker="RCOM",
        source_url="https://www.bseindia.com/corporates/sastpledge.aspx?scripcode=532712",
    )
    assert len(rows) == 2

    latest = rows[0]
    assert latest.ticker == "RCOM"
    assert latest.as_of_date.isoformat() == "2026-01-31"
    assert latest.pledged_pct == 80.0
    assert latest.pledged_shares == 4_400_000_000
    assert latest.promoter_group_pct == 17.58


def test_fetch_from_bse_uses_http_seam_without_network():
    """``fetch_from_bse`` must accept an injected HTTP getter so unit tests
    don't hit BSE. We also patch the bse_code lookup to avoid DB dep."""
    from backend.services import promoter_pledge_service as svc

    def fake_get(url, headers, timeout):
        assert "scripcode=532712" in url
        return 200, _BSE_FIXTURE_HTML

    with patch.object(svc, "_bse_code_for", return_value="532712"):
        rows = svc.fetch_from_bse("RCOM", _http_get=fake_get)

    assert len(rows) == 2
    assert rows[0].pledged_pct == 80.0


def test_fetch_from_bse_handles_empty_response():
    from backend.services import promoter_pledge_service as svc

    def fake_get(url, headers, timeout):
        return 200, "<html><body><p>No data</p></body></html>"

    with patch.object(svc, "_bse_code_for", return_value="500001"):
        rows = svc.fetch_from_bse("FOO", _http_get=fake_get)
    assert rows == []


def test_fetch_from_bse_returns_empty_on_http_error():
    from backend.services import promoter_pledge_service as svc

    def fake_get(url, headers, timeout):
        return 503, ""

    with patch.object(svc, "_bse_code_for", return_value="500001"):
        rows = svc.fetch_from_bse("FOO", _http_get=fake_get)
    assert rows == []


def test_nse_payload_parser_groups_by_symbol():
    from backend.services.promoter_pledge_service import _parse_nse_pledge_payload

    payload = {
        "data": [
            {
                "symbol": "RCOM",
                "date": "31-Jan-2026",
                "personPledgedHoldingPct": 80.0,
                "totalPledgedShares": 4_400_000_000,
                "promoterHoldingPct": 21.97,
                "attchmntFile": "https://nsearchives/x.pdf",
            },
            {
                "symbol": "JINDALSTEL",
                "date": "31-Jan-2026",
                "personPledgedHoldingPct": 20.0,
                "totalPledgedShares": 122_000_000,
                "promoterHoldingPct": 60.45,
            },
            {
                # Should be skipped — no symbol.
                "date": "31-Jan-2026",
                "personPledgedHoldingPct": 5.0,
            },
        ]
    }
    by_sym = _parse_nse_pledge_payload(payload)
    assert set(by_sym.keys()) == {"RCOM", "JINDALSTEL"}
    assert by_sym["RCOM"][0].pledged_pct == 80.0
    assert by_sym["JINDALSTEL"][0].pledged_shares == 122_000_000
