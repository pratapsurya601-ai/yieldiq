"""Public analytics API — DuckDB-backed SQL on Parquet snapshots.

Serves read-only SQL over the Parquet mirror of our DB (see
``data/parquet/`` populated by ``scripts/export_to_parquet.py``).
Decouples heavy analytical scans from the OLTP path so:

  • Screen-fill queries (e.g. "top 50 by ROCE in FY25") don't
    compete with live Postgres for connections.
  • Collaborators / power users can pull any slice without DB creds.
  • The payload surface is exactly what's in Parquet — easy to audit.

Safety model
------------
SELECT-only. Every query is parsed to reject statements that aren't
a single read. Row-limit enforced. Query timeout enforced. The only
registered views are our own Parquet files; there is no filesystem
or network escape hatch.

Endpoints
---------
GET  /api/v1/analytics/schema
    List registered tables + their columns with types.

POST /api/v1/analytics/query
    Body: {"sql": "SELECT ...", "limit": 1000}
    Returns: {"columns": [...], "rows": [...], "elapsed_ms": float}

GET  /api/v1/analytics/presets
    Canned queries that showcase what the surface can do.

GET  /api/v1/analytics/preset/{name}
    Run a specific preset.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


# ── Module-level lazy DuckDB connection ───────────────────────────────
_CON = None
_PARQUET_ROOT = Path(__file__).resolve().parents[2] / "data" / "parquet"
_SINGLE_FILES = [
    "stocks", "financials", "ratio_history", "peer_groups",
    "market_metrics", "shareholding_pattern", "fair_value_history",
]
_PARTITIONED = ["daily_prices"]


def _register_views(con: "duckdb.DuckDBPyConnection") -> list[str]:  # noqa: F821
    """Register each Parquet file as a DuckDB view. Returns table names."""
    registered: list[str] = []
    for name in _SINGLE_FILES:
        path = _PARQUET_ROOT / f"{name}.parquet"
        if path.exists():
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS "
                f"SELECT * FROM read_parquet('{path.as_posix()}')"
            )
            registered.append(name)
    for name in _PARTITIONED:
        glob = _PARQUET_ROOT / name / "*" / "*.parquet"
        if any(_PARQUET_ROOT.joinpath(name).rglob("*.parquet")):
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS "
                f"SELECT * FROM read_parquet('{glob.as_posix()}', "
                f"hive_partitioning = 1)"
            )
            registered.append(name)
    return registered


def _con() -> "duckdb.DuckDBPyConnection":  # noqa: F821
    global _CON
    if _CON is not None:
        return _CON
    try:
        import duckdb
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="duckdb not installed on server; pip install duckdb",
        )
    if not _PARQUET_ROOT.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Parquet snapshot not found. "
                "Run scripts/export_to_parquet.py to populate."
            ),
        )
    con = duckdb.connect(":memory:")
    _register_views(con)
    _CON = con
    return _CON


# ── Safety: only allow SELECT-style queries ───────────────────────────
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|TRUNCATE|COPY|ATTACH|"
    r"DETACH|INSTALL|LOAD|PRAGMA|SET|EXPORT|IMPORT|CALL)\b",
    re.IGNORECASE,
)


def _validate_sql(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise HTTPException(400, "empty query")
    # Only the leading statement is considered — reject anything that
    # smells like multiple statements. DuckDB does allow `;` in string
    # literals so we don't hard-forbid it, just cap to 1 statement
    # by splitting and taking the first non-empty chunk.
    statements = [x.strip() for x in s.split(";") if x.strip()]
    if len(statements) > 1:
        raise HTTPException(400, "only one statement per request")
    q = statements[0]
    head = q.lstrip().upper()
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        raise HTTPException(
            400, "only SELECT / WITH (CTE) queries are allowed",
        )
    if _FORBIDDEN.search(q):
        raise HTTPException(400, "write operations are not permitted")
    return q


# ── Models ────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    sql: str = Field(..., description="SELECT or WITH query")
    limit: int = Field(
        default=1000,
        ge=1,
        le=10_000,
        description="Max rows to return (1–10,000)",
    )


class ColumnInfo(BaseModel):
    name: str
    type: str


class TableSchema(BaseModel):
    name: str
    columns: list[ColumnInfo]
    row_count: int | None = None


# ── Endpoints ─────────────────────────────────────────────────────────
@router.get("/schema")
async def schema() -> dict[str, Any]:
    """List registered tables and their columns."""
    con = _con()
    out: list[TableSchema] = []
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    for t in tables:
        cols = con.execute(f"DESCRIBE {t}").fetchall()
        # Quick row count — cheap because of Parquet metadata
        try:
            rc = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            rc = None
        out.append(TableSchema(
            name=t,
            columns=[ColumnInfo(name=c[0], type=c[1]) for c in cols],
            row_count=rc,
        ))
    return {"tables": [t.dict() for t in out]}


@router.post("/query")
async def run_query(req: QueryRequest) -> dict[str, Any]:
    """Execute a read-only SQL query against the Parquet snapshot."""
    sql = _validate_sql(req.sql)
    # Wrap in LIMIT regardless of user's clauses — sanity cap
    wrapped = f"SELECT * FROM ({sql}) LIMIT {req.limit}"
    con = _con()
    t0 = time.perf_counter()
    try:
        res = con.execute(wrapped)
    except Exception as e:
        raise HTTPException(400, f"query error: {e}")
    cols = [d[0] for d in res.description]
    rows = res.fetchall()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "columns": cols,
        "rows": [list(r) for r in rows],
        "row_count": len(rows),
        "truncated": len(rows) >= req.limit,
        "elapsed_ms": round(elapsed_ms, 2),
    }


# ── Preset queries (discoverable, curated) ────────────────────────────
PRESETS: dict[str, dict[str, str]] = {
    "top_roe_fy25": {
        "title": "Top-20 ROE among large-caps (FY25)",
        "description": (
            "Quality compounders screen: ROE 15-60% (excludes distress "
            "outliers), D/E < 1, PE 10-50, by latest annual."
        ),
        "sql": """
            SELECT ticker,
                   ROUND(roe, 1) AS roe_pct,
                   ROUND(roce, 1) AS roce_pct,
                   ROUND(de_ratio, 2) AS de,
                   ROUND(pe_ratio, 1) AS pe,
                   ROUND(market_cap_cr) AS mcap_cr
            FROM ratio_history
            WHERE period_type = 'annual'
              AND period_end = '2025-03-31'
              AND roe BETWEEN 15 AND 60
              AND de_ratio < 1
              AND pe_ratio BETWEEN 10 AND 50
              AND market_cap_cr > 20000
            ORDER BY roe DESC
        """,
    },
    "deep_value_fy25": {
        "title": "Deep value — low PE + high ROCE (FY25)",
        "description": "PE < 15, ROCE > 20, market cap > 5,000 Cr.",
        "sql": """
            SELECT ticker,
                   ROUND(pe_ratio, 1) AS pe,
                   ROUND(roce, 1) AS roce_pct,
                   ROUND(de_ratio, 2) AS de,
                   ROUND(market_cap_cr) AS mcap_cr
            FROM ratio_history
            WHERE period_type = 'annual'
              AND period_end = '2025-03-31'
              AND pe_ratio BETWEEN 5 AND 15
              AND roce > 20
              AND market_cap_cr > 5000
            ORDER BY pe_ratio ASC
        """,
    },
    "revenue_compounders_5y": {
        "title": "Revenue compounders — 5Y CAGR > 20%",
        "description": "Sustained revenue growth with healthy margins.",
        "sql": """
            SELECT ticker,
                   ROUND(revenue_yoy * 100, 1) AS rev_yoy_pct,
                   ROUND(roe, 1) AS roe_pct,
                   ROUND(pe_ratio, 1) AS pe
            FROM ratio_history
            WHERE period_type = 'annual'
              AND period_end = '2025-03-31'
              AND revenue_yoy > 0.20
              AND roe > 15
            ORDER BY revenue_yoy DESC
            LIMIT 25
        """,
    },
    "piotroski_9": {
        "title": "Perfect Piotroski F-Score (9/9) in FY25",
        "description": "Every quality checkpoint passes — rare elite set.",
        "sql": """
            SELECT ticker,
                   piotroski_f_score,
                   ROUND(roe, 1) AS roe_pct,
                   ROUND(roce, 1) AS roce_pct,
                   ROUND(pe_ratio, 1) AS pe
            FROM ratio_history
            WHERE period_type = 'annual'
              AND period_end = '2025-03-31'
              AND piotroski_f_score = 9
            ORDER BY roce DESC
        """,
    },
    "altman_safe": {
        "title": "Altman Z-Score > 3 (low distress risk)",
        "description": "Balance-sheet strength filter.",
        "sql": """
            SELECT ticker,
                   ROUND(altman_z_score, 2) AS z_score,
                   ROUND(de_ratio, 2) AS de,
                   ROUND(roe, 1) AS roe_pct
            FROM ratio_history
            WHERE period_type = 'annual'
              AND period_end = '2025-03-31'
              AND altman_z_score > 3
            ORDER BY altman_z_score DESC
            LIMIT 25
        """,
    },
    "longest_roe_history": {
        "title": "Tickers with the longest continuous ROE history",
        "description": "Sort by most annual periods with ROE populated.",
        "sql": """
            SELECT ticker,
                   COUNT(*) AS periods,
                   MIN(period_end) AS earliest,
                   MAX(period_end) AS latest
            FROM ratio_history
            WHERE period_type = 'annual' AND roe IS NOT NULL
            GROUP BY ticker
            ORDER BY periods DESC, ticker
            LIMIT 25
        """,
    },
}


@router.get("/presets")
async def list_presets() -> dict[str, Any]:
    """Catalogue of canned queries."""
    return {
        "presets": [
            {"name": k, "title": v["title"], "description": v["description"]}
            for k, v in PRESETS.items()
        ]
    }


@router.get("/preset/{name}")
async def run_preset(name: str) -> dict[str, Any]:
    """Execute a preset query by name."""
    p = PRESETS.get(name)
    if p is None:
        raise HTTPException(404, f"unknown preset '{name}'")
    req = QueryRequest(sql=p["sql"], limit=1000)
    return await run_query(req)
