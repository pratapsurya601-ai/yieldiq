# dashboard/sheets_export.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ — Google Sheets Portfolio Export
#
# Auth: Service-account OAuth2 (JSON stored in env var
#       GOOGLE_SHEETS_CREDENTIALS or file path in
#       GOOGLE_SHEETS_CREDENTIALS_FILE).
#
# The service account creates/owns the spreadsheet and shares it
# with the user's Google-account email.  All formatting is applied
# via the Sheets API v4 through gspread's batch_update().
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional, Tuple

# ── Optional imports — fail gracefully if gspread not installed ──
try:
    import gspread
    from google.oauth2.service_account import Credentials as _SACredentials
    _GSPREAD_OK = True
except ImportError:
    _GSPREAD_OK = False

# ── Google API scopes ────────────────────────────────────────────
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# ── Signal → colour mapping (RGB 0-1 floats) ─────────────────────
_SIG_COLOURS: dict[str, dict] = {
    "undervalued": {
        "red": 0.851, "green": 0.918, "blue": 0.827,   # #D9EAAD → soft green
    },
    "overvalued": {
        "red": 0.957, "green": 0.800, "blue": 0.800,   # #F4CCCC → soft red
    },
    "fairly valued": {
        "red": 1.000, "green": 0.949, "blue": 0.800,   # #FFF2CC → soft amber
    },
    "neutral": {
        "red": 1.000, "green": 0.949, "blue": 0.800,
    },
    "hold": {
        "red": 1.000, "green": 0.949, "blue": 0.800,
    },
}

# Header background (YieldIQ dark navy → closest Sheets colour)
_HDR_BG   = {"red": 0.059, "green": 0.161, "blue": 0.259}   # #0F2942
_HDR_FG   = {"red": 1.000, "green": 1.000, "blue": 1.000}   # white

# Column definitions for the exported sheet
_COLUMNS = [
    "Ticker",
    "Company",
    "Sector",
    "Entry Price",
    "Current Price",
    "Intrinsic Value (IV)",
    "MoS %",
    "Signal",
    "P&L %",
    "Annualized Return %",
    "WACC",
    "Currency",
    "Days Held",
    "Saved At",
    "Notes",
]


# ════════════════════════════════════════════════════════════════
#  Auth
# ════════════════════════════════════════════════════════════════

def _load_credentials_dict() -> dict:
    """
    Load service-account JSON from env var or file.
    Raises RuntimeError with a helpful message when absent.
    """
    raw = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "").strip()
    if not raw:
        fpath = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE", "").strip()
        if fpath and os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as fh:
                raw = fh.read()
    if not raw:
        raise RuntimeError(
            "Google Sheets credentials not found.\n\n"
            "Set the environment variable GOOGLE_SHEETS_CREDENTIALS with the "
            "full contents of your service-account JSON file, or set "
            "GOOGLE_SHEETS_CREDENTIALS_FILE to the file path.\n\n"
            "To create a service account:\n"
            "  1. Go to Google Cloud Console → IAM & Admin → Service Accounts\n"
            "  2. Create account, download JSON key\n"
            "  3. Enable Google Sheets API and Google Drive API\n"
            "  4. Paste JSON content into the GOOGLE_SHEETS_CREDENTIALS env var"
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"GOOGLE_SHEETS_CREDENTIALS contains invalid JSON: {exc}"
        ) from exc


def _get_client() -> "gspread.Client":
    if not _GSPREAD_OK:
        raise RuntimeError(
            "gspread is not installed. Run: pip install gspread google-auth"
        )
    creds_dict = _load_credentials_dict()
    creds = _SACredentials.from_service_account_info(creds_dict, scopes=_SCOPES)
    return gspread.authorize(creds)


def get_service_account_email() -> str:
    """Return the service-account email (used to tell users who to share with)."""
    try:
        creds_dict = _load_credentials_dict()
        return creds_dict.get("client_email", "")
    except Exception:
        return ""


