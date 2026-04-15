import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from this module's directory, not cwd — so cd-from-repo-root works.
_ENV_PATH = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=_ENV_PATH, override=False)
# Fallback: also try repo-root .env for any non-DB keys.
load_dotenv(override=False)

DATABASE_URL = os.getenv('DATABASE_URL')
YFINANCE_DELAY = 2        # seconds between tickers
NSE_DELAY = 3             # seconds between NSE calls
RUPEES_TO_CRORES = 1e7    # divide raw yfinance values
LOOKBACK_YEARS = 5        # fetch 5 years history
RAW_DATA_DIR = 'data_pipeline/xbrl/raw_cache'
os.makedirs(RAW_DATA_DIR, exist_ok=True)
