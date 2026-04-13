# backend/services/ticker_search.py
# Maps company names/keywords to NSE tickers.
# Static list for instant results — no API call needed.
from __future__ import annotations

# 200+ Indian stocks — name variants → ticker
INDIAN_STOCKS: list[dict] = [
    # NIFTY 50
    {"ticker": "RELIANCE.NS", "name": "Reliance Industries", "keywords": ["reliance", "ril", "jio", "mukesh ambani"]},
    {"ticker": "TCS.NS", "name": "Tata Consultancy Services", "keywords": ["tcs", "tata consultancy", "tata it"]},
    {"ticker": "HDFCBANK.NS", "name": "HDFC Bank", "keywords": ["hdfc bank", "hdfc", "hdfcbank"]},
    {"ticker": "INFY.NS", "name": "Infosys", "keywords": ["infosys", "infy", "narayana murthy"]},
    {"ticker": "ICICIBANK.NS", "name": "ICICI Bank", "keywords": ["icici bank", "icici", "icicibank"]},
    {"ticker": "HINDUNILVR.NS", "name": "Hindustan Unilever", "keywords": ["hindustan unilever", "hul", "hindunilvr", "unilever"]},
    {"ticker": "ITC.NS", "name": "ITC Limited", "keywords": ["itc", "itc limited"]},
    {"ticker": "BHARTIARTL.NS", "name": "Bharti Airtel", "keywords": ["airtel", "bharti airtel", "bhartiartl"]},
    {"ticker": "SBIN.NS", "name": "State Bank of India", "keywords": ["sbi", "state bank", "sbin"]},
    {"ticker": "BAJFINANCE.NS", "name": "Bajaj Finance", "keywords": ["bajaj finance", "bajfinance", "bajaj fin"]},
    {"ticker": "LT.NS", "name": "Larsen & Toubro", "keywords": ["l&t", "larsen", "lt", "larsen toubro"]},
    {"ticker": "KOTAKBANK.NS", "name": "Kotak Mahindra Bank", "keywords": ["kotak", "kotak bank", "kotakbank", "kotak mahindra"]},
    {"ticker": "HCLTECH.NS", "name": "HCL Technologies", "keywords": ["hcl", "hcltech", "hcl tech", "hcl technologies"]},
    {"ticker": "AXISBANK.NS", "name": "Axis Bank", "keywords": ["axis bank", "axis", "axisbank"]},
    {"ticker": "ASIANPAINT.NS", "name": "Asian Paints", "keywords": ["asian paints", "asianpaint", "asian paint"]},
    {"ticker": "MARUTI.NS", "name": "Maruti Suzuki", "keywords": ["maruti", "maruti suzuki", "maruti suzuki india"]},
    {"ticker": "SUNPHARMA.NS", "name": "Sun Pharma", "keywords": ["sun pharma", "sunpharma", "sun pharmaceutical"]},
    {"ticker": "TITAN.NS", "name": "Titan Company", "keywords": ["titan", "titan company", "tanishq"]},
    {"ticker": "TATAMOTORS.NS", "name": "Tata Motors", "keywords": ["tata motors", "tatamotors", "tata motor"]},
    {"ticker": "WIPRO.NS", "name": "Wipro", "keywords": ["wipro"]},
    {"ticker": "ULTRACEMCO.NS", "name": "UltraTech Cement", "keywords": ["ultratech", "ultracemco", "ultratech cement"]},
    {"ticker": "NESTLEIND.NS", "name": "Nestle India", "keywords": ["nestle", "nestleind", "nestle india"]},
    {"ticker": "NTPC.NS", "name": "NTPC Limited", "keywords": ["ntpc"]},
    {"ticker": "M&M.NS", "name": "Mahindra & Mahindra", "keywords": ["mahindra", "m&m", "mahindra mahindra"]},
    {"ticker": "POWERGRID.NS", "name": "Power Grid Corp", "keywords": ["power grid", "powergrid", "pgcil"]},
    {"ticker": "ONGC.NS", "name": "ONGC", "keywords": ["ongc", "oil natural gas"]},
    {"ticker": "TATASTEEL.NS", "name": "Tata Steel", "keywords": ["tata steel", "tatasteel"]},
    {"ticker": "JSWSTEEL.NS", "name": "JSW Steel", "keywords": ["jsw steel", "jswsteel", "jsw"]},
    {"ticker": "BAJAJFINSV.NS", "name": "Bajaj Finserv", "keywords": ["bajaj finserv", "bajajfinsv"]},
    {"ticker": "ADANIENT.NS", "name": "Adani Enterprises", "keywords": ["adani", "adani enterprises", "adanient"]},
    {"ticker": "TECHM.NS", "name": "Tech Mahindra", "keywords": ["tech mahindra", "techm"]},
    {"ticker": "HDFCLIFE.NS", "name": "HDFC Life Insurance", "keywords": ["hdfc life", "hdfclife"]},
    {"ticker": "DRREDDY.NS", "name": "Dr Reddys Laboratories", "keywords": ["dr reddy", "drreddy", "dr reddys"]},
    {"ticker": "DIVISLAB.NS", "name": "Divis Laboratories", "keywords": ["divis", "divislab", "divis lab"]},
    {"ticker": "CIPLA.NS", "name": "Cipla", "keywords": ["cipla"]},
    {"ticker": "BRITANNIA.NS", "name": "Britannia Industries", "keywords": ["britannia", "britannia industries"]},
    {"ticker": "GRASIM.NS", "name": "Grasim Industries", "keywords": ["grasim", "grasim industries"]},
    {"ticker": "COALINDIA.NS", "name": "Coal India", "keywords": ["coal india", "coalindia", "cil"]},
    {"ticker": "BPCL.NS", "name": "Bharat Petroleum", "keywords": ["bpcl", "bharat petroleum"]},
    {"ticker": "EICHERMOT.NS", "name": "Eicher Motors", "keywords": ["eicher", "eicher motors", "royal enfield"]},
    {"ticker": "HEROMOTOCO.NS", "name": "Hero MotoCorp", "keywords": ["hero", "hero motocorp", "heromotoco"]},
    {"ticker": "INDUSINDBK.NS", "name": "IndusInd Bank", "keywords": ["indusind", "indusind bank", "indusindbk"]},
    {"ticker": "SBILIFE.NS", "name": "SBI Life Insurance", "keywords": ["sbi life", "sbilife"]},
    {"ticker": "TATACONSUM.NS", "name": "Tata Consumer Products", "keywords": ["tata consumer", "tataconsum", "tata tea"]},
    {"ticker": "BAJAJ-AUTO.NS", "name": "Bajaj Auto", "keywords": ["bajaj auto", "bajaj-auto"]},
    # Popular midcaps
    {"ticker": "PERSISTENT.NS", "name": "Persistent Systems", "keywords": ["persistent", "persistent systems"]},
    {"ticker": "COFORGE.NS", "name": "Coforge", "keywords": ["coforge", "niit tech"]},
    {"ticker": "MPHASIS.NS", "name": "Mphasis", "keywords": ["mphasis"]},
    {"ticker": "CHOLAFIN.NS", "name": "Cholamandalam Finance", "keywords": ["chola", "cholafin", "cholamandalam"]},
    {"ticker": "MUTHOOTFIN.NS", "name": "Muthoot Finance", "keywords": ["muthoot", "muthootfin"]},
    {"ticker": "TATAELXSI.NS", "name": "Tata Elxsi", "keywords": ["tata elxsi", "tataelxsi"]},
    {"ticker": "PIIND.NS", "name": "PI Industries", "keywords": ["pi industries", "piind"]},
    {"ticker": "APOLLOHOSP.NS", "name": "Apollo Hospitals", "keywords": ["apollo", "apollo hospitals", "apollohosp"]},
    {"ticker": "ADANIPORTS.NS", "name": "Adani Ports", "keywords": ["adani ports", "adaniports"]},
    {"ticker": "HINDALCO.NS", "name": "Hindalco Industries", "keywords": ["hindalco", "hindalco industries"]},
    {"ticker": "DABUR.NS", "name": "Dabur India", "keywords": ["dabur", "dabur india"]},
    {"ticker": "PIDILITIND.NS", "name": "Pidilite Industries", "keywords": ["pidilite", "pidilitind", "fevicol"]},
    {"ticker": "GODREJCP.NS", "name": "Godrej Consumer Products", "keywords": ["godrej", "godrejcp", "godrej consumer"]},
    # Pharma
    {"ticker": "MANKINDPHARMA.NS", "name": "Mankind Pharma", "keywords": ["mankind", "mankind pharma", "mankindpharma"]},
    {"ticker": "ZYDUSLIFE.NS", "name": "Zydus Lifesciences", "keywords": ["zydus", "zyduslife", "cadila"]},
    {"ticker": "TORNTPHARM.NS", "name": "Torrent Pharma", "keywords": ["torrent pharma", "torntpharm"]},
    {"ticker": "AUROPHARMA.NS", "name": "Aurobindo Pharma", "keywords": ["aurobindo", "auropharma"]},
    {"ticker": "BIOCON.NS", "name": "Biocon", "keywords": ["biocon"]},
    {"ticker": "LUPIN.NS", "name": "Lupin", "keywords": ["lupin"]},
    # Auto
    {"ticker": "TVSMOTOR.NS", "name": "TVS Motor", "keywords": ["tvs", "tvs motor", "tvsmotor"]},
    {"ticker": "ASHOKLEY.NS", "name": "Ashok Leyland", "keywords": ["ashok leyland", "ashokley"]},
    {"ticker": "MOTHERSON.NS", "name": "Motherson Sumi", "keywords": ["motherson", "motherson sumi"]},
    # FMCG
    {"ticker": "MARICO.NS", "name": "Marico", "keywords": ["marico", "parachute"]},
    {"ticker": "COLPAL.NS", "name": "Colgate Palmolive", "keywords": ["colgate", "colpal"]},
    {"ticker": "TATAPOWER.NS", "name": "Tata Power", "keywords": ["tata power", "tatapower"]},
    {"ticker": "ADANIGREEN.NS", "name": "Adani Green Energy", "keywords": ["adani green", "adanigreen"]},
    {"ticker": "IRCTC.NS", "name": "IRCTC", "keywords": ["irctc", "indian railway catering"]},
    {"ticker": "ZOMATO.NS", "name": "Zomato", "keywords": ["zomato"]},
    {"ticker": "PAYTM.NS", "name": "Paytm (One97)", "keywords": ["paytm", "one97"]},
    {"ticker": "NYKAA.NS", "name": "Nykaa (FSN E-Commerce)", "keywords": ["nykaa", "fsn"]},
    {"ticker": "POLICYBZR.NS", "name": "PB Fintech (PolicyBazaar)", "keywords": ["policybazaar", "pb fintech", "policybzr"]},
    {"ticker": "DMART.NS", "name": "Avenue Supermarts (DMart)", "keywords": ["dmart", "d-mart", "avenue supermarts"]},
    {"ticker": "TRENT.NS", "name": "Trent (Westside/Zudio)", "keywords": ["trent", "westside", "zudio"]},
    {"ticker": "HAVELLS.NS", "name": "Havells India", "keywords": ["havells"]},
    {"ticker": "VOLTAS.NS", "name": "Voltas", "keywords": ["voltas"]},
    {"ticker": "INDIGO.NS", "name": "InterGlobe Aviation (IndiGo)", "keywords": ["indigo", "interglobe"]},
    {"ticker": "HAL.NS", "name": "Hindustan Aeronautics", "keywords": ["hal", "hindustan aeronautics"]},
    {"ticker": "BEL.NS", "name": "Bharat Electronics", "keywords": ["bel", "bharat electronics"]},
    {"ticker": "TATACHEM.NS", "name": "Tata Chemicals", "keywords": ["tata chemicals", "tatachem"]},
    {"ticker": "SIEMENS.NS", "name": "Siemens India", "keywords": ["siemens"]},
    {"ticker": "ABB.NS", "name": "ABB India", "keywords": ["abb"]},
    {"ticker": "PAGEIND.NS", "name": "Page Industries (Jockey)", "keywords": ["page", "page industries", "jockey"]},
    {"ticker": "BANKBARODA.NS", "name": "Bank of Baroda", "keywords": ["bank of baroda", "bob", "bankbaroda"]},
    {"ticker": "PNB.NS", "name": "Punjab National Bank", "keywords": ["pnb", "punjab national"]},
    {"ticker": "CANBK.NS", "name": "Canara Bank", "keywords": ["canara bank", "canbk"]},
    {"ticker": "IDFCFIRSTB.NS", "name": "IDFC First Bank", "keywords": ["idfc first", "idfc", "idfcfirstb"]},
    {"ticker": "FEDERALBNK.NS", "name": "Federal Bank", "keywords": ["federal bank", "federalbnk"]},
    {"ticker": "BANDHANBNK.NS", "name": "Bandhan Bank", "keywords": ["bandhan", "bandhan bank", "bandhanbnk"]},
]