def is_configured() -> bool:
    """True if credentials env var is present and gspread is installed."""
    if not _GSPREAD_OK:
        return False
    try:
        _load_credentials_dict()
        return True
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════
#  Data preparation
# ════════════════════════════════════════════════════════════════

def _annualized_return(pnl_pct: float, saved_at: str) -> float:
    """
    Compound-annualize a total P&L% from the save date to today.
    Returns 0.0 if days_held < 1.
    """
    try:
        saved_dt = datetime.fromisoformat(saved_at)
    except Exception:
        return 0.0
    days = max((datetime.now() - saved_dt).days, 1)
    if days < 1:
        return 0.0
    total = pnl_pct / 100.0
    return (((1.0 + total) ** (365.0 / days)) - 1.0) * 100.0


def _sig_label(raw_signal: str) -> str:
    """Normalise signal to a short readable label."""
    s = (raw_signal or "").lower()
    if "undervalued" in s:  return "BUY"
    if "overvalued"  in s:  return "SELL"
    if "fairly"      in s:  return "HOLD"
    if "neutral"     in s:  return "HOLD"
    return raw_signal or "—"


def _build_rows(holdings: list[dict]) -> list[list]:
    """Convert holdings list to list-of-lists for Sheets."""
    rows = [_COLUMNS]
    for h in holdings:
        saved_at   = h.get("saved_at", "")
        pnl_pct    = h.get("pnl_pct",  0.0) or 0.0
        ann_ret    = _annualized_return(pnl_pct, saved_at)

        try:
            saved_dt = datetime.fromisoformat(saved_at)
            days_held = (datetime.now() - saved_dt).days
        except Exception:
            days_held = 0

        ep   = h.get("entry_price", 0.0) or 0.0
        lp   = h.get("live_price",  0.0) or 0.0
        iv   = h.get("iv",          0.0) or 0.0
        mos  = h.get("mos_pct",     0.0) or 0.0
        wacc = h.get("wacc",        0.0) or 0.0
        curr = h.get("to_code",     "USD")
        sig  = _sig_label(h.get("signal", ""))

        rows.append([
            h.get("ticker",       ""),
            h.get("company_name", ""),
            h.get("sector",       ""),
            round(ep,   2),
            round(lp,   2),
            round(iv,   2),
            round(mos,  2),
            sig,
            round(pnl_pct,  2),
            round(ann_ret,  2),
            round(wacc * 100, 2),   # store as % not decimal
            curr,
            days_held,
            saved_at[:10],          # date only
            h.get("notes", ""),
        ])
    return rows


# ════════════════════════════════════════════════════════════════
#  Formatting helpers (Sheets API v4 request dicts)
# ════════════════════════════════════════════════════════════════

def _freeze_header(sheet_id: int) -> dict:
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    }


def _header_format(sheet_id: int, n_cols: int) -> dict:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": n_cols,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": _HDR_BG,
                    "textFormat": {
                        "foregroundColor": _HDR_FG,
                        "bold": True,
                        "fontSize": 10,
                        "fontFamily": "Arial",
                    },
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "wrapStrategy": "CLIP",
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,"
                      "horizontalAlignment,verticalAlignment,wrapStrategy)",
        }
    }


