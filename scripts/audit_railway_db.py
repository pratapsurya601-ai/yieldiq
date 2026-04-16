"""
Audit Railway Postgres — show table sizes, row counts, and
recommend which tables can be safely dropped.

Usage:
    DATABASE_URL="postgresql://..." python scripts/audit_railway_db.py

Or via Railway CLI:
    railway run python scripts/audit_railway_db.py

Requires: sqlalchemy, psycopg2-binary
"""
import os, sys
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL", "")
if not url:
    print("ERROR: DATABASE_URL not set")
    print('Usage: DATABASE_URL="postgresql://..." python scripts/audit_railway_db.py')
    sys.exit(1)
if url.startswith("postgres://"):
    url = "postgresql://" + url[len("postgres://"):]

engine = create_engine(url)

# Tables with user data — NEVER drop
PROTECTED = {
    "users", "sessions", "auth", "payments", "subscriptions",
    "user_profiles", "user_settings", "referrals", "alerts",
    "watchlist", "portfolio", "holdings",
}

print("=" * 70)
print("RAILWAY POSTGRES AUDIT")
print("=" * 70)

with engine.connect() as conn:
    # Total DB size
    total = conn.execute(text(
        "SELECT pg_size_pretty(pg_database_size(current_database()))"
    )).scalar()
    print(f"\nTotal DB size: {total}\n")

    # Per-table breakdown
    rows = conn.execute(text("""
        SELECT
            t.tablename,
            pg_size_pretty(pg_total_relation_size('public.'||t.tablename)) AS size,
            pg_total_relation_size('public.'||t.tablename) AS raw_size
        FROM pg_tables t
        WHERE t.schemaname = 'public'
        ORDER BY raw_size DESC
    """)).fetchall()

    print(f"{'TABLE':<35} {'SIZE':>12} {'ROWS':>10} {'ACTION':>12}")
    print("-" * 70)

    droppable = []
    for tablename, size, raw_size in rows:
        try:
            count = conn.execute(text(
                f"SELECT COUNT(*) FROM \"{tablename}\""
            )).scalar()
        except Exception:
            count = "?"

        if tablename.lower() in PROTECTED:
            action = "PROTECTED"
        elif raw_size < 8192:
            action = "tiny"
        else:
            action = "review"

        print(f"{tablename:<35} {size:>12} {str(count):>10} {action:>12}")

        if action == "review":
            droppable.append(tablename)

    print("-" * 70)
    print(f"\nTables marked 'review' ({len(droppable)}):")
    for t in droppable:
        print(f"  - {t}")

    print(f"\nTables marked 'PROTECTED' (never drop):")
    for t in PROTECTED:
        print(f"  - {t}")

    print(f"""
NEXT STEPS:
1. Review the 'review' tables above
2. Tables that also exist in Aiven → safe to DROP
3. Tables with only old pipeline data → safe to DROP
4. Run cleanup with:
   DATABASE_URL="..." python scripts/cleanup_railway_db.py --tables "table1,table2"
""")
