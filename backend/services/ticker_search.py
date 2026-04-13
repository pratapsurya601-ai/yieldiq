# backend/services/ticker_search.py
# Maps company names/keywords to NSE tickers.
# Static list for instant results — no API call needed.
from __future__ import annotations

# ---------------------------------------------------------------------------
# 400+ Indian stocks — name variants -> ticker
# ---------------------------------------------------------------------------
INDIAN_STOCKS: list[dict] = [
    # ===== NIFTY 50 =====
    {"ticker": "RELIANCE.NS", "name": "Reliance Industries", "keywords": ["reliance", "ril", "jio", "mukesh ambani"], "type": "stock"},
    {"ticker": "TCS.NS", "name": "Tata Consultancy Services", "keywords": ["tcs", "tata consultancy", "tata it"], "type": "stock"},
    {"ticker": "HDFCBANK.NS", "name": "HDFC Bank", "keywords": ["hdfc bank", "hdfc", "hdfcbank"], "type": "stock"},
    {"ticker": "INFY.NS", "name": "Infosys", "keywords": ["infosys", "infy", "narayana murthy"], "type": "stock"},
    {"ticker": "ICICIBANK.NS", "name": "ICICI Bank", "keywords": ["icici bank", "icici", "icicibank"], "type": "stock"},
    {"ticker": "HINDUNILVR.NS", "name": "Hindustan Unilever", "keywords": ["hindustan unilever", "hul", "hindunilvr", "unilever"], "type": "stock"},
    {"ticker": "ITC.NS", "name": "ITC Limited", "keywords": ["itc", "itc limited", "itc hotels"], "type": "stock"},
    {"ticker": "BHARTIARTL.NS", "name": "Bharti Airtel", "keywords": ["airtel", "bharti airtel", "bhartiartl"], "type": "stock"},
    {"ticker": "SBIN.NS", "name": "State Bank of India", "keywords": ["sbi", "state bank", "sbin", "state bank of india"], "type": "stock"},
    {"ticker": "BAJFINANCE.NS", "name": "Bajaj Finance", "keywords": ["bajaj finance", "bajfinance", "bajaj fin"], "type": "stock"},
    {"ticker": "LT.NS", "name": "Larsen & Toubro", "keywords": ["l&t", "larsen", "lt", "larsen toubro"], "type": "stock"},
    {"ticker": "KOTAKBANK.NS", "name": "Kotak Mahindra Bank", "keywords": ["kotak", "kotak bank", "kotakbank", "kotak mahindra"], "type": "stock"},
    {"ticker": "HCLTECH.NS", "name": "HCL Technologies", "keywords": ["hcl", "hcltech", "hcl tech", "hcl technologies"], "type": "stock"},
    {"ticker": "AXISBANK.NS", "name": "Axis Bank", "keywords": ["axis bank", "axis", "axisbank"], "type": "stock"},
    {"ticker": "ASIANPAINT.NS", "name": "Asian Paints", "keywords": ["asian paints", "asianpaint", "asian paint"], "type": "stock"},
    {"ticker": "MARUTI.NS", "name": "Maruti Suzuki", "keywords": ["maruti", "maruti suzuki", "maruti suzuki india", "nexa"], "type": "stock"},
    {"ticker": "SUNPHARMA.NS", "name": "Sun Pharma", "keywords": ["sun pharma", "sunpharma", "sun pharmaceutical"], "type": "stock"},
    {"ticker": "TITAN.NS", "name": "Titan Company", "keywords": ["titan", "titan company", "tanishq", "titan watch"], "type": "stock"},
    {"ticker": "TATAMOTORS.NS", "name": "Tata Motors", "keywords": ["tata motors", "tatamotors", "tata motor", "tata ev"], "type": "stock"},
    {"ticker": "WIPRO.NS", "name": "Wipro", "keywords": ["wipro"], "type": "stock"},
    {"ticker": "ULTRACEMCO.NS", "name": "UltraTech Cement", "keywords": ["ultratech", "ultracemco", "ultratech cement"], "type": "stock"},
    {"ticker": "NESTLEIND.NS", "name": "Nestle India", "keywords": ["nestle", "nestleind", "nestle india", "maggi"], "type": "stock"},
    {"ticker": "NTPC.NS", "name": "NTPC Limited", "keywords": ["ntpc", "ntpc limited"], "type": "stock"},
    {"ticker": "M&M.NS", "name": "Mahindra & Mahindra", "keywords": ["mahindra", "m&m", "mahindra mahindra", "xuv", "thar"], "type": "stock"},
    {"ticker": "POWERGRID.NS", "name": "Power Grid Corp", "keywords": ["power grid", "powergrid", "pgcil"], "type": "stock"},
    {"ticker": "ONGC.NS", "name": "ONGC", "keywords": ["ongc", "oil natural gas"], "type": "stock"},
    {"ticker": "TATASTEEL.NS", "name": "Tata Steel", "keywords": ["tata steel", "tatasteel"], "type": "stock"},
    {"ticker": "JSWSTEEL.NS", "name": "JSW Steel", "keywords": ["jsw steel", "jswsteel", "jsw"], "type": "stock"},
    {"ticker": "BAJAJFINSV.NS", "name": "Bajaj Finserv", "keywords": ["bajaj finserv", "bajajfinsv", "bajaj fin serv"], "type": "stock"},
    {"ticker": "ADANIENT.NS", "name": "Adani Enterprises", "keywords": ["adani", "adani enterprises", "adanient"], "type": "stock"},
    {"ticker": "TECHM.NS", "name": "Tech Mahindra", "keywords": ["tech mahindra", "techm"], "type": "stock"},
    {"ticker": "HDFCLIFE.NS", "name": "HDFC Life Insurance", "keywords": ["hdfc life", "hdfclife"], "type": "stock"},
    {"ticker": "DRREDDY.NS", "name": "Dr Reddys Laboratories", "keywords": ["dr reddy", "drreddy", "dr reddys"], "type": "stock"},
    {"ticker": "DIVISLAB.NS", "name": "Divis Laboratories", "keywords": ["divis", "divislab", "divis lab"], "type": "stock"},
    {"ticker": "CIPLA.NS", "name": "Cipla", "keywords": ["cipla"], "type": "stock"},
    {"ticker": "BRITANNIA.NS", "name": "Britannia Industries", "keywords": ["britannia", "britannia industries", "good day"], "type": "stock"},
    {"ticker": "GRASIM.NS", "name": "Grasim Industries", "keywords": ["grasim", "grasim industries"], "type": "stock"},
    {"ticker": "COALINDIA.NS", "name": "Coal India", "keywords": ["coal india", "coalindia", "cil"], "type": "stock"},
    {"ticker": "BPCL.NS", "name": "Bharat Petroleum", "keywords": ["bpcl", "bharat petroleum"], "type": "stock"},
    {"ticker": "EICHERMOT.NS", "name": "Eicher Motors", "keywords": ["eicher", "eicher motors", "royal enfield", "enfield"], "type": "stock"},
    {"ticker": "HEROMOTOCO.NS", "name": "Hero MotoCorp", "keywords": ["hero", "hero motocorp", "heromotoco", "hero honda"], "type": "stock"},
    {"ticker": "INDUSINDBK.NS", "name": "IndusInd Bank", "keywords": ["indusind", "indusind bank", "indusindbk"], "type": "stock"},
    {"ticker": "SBILIFE.NS", "name": "SBI Life Insurance", "keywords": ["sbi life", "sbilife"], "type": "stock"},
    {"ticker": "TATACONSUM.NS", "name": "Tata Consumer Products", "keywords": ["tata consumer", "tataconsum", "tata tea", "tetley"], "type": "stock"},
    {"ticker": "BAJAJ-AUTO.NS", "name": "Bajaj Auto", "keywords": ["bajaj auto", "bajaj-auto", "bajaj bike"], "type": "stock"},
    {"ticker": "APOLLOHOSP.NS", "name": "Apollo Hospitals", "keywords": ["apollo", "apollo hospitals", "apollohosp"], "type": "stock"},
    {"ticker": "ADANIPORTS.NS", "name": "Adani Ports", "keywords": ["adani ports", "adaniports", "apsez"], "type": "stock"},
    {"ticker": "HINDALCO.NS", "name": "Hindalco Industries", "keywords": ["hindalco", "hindalco industries", "novelis"], "type": "stock"},

    # ===== NIFTY NEXT 50 =====
    {"ticker": "SHRIRAMFIN.NS", "name": "Shriram Finance", "keywords": ["shriram", "shriram finance", "shriramfin"], "type": "stock"},
    {"ticker": "ICICIGI.NS", "name": "ICICI Lombard General Insurance", "keywords": ["icici lombard", "icicigi", "icici general"], "type": "stock"},
    {"ticker": "DLF.NS", "name": "DLF Limited", "keywords": ["dlf", "dlf limited", "dlf homes"], "type": "stock"},
    {"ticker": "GODREJPROP.NS", "name": "Godrej Properties", "keywords": ["godrej properties", "godrejprop", "godrej prop"], "type": "stock"},
    {"ticker": "DABUR.NS", "name": "Dabur India", "keywords": ["dabur", "dabur india", "real juice"], "type": "stock"},
    {"ticker": "PIDILITIND.NS", "name": "Pidilite Industries", "keywords": ["pidilite", "pidilitind", "fevicol", "pidilite industries"], "type": "stock"},
    {"ticker": "GODREJCP.NS", "name": "Godrej Consumer Products", "keywords": ["godrej", "godrejcp", "godrej consumer", "cinthol"], "type": "stock"},
    {"ticker": "SIEMENS.NS", "name": "Siemens India", "keywords": ["siemens", "siemens india"], "type": "stock"},
    {"ticker": "ABB.NS", "name": "ABB India", "keywords": ["abb", "abb india"], "type": "stock"},
    {"ticker": "HAVELLS.NS", "name": "Havells India", "keywords": ["havells", "havells india", "lloyd"], "type": "stock"},
    {"ticker": "INDIGO.NS", "name": "InterGlobe Aviation (IndiGo)", "keywords": ["indigo", "interglobe", "indigo airlines"], "type": "stock"},
    {"ticker": "HAL.NS", "name": "Hindustan Aeronautics", "keywords": ["hal", "hindustan aeronautics", "hal share"], "type": "stock"},
    {"ticker": "BEL.NS", "name": "Bharat Electronics", "keywords": ["bel", "bharat electronics"], "type": "stock"},
    {"ticker": "BANKBARODA.NS", "name": "Bank of Baroda", "keywords": ["bank of baroda", "bob", "bankbaroda"], "type": "stock"},
    {"ticker": "PNB.NS", "name": "Punjab National Bank", "keywords": ["pnb", "punjab national", "punjab national bank"], "type": "stock"},
    {"ticker": "CANBK.NS", "name": "Canara Bank", "keywords": ["canara bank", "canbk", "canara"], "type": "stock"},
    {"ticker": "IDFCFIRSTB.NS", "name": "IDFC First Bank", "keywords": ["idfc first", "idfc", "idfcfirstb"], "type": "stock"},
    {"ticker": "FEDERALBNK.NS", "name": "Federal Bank", "keywords": ["federal bank", "federalbnk", "federal"], "type": "stock"},
    {"ticker": "BANDHANBNK.NS", "name": "Bandhan Bank", "keywords": ["bandhan", "bandhan bank", "bandhanbnk"], "type": "stock"},
    {"ticker": "TRENT.NS", "name": "Trent (Westside/Zudio)", "keywords": ["trent", "westside", "zudio", "trent limited"], "type": "stock"},
    {"ticker": "DMART.NS", "name": "Avenue Supermarts (DMart)", "keywords": ["dmart", "d-mart", "avenue supermarts"], "type": "stock"},
    {"ticker": "IRCTC.NS", "name": "IRCTC", "keywords": ["irctc", "indian railway catering", "irctc share"], "type": "stock"},
    {"ticker": "ZOMATO.NS", "name": "Zomato", "keywords": ["zomato", "blinkit"], "type": "stock"},
    {"ticker": "PAGEIND.NS", "name": "Page Industries (Jockey)", "keywords": ["page", "page industries", "jockey", "pageind"], "type": "stock"},
    {"ticker": "COLPAL.NS", "name": "Colgate Palmolive", "keywords": ["colgate", "colpal", "colgate palmolive"], "type": "stock"},
    {"ticker": "MARICO.NS", "name": "Marico", "keywords": ["marico", "parachute", "saffola"], "type": "stock"},
    {"ticker": "TATAPOWER.NS", "name": "Tata Power", "keywords": ["tata power", "tatapower"], "type": "stock"},
    {"ticker": "ADANIGREEN.NS", "name": "Adani Green Energy", "keywords": ["adani green", "adanigreen", "adani solar"], "type": "stock"},
    {"ticker": "NAUKRI.NS", "name": "Info Edge (Naukri)", "keywords": ["naukri", "info edge", "naukri.com", "infoedge"], "type": "stock"},
    {"ticker": "MCDOWELL-N.NS", "name": "United Spirits", "keywords": ["united spirits", "mcdowell", "diageo india"], "type": "stock"},
    {"ticker": "AMBUJACEM.NS", "name": "Ambuja Cements", "keywords": ["ambuja", "ambuja cements", "ambujacem"], "type": "stock"},
    {"ticker": "ACC.NS", "name": "ACC Limited", "keywords": ["acc", "acc cement", "acc limited"], "type": "stock"},
    {"ticker": "BERGEPAINT.NS", "name": "Berger Paints", "keywords": ["berger paints", "bergepaint", "berger"], "type": "stock"},
    {"ticker": "ICICIPRULI.NS", "name": "ICICI Prudential Life", "keywords": ["icici prudential", "icicipruli", "icici pru life"], "type": "stock"},
    {"ticker": "SBICARD.NS", "name": "SBI Cards", "keywords": ["sbi cards", "sbicard", "sbi card"], "type": "stock"},
    {"ticker": "MAXHEALTH.NS", "name": "Max Healthcare", "keywords": ["max healthcare", "maxhealth", "max hospital"], "type": "stock"},
    {"ticker": "TORNTPHARM.NS", "name": "Torrent Pharma", "keywords": ["torrent pharma", "torntpharm", "torrent pharmaceutical"], "type": "stock"},
    {"ticker": "ZYDUSLIFE.NS", "name": "Zydus Lifesciences", "keywords": ["zydus", "zyduslife", "cadila", "zydus life"], "type": "stock"},
    {"ticker": "LUPIN.NS", "name": "Lupin", "keywords": ["lupin", "lupin pharma"], "type": "stock"},
    {"ticker": "IOC.NS", "name": "Indian Oil Corporation", "keywords": ["ioc", "indian oil", "indian oil corporation"], "type": "stock"},
    {"ticker": "GAIL.NS", "name": "GAIL India", "keywords": ["gail", "gail india"], "type": "stock"},
    {"ticker": "VEDL.NS", "name": "Vedanta Limited", "keywords": ["vedanta", "vedl", "vedanta limited"], "type": "stock"},
    {"ticker": "JINDALSTEL.NS", "name": "Jindal Steel & Power", "keywords": ["jindal steel", "jindalstel", "jspl"], "type": "stock"},
    {"ticker": "NMDC.NS", "name": "NMDC Limited", "keywords": ["nmdc", "nmdc steel"], "type": "stock"},
    {"ticker": "SAIL.NS", "name": "Steel Authority of India", "keywords": ["sail", "steel authority"], "type": "stock"},
    {"ticker": "PEL.NS", "name": "Piramal Enterprises", "keywords": ["piramal", "pel", "piramal enterprises"], "type": "stock"},
    {"ticker": "MFSL.NS", "name": "Max Financial Services", "keywords": ["max financial", "mfsl", "max life"], "type": "stock"},
    {"ticker": "OBEROIRLTY.NS", "name": "Oberoi Realty", "keywords": ["oberoi realty", "oberoirlty", "oberoi"], "type": "stock"},
    {"ticker": "PRESTIGE.NS", "name": "Prestige Estates", "keywords": ["prestige", "prestige estates"], "type": "stock"},
    {"ticker": "PHOENIXLTD.NS", "name": "Phoenix Mills", "keywords": ["phoenix mills", "phoenixltd", "phoenix mall"], "type": "stock"},
    {"ticker": "YESBANK.NS", "name": "Yes Bank", "keywords": ["yes bank", "yesbank"], "type": "stock"},
    {"ticker": "AUBANK.NS", "name": "AU Small Finance Bank", "keywords": ["au bank", "au small finance", "aubank"], "type": "stock"},
    {"ticker": "JUBLFOOD.NS", "name": "Jubilant FoodWorks", "keywords": ["jubilant", "jublfood", "dominos india", "dominos"], "type": "stock"},
    {"ticker": "UNITDSPR.NS", "name": "United Spirits", "keywords": ["united spirits", "unitdspr", "diageo"], "type": "stock"},

    # ===== NIFTY MIDCAP 100 & POPULAR MIDCAPS =====
    {"ticker": "PERSISTENT.NS", "name": "Persistent Systems", "keywords": ["persistent", "persistent systems"], "type": "stock"},
    {"ticker": "COFORGE.NS", "name": "Coforge", "keywords": ["coforge", "niit tech"], "type": "stock"},
    {"ticker": "MPHASIS.NS", "name": "Mphasis", "keywords": ["mphasis", "mphasis it"], "type": "stock"},
    {"ticker": "LTTS.NS", "name": "L&T Technology Services", "keywords": ["ltts", "l&t technology", "lt technology"], "type": "stock"},
    {"ticker": "LTIM.NS", "name": "LTIMindtree", "keywords": ["ltimindtree", "ltim", "mindtree", "lti"], "type": "stock"},
    {"ticker": "CHOLAFIN.NS", "name": "Cholamandalam Finance", "keywords": ["chola", "cholafin", "cholamandalam"], "type": "stock"},
    {"ticker": "MUTHOOTFIN.NS", "name": "Muthoot Finance", "keywords": ["muthoot", "muthootfin", "muthoot gold"], "type": "stock"},
    {"ticker": "TATAELXSI.NS", "name": "Tata Elxsi", "keywords": ["tata elxsi", "tataelxsi"], "type": "stock"},
    {"ticker": "PIIND.NS", "name": "PI Industries", "keywords": ["pi industries", "piind"], "type": "stock"},
    {"ticker": "VOLTAS.NS", "name": "Voltas", "keywords": ["voltas", "voltas ac"], "type": "stock"},
    {"ticker": "TATACHEM.NS", "name": "Tata Chemicals", "keywords": ["tata chemicals", "tatachem"], "type": "stock"},
    {"ticker": "TVSMOTOR.NS", "name": "TVS Motor", "keywords": ["tvs", "tvs motor", "tvsmotor", "tvs jupiter"], "type": "stock"},
    {"ticker": "ASHOKLEY.NS", "name": "Ashok Leyland", "keywords": ["ashok leyland", "ashokley", "leyland"], "type": "stock"},
    {"ticker": "MOTHERSON.NS", "name": "Motherson Sumi", "keywords": ["motherson", "motherson sumi", "samvardhana"], "type": "stock"},
    {"ticker": "BIOCON.NS", "name": "Biocon", "keywords": ["biocon", "biocon biologics", "kiran mazumdar"], "type": "stock"},
    {"ticker": "AUROPHARMA.NS", "name": "Aurobindo Pharma", "keywords": ["aurobindo", "auropharma", "aurobindo pharma"], "type": "stock"},
    {"ticker": "MANKINDPHARMA.NS", "name": "Mankind Pharma", "keywords": ["mankind", "mankind pharma", "mankindpharma"], "type": "stock"},
    {"ticker": "PAYTM.NS", "name": "Paytm (One97)", "keywords": ["paytm", "one97", "one 97"], "type": "stock"},
    {"ticker": "NYKAA.NS", "name": "Nykaa (FSN E-Commerce)", "keywords": ["nykaa", "fsn", "nykaa fashion"], "type": "stock"},
    {"ticker": "POLICYBZR.NS", "name": "PB Fintech (PolicyBazaar)", "keywords": ["policybazaar", "pb fintech", "policybzr", "policy bazaar"], "type": "stock"},
    {"ticker": "CROMPTON.NS", "name": "Crompton Greaves Consumer", "keywords": ["crompton", "crompton greaves"], "type": "stock"},
    {"ticker": "POLYCAB.NS", "name": "Polycab India", "keywords": ["polycab", "polycab india", "polycab wire"], "type": "stock"},
    {"ticker": "ASTRAL.NS", "name": "Astral Limited", "keywords": ["astral", "astral pipes", "astral poly"], "type": "stock"},
    {"ticker": "SUPREMEIND.NS", "name": "Supreme Industries", "keywords": ["supreme", "supreme industries", "supremeind"], "type": "stock"},
    {"ticker": "CUMMINSIND.NS", "name": "Cummins India", "keywords": ["cummins", "cumminsind", "cummins india"], "type": "stock"},
    {"ticker": "THERMAX.NS", "name": "Thermax", "keywords": ["thermax"], "type": "stock"},
    {"ticker": "AIAENG.NS", "name": "AIA Engineering", "keywords": ["aia engineering", "aiaeng", "aia"], "type": "stock"},
    {"ticker": "SUNDRMFAST.NS", "name": "Sundram Fasteners", "keywords": ["sundram", "sundrmfast", "sundaram fasteners"], "type": "stock"},
    {"ticker": "BALKRISIND.NS", "name": "Balkrishna Industries", "keywords": ["balkrishna", "balkrisind", "bkt tyres"], "type": "stock"},
    {"ticker": "ESCORTS.NS", "name": "Escorts Kubota", "keywords": ["escorts", "escorts kubota", "farmtrac"], "type": "stock"},
    {"ticker": "BHARATFORG.NS", "name": "Bharat Forge", "keywords": ["bharat forge", "bharatforg", "kalyani"], "type": "stock"},
    {"ticker": "SOLARINDS.NS", "name": "Solar Industries", "keywords": ["solar industries", "solarinds"], "type": "stock"},
    {"ticker": "DEEPAKNTR.NS", "name": "Deepak Nitrite", "keywords": ["deepak nitrite", "deepakntr"], "type": "stock"},
    {"ticker": "ATUL.NS", "name": "Atul Limited", "keywords": ["atul", "atul limited", "atul chemicals"], "type": "stock"},
    {"ticker": "NAVINFLUOR.NS", "name": "Navin Fluorine", "keywords": ["navin fluorine", "navinfluor"], "type": "stock"},
    {"ticker": "AARTIIND.NS", "name": "Aarti Industries", "keywords": ["aarti", "aarti industries", "aartiind"], "type": "stock"},
    {"ticker": "COROMANDEL.NS", "name": "Coromandel International", "keywords": ["coromandel", "coromandel intl"], "type": "stock"},
    {"ticker": "UPL.NS", "name": "UPL Limited", "keywords": ["upl", "upl limited"], "type": "stock"},
    {"ticker": "SUMICHEM.NS", "name": "Sumitomo Chemical India", "keywords": ["sumitomo chemical", "sumichem"], "type": "stock"},
    {"ticker": "BATAINDIA.NS", "name": "Bata India", "keywords": ["bata", "bata india", "bataindia"], "type": "stock"},
    {"ticker": "RELAXO.NS", "name": "Relaxo Footwears", "keywords": ["relaxo", "relaxo footwear", "sparx"], "type": "stock"},
    {"ticker": "METROBRAND.NS", "name": "Metro Brands", "keywords": ["metro brands", "metrobrand", "metro shoes"], "type": "stock"},
    {"ticker": "VBL.NS", "name": "Varun Beverages", "keywords": ["varun beverages", "vbl", "pepsi india"], "type": "stock"},
    {"ticker": "DEVYANI.NS", "name": "Devyani International", "keywords": ["devyani", "kfc india", "pizza hut india"], "type": "stock"},
    {"ticker": "SAPPHIRE.NS", "name": "Sapphire Foods", "keywords": ["sapphire foods", "sapphire", "kfc franchise"], "type": "stock"},
    {"ticker": "RAJESHEXPO.NS", "name": "Rajesh Exports", "keywords": ["rajesh exports", "rajeshexpo"], "type": "stock"},
    {"ticker": "KALYANKJIL.NS", "name": "Kalyan Jewellers", "keywords": ["kalyan jewellers", "kalyankjil", "kalyan"], "type": "stock"},
    {"ticker": "CARTRADE.NS", "name": "CarTrade Tech", "keywords": ["cartrade", "cartrade tech"], "type": "stock"},
    {"ticker": "LICI.NS", "name": "Life Insurance Corporation", "keywords": ["lic", "lici", "life insurance corporation"], "type": "stock"},
    {"ticker": "GICRE.NS", "name": "General Insurance Corporation", "keywords": ["gic", "gicre", "general insurance"], "type": "stock"},
    {"ticker": "NIACL.NS", "name": "New India Assurance", "keywords": ["new india assurance", "niacl"], "type": "stock"},
    {"ticker": "SRTRANSFIN.NS", "name": "Shriram Transport Finance", "keywords": ["shriram transport", "srtransfin"], "type": "stock"},
    {"ticker": "MANAPPURAM.NS", "name": "Manappuram Finance", "keywords": ["manappuram", "manappuram finance", "manappuram gold"], "type": "stock"},
    {"ticker": "LICHSGFIN.NS", "name": "LIC Housing Finance", "keywords": ["lic housing", "lichsgfin", "lic hfl"], "type": "stock"},
    {"ticker": "PFC.NS", "name": "Power Finance Corporation", "keywords": ["pfc", "power finance", "power finance corporation"], "type": "stock"},
    {"ticker": "RECLTD.NS", "name": "REC Limited", "keywords": ["rec", "recltd", "rural electrification"], "type": "stock"},
    {"ticker": "IREDA.NS", "name": "IREDA", "keywords": ["ireda", "indian renewable energy"], "type": "stock"},
    {"ticker": "CESC.NS", "name": "CESC Limited", "keywords": ["cesc", "cesc limited"], "type": "stock"},
    {"ticker": "TORNTPOWER.NS", "name": "Torrent Power", "keywords": ["torrent power", "torntpower"], "type": "stock"},
    {"ticker": "NHPC.NS", "name": "NHPC Limited", "keywords": ["nhpc", "nhpc limited"], "type": "stock"},
    {"ticker": "SJVN.NS", "name": "SJVN Limited", "keywords": ["sjvn", "sjvn limited"], "type": "stock"},
    {"ticker": "JSWENERGY.NS", "name": "JSW Energy", "keywords": ["jsw energy", "jswenergy"], "type": "stock"},
    {"ticker": "ADANIPOWER.NS", "name": "Adani Power", "keywords": ["adani power", "adanipower"], "type": "stock"},
    {"ticker": "SUZLON.NS", "name": "Suzlon Energy", "keywords": ["suzlon", "suzlon energy"], "type": "stock"},
    {"ticker": "TATACOMM.NS", "name": "Tata Communications", "keywords": ["tata communications", "tatacomm", "tata comm"], "type": "stock"},
    {"ticker": "IDEA.NS", "name": "Vodafone Idea", "keywords": ["vodafone idea", "idea", "vi", "vodafone"], "type": "stock"},
    {"ticker": "MTNL.NS", "name": "MTNL", "keywords": ["mtnl", "mahanagar telephone"], "type": "stock"},
    {"ticker": "ZEEL.NS", "name": "Zee Entertainment", "keywords": ["zee", "zeel", "zee tv", "zee entertainment"], "type": "stock"},
    {"ticker": "PVR.NS", "name": "PVR INOX", "keywords": ["pvr", "pvr inox", "inox"], "type": "stock"},
    {"ticker": "SONACOMS.NS", "name": "Sona BLW Precision", "keywords": ["sona blw", "sonacoms", "sona comstar"], "type": "stock"},
    {"ticker": "SCHAEFFLER.NS", "name": "Schaeffler India", "keywords": ["schaeffler", "schaeffler india"], "type": "stock"},
    {"ticker": "TIMKEN.NS", "name": "Timken India", "keywords": ["timken", "timken india"], "type": "stock"},
    {"ticker": "SKFINDIA.NS", "name": "SKF India", "keywords": ["skf", "skf india", "skfindia"], "type": "stock"},
    {"ticker": "WHIRLPOOL.NS", "name": "Whirlpool of India", "keywords": ["whirlpool", "whirlpool india"], "type": "stock"},
    {"ticker": "BLUESTARLT.NS", "name": "Blue Star", "keywords": ["blue star", "bluestar", "bluestarlt"], "type": "stock"},
    {"ticker": "DIXON.NS", "name": "Dixon Technologies", "keywords": ["dixon", "dixon technologies"], "type": "stock"},
    {"ticker": "KAYNES.NS", "name": "Kaynes Technology", "keywords": ["kaynes", "kaynes technology"], "type": "stock"},
    {"ticker": "AMBER.NS", "name": "Amber Enterprises", "keywords": ["amber", "amber enterprises"], "type": "stock"},
    {"ticker": "CLEAN.NS", "name": "Clean Science and Technology", "keywords": ["clean science", "clean"], "type": "stock"},
    {"ticker": "AFFLE.NS", "name": "Affle India", "keywords": ["affle", "affle india"], "type": "stock"},
    {"ticker": "ROUTE.NS", "name": "Route Mobile", "keywords": ["route mobile", "route"], "type": "stock"},
    {"ticker": "HAPPSTMNDS.NS", "name": "Happiest Minds", "keywords": ["happiest minds", "happstmnds"], "type": "stock"},
    {"ticker": "KPITTECH.NS", "name": "KPIT Technologies", "keywords": ["kpit", "kpittech", "kpit technologies"], "type": "stock"},
    {"ticker": "TATATECH.NS", "name": "Tata Technologies", "keywords": ["tata technologies", "tatatech"], "type": "stock"},
    {"ticker": "CYIENT.NS", "name": "Cyient", "keywords": ["cyient", "infotech enterprises"], "type": "stock"},
    {"ticker": "BIRLASOFT.NS", "name": "Birlasoft", "keywords": ["birlasoft", "birla soft"], "type": "stock"},
    {"ticker": "ZENSAR.NS", "name": "Zensar Technologies", "keywords": ["zensar", "zensar technologies"], "type": "stock"},
    {"ticker": "MASTEK.NS", "name": "Mastek", "keywords": ["mastek"], "type": "stock"},
    {"ticker": "TANLA.NS", "name": "Tanla Platforms", "keywords": ["tanla", "tanla platforms"], "type": "stock"},
    {"ticker": "INTELLECT.NS", "name": "Intellect Design Arena", "keywords": ["intellect", "intellect design"], "type": "stock"},
    {"ticker": "DATAPATTNS.NS", "name": "Data Patterns", "keywords": ["data patterns", "datapattns"], "type": "stock"},
    {"ticker": "PARAS.NS", "name": "Paras Defence", "keywords": ["paras defence", "paras"], "type": "stock"},
    {"ticker": "IDEAFORGE.NS", "name": "ideaForge Technology", "keywords": ["ideaforge", "drone india"], "type": "stock"},

    # ===== BANKS & NBFC (additional) =====
    {"ticker": "RBLBANK.NS", "name": "RBL Bank", "keywords": ["rbl bank", "rblbank", "rbl"], "type": "stock"},
    {"ticker": "CUB.NS", "name": "City Union Bank", "keywords": ["city union bank", "cub"], "type": "stock"},
    {"ticker": "KARURVYSYA.NS", "name": "Karur Vysya Bank", "keywords": ["karur vysya", "karurvysya", "kvb"], "type": "stock"},
    {"ticker": "SOUTHBANK.NS", "name": "South Indian Bank", "keywords": ["south indian bank", "southbank", "sib"], "type": "stock"},
    {"ticker": "DCBBANK.NS", "name": "DCB Bank", "keywords": ["dcb bank", "dcbbank"], "type": "stock"},
    {"ticker": "UJJIVANSFB.NS", "name": "Ujjivan Small Finance Bank", "keywords": ["ujjivan", "ujjivansfb", "ujjivan sfb"], "type": "stock"},
    {"ticker": "EQUITASBNK.NS", "name": "Equitas Small Finance Bank", "keywords": ["equitas", "equitasbnk"], "type": "stock"},
    {"ticker": "MAHABANK.NS", "name": "Bank of Maharashtra", "keywords": ["bank of maharashtra", "mahabank", "bom"], "type": "stock"},
    {"ticker": "INDIANB.NS", "name": "Indian Bank", "keywords": ["indian bank", "indianb"], "type": "stock"},
    {"ticker": "IOB.NS", "name": "Indian Overseas Bank", "keywords": ["iob", "indian overseas bank"], "type": "stock"},
    {"ticker": "UCOBANK.NS", "name": "UCO Bank", "keywords": ["uco bank", "ucobank"], "type": "stock"},
    {"ticker": "CENTRALBK.NS", "name": "Central Bank of India", "keywords": ["central bank", "centralbk"], "type": "stock"},
    {"ticker": "UNIONBANK.NS", "name": "Union Bank of India", "keywords": ["union bank", "unionbank"], "type": "stock"},
    {"ticker": "PNBHOUSING.NS", "name": "PNB Housing Finance", "keywords": ["pnb housing", "pnbhousing"], "type": "stock"},
    {"ticker": "CANFINHOME.NS", "name": "Can Fin Homes", "keywords": ["can fin homes", "canfinhome", "canfin"], "type": "stock"},
    {"ticker": "AAVAS.NS", "name": "Aavas Financiers", "keywords": ["aavas", "aavas financiers"], "type": "stock"},
    {"ticker": "HOMEFIRST.NS", "name": "Home First Finance", "keywords": ["home first", "homefirst"], "type": "stock"},
    {"ticker": "BAJAJHFL.NS", "name": "Bajaj Housing Finance", "keywords": ["bajaj housing", "bajajhfl", "bajaj hfl"], "type": "stock"},
    {"ticker": "IIFL.NS", "name": "IIFL Finance", "keywords": ["iifl", "iifl finance"], "type": "stock"},
    {"ticker": "M&MFIN.NS", "name": "Mahindra & Mahindra Financial", "keywords": ["mahindra finance", "m&mfin", "mmfin"], "type": "stock"},
    {"ticker": "L&TFH.NS", "name": "L&T Finance Holdings", "keywords": ["l&t finance", "ltfh", "lt finance"], "type": "stock"},
    {"ticker": "POONAWALLA.NS", "name": "Poonawalla Fincorp", "keywords": ["poonawalla", "poonawalla fincorp"], "type": "stock"},

    # ===== ENERGY & OIL & GAS =====
    {"ticker": "HINDPETRO.NS", "name": "Hindustan Petroleum", "keywords": ["hpcl", "hindustan petroleum", "hindpetro"], "type": "stock"},
    {"ticker": "PETRONET.NS", "name": "Petronet LNG", "keywords": ["petronet", "petronet lng"], "type": "stock"},
    {"ticker": "MGL.NS", "name": "Mahanagar Gas", "keywords": ["mahanagar gas", "mgl"], "type": "stock"},
    {"ticker": "IGL.NS", "name": "Indraprastha Gas", "keywords": ["igl", "indraprastha gas"], "type": "stock"},
    {"ticker": "GUJGASLTD.NS", "name": "Gujarat Gas", "keywords": ["gujarat gas", "gujgas"], "type": "stock"},
    {"ticker": "OIL.NS", "name": "Oil India", "keywords": ["oil india", "oil"], "type": "stock"},
    {"ticker": "RELINFRA.NS", "name": "Reliance Infrastructure", "keywords": ["reliance infra", "relinfra", "rinfra"], "type": "stock"},
    {"ticker": "ADANITRANS.NS", "name": "Adani Energy Solutions", "keywords": ["adani transmission", "adanitrans", "adani energy"], "type": "stock"},

    # ===== PHARMA (additional) =====
    {"ticker": "ALKEM.NS", "name": "Alkem Laboratories", "keywords": ["alkem", "alkem lab"], "type": "stock"},
    {"ticker": "IPCALAB.NS", "name": "Ipca Laboratories", "keywords": ["ipca", "ipcalab", "ipca labs"], "type": "stock"},
    {"ticker": "GLENMARK.NS", "name": "Glenmark Pharma", "keywords": ["glenmark", "glenmark pharma"], "type": "stock"},
    {"ticker": "LAURUSLABS.NS", "name": "Laurus Labs", "keywords": ["laurus labs", "lauruslabs", "laurus"], "type": "stock"},
    {"ticker": "GRANULES.NS", "name": "Granules India", "keywords": ["granules", "granules india"], "type": "stock"},
    {"ticker": "NATCOPHARM.NS", "name": "Natco Pharma", "keywords": ["natco", "natcopharm", "natco pharma"], "type": "stock"},
    {"ticker": "AJANTPHARM.NS", "name": "Ajanta Pharma", "keywords": ["ajanta", "ajanta pharma", "ajantpharm"], "type": "stock"},
    {"ticker": "ERIS.NS", "name": "Eris Lifesciences", "keywords": ["eris", "eris lifesciences"], "type": "stock"},
    {"ticker": "SYNGENE.NS", "name": "Syngene International", "keywords": ["syngene", "syngene international"], "type": "stock"},
    {"ticker": "ABBOTINDIA.NS", "name": "Abbott India", "keywords": ["abbott", "abbott india", "abbotindia"], "type": "stock"},
    {"ticker": "PFIZER.NS", "name": "Pfizer India", "keywords": ["pfizer", "pfizer india"], "type": "stock"},
    {"ticker": "GLAXO.NS", "name": "GlaxoSmithKline Pharma", "keywords": ["gsk", "glaxo", "glaxosmithkline"], "type": "stock"},
    {"ticker": "JBCHEPHARM.NS", "name": "JB Chemicals", "keywords": ["jb chemicals", "jbchepharm", "jb pharma"], "type": "stock"},

    # ===== CEMENT (additional) =====
    {"ticker": "SHREECEM.NS", "name": "Shree Cement", "keywords": ["shree cement", "shreecem"], "type": "stock"},
    {"ticker": "RAMCOCEM.NS", "name": "Ramco Cements", "keywords": ["ramco", "ramco cements", "ramcocem"], "type": "stock"},
    {"ticker": "DALMIACEM.NS", "name": "Dalmia Bharat Cement", "keywords": ["dalmia", "dalmia bharat", "dalmiacem"], "type": "stock"},
    {"ticker": "JKCEMENT.NS", "name": "JK Cement", "keywords": ["jk cement", "jkcement"], "type": "stock"},
    {"ticker": "JKLAKSHMI.NS", "name": "JK Lakshmi Cement", "keywords": ["jk lakshmi", "jklakshmi"], "type": "stock"},
    {"ticker": "BIRLACEM.NS", "name": "Nuvoco Vistas", "keywords": ["nuvoco", "nuvoco vistas", "birla cement"], "type": "stock"},
    {"ticker": "HEIDELBERG.NS", "name": "Heidelberg Cement India", "keywords": ["heidelberg", "heidelberg cement"], "type": "stock"},
    {"ticker": "PRISMJOINS.NS", "name": "Prism Johnson", "keywords": ["prism johnson", "prismjoins"], "type": "stock"},

    # ===== METALS & MINING (additional) =====
    {"ticker": "NATIONALUM.NS", "name": "National Aluminium", "keywords": ["nalco", "national aluminium", "nationalum"], "type": "stock"},
    {"ticker": "HINDZINC.NS", "name": "Hindustan Zinc", "keywords": ["hindustan zinc", "hindzinc", "hzl"], "type": "stock"},
    {"ticker": "MOIL.NS", "name": "MOIL Limited", "keywords": ["moil", "moil limited"], "type": "stock"},
    {"ticker": "RATNAMANI.NS", "name": "Ratnamani Metals", "keywords": ["ratnamani", "ratnamani metals"], "type": "stock"},
    {"ticker": "APLAPOLLO.NS", "name": "APL Apollo Tubes", "keywords": ["apl apollo", "aplapollo", "apollo tubes"], "type": "stock"},
    {"ticker": "WELCORP.NS", "name": "Welspun Corp", "keywords": ["welspun", "welcorp", "welspun corp"], "type": "stock"},

    # ===== AUTOMOBILE (additional) =====
    {"ticker": "MRF.NS", "name": "MRF Limited", "keywords": ["mrf", "mrf tyres", "mrf tyre"], "type": "stock"},
    {"ticker": "APOLLOTYRE.NS", "name": "Apollo Tyres", "keywords": ["apollo tyres", "apollotyre"], "type": "stock"},
    {"ticker": "CEATLTD.NS", "name": "CEAT Limited", "keywords": ["ceat", "ceatltd", "ceat tyres"], "type": "stock"},
    {"ticker": "JKTYRE.NS", "name": "JK Tyre", "keywords": ["jk tyre", "jktyre"], "type": "stock"},
    {"ticker": "EXIDEIND.NS", "name": "Exide Industries", "keywords": ["exide", "exide industries", "exideind"], "type": "stock"},
    {"ticker": "AMARAJABAT.NS", "name": "Amara Raja Energy", "keywords": ["amara raja", "amarajabat", "amaron"], "type": "stock"},
    {"ticker": "BOSCHLTD.NS", "name": "Bosch India", "keywords": ["bosch", "boschltd", "bosch india"], "type": "stock"},
    {"ticker": "HONAUT.NS", "name": "Honeywell Automation", "keywords": ["honeywell", "honaut", "honeywell automation"], "type": "stock"},
    {"ticker": "SWARAJENG.NS", "name": "Swaraj Engines", "keywords": ["swaraj", "swaraj engines"], "type": "stock"},
    {"ticker": "FORCEMOT.NS", "name": "Force Motors", "keywords": ["force motors", "forcemot"], "type": "stock"},
    {"ticker": "OLECTRA.NS", "name": "Olectra Greentech", "keywords": ["olectra", "olectra greentech", "olectra bus"], "type": "stock"},

    # ===== FMCG (additional) =====
    {"ticker": "EMAMILTD.NS", "name": "Emami Limited", "keywords": ["emami", "emamiltd", "emami fair"], "type": "stock"},
    {"ticker": "JYOTHYLAB.NS", "name": "Jyothy Labs", "keywords": ["jyothy", "jyothy labs", "ujala"], "type": "stock"},
    {"ticker": "BIKAJI.NS", "name": "Bikaji Foods", "keywords": ["bikaji", "bikaji foods"], "type": "stock"},
    {"ticker": "KRBL.NS", "name": "KRBL Limited", "keywords": ["krbl", "india gate", "india gate basmati"], "type": "stock"},
    {"ticker": "VENKY.NS", "name": "Venky's India", "keywords": ["venkys", "venky"], "type": "stock"},
    {"ticker": "HATSUN.NS", "name": "Hatsun Agro Products", "keywords": ["hatsun", "arun ice cream", "ibaco"], "type": "stock"},
    {"ticker": "ZENSARTECH.NS", "name": "Zen Technologies", "keywords": ["zen tech", "zen technologies"], "type": "stock"},
    {"ticker": "CCL.NS", "name": "CCL Products", "keywords": ["ccl products", "ccl", "continental coffee"], "type": "stock"},
    {"ticker": "TATACOFFEE.NS", "name": "Tata Coffee", "keywords": ["tata coffee", "tatacoffee"], "type": "stock"},
    {"ticker": "RADICO.NS", "name": "Radico Khaitan", "keywords": ["radico", "radico khaitan", "magic moments"], "type": "stock"},
    {"ticker": "UBL.NS", "name": "United Breweries", "keywords": ["ubl", "united breweries", "kingfisher beer"], "type": "stock"},

    # ===== IT SERVICES (additional) =====
    {"ticker": "MPHASIS.NS", "name": "Mphasis", "keywords": ["mphasis"], "type": "stock"},
    {"ticker": "OFSS.NS", "name": "Oracle Financial Services", "keywords": ["oracle financial", "ofss", "oracle finserv"], "type": "stock"},
    {"ticker": "NEWGEN.NS", "name": "Newgen Software", "keywords": ["newgen", "newgen software"], "type": "stock"},
    {"ticker": "NUCLEUS.NS", "name": "Nucleus Software", "keywords": ["nucleus", "nucleus software"], "type": "stock"},
    {"ticker": "SONATSOFTW.NS", "name": "Sonata Software", "keywords": ["sonata", "sonata software"], "type": "stock"},
    {"ticker": "ECLERX.NS", "name": "eClerx Services", "keywords": ["eclerx", "eclerx services"], "type": "stock"},
    {"ticker": "NIITLTD.NS", "name": "NIIT Limited", "keywords": ["niit", "niitltd"], "type": "stock"},
    {"ticker": "RATEGAIN.NS", "name": "RateGain Travel", "keywords": ["rategain", "rategain travel"], "type": "stock"},

    # ===== INFRASTRUCTURE & CONSTRUCTION =====
    {"ticker": "IRB.NS", "name": "IRB Infrastructure", "keywords": ["irb", "irb infra", "irb infrastructure"], "type": "stock"},
    {"ticker": "NCC.NS", "name": "NCC Limited", "keywords": ["ncc", "ncc limited", "nagarjuna construction"], "type": "stock"},
    {"ticker": "NBCC.NS", "name": "NBCC India", "keywords": ["nbcc", "nbcc india"], "type": "stock"},
    {"ticker": "KEC.NS", "name": "KEC International", "keywords": ["kec", "kec international"], "type": "stock"},
    {"ticker": "KALPATPOWR.NS", "name": "Kalpataru Projects", "keywords": ["kalpataru", "kalpatpowr"], "type": "stock"},
    {"ticker": "ENGINERSIN.NS", "name": "Engineers India", "keywords": ["engineers india", "eil", "enginersin"], "type": "stock"},
    {"ticker": "RITES.NS", "name": "RITES Limited", "keywords": ["rites", "rites limited"], "type": "stock"},
    {"ticker": "RVNL.NS", "name": "Rail Vikas Nigam", "keywords": ["rvnl", "rail vikas", "rail vikas nigam"], "type": "stock"},
    {"ticker": "IRFC.NS", "name": "Indian Railway Finance", "keywords": ["irfc", "indian railway finance"], "type": "stock"},
    {"ticker": "RAILTEL.NS", "name": "RailTel Corporation", "keywords": ["railtel", "railtel corporation"], "type": "stock"},
    {"ticker": "HUDCO.NS", "name": "HUDCO", "keywords": ["hudco", "housing urban development"], "type": "stock"},
    {"ticker": "COCHINSHIP.NS", "name": "Cochin Shipyard", "keywords": ["cochin shipyard", "cochinship"], "type": "stock"},
    {"ticker": "GRSE.NS", "name": "Garden Reach Shipbuilders", "keywords": ["grse", "garden reach", "garden reach ship"], "type": "stock"},
    {"ticker": "MAZAGONDOC.NS", "name": "Mazagon Dock Shipbuilders", "keywords": ["mazagon dock", "mazagondoc", "mdl"], "type": "stock"},
    {"ticker": "BDL.NS", "name": "Bharat Dynamics", "keywords": ["bdl", "bharat dynamics"], "type": "stock"},
    {"ticker": "BEML.NS", "name": "BEML Limited", "keywords": ["beml", "beml limited"], "type": "stock"},

    # ===== REAL ESTATE (additional) =====
    {"ticker": "LODHA.NS", "name": "Macrotech Developers (Lodha)", "keywords": ["lodha", "macrotech", "lodha group"], "type": "stock"},
    {"ticker": "BRIGADE.NS", "name": "Brigade Enterprises", "keywords": ["brigade", "brigade enterprises"], "type": "stock"},
    {"ticker": "SOBHA.NS", "name": "Sobha Limited", "keywords": ["sobha", "sobha limited", "sobha developers"], "type": "stock"},
    {"ticker": "SUNTECK.NS", "name": "Sunteck Realty", "keywords": ["sunteck", "sunteck realty"], "type": "stock"},
    {"ticker": "MAHLIFE.NS", "name": "Mahindra Lifespace", "keywords": ["mahindra lifespace", "mahlife"], "type": "stock"},
    {"ticker": "KOLTEPATIL.NS", "name": "Kolte Patil Developers", "keywords": ["kolte patil", "koltepatil"], "type": "stock"},
    {"ticker": "RAYMOND.NS", "name": "Raymond Limited", "keywords": ["raymond", "raymond limited"], "type": "stock"},

    # ===== TELECOM & MEDIA =====
    {"ticker": "BHARTIARTL.NS", "name": "Bharti Airtel", "keywords": ["airtel", "bharti airtel"], "type": "stock"},
    {"ticker": "INDUSTOWER.NS", "name": "Indus Towers", "keywords": ["indus towers", "industower"], "type": "stock"},
    {"ticker": "SUNTV.NS", "name": "Sun TV Network", "keywords": ["sun tv", "suntv", "sun network"], "type": "stock"},
    {"ticker": "NAZARA.NS", "name": "Nazara Technologies", "keywords": ["nazara", "nazara technologies", "nazara gaming"], "type": "stock"},

    # ===== CHEMICALS (additional) =====
    {"ticker": "SRF.NS", "name": "SRF Limited", "keywords": ["srf", "srf limited", "srf chemicals"], "type": "stock"},
    {"ticker": "FLUOROCHEM.NS", "name": "Gujarat Fluorochemicals", "keywords": ["gujarat fluoro", "fluorochem", "gfl"], "type": "stock"},
    {"ticker": "TATACHEMICALS.NS", "name": "Tata Chemicals", "keywords": ["tata chemicals"], "type": "stock"},
    {"ticker": "BASF.NS", "name": "BASF India", "keywords": ["basf", "basf india"], "type": "stock"},
    {"ticker": "LXCHEM.NS", "name": "Laxmi Organic Industries", "keywords": ["laxmi organic", "lxchem"], "type": "stock"},
    {"ticker": "NOCIL.NS", "name": "NOCIL Limited", "keywords": ["nocil", "nocil limited"], "type": "stock"},
    {"ticker": "GALAXYSURF.NS", "name": "Galaxy Surfactants", "keywords": ["galaxy surfactants", "galaxysurf"], "type": "stock"},
    {"ticker": "FINEORG.NS", "name": "Fine Organic Industries", "keywords": ["fine organic", "fineorg"], "type": "stock"},
    {"ticker": "ALKYLAMINE.NS", "name": "Alkyl Amines", "keywords": ["alkyl amines", "alkylamine"], "type": "stock"},
    {"ticker": "ROSSARI.NS", "name": "Rossari Biotech", "keywords": ["rossari", "rossari biotech"], "type": "stock"},
    {"ticker": "TATVA.NS", "name": "Tatva Chintan Pharma", "keywords": ["tatva chintan", "tatva"], "type": "stock"},

    # ===== CAPITAL GOODS & ELECTRICAL =====
    {"ticker": "BHEL.NS", "name": "Bharat Heavy Electricals", "keywords": ["bhel", "bharat heavy", "bharat heavy electricals"], "type": "stock"},
    {"ticker": "CGPOWER.NS", "name": "CG Power and Industrial", "keywords": ["cg power", "cgpower", "crompton greaves"], "type": "stock"},
    {"ticker": "KAJARIACER.NS", "name": "Kajaria Ceramics", "keywords": ["kajaria", "kajariacer", "kajaria ceramics"], "type": "stock"},
    {"ticker": "CENTURYTEX.NS", "name": "Century Textiles", "keywords": ["century textiles", "centurytex", "century"], "type": "stock"},
    {"ticker": "ASTRAZEN.NS", "name": "AstraZeneca Pharma India", "keywords": ["astrazeneca", "astrazen"], "type": "stock"},
    {"ticker": "3MINDIA.NS", "name": "3M India", "keywords": ["3m", "3m india", "3mindia"], "type": "stock"},
    {"ticker": "GRINDWELL.NS", "name": "Grindwell Norton", "keywords": ["grindwell", "grindwell norton"], "type": "stock"},
    {"ticker": "CARBORUNIV.NS", "name": "Carborundum Universal", "keywords": ["carborundum", "carboruniv", "cumi"], "type": "stock"},
    {"ticker": "ELGIEQUIP.NS", "name": "Elgi Equipments", "keywords": ["elgi", "elgi equipments"], "type": "stock"},
    {"ticker": "ISGEC.NS", "name": "ISGEC Heavy Engineering", "keywords": ["isgec", "isgec heavy"], "type": "stock"},
    {"ticker": "EIHOTEL.NS", "name": "EIH (Oberoi Hotels)", "keywords": ["eih", "oberoi hotels", "eihotel"], "type": "stock"},
    {"ticker": "INDHOTEL.NS", "name": "Indian Hotels (Taj)", "keywords": ["indian hotels", "taj hotels", "indhotel", "taj"], "type": "stock"},
    {"ticker": "LEMON.NS", "name": "Lemon Tree Hotels", "keywords": ["lemon tree", "lemon tree hotels"], "type": "stock"},
    {"ticker": "CHALET.NS", "name": "Chalet Hotels", "keywords": ["chalet", "chalet hotels"], "type": "stock"},

    # ===== LOGISTICS & TRANSPORT =====
    {"ticker": "CONCOR.NS", "name": "Container Corporation", "keywords": ["concor", "container corporation", "container corp"], "type": "stock"},
    {"ticker": "DELHIVERY.NS", "name": "Delhivery", "keywords": ["delhivery", "delhivery logistics"], "type": "stock"},
    {"ticker": "BLUEDART.NS", "name": "Blue Dart Express", "keywords": ["blue dart", "bluedart"], "type": "stock"},
    {"ticker": "ALLCARGO.NS", "name": "Allcargo Logistics", "keywords": ["allcargo", "allcargo logistics"], "type": "stock"},
    {"ticker": "TCI.NS", "name": "Transport Corporation of India", "keywords": ["tci", "transport corporation"], "type": "stock"},
    {"ticker": "VRL.NS", "name": "VRL Logistics", "keywords": ["vrl", "vrl logistics"], "type": "stock"},
    {"ticker": "MAHSEAMLES.NS", "name": "Maharashtra Seamless", "keywords": ["maharashtra seamless", "mahseamles"], "type": "stock"},

    # ===== DEFENCE (additional) =====
    {"ticker": "BHARATDYN.NS", "name": "Bharat Dynamics", "keywords": ["bharat dynamics", "bharatdyn", "bdl"], "type": "stock"},
    {"ticker": "MIDHANI.NS", "name": "Mishra Dhatu Nigam", "keywords": ["midhani", "mishra dhatu"], "type": "stock"},
    {"ticker": "SOLARINDS.NS", "name": "Solar Industries", "keywords": ["solar industries", "solarinds", "solar explosives"], "type": "stock"},
    {"ticker": "ZENTEC.NS", "name": "Zen Technologies", "keywords": ["zen technologies", "zentec", "zen tech defence"], "type": "stock"},

    # ===== HEALTHCARE (additional) =====
    {"ticker": "FORTIS.NS", "name": "Fortis Healthcare", "keywords": ["fortis", "fortis healthcare", "fortis hospital"], "type": "stock"},
    {"ticker": "MEDANTA.NS", "name": "Global Health (Medanta)", "keywords": ["medanta", "global health", "medanta hospital"], "type": "stock"},
    {"ticker": "YATHARTH.NS", "name": "Yatharth Hospital", "keywords": ["yatharth", "yatharth hospital"], "type": "stock"},
    {"ticker": "KIMS.NS", "name": "Krishna Institute of Medical Sciences", "keywords": ["kims", "kims hospital"], "type": "stock"},
    {"ticker": "NH.NS", "name": "Narayana Hrudayalaya", "keywords": ["narayana health", "nh", "narayana hrudayalaya"], "type": "stock"},
    {"ticker": "METROPOLIS.NS", "name": "Metropolis Healthcare", "keywords": ["metropolis", "metropolis healthcare", "metropolis lab"], "type": "stock"},
    {"ticker": "LALPATHLAB.NS", "name": "Dr Lal PathLabs", "keywords": ["lal pathlabs", "lalpathlab", "dr lal path"], "type": "stock"},
    {"ticker": "THYROCARE.NS", "name": "Thyrocare Technologies", "keywords": ["thyrocare", "thyrocare technologies"], "type": "stock"},

    # ===== INSURANCE (additional) =====
    {"ticker": "STARHEALTH.NS", "name": "Star Health Insurance", "keywords": ["star health", "starhealth", "star health insurance"], "type": "stock"},
    {"ticker": "NIACL.NS", "name": "New India Assurance", "keywords": ["new india assurance", "niacl", "nia"], "type": "stock"},

    # ===== POWER & UTILITIES (additional) =====
    {"ticker": "TATAPOWER.NS", "name": "Tata Power", "keywords": ["tata power", "tatapower"], "type": "stock"},
    {"ticker": "CESC.NS", "name": "CESC Limited", "keywords": ["cesc"], "type": "stock"},
    {"ticker": "JPPOWER.NS", "name": "Jaiprakash Power", "keywords": ["jp power", "jppower", "jaiprakash power"], "type": "stock"},

    # ===== CONSUMER DURABLES (additional) =====
    {"ticker": "TITAN.NS", "name": "Titan Company", "keywords": ["titan", "tanishq", "titan eye"], "type": "stock"},
    {"ticker": "RAJESHEXPO.NS", "name": "Rajesh Exports", "keywords": ["rajesh exports", "rajeshexpo"], "type": "stock"},
    {"ticker": "RELAXO.NS", "name": "Relaxo Footwears", "keywords": ["relaxo", "sparx"], "type": "stock"},
    {"ticker": "VGUARD.NS", "name": "V-Guard Industries", "keywords": ["v guard", "vguard", "v-guard"], "type": "stock"},
    {"ticker": "ORIENTELEC.NS", "name": "Orient Electric", "keywords": ["orient electric", "orientelec"], "type": "stock"},
    {"ticker": "TTKHLTCARE.NS", "name": "TTK Healthcare", "keywords": ["ttk healthcare", "ttkhltcare", "prestige kitchen"], "type": "stock"},
    {"ticker": "TTKPRESTIG.NS", "name": "TTK Prestige", "keywords": ["ttk prestige", "ttkprestig", "prestige cooker"], "type": "stock"},
    {"ticker": "BAJAJELEC.NS", "name": "Bajaj Electricals", "keywords": ["bajaj electricals", "bajajelec"], "type": "stock"},
    {"ticker": "SYMPHONY.NS", "name": "Symphony Limited", "keywords": ["symphony", "symphony cooler"], "type": "stock"},

    # ===== TEXTILE & APPAREL =====
    {"ticker": "RAYMOND.NS", "name": "Raymond Limited", "keywords": ["raymond", "raymond suits"], "type": "stock"},
    {"ticker": "ARVIND.NS", "name": "Arvind Limited", "keywords": ["arvind", "arvind limited"], "type": "stock"},
    {"ticker": "PGHL.NS", "name": "Procter & Gamble Health", "keywords": ["procter gamble", "pghl", "p&g health"], "type": "stock"},
    {"ticker": "PGHH.NS", "name": "Procter & Gamble Hygiene", "keywords": ["procter gamble hygiene", "pghh", "p&g"], "type": "stock"},
    {"ticker": "GILLETTE.NS", "name": "Gillette India", "keywords": ["gillette", "gillette india"], "type": "stock"},
    {"ticker": "MANYAVAR.NS", "name": "Vedant Fashions (Manyavar)", "keywords": ["manyavar", "vedant fashions", "mohey"], "type": "stock"},
    {"ticker": "GOCOLORS.NS", "name": "Go Fashion (Go Colors)", "keywords": ["go colors", "gocolors", "go fashion"], "type": "stock"},
    {"ticker": "CAMPUS.NS", "name": "Campus Activewear", "keywords": ["campus", "campus activewear", "campus shoes"], "type": "stock"},

    # ===== MISCELLANEOUS / NEW AGE =====
    {"ticker": "MAPMYINDIA.NS", "name": "C.E. Info Systems (MapmyIndia)", "keywords": ["mapmyindia", "map my india", "ce info"], "type": "stock"},
    {"ticker": "EASEMYTRIP.NS", "name": "Easy Trip Planners", "keywords": ["easemytrip", "easy trip", "ease my trip"], "type": "stock"},
    {"ticker": "IXIGO.NS", "name": "Le Travenues Technology (ixigo)", "keywords": ["ixigo", "le travenues"], "type": "stock"},
    {"ticker": "YATRA.NS", "name": "Yatra Online", "keywords": ["yatra", "yatra online"], "type": "stock"},
    {"ticker": "JUSTDIAL.NS", "name": "Just Dial", "keywords": ["just dial", "justdial"], "type": "stock"},
    {"ticker": "BSOFT.NS", "name": "Birlasoft", "keywords": ["birlasoft", "bsoft"], "type": "stock"},
    {"ticker": "ANGELONE.NS", "name": "Angel One", "keywords": ["angel one", "angelone", "angel broking"], "type": "stock"},
    {"ticker": "MOTILALOFS.NS", "name": "Motilal Oswal Financial", "keywords": ["motilal oswal", "motilalofs", "motilal"], "type": "stock"},
    {"ticker": "CDSL.NS", "name": "CDSL", "keywords": ["cdsl", "central depository"], "type": "stock"},
    {"ticker": "BSE.NS", "name": "BSE Limited", "keywords": ["bse", "bombay stock exchange"], "type": "stock"},
    {"ticker": "MCX.NS", "name": "Multi Commodity Exchange", "keywords": ["mcx", "multi commodity exchange"], "type": "stock"},
    {"ticker": "IEX.NS", "name": "Indian Energy Exchange", "keywords": ["iex", "indian energy exchange"], "type": "stock"},
    {"ticker": "CAMS.NS", "name": "Computer Age Management", "keywords": ["cams", "computer age"], "type": "stock"},
    {"ticker": "KFINTECH.NS", "name": "KFin Technologies", "keywords": ["kfintech", "kfin technologies"], "type": "stock"},
    {"ticker": "NSDL.NS", "name": "NSDL", "keywords": ["nsdl", "national securities depository"], "type": "stock"},

    # ===== AGRI & FERTILIZER =====
    {"ticker": "CHAMBLFERT.NS", "name": "Chambal Fertilisers", "keywords": ["chambal", "chambal fertilisers", "chamblfert"], "type": "stock"},
    {"ticker": "GNFC.NS", "name": "Gujarat Narmada Valley Fertilizers", "keywords": ["gnfc", "gujarat narmada"], "type": "stock"},
    {"ticker": "GSFC.NS", "name": "Gujarat State Fertilizers", "keywords": ["gsfc", "gujarat state fertilizers"], "type": "stock"},
    {"ticker": "RCF.NS", "name": "Rashtriya Chemicals and Fertilizers", "keywords": ["rcf", "rashtriya chemicals"], "type": "stock"},
    {"ticker": "NFL.NS", "name": "National Fertilizers", "keywords": ["nfl", "national fertilizers"], "type": "stock"},
    {"ticker": "GODREJAGRO.NS", "name": "Godrej Agrovet", "keywords": ["godrej agrovet", "godrejagro"], "type": "stock"},
    {"ticker": "DHANUKA.NS", "name": "Dhanuka Agritech", "keywords": ["dhanuka", "dhanuka agritech"], "type": "stock"},
    {"ticker": "BAYER.NS", "name": "Bayer CropScience", "keywords": ["bayer", "bayer cropscience"], "type": "stock"},
    {"ticker": "RALLIS.NS", "name": "Rallis India", "keywords": ["rallis", "rallis india"], "type": "stock"},

    # ===== PAPER & PACKAGING =====
    {"ticker": "JKPAPER.NS", "name": "JK Paper", "keywords": ["jk paper", "jkpaper"], "type": "stock"},
    {"ticker": "TNPL.NS", "name": "Tamil Nadu Newsprint", "keywords": ["tnpl", "tamil nadu newsprint"], "type": "stock"},
    {"ticker": "EPL.NS", "name": "EPL Limited", "keywords": ["epl", "epl limited", "essel propack"], "type": "stock"},
    {"ticker": "UFLEX.NS", "name": "Uflex Limited", "keywords": ["uflex", "uflex limited"], "type": "stock"},

    # ===== SUGAR =====
    {"ticker": "BALRAMCHIN.NS", "name": "Balrampur Chini Mills", "keywords": ["balrampur", "balramchin", "balrampur chini"], "type": "stock"},
    {"ticker": "RENUKA.NS", "name": "Shree Renuka Sugars", "keywords": ["renuka", "shree renuka"], "type": "stock"},
    {"ticker": "DWARIKESH.NS", "name": "Dwarikesh Sugar", "keywords": ["dwarikesh", "dwarikesh sugar"], "type": "stock"},
    {"ticker": "TRIVENI.NS", "name": "Triveni Engineering", "keywords": ["triveni", "triveni engineering", "triveni sugar"], "type": "stock"},

    # ===== EDUCATION =====
    {"ticker": "APARINDS.NS", "name": "Apar Industries", "keywords": ["apar", "apar industries"], "type": "stock"},
    {"ticker": "APLLTD.NS", "name": "Alembic Pharmaceuticals", "keywords": ["alembic", "aplltd", "alembic pharma"], "type": "stock"},

    # ===== PSU & GOVT COMPANIES =====
    {"ticker": "IRCON.NS", "name": "Ircon International", "keywords": ["ircon", "ircon international"], "type": "stock"},
    {"ticker": "HFCL.NS", "name": "HFCL Limited", "keywords": ["hfcl", "himachal futuristic"], "type": "stock"},
    {"ticker": "ITI.NS", "name": "ITI Limited", "keywords": ["iti", "iti limited"], "type": "stock"},
    {"ticker": "HINDCOPPER.NS", "name": "Hindustan Copper", "keywords": ["hindustan copper", "hindcopper", "hcl copper"], "type": "stock"},
    {"ticker": "BEL.NS", "name": "Bharat Electronics", "keywords": ["bel", "bharat electronics"], "type": "stock"},
    {"ticker": "FACT.NS", "name": "Fertilisers and Chemicals Travancore", "keywords": ["fact", "fact fertilizers"], "type": "stock"},
    {"ticker": "MMTC.NS", "name": "MMTC Limited", "keywords": ["mmtc", "mmtc limited"], "type": "stock"},
    {"ticker": "NBCC.NS", "name": "NBCC India", "keywords": ["nbcc", "nbcc india"], "type": "stock"},
    {"ticker": "NLC.NS", "name": "NLC India", "keywords": ["nlc", "nlc india", "neyveli lignite"], "type": "stock"},
    {"ticker": "NATIONALUM.NS", "name": "National Aluminium", "keywords": ["nalco", "national aluminium"], "type": "stock"},
    {"ticker": "SJVN.NS", "name": "SJVN Limited", "keywords": ["sjvn"], "type": "stock"},
    {"ticker": "NHPC.NS", "name": "NHPC Limited", "keywords": ["nhpc"], "type": "stock"},

    # ===== MISCELLANEOUS POPULAR SMALLCAPS =====
    {"ticker": "RPOWER.NS", "name": "Reliance Power", "keywords": ["reliance power", "rpower", "r power"], "type": "stock"},
    {"ticker": "ADANIWILMAR.NS", "name": "Adani Wilmar", "keywords": ["adani wilmar", "fortune oil", "adaniwilmar"], "type": "stock"},
    {"ticker": "TATACOM.NS", "name": "Tata Communications", "keywords": ["tata communications", "tatacom"], "type": "stock"},
    {"ticker": "SWANENERGY.NS", "name": "Swan Energy", "keywords": ["swan energy", "swanenergy"], "type": "stock"},
    {"ticker": "TIINDIA.NS", "name": "Tube Investments", "keywords": ["tube investments", "tiindia", "ti india"], "type": "stock"},
    {"ticker": "SUNDARMFIN.NS", "name": "Sundaram Finance", "keywords": ["sundaram finance", "sundarmfin"], "type": "stock"},
    {"ticker": "ABCAPITAL.NS", "name": "Aditya Birla Capital", "keywords": ["aditya birla capital", "abcapital", "ab capital"], "type": "stock"},
    {"ticker": "ABFRL.NS", "name": "Aditya Birla Fashion", "keywords": ["aditya birla fashion", "abfrl", "pantaloons", "louis philippe"], "type": "stock"},
    {"ticker": "JSWINFRA.NS", "name": "JSW Infrastructure", "keywords": ["jsw infra", "jswinfra", "jsw infrastructure"], "type": "stock"},
    {"ticker": "JIOFIN.NS", "name": "Jio Financial Services", "keywords": ["jio financial", "jiofin", "jio finance"], "type": "stock"},
    {"ticker": "PPLPHARMA.NS", "name": "Piramal Pharma", "keywords": ["piramal pharma", "pplpharma"], "type": "stock"},
    {"ticker": "GOLDIAM.NS", "name": "Goldiam International", "keywords": ["goldiam", "goldiam international"], "type": "stock"},
    {"ticker": "GMRAIRPORT.NS", "name": "GMR Airports", "keywords": ["gmr", "gmr airports", "gmrairport"], "type": "stock"},
    {"ticker": "KEI.NS", "name": "KEI Industries", "keywords": ["kei", "kei industries", "kei wires"], "type": "stock"},
    {"ticker": "FINOLEX.NS", "name": "Finolex Cables", "keywords": ["finolex", "finolex cables"], "type": "stock"},
    {"ticker": "FINPIPE.NS", "name": "Finolex Industries", "keywords": ["finolex industries", "finolex pipes"], "type": "stock"},
    {"ticker": "SHYAMMETL.NS", "name": "Shyam Metalics", "keywords": ["shyam metalics", "shyammetl"], "type": "stock"},
    {"ticker": "HAPPSTMNDS.NS", "name": "Happiest Minds Technologies", "keywords": ["happiest minds", "happstmnds"], "type": "stock"},
    {"ticker": "JBMA.NS", "name": "JBM Auto", "keywords": ["jbm auto", "jbma"], "type": "stock"},
    {"ticker": "DOMS.NS", "name": "DOMS Industries", "keywords": ["doms", "doms industries", "doms pen"], "type": "stock"},
    {"ticker": "CELLO.NS", "name": "Cello World", "keywords": ["cello", "cello world"], "type": "stock"},
    {"ticker": "SAPPHIRE.NS", "name": "Sapphire Foods", "keywords": ["sapphire", "sapphire foods"], "type": "stock"},
    {"ticker": "SWIGGY.NS", "name": "Swiggy", "keywords": ["swiggy", "swiggy ipo"], "type": "stock"},
    {"ticker": "FIRSTCRY.NS", "name": "Brainbees Solutions (FirstCry)", "keywords": ["firstcry", "brainbees", "first cry"], "type": "stock"},
    {"ticker": "ATHER.NS", "name": "Ather Energy", "keywords": ["ather", "ather energy", "ather scooter"], "type": "stock"},
    {"ticker": "AWFIS.NS", "name": "Awfis Space Solutions", "keywords": ["awfis", "awfis space"], "type": "stock"},
    {"ticker": "JYOTISTRUC.NS", "name": "Jyoti Structures", "keywords": ["jyoti structures", "jyotistruc"], "type": "stock"},
    {"ticker": "ELECTCAST.NS", "name": "Electrosteel Castings", "keywords": ["electrosteel", "electcast"], "type": "stock"},
    {"ticker": "GPPL.NS", "name": "Gujarat Pipavav Port", "keywords": ["gujarat pipavav", "gppl"], "type": "stock"},
    {"ticker": "REDINGTON.NS", "name": "Redington India", "keywords": ["redington", "redington india"], "type": "stock"},
    {"ticker": "DCMSHRIRAM.NS", "name": "DCM Shriram", "keywords": ["dcm shriram", "dcmshriram"], "type": "stock"},
    {"ticker": "PHOENIXLTD.NS", "name": "Phoenix Mills", "keywords": ["phoenix mills", "phoenix mall"], "type": "stock"},
    {"ticker": "CENTRALBK.NS", "name": "Central Bank of India", "keywords": ["central bank", "centralbk"], "type": "stock"},
    {"ticker": "NUVOCO.NS", "name": "Nuvoco Vistas", "keywords": ["nuvoco", "nuvoco vistas", "nuvoco cement"], "type": "stock"},
    {"ticker": "CHEMPLAST.NS", "name": "Chemplast Sanmar", "keywords": ["chemplast", "chemplast sanmar"], "type": "stock"},
    {"ticker": "TEGA.NS", "name": "Tega Industries", "keywords": ["tega", "tega industries"], "type": "stock"},
    {"ticker": "PNCINFRA.NS", "name": "PNC Infratech", "keywords": ["pnc infra", "pncinfra"], "type": "stock"},
    {"ticker": "GRINFRA.NS", "name": "G R Infraprojects", "keywords": ["gr infra", "grinfra", "g r infraprojects"], "type": "stock"},
    {"ticker": "HGS.NS", "name": "Hinduja Global Solutions", "keywords": ["hinduja global", "hgs"], "type": "stock"},
    {"ticker": "FIVESTAR.NS", "name": "Five Star Business Finance", "keywords": ["five star", "fivestar", "five star finance"], "type": "stock"},
    {"ticker": "CREDITACC.NS", "name": "CreditAccess Grameen", "keywords": ["creditaccess", "creditacc", "grameen"], "type": "stock"},
    {"ticker": "FUSION.NS", "name": "Fusion Micro Finance", "keywords": ["fusion micro", "fusion"], "type": "stock"},
]

