import requests
import time
import urllib.parse

from config import NSE_DELAY


def get_nse_session():
    """Create warmed NSE session."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://www.nseindia.com',
        'Accept-Language': 'en-IN,en;q=0.9',
        'X-Requested-With': 'XMLHttpRequest',
    })
    try:
        session.get('https://www.nseindia.com', timeout=15)
        time.sleep(2)
    except Exception:
        pass
    return session


def _nse_to_cr(val):
    """NSE reports in Lakhs (1 unit = 100 Cr...no wait).

    Confirmed from probe: re_net_sale=12826000 for RELIANCE Q3 FY25
    equals ₹1,28,260 Cr. So divide by 100.
    """
    try:
        if val is None:
            return None
        return round(float(val) / 100, 2)
    except Exception:
        return None


def fetch_nse_quarterly(ticker, session=None):
    """Fetch last 5 quarters P&L from NSE."""
    if session is None:
        session = get_nse_session()

    symbol = urllib.parse.quote(ticker, safe='')
    url = (f"https://www.nseindia.com/api/results-comparision"
           f"?index=equities&symbol={symbol}")

    try:
        time.sleep(NSE_DELAY)
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        periods = data.get('resCmpData') or []

        is_bank = False
        if periods:
            is_bank = bool(periods[0].get('re_int_earned'))

        records = []
        for p in periods:
            record = {
                'ticker_nse': ticker,
                'period_type': 'quarterly',
                'period_from': p.get('re_from_dt', ''),
                'period_to': p.get('re_to_dt', ''),
                'filing_date': p.get('re_create_dt', ''),
                'result_type': p.get('re_res_type', ''),
                'is_audited': p.get('re_res_type') == 'A',
                'is_bank': is_bank,
                'revenue': _nse_to_cr(p.get('re_net_sale')),
                'other_income': _nse_to_cr(p.get('re_oth_inc_new')),
                'total_income': _nse_to_cr(p.get('re_total_inc')),
                'depreciation': _nse_to_cr(p.get('re_depr_und_exp')),
                'interest': _nse_to_cr(p.get('re_int_new')),
                'pretax_income': _nse_to_cr(p.get('re_pro_loss_bef_tax')),
                'tax': _nse_to_cr(p.get('re_tax')),
                'net_income': _nse_to_cr(
                    p.get('re_net_profit') or p.get('re_con_pro_loss')
                ),
                'eps_basic': p.get('re_basic_eps_for_cont_dic_opr') or p.get('re_basic_eps'),
                'eps_diluted': p.get('re_dilut_eps_for_cont_dic_opr') or p.get('re_diluted_eps'),
                'interest_earned': _nse_to_cr(p.get('re_int_earned')),
                'interest_expended': _nse_to_cr(p.get('re_int_expd')),
                'source': 'nse',
                'statement_type': 'income',
                'notes': (p.get('re_desc_note_fin') or '')[:500],
            }
            records.append(record)
        return records
    except Exception as e:
        print(f"  NSE error for {ticker}: {e}")
        return []