def _data_format(sheet_id: int, n_rows: int, n_cols: int) -> dict:
    """Zebra stripe + vertical centre for data rows."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1, "endRowIndex": n_rows,
                "startColumnIndex": 0, "endColumnIndex": n_cols,
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"fontSize": 9, "fontFamily": "Arial"},
                    "verticalAlignment": "MIDDLE",
                }
            },
            "fields": "userEnteredFormat(textFormat,verticalAlignment)",
        }
    }


def _conditional_fmt(sheet_id: int, n_rows: int, sig_col: int) -> list[dict]:
    """
    Conditional formatting rules for the Signal column.
    Returns a list of addConditionalFormatRule requests.
    """
    def _rule(text_contains: str, bg_key: str, index: int) -> dict:
        bg = _SIG_COLOURS.get(bg_key, _SIG_COLOURS["fairly valued"])
        return {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId":       sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex":   n_rows,
                        "startColumnIndex": sig_col,
                        "endColumnIndex":   sig_col + 1,
                    }],
                    "booleanRule": {
                        "condition": {
                            "type":   "TEXT_EQ",
                            "values": [{"userEnteredValue": text_contains}],
                        },
                        "format": {"backgroundColor": bg},
                    },
                },
                "index": index,
            }
        }

    return [
        _rule("BUY",  "undervalued",   0),
        _rule("SELL", "overvalued",    1),
        _rule("HOLD", "fairly valued", 2),
    ]


def _pnl_conditional(sheet_id: int, n_rows: int, pnl_col: int) -> list[dict]:
    """Red/green conditional formatting for the P&L % column."""
    def _rule(cond_type: str, value: str, bg: dict, index: int) -> dict:
        return {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sheet_id,
                        "startRowIndex":    1,
                        "endRowIndex":      n_rows,
                        "startColumnIndex": pnl_col,
                        "endColumnIndex":   pnl_col + 1,
                    }],
                    "booleanRule": {
                        "condition": {
                            "type":   cond_type,
                            "values": [{"userEnteredValue": value}],
                        },
                        "format": {"backgroundColor": bg},
                    },
                },
                "index": index,
            }
        }

    green = {"red": 0.851, "green": 0.918, "blue": 0.827}
    red   = {"red": 0.957, "green": 0.800, "blue": 0.800}
    return [
        _rule("NUMBER_GREATER",    "0", green, 3),
        _rule("NUMBER_LESS",       "0", red,   4),
    ]


def _auto_resize(sheet_id: int, n_cols: int) -> dict:
    return {
        "autoResizeDimensions": {
            "dimensions": {
                "sheetId":    sheet_id,
                "dimension":  "COLUMNS",
                "startIndex": 0,
                "endIndex":   n_cols,
            }
        }
    }


def _number_format(sheet_id: int, n_rows: int,
                   col_indices: list[int], pattern: str) -> list[dict]:
    """Apply a number format pattern to specific columns."""
    return [{
        "repeatCell": {
            "range": {
                "sheetId":          sheet_id,
                "startRowIndex":    1,
                "endRowIndex":      n_rows,
                "startColumnIndex": c,
                "endColumnIndex":   c + 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "NUMBER", "pattern": pattern}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    } for c in col_indices]


# ════════════════════════════════════════════════════════════════
#  Core export function
# ════════════════════════════════════════════════════════════════

def export_portfolio_to_sheets(
    holdings:          list[dict],
    user_email:        str,
    spreadsheet_title: str              = "YieldIQ Portfolio",
    existing_sheet_id: Optional[str]   = None,
) -> Tuple[str, str]:
    """
    Create or update a Google Sheet with portfolio data.

    Parameters
    ----------
    holdings          : list of holding dicts (from get_portfolio() with live prices).
    user_email        : The user's Google account email — the sheet is shared with them.
    spreadsheet_title : Title for new spreadsheets.
    existing_sheet_id : If provided, update the existing spreadsheet instead of creating.

    Returns
    -------
    (sheets_url, spreadsheet_id)

    Raises
    ------
    RuntimeError  : credentials missing, gspread not installed, or API error.
    """
    gc = _get_client()

    # ── Open or create the spreadsheet ──────────────────────────
    if existing_sheet_id:
        try:
            sh = gc.open_by_key(existing_sheet_id)
        except Exception:
            # Sheet was deleted — create fresh
            existing_sheet_id = None

    if not existing_sheet_id:
        sh = gc.create(spreadsheet_title)
        # Share with the user (write access)
        if user_email:
            try:
                sh.share(user_email, perm_type="user", role="writer",
                         notify=True,
                         email_message=(
                             "Your YieldIQ portfolio has been synced to this "
                             "Google Sheet. It updates each time you press "
                             "'Sync to Google Sheets' in the app."
                         ))
            except Exception:
                # Sharing is best-effort; don't fail the export
                pass

    # ── Build data ───────────────────────────────────────────────
    rows    = _build_rows(holdings)
    n_rows  = len(rows)
    n_cols  = len(_COLUMNS)

    # ── Write to first worksheet ─────────────────────────────────
    ws = sh.sheet1
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")

    # ── Sheet metadata ───────────────────────────────────────────
    ws_id   = ws.id          # integer sheet id
    sig_col = _COLUMNS.index("Signal")        # 0-based column index
    pnl_col = _COLUMNS.index("P&L %")

    # Columns that hold numeric % values
    pct_cols = [
        _COLUMNS.index("MoS %"),
        _COLUMNS.index("P&L %"),
        _COLUMNS.index("Annualized Return %"),
        _COLUMNS.index("WACC"),
    ]
    price_cols = [
        _COLUMNS.index("Entry Price"),
        _COLUMNS.index("Current Price"),
        _COLUMNS.index("Intrinsic Value (IV)"),
    ]

    # ── Batch format requests ────────────────────────────────────
    requests: list[dict] = []
    requests.append(_freeze_header(ws_id))
    requests.append(_header_format(ws_id, n_cols))
    requests.append(_data_format(ws_id, n_rows, n_cols))
    requests.extend(_conditional_fmt(ws_id, n_rows, sig_col))
    requests.extend(_pnl_conditional(ws_id, n_rows, pnl_col))
    requests.extend(_number_format(ws_id, n_rows, pct_cols,  '#,##0.00"%"'))
    requests.extend(_number_format(ws_id, n_rows, price_cols,'#,##0.00'))
    requests.append(_auto_resize(ws_id, n_cols))

    sh.batch_update({"requests": requests})

    # ── Add metadata tab ─────────────────────────────────────────
    _write_meta_tab(sh, holdings)

    url = f"https://docs.google.com/spreadsheets/d/{sh.id}"
    return url, sh.id


def _write_meta_tab(sh: "gspread.Spreadsheet", holdings: list[dict]) -> None:
    """
    Write (or update) a 'Summary' worksheet with portfolio-level stats.
    """
    tab_name = "Summary"
    try:
        try:
            meta_ws = sh.worksheet(tab_name)
            meta_ws.clear()
        except gspread.exceptions.WorksheetNotFound:
            meta_ws = sh.add_worksheet(title=tab_name, rows=30, cols=6)

        total     = len(holdings)
        wins      = sum(1 for h in holdings if (h.get("pnl_pct") or 0) > 0)
        losses    = sum(1 for h in holdings if (h.get("pnl_pct") or 0) < 0)
        avg_pnl   = (sum((h.get("pnl_pct") or 0) for h in holdings) / total
                     if total else 0.0)
        buy_ct    = sum(1 for h in holdings if "undervalued" in (h.get("signal") or "").lower())
        sell_ct   = sum(1 for h in holdings if "overvalued"  in (h.get("signal") or "").lower())
        hold_ct   = total - buy_ct - sell_ct
        synced_at = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

        summary_rows = [
            ["YieldIQ Portfolio Summary", ""],
            ["Synced at", synced_at],
            ["", ""],
            ["Metric",            "Value"],
            ["Total Positions",   total],
            ["Winners",           wins],
            ["Losers",            losses],
            ["Avg P&L %",         round(avg_pnl, 2)],
            ["BUY signals",       buy_ct],
            ["SELL signals",      sell_ct],
            ["HOLD signals",      hold_ct],
        ]
        meta_ws.update(summary_rows, value_input_option="USER_ENTERED")
    except Exception:
        pass   # summary tab is best-effort