# ---------------------------------------------------------------------------
# Top 30 Mutual Funds — Yahoo Finance tickers
# ---------------------------------------------------------------------------
MUTUAL_FUNDS: list[dict] = [
    # SBI Mutual Fund
    {"ticker": "0P0000XVAA.BO", "name": "SBI Bluechip Fund", "keywords": ["sbi bluechip", "sbi mutual fund", "sbi blue chip"], "type": "mf"},
    {"ticker": "0P0000XVAB.BO", "name": "SBI Small Cap Fund", "keywords": ["sbi small cap", "sbi smallcap fund"], "type": "mf"},
    {"ticker": "0P0000XVAC.BO", "name": "SBI Focused Equity Fund", "keywords": ["sbi focused", "sbi focused equity"], "type": "mf"},
    {"ticker": "0P0000XVAD.BO", "name": "SBI Equity Hybrid Fund", "keywords": ["sbi equity hybrid", "sbi hybrid fund"], "type": "mf"},

    # HDFC Mutual Fund
    {"ticker": "0P0000XVIA.BO", "name": "HDFC Mid-Cap Opportunities Fund", "keywords": ["hdfc midcap", "hdfc mid cap", "hdfc midcap fund"], "type": "mf"},
    {"ticker": "0P0000XVIB.BO", "name": "HDFC Flexi Cap Fund", "keywords": ["hdfc flexi cap", "hdfc flexicap", "hdfc flexi"], "type": "mf"},
    {"ticker": "0P0000XVIC.BO", "name": "HDFC Top 100 Fund", "keywords": ["hdfc top 100", "hdfc large cap", "hdfc top100"], "type": "mf"},
    {"ticker": "0P0000XVID.BO", "name": "HDFC Small Cap Fund", "keywords": ["hdfc small cap", "hdfc smallcap"], "type": "mf"},
    {"ticker": "0P0000XVIE.BO", "name": "HDFC Balanced Advantage Fund", "keywords": ["hdfc balanced advantage", "hdfc baf", "hdfc balanced"], "type": "mf"},

    # ICICI Prudential Mutual Fund
    {"ticker": "0P0000XW8A.BO", "name": "ICICI Prudential Bluechip Fund", "keywords": ["icici bluechip", "icici pru bluechip", "icici prudential bluechip"], "type": "mf"},
    {"ticker": "0P0000XW8B.BO", "name": "ICICI Prudential Value Discovery Fund", "keywords": ["icici value discovery", "icici pru value"], "type": "mf"},
    {"ticker": "0P0000XW8C.BO", "name": "ICICI Prudential Balanced Advantage Fund", "keywords": ["icici balanced advantage", "icici pru baf"], "type": "mf"},

    # Axis Mutual Fund
    {"ticker": "0P0000XWDA.BO", "name": "Axis Bluechip Fund", "keywords": ["axis bluechip", "axis blue chip", "axis mutual fund"], "type": "mf"},
    {"ticker": "0P0000XWDB.BO", "name": "Axis Midcap Fund", "keywords": ["axis midcap", "axis mid cap"], "type": "mf"},
    {"ticker": "0P0000XWDC.BO", "name": "Axis Small Cap Fund", "keywords": ["axis small cap", "axis smallcap"], "type": "mf"},

    # Kotak Mutual Fund
    {"ticker": "0P0000XVGA.BO", "name": "Kotak Emerging Equity Fund", "keywords": ["kotak emerging equity", "kotak midcap", "kotak emerging"], "type": "mf"},
    {"ticker": "0P0000XVGB.BO", "name": "Kotak Flexi Cap Fund", "keywords": ["kotak flexi cap", "kotak flexicap"], "type": "mf"},
    {"ticker": "0P0000XVGC.BO", "name": "Kotak Small Cap Fund", "keywords": ["kotak small cap", "kotak smallcap"], "type": "mf"},

    # Nippon India Mutual Fund
    {"ticker": "0P0000XV5A.BO", "name": "Nippon India Growth Fund", "keywords": ["nippon growth", "nippon india growth", "nippon midcap"], "type": "mf"},
    {"ticker": "0P0000XV5B.BO", "name": "Nippon India Small Cap Fund", "keywords": ["nippon small cap", "nippon india small cap", "nippon smallcap"], "type": "mf"},

    # Mirae Asset Mutual Fund
    {"ticker": "0P0000XW2A.BO", "name": "Mirae Asset Large Cap Fund", "keywords": ["mirae large cap", "mirae asset largecap", "mirae asset mutual fund"], "type": "mf"},
    {"ticker": "0P0000XW2B.BO", "name": "Mirae Asset Emerging Bluechip Fund", "keywords": ["mirae emerging bluechip", "mirae asset emerging"], "type": "mf"},

    # Parag Parikh Mutual Fund
    {"ticker": "0P0000XWKA.BO", "name": "Parag Parikh Flexi Cap Fund", "keywords": ["parag parikh", "ppfas", "parag parikh flexi cap", "ppfcf"], "type": "mf"},
    {"ticker": "0P0000XWKB.BO", "name": "Parag Parikh ELSS Tax Saver Fund", "keywords": ["parag parikh elss", "ppfas elss", "parag parikh tax saver"], "type": "mf"},

    # Motilal Oswal Mutual Fund
    {"ticker": "0P0000XWMA.BO", "name": "Motilal Oswal Midcap Fund", "keywords": ["motilal oswal midcap", "motilal midcap"], "type": "mf"},
    {"ticker": "0P0000XWMB.BO", "name": "Motilal Oswal Flexi Cap Fund", "keywords": ["motilal oswal flexi cap", "motilal flexicap"], "type": "mf"},

    # DSP Mutual Fund
    {"ticker": "0P0000XWPA.BO", "name": "DSP Midcap Fund", "keywords": ["dsp midcap", "dsp mid cap fund"], "type": "mf"},
    {"ticker": "0P0000XWPB.BO", "name": "DSP Small Cap Fund", "keywords": ["dsp small cap", "dsp smallcap"], "type": "mf"},

    # Tata Mutual Fund
    {"ticker": "0P0000XWRA.BO", "name": "Tata Digital India Fund", "keywords": ["tata digital india", "tata it fund", "tata digital"], "type": "mf"},

    # Quant Mutual Fund
    {"ticker": "0P0000XWSA.BO", "name": "Quant Small Cap Fund", "keywords": ["quant small cap", "quant smallcap", "quant mutual fund"], "type": "mf"},
    {"ticker": "0P0000XWSB.BO", "name": "Quant Active Fund", "keywords": ["quant active", "quant active fund"], "type": "mf"},
]

