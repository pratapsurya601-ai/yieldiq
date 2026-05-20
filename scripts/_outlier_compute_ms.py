"""Find which tickers/engines historically had slow cold computes."""
import os
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"].replace("postgres://", "postgresql://")
e = create_engine(url, pool_pre_ping=True)

with e.connect() as cn:
    rows = cn.execute(text("""
        SELECT
            ticker,
            cache_version,
            compute_ms,
            (payload->'valuation'->>'valuation_engine_used') AS engine,
            computed_at
        FROM analysis_cache
        WHERE compute_ms IS NOT NULL
        ORDER BY compute_ms DESC
        LIMIT 30
    """)).fetchall()

print(f"{'ticker':<14} {'v':<4} {'compute_ms':>11} {'engine':<32} {'computed_at':<22}")
print("-" * 90)
for r in rows:
    print(
        f"{r[0]:<14} "
        f"{(r[1] or '?'):<4} "
        f"{r[2]:>11} "
        f"{(r[3] or '?')[:32]:<32} "
        f"{str(r[4])[:22]:<22}"
    )

# Histogram by engine
print()
print("=== Aggregate by engine (last 1000 rows) ===")
agg = cn.execute(text("""
    SELECT
        (payload->'valuation'->>'valuation_engine_used') AS engine,
        COUNT(*) AS n,
        ROUND(AVG(compute_ms)::numeric, 0) AS avg_ms,
        ROUND(percentile_cont(0.50) WITHIN GROUP (ORDER BY compute_ms)::numeric, 0) AS p50_ms,
        ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY compute_ms)::numeric, 0) AS p95_ms,
        MAX(compute_ms) AS max_ms
    FROM (
        SELECT * FROM analysis_cache
        WHERE compute_ms IS NOT NULL
        ORDER BY computed_at DESC
        LIMIT 1000
    ) recent
    GROUP BY engine
    ORDER BY p95_ms DESC NULLS LAST
""")).fetchall()
print(f"{'engine':<32} {'n':>5} {'avg':>7} {'p50':>7} {'p95':>7} {'max':>8}")
for r in agg:
    print(
        f"{(r[0] or '?')[:32]:<32} "
        f"{r[1]:>5} "
        f"{r[2]:>7} "
        f"{r[3]:>7} "
        f"{r[4]:>7} "
        f"{r[5]:>8}"
    )
