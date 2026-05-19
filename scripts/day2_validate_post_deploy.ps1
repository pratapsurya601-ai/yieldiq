# Day 2/3 post-deploy validation
# ---------------------------------
# Run AFTER fix/hfc-canfinhome-reclassify + fix/gi-peer-split are
# merged and Railway has redeployed (~5-7 min). This:
#   1. Purges stale analysis_cache for the HFC + GI tickers
#   2. Triggers a fresh compute by hitting the public endpoint
#   3. Reads back the new FVs and compares to consensus targets
#
# Expected results (after deploy):
#   LICHSGFIN:  FV ~700-800  (consensus 630)
#   NIACL:      FV ~150-220  (consensus 170)
#   GICRE:      FV ~450-550  (consensus 480)
#   ICICIGI:    FV ~1900-2300 (consensus 2125)
#   PNBHOUSING: FV trend lower than pre-fix

$env:DATABASE_URL = [System.Environment]::GetEnvironmentVariable('DATABASE_URL', 'User')
if ($env:DATABASE_URL -notlike '*neon*') {
    Write-Error "DATABASE_URL doesn't look like Neon — abort"
    exit 1
}

$tickers = @(
    'LICHSGFIN.NS', 'LICHOUSFIN.NS', 'PNBHOUSING.NS', 'CANFINHOME.NS',
    'AAVAS.NS', 'HOMEFIRST.NS',
    'NIACL.NS', 'GICRE.NS', 'ICICIGI.NS', 'GODIGIT.NS',
    'STARHEALTH.NS', 'NIVABUPA.NS'
)

Write-Output "=== Step 1: Purge stale cache ==="
$inList = $tickers -join "','"
$sql = "DELETE FROM analysis_cache WHERE ticker IN ('$inList') RETURNING ticker;"
psql $env:DATABASE_URL -c $sql

Write-Output ""
Write-Output "=== Step 2: Trigger fresh computes (10-30s each) ==="
foreach ($t in $tickers) {
    $r = curl.exe -s --max-time 60 -o /dev/null -w "HTTP %{http_code} | %{time_total}s" "https://api.yieldiq.in/api/v1/public/stock-summary/$t"
    Write-Output "$t : $r"
}

Write-Output ""
Write-Output "=== Step 3: Read back new FVs ==="
$tickerList = $tickers -join "','"
$sql = "
SELECT
  ticker,
  (payload->'valuation'->>'fair_value')::numeric AS fv,
  payload->'valuation'->>'verdict' AS verdict,
  computed_at::time AS computed
FROM analysis_cache
WHERE ticker IN ('$tickerList')
ORDER BY computed_at DESC;"
psql $env:DATABASE_URL -c $sql

Write-Output ""
Write-Output "=== Step 4: Drift check vs consensus ==="
$sql = @"
WITH cache AS (
  SELECT
    REPLACE(REPLACE(ticker, '.NS', ''), '.BO', '') AS bare,
    (payload->'valuation'->>'fair_value')::numeric AS fv
  FROM analysis_cache
  WHERE ticker IN ('$tickerList')
),
cons AS (
  SELECT DISTINCT ON (ticker)
    ticker AS bare, target_mean, analyst_count
  FROM consensus_estimates
  ORDER BY ticker, fetched_at DESC
)
SELECT
  c.bare,
  c.fv AS model_fv,
  cs.target_mean AS consensus,
  cs.analyst_count AS analysts,
  ROUND(((c.fv - cs.target_mean) / cs.target_mean * 100)::numeric, 1) AS drift_pct
FROM cache c
JOIN cons cs ON c.bare = cs.bare
ORDER BY ABS(c.fv - cs.target_mean) / NULLIF(cs.target_mean, 0) DESC;
"@
psql $env:DATABASE_URL -c $sql