# ---------------------------------------------------------------------------
# Top 20 ETFs — NSE tickers
# ---------------------------------------------------------------------------
ETFS: list[dict] = [
    {"ticker": "NIFTYBEES.NS", "name": "Nippon India Nifty 50 BeES", "keywords": ["niftybees", "nifty etf", "nifty 50 etf", "nifty bees"], "type": "etf"},
    {"ticker": "BANKBEES.NS", "name": "Nippon India Bank BeES", "keywords": ["bankbees", "bank etf", "bank nifty etf", "bank bees"], "type": "etf"},
    {"ticker": "GOLDBEES.NS", "name": "Nippon India Gold BeES", "keywords": ["goldbees", "gold etf", "gold bees", "nippon gold"], "type": "etf"},
    {"ticker": "JUNIORBEES.NS", "name": "Nippon India Junior BeES (Nifty Next 50)", "keywords": ["juniorbees", "junior bees", "nifty next 50 etf"], "type": "etf"},
    {"ticker": "SILVERBEES.NS", "name": "Nippon India Silver BeES", "keywords": ["silverbees", "silver etf", "silver bees"], "type": "etf"},
    {"ticker": "ITBEES.NS", "name": "Nippon India IT BeES", "keywords": ["itbees", "it etf", "nifty it etf", "it bees"], "type": "etf"},
    {"ticker": "SETFNIF50.NS", "name": "SBI Nifty 50 ETF", "keywords": ["sbi nifty etf", "setfnif50", "sbi etf nifty 50"], "type": "etf"},
    {"ticker": "SETFNIFBK.NS", "name": "SBI Nifty Bank ETF", "keywords": ["sbi bank etf", "setfnifbk", "sbi bank nifty etf"], "type": "etf"},
    {"ticker": "HDFCNIFTY.NS", "name": "HDFC Nifty 50 ETF", "keywords": ["hdfc nifty etf", "hdfcnifty", "hdfc nifty 50"], "type": "etf"},
    {"ticker": "ICICINIFTY.NS", "name": "ICICI Prudential Nifty 50 ETF", "keywords": ["icici nifty etf", "icicinifty"], "type": "etf"},
    {"ticker": "KOTAKNIFTY.NS", "name": "Kotak Nifty 50 ETF", "keywords": ["kotak nifty etf", "kotaknifty"], "type": "etf"},
    {"ticker": "MOM50.NS", "name": "Motilal Oswal Nifty Midcap 50 ETF", "keywords": ["midcap etf", "mom50", "motilal midcap etf", "nifty midcap etf"], "type": "etf"},
    {"ticker": "LIQUIDBEES.NS", "name": "Nippon India Liquid BeES", "keywords": ["liquidbees", "liquid etf", "liquid bees"], "type": "etf"},
    {"ticker": "CPSEETF.NS", "name": "Nippon India CPSE ETF", "keywords": ["cpse etf", "cpseetf", "psu etf"], "type": "etf"},
    {"ticker": "PSUBNKBEES.NS", "name": "Nippon India PSU Bank BeES", "keywords": ["psu bank etf", "psubnkbees", "psu bank bees"], "type": "etf"},
    {"ticker": "INFRAETF.NS", "name": "Nippon India Infra BeES", "keywords": ["infra etf", "infraetf", "infrastructure etf"], "type": "etf"},
    {"ticker": "PHARMABEES.NS", "name": "Nippon India Pharma BeES", "keywords": ["pharma etf", "pharmabees", "pharma bees"], "type": "etf"},
    {"ticker": "MOM100.NS", "name": "Motilal Oswal Nifty Midcap 100 ETF", "keywords": ["midcap 100 etf", "mom100", "nifty midcap 100 etf"], "type": "etf"},
    {"ticker": "CONSUMETF.NS", "name": "Nippon India Consumption ETF", "keywords": ["consumption etf", "consumetf", "consumer etf"], "type": "etf"},
    {"ticker": "LOWVOL1.NS", "name": "ICICI Prudential Nifty Low Vol 30 ETF", "keywords": ["low volatility etf", "lowvol", "nifty low vol etf"], "type": "etf"},
]


