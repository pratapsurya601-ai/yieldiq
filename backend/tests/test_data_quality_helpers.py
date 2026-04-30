import pytest


def test_rank_for_known_sources():
    from data_pipeline.sources._data_quality import rank_for
    assert rank_for("NSE_XBRL") == 10
    assert rank_for("yfinance") == 50
    assert rank_for("unknown_source") == 70
    assert rank_for(None) == 70


def test_pe_plausibility_guard():
    from data_pipeline.sources._data_quality import is_plausible_pe
    assert is_plausible_pe(25.0)[0] is True
    assert is_plausible_pe(None)[0] is True
    assert is_plausible_pe(-5)[0] is False
    assert is_plausible_pe(1500)[0] is False


def test_mcap_plausibility_guard():
    from data_pipeline.sources._data_quality import is_plausible_mcap
    assert is_plausible_mcap(800000)[0] is True       # ₹8 lakh Cr — fine
    assert is_plausible_mcap(None)[0] is False        # NULL is bad
    assert is_plausible_mcap(0)[0] is False           # zero is bad
    assert is_plausible_mcap(2e10)[0] is False        # too big


@pytest.fixture
def in_memory_session():
    """Stub session — log_anomaly should swallow whatever we pass."""
    return None


def test_log_anomaly_does_not_raise(in_memory_session):
    """log_anomaly is best-effort — even if DB write fails, must not propagate."""
    from data_pipeline.sources._data_quality import log_anomaly
    # call with a None session — should swallow the AttributeError
    log_anomaly(in_memory_session, table_name="x", ticker="Y", field="z",
                suspected_value=1, reason="t", auto_handled="logged")
