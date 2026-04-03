# dashboard/init_db.py
# ===================================================================
# YieldIQ --- Database Initialisation
# Called once at startup. Safe to call multiple times.
# Creates all SQLite tables if they do not exist.
# On Streamlit Cloud: databases are recreated on each deploy.
# ===================================================================

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def init_all_databases() -> None:
    from auth import init_auth_db
    from portfolio import (
        init_db, init_watchlist_db,
        init_institutional_db, init_sheets_db,
    )
    from admin_analytics import init_analytics_db
    from alerts import init_alerts_db
    from sector_dashboard import init_sector_db
    from onboarding import init_onboarding_db

    import importlib.util, pathlib
    bt_path = pathlib.Path(__file__).parent / "tabs" / "backtest_tab.py"
    bt_spec = importlib.util.spec_from_file_location("backtest_tab", bt_path)
    bt_mod  = importlib.util.module_from_spec(bt_spec)
    bt_spec.loader.exec_module(bt_mod)

    init_auth_db()
    init_db()
    init_watchlist_db()
    init_institutional_db()
    init_sheets_db()
    init_analytics_db()
    init_alerts_db()
    init_sector_db()
    init_onboarding_db()
    bt_mod.init_backtest_db()

    print("All databases initialised.")


if __name__ == "__main__":
    init_all_databases()