def search_tickers(query: str, limit: int = 8) -> list[dict]:
    """Search Indian stocks by name, ticker, or keyword."""
    if not query or len(query) < 2:
        return []

    q = query.lower().strip()
    results = []

    for stock in INDIAN_STOCKS:
        score = 0
        ticker_clean = stock["ticker"].replace(".NS", "").lower()
        name_lower = stock["name"].lower()

        # Exact ticker match — highest priority
        if q == ticker_clean:
            score = 100
        # Ticker starts with query
        elif ticker_clean.startswith(q):
            score = 90
        # Name starts with query
        elif name_lower.startswith(q):
            score = 80
        # Keyword exact match
        elif any(q == kw for kw in stock["keywords"]):
            score = 85
        # Keyword starts with query
        elif any(kw.startswith(q) for kw in stock["keywords"]):
            score = 70
        # Name contains query
        elif q in name_lower:
            score = 60
        # Keyword contains query
        elif any(q in kw for kw in stock["keywords"]):
            score = 50
        # Ticker contains query
        elif q in ticker_clean:
            score = 40

        if score > 0:
            results.append({**stock, "_score": score})

    results.sort(key=lambda x: x["_score"], reverse=True)
    return [{"ticker": r["ticker"], "name": r["name"]} for r in results[:limit]]