# ---------------------------------------------------------------------------
# Unified search across stocks, mutual funds, and ETFs
# ---------------------------------------------------------------------------
# Pre-build a combined list once at import time
_ALL_INSTRUMENTS: list[dict] = INDIAN_STOCKS + MUTUAL_FUNDS + ETFS


def search_tickers(query: str, limit: int = 8) -> list[dict]:
    """Search Indian stocks, mutual funds, and ETFs by name, ticker, or keyword."""
    if not query or len(query) < 2:
        return []

    q = query.lower().strip()
    results: list[dict] = []

    for item in _ALL_INSTRUMENTS:
        score = 0
        ticker_clean = (
            item["ticker"]
            .replace(".NS", "")
            .replace(".BO", "")
            .lower()
        )
        name_lower = item["name"].lower()

        # Exact ticker match — highest priority
        if q == ticker_clean:
            score = 100
        # Ticker starts with query
        elif ticker_clean.startswith(q):
            score = 90
        # Keyword exact match
        elif any(q == kw for kw in item["keywords"]):
            score = 85
        # Name starts with query
        elif name_lower.startswith(q):
            score = 80
        # Keyword starts with query
        elif any(kw.startswith(q) for kw in item["keywords"]):
            score = 70
        # Name contains query
        elif q in name_lower:
            score = 60
        # Keyword contains query
        elif any(q in kw for kw in item["keywords"]):
            score = 50
        # Ticker contains query
        elif q in ticker_clean:
            score = 40

        if score > 0:
            results.append({**item, "_score": score})

    results.sort(key=lambda x: x["_score"], reverse=True)

    # De-duplicate by ticker (keep highest-scoring entry)
    seen: set[str] = set()
    unique: list[dict] = []
    for r in results:
        if r["ticker"] not in seen:
            seen.add(r["ticker"])
            unique.append(r)

    return [
        {"ticker": r["ticker"], "name": r["name"], "type": r["type"]}
        for r in unique[:limit]
    ]
