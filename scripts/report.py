"""
reports.py
Generate patent intelligence reports from patents.db using queries.sql.

Usage:
    python reports.py            (from project root)
    python scripts/reports.py    (from any directory)

Outputs → report/
    Console          formatted summary to stdout
    *.csv            one file per result set
    patent_report.json
"""

import re
import sqlite3
import json
import time
import sys
from pathlib import Path

import pandas as pd

# ====================== PATHS ======================
BASE_DIR    = Path(__file__).resolve().parent.parent
DB_PATH     = BASE_DIR / "patents.db"
QUERIES_SQL = BASE_DIR / "database" / "queries.sql"
REPORTS_DIR = BASE_DIR / "report"
REPORTS_DIR.mkdir(exist_ok=True)

# ====================== CPC LABELS =====================
# Defined at module level so every section can use it safely.
CPC_NAMES = {
    "A": "Human Necessities",
    "B": "Operations & Transport",
    "C": "Chemistry & Metallurgy",
    "D": "Textiles & Paper",
    "E": "Fixed Constructions",
    "F": "Mechanical Engineering",
    "G": "Physics",
    "H": "Electricity",
    "Y": "Emerging Technologies",
}

# ====================== TIMER ======================
_t0_global = time.perf_counter()

def _elapsed() -> str:
    return f"+{time.perf_counter() - _t0_global:6.1f}s"

def _timed(label: str, fn):
    t = time.perf_counter()
    result = fn()
    print(f"    {label:<50} {time.perf_counter() - t:7.2f}s")
    return result


# ====================== VALUE HELPERS ======================
def _safe_int(v) -> int | None:
    """
    Coerce v to a plain Python int.

    Defensive against:
      - None / pd.NA              → return None
      - bytes  (BLOB int64 from an older DB load that passed numpy.int64
                directly to sqlite3 — stored as little-endian 8-byte blob)
                → unpack via struct
      - str    ("1976")           → int(v)
      - numpy / pandas scalars    → int(v)
    """
    if v is None:
        return None
    if isinstance(v, bytes):
        import struct
        raw = v.ljust(8, b"\x00")[:8]
        return struct.unpack("<q", raw)[0]
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _fmt_days(days) -> str:
    """'1,234 days (3.4 yrs)' — handles None and bytes safely."""
    v = _safe_int(days)
    if v is None:
        return "N/A"
    return f"{v:,} days  ({v / 365.25:.1f} yrs)"


# ====================== PRE-FLIGHT ======================
for _req in [DB_PATH, QUERIES_SQL]:
    if not _req.exists():
        _lbl = "Database" if _req == DB_PATH else "queries.sql"
        print(f"\n[ERROR] {_lbl} not found at {_req}")
        if _req == DB_PATH:
            print("Run the ETL pipeline first: python scripts/pipeline.py")
        sys.exit(1)

try:
    # No row_factory — we build dicts ourselves so row_factory adds overhead.
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-131072")   # 128 MB page cache
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=536870912")  # 512 MB mmap
    # PRAGMA optimize refreshes stale query-planner hints cheaply (<1 ms).
    # We deliberately do NOT run ANALYZE here — it rewrites histogram stats
    # for 9.4 M rows on every report run; it belongs only in load_db.py.
    conn.execute("PRAGMA optimize")
except Exception as e:
    print(f"\n[ERROR] Cannot connect to database: {e}")
    sys.exit(1)

try:
    for _tbl in ("patents", "inventors", "companies",
                 "patent_inventor", "patent_company"):
        conn.execute(f"SELECT 1 FROM {_tbl} LIMIT 1")
except sqlite3.OperationalError as e:
    print(f"\n[ERROR] Required table missing ({e}). Run the ETL pipeline first.")
    conn.close()
    sys.exit(1)

cpc_available: bool = conn.execute(
    "SELECT COUNT(*) FROM sqlite_master "
    "WHERE type='table' AND name='patent_cpc'"
).fetchone()[0] > 0


# ====================== QUERY LOADER ======================
def load_queries(sql_path: Path) -> dict[str, str]:
    """
    Parse queries.sql → {label: sql_string}.
    Recognises comment headers: -- Q1: ...  -- E2: ...  -- A3: ...
    """
    text   = sql_path.read_text(encoding="utf-8")
    header = re.compile(r"--\s+((?:Q|E|A)\d+):\s+(.+)")

    queries: dict[str, str] = {}
    current_key: str | None = None
    buffer: list[str]       = []

    for line in text.splitlines():
        m = header.match(line.strip())
        if m:
            if current_key and buffer:
                sql = "\n".join(buffer).strip().rstrip(";")
                if sql:
                    queries[current_key] = sql
            current_key = m.group(1)
            buffer      = []
        elif current_key is not None:
            buffer.append(line)

    if current_key and buffer:
        sql = "\n".join(buffer).strip().rstrip(";")
        if sql:
            queries[current_key] = sql

    return queries


# ====================== QUERY RUNNERS ======================
def run(label: str) -> list[dict]:
    """
    Execute a named query and return results as a list of dicts.

    Streams from the cursor directly — no fetchall().
    fetchall() would buffer all rows into a SQLite C-level list AND then
    into a Python list before we ever start processing.
    Iterating the cursor directly ('for row in cur') reads rows lazily,
    so only one row at a time is alive in Python while the list is built.
    For small result sets (≤ a few hundred rows) this is the right pattern.
    For large result sets use save_query_to_csv() to stream to disk.
    """
    sql = QUERIES.get(label)
    if not sql:
        print(f"  [WARN] Query '{label}' not found in queries.sql — skipping.")
        return []
    try:
        cur  = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur]   # ← iterate, never fetchall
    except Exception as e:
        print(f"  [ERROR] Query {label} failed: {e}")
        return []


def run_sql(sql: str) -> list[dict]:
    """Execute a raw SQL string and stream results into a list of dicts."""
    try:
        cur  = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur]   # ← same pattern
    except Exception as e:
        print(f"  [ERROR] Inline query failed: {e}")
        return []


def save_query_to_csv(sql: str, filename: str, batch: int = 20_000) -> int:
    """
    Stream a query's results directly to CSV in batches of `batch` rows.

    Never loads the full result set into Python RAM at once — each batch is
    written to disk and then discarded.  Use this for queries that return
    thousands of rows (year × country trends, full CPC trend timelines, etc.)

    Returns the total row count written.
    """
    path = REPORTS_DIR / filename
    try:
        t0   = time.perf_counter()
        cur  = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        total, first = 0, True
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            pd.DataFrame(rows, columns=cols).to_csv(
                path,
                mode   = "w" if first else "a",
                header = first,
                index  = False,
            )
            first   = False
            total  += len(rows)
        elapsed = time.perf_counter() - t0
        print(f"  [OK]  {filename:<50} {total:>9,} rows  ({elapsed:.1f}s)")
        return total
    except Exception as e:
        print(f"  [ERROR] Could not stream {filename}: {e}")
        return 0


def save_csv(data: list[dict], filename: str) -> None:
    """Write a pre-materialised list of dicts to CSV (for small result sets)."""
    if not data:
        print(f"  [SKIP] {filename} — no data")
        return
    path = REPORTS_DIR / filename
    try:
        pd.DataFrame(data).to_csv(path, index=False)
        print(f"  [OK]  {filename:<50} {len(data):>9,} rows")
    except Exception as e:
        print(f"  [ERROR] Could not save {filename}: {e}")


# ====================== LOAD ALL QUERIES ======================
QUERIES = load_queries(QUERIES_SQL)
print(f"\n[{_elapsed()}] Loaded {len(QUERIES)} queries: {', '.join(sorted(QUERIES))}")


# ====================== RUN ALL QUERIES ======================
print(f"\n[{_elapsed()}] Running queries...\n")

q1 = _timed("Q1  Top Inventors",                   lambda: run("Q1"))
q2 = _timed("Q2  Top Companies",                   lambda: run("Q2"))
q3 = _timed("Q3  Top Countries",                   lambda: run("Q3"))
q4 = _timed("Q4  Patents Per Year",                lambda: run("Q4"))
q5 = _timed("Q5  JOIN preview",                    lambda: run("Q5"))
q6 = _timed("Q6  CTE top countries/decade",        lambda: run("Q6"))

# Q7 = Q1 + ROW_NUMBER — derive in Python, zero extra DB cost.
q7 = [
    {
        "rank"        : i + 1,
        "inventor_id" : r["inventor_id"],
        "name"        : r["name"],
        "country"     : r.get("country"),
        "patent_count": r["patent_count"],
    }
    for i, r in enumerate(q1)
]
print(f"    {'Q7  Inventor Rankings (derived from Q1)':<50}    0.00s")

if cpc_available:
    e1 = _timed("E1  CPC Section Distribution",    lambda: run("E1"))
    e3 = _timed("E3  Top Companies / CPC",         lambda: run("E3"))
    e4 = _timed("E4  Top Countries / CPC",         lambda: run("E4"))
    a1 = _timed("A1  Grant Lag by CPC Section",    lambda: run("A1"))
    a5 = _timed("A5  Avg Claims by CPC Section",   lambda: run("A5"))
    # E2 and E5 are CSV-only (low console value, streamed directly to disk).
else:
    e1 = e3 = e4 = a1 = a5 = []
    print("  [INFO] patent_cpc table absent — CPC queries skipped.")

a2 = _timed("A2  Grant Lag by Country",            lambda: run("A2"))
a3 = _timed("A3  Avg Claims per Year",             lambda: run("A3"))
a4 = _timed("A4  Grant Lag Trend by Year",         lambda: run("A4"))

# top_country_share: 10 rows for JSON.
# Uses bridge-table-first aggregation to avoid COUNT(DISTINCT) on 24 M rows
# (the pattern that caused the original 459s runtime).
_SHARE_SQL = """
WITH country_patent AS (
    SELECT DISTINCT i.country, pi.patent_id
    FROM   patent_inventor pi
    JOIN   inventors       i  ON pi.inventor_id = i.inventor_id
    WHERE  i.country NOT IN ('Unknown', '')
),
total AS (SELECT COUNT(*) AS n FROM patents)
SELECT cp.country,
       COUNT(*)                        AS patents,
       ROUND(COUNT(*) * 1.0 / t.n, 4) AS share
FROM   country_patent cp
CROSS  JOIN total t
GROUP  BY cp.country
ORDER  BY patents DESC
LIMIT  10
"""
top_country_share = _timed(
    "Top countries + share (JSON)", lambda: run_sql(_SHARE_SQL)
)


# ====================== SUMMARY STATS ======================
_stats = conn.execute("""
    SELECT COUNT(*)   AS total_patents,
           MIN(year)  AS yr_min,
           MAX(year)  AS yr_max
    FROM   patents
    WHERE  year IS NOT NULL
""").fetchone()

total_patents   = _stats[0]
year_min        = _safe_int(_stats[1])
year_max        = _safe_int(_stats[2])
total_inventors = conn.execute("SELECT COUNT(*) FROM inventors").fetchone()[0]
total_companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]


# ====================== SECTION 1: CONSOLE REPORT ======================
SEP  = "=" * 60
SEP2 = "-" * 60

print(f"\n[{_elapsed()}]")
print(SEP)
print(" PATENT INTELLIGENCE REPORT")
print(SEP)
print(f"\n  Total Patents  : {total_patents:>12,}")
print(f"  Total Inventors: {total_inventors:>12,}")
print(f"  Total Companies: {total_companies:>12,}")
print(f"  Year Range     : {year_min} – {year_max}")

# ── Q1: Top Inventors ────────────────────────────────────────────────
print(f"\n{SEP2}")
print(" TOP INVENTORS  (Q1)")
print(SEP2)
for i, row in enumerate(q1[:10], 1):
    print(f"  {i:>2}. {row['name']}  ({row.get('country') or 'N/A'})  —  "
          f"{_safe_int(row['patent_count']):,} patents")

# ── Q2: Top Companies ────────────────────────────────────────────────
print(f"\n{SEP2}")
print(" TOP COMPANIES  (Q2)")
print(SEP2)
for i, row in enumerate(q2[:10], 1):
    print(f"  {i:>2}. {row['name']}  —  {_safe_int(row['patent_count']):,} patents")

# ── Q3: Top Countries ────────────────────────────────────────────────
print(f"\n{SEP2}")
print(" TOP COUNTRIES  (Q3)")
print(SEP2)
for i, row in enumerate(q3[:10], 1):
    print(f"  {i:>2}. {row['country']}  —  {_safe_int(row['patent_count']):,} patents")

# ── Q4: Patents Per Year (last 10 years) ────────────────────────────
print(f"\n{SEP2}")
print(" PATENTS PER YEAR — most recent 10 years  (Q4)")
print(SEP2)
if q4:
    for row in q4[-10:]:
        yr  = _safe_int(row["year"])
        cnt = _safe_int(row["patent_count"]) or 0
        bar = "█" * min(40, cnt // 10_000)
        print(f"  {yr}  {cnt:>9,}  {bar}")
else:
    print("  [no data — check that year column is stored as INTEGER]")

# ── Q5: JOIN preview ────────────────────────────────────────────────
print(f"\n{SEP2}")
print(f" JOIN PREVIEW — patents × inventors × companies  (Q5, {len(q5)} rows)")
print(SEP2)
for row in q5[:5]:
    yr = _safe_int(row["year"])
    print(f"  [{yr}] {str(row['patent_id']):<14}"
          f"  inv: {str(row.get('inventor_names') or '')[:28]:<28}"
          f"  co: {str(row.get('company_names') or '')[:22]}")

# ── Q6: Top countries by decade ──────────────────────────────────────
print(f"\n{SEP2}")
print(f" TOP COUNTRIES BY DECADE  (Q6, {len(q6)} rows)")
print(SEP2)
if q6:
    prev_decade = None
    for row in q6:
        dec = _safe_int(row["decade"])
        if dec != prev_decade:
            print(f"\n  {dec}s")
            prev_decade = dec
        print(f"    {str(row['country']):<6}  "
              f"{_safe_int(row['patents_per_decade']):>9,} patents")
else:
    print("  [no data]")

# ── Q7: Inventor Rankings ────────────────────────────────────────────
print(f"\n{SEP2}")
print(" INVENTOR RANKINGS  (Q7 — window function, derived from Q1)")
print(SEP2)
for row in q7[:10]:
    print(f"  #{row['rank']:>3}  {row['name']:<36}"
          f"  ({row.get('country') or 'N/A':<3})  "
          f"{_safe_int(row['patent_count']):,}")

# ── E1: CPC Distribution ─────────────────────────────────────────────
if e1:
    print(f"\n{SEP2}")
    print(" CPC SECTION DISTRIBUTION  (E1)")
    print(SEP2)
    for row in e1:
        sec  = row["cpc_section"]
        name = CPC_NAMES.get(sec, "")
        pct  = float(row.get("percentage") or 0)
        print(f"  {sec}  {name:<28}  "
              f"{_safe_int(row['patent_count']):>9,}  ({pct:.2f}%)")

# ── A1: Grant Lag by CPC ─────────────────────────────────────────────
if a1:
    print(f"\n{SEP2}")
    print(" GRANT LAG BY CPC SECTION  (A1)")
    print(SEP2)
    print(f"  {'Sec':<4} {'Patents':>9}  {'Avg Lag':>24}  {'Min d':>7}  {'Max d':>7}")
    for row in a1:
        print(f"  {row['cpc_section']:<4} "
              f"{_safe_int(row['patent_count']):>9,}  "
              f"{_fmt_days(row['avg_grant_lag_days']):>24}  "
              f"{_safe_int(row['min_lag_days']):>7,}  "
              f"{_safe_int(row['max_lag_days']):>7,}")

# ── A2: Grant Lag by Country ─────────────────────────────────────────
if a2:
    print(f"\n{SEP2}")
    print(" GRANT LAG BY COUNTRY — top 15  (A2)")
    print(SEP2)
    print(f"  {'Country':<6} {'Patents':>9}  {'Avg Lag':>24}")
    for row in a2[:15]:
        print(f"  {str(row['country']):<6} "
              f"{_safe_int(row['patent_count']):>9,}  "
              f"{_fmt_days(row['avg_grant_lag_days']):>24}")

# ── A3: Claims Per Year (last 10) ────────────────────────────────────
if a3:
    print(f"\n{SEP2}")
    print(" AVG CLAIMS PER YEAR — most recent 10 years  (A3)")
    print(SEP2)
    for row in a3[-10:]:
        yr  = _safe_int(row["year"])
        cnt = _safe_int(row["patent_count"]) or 0
        avg = float(row.get("avg_claims") or 0)
        print(f"  {yr}  avg {avg:>6.1f} claims  ({cnt:,} patents)")

# ── A5: Claims by CPC ────────────────────────────────────────────────
if a5:
    print(f"\n{SEP2}")
    print(" AVG CLAIMS BY CPC SECTION  (A5)")
    print(SEP2)
    for row in a5:
        sec  = row["cpc_section"]
        name = CPC_NAMES.get(sec, "")
        avg  = float(row.get("avg_claims") or 0)
        mx   = _safe_int(row["max_claims"]) or 0
        cnt  = _safe_int(row["patent_count"]) or 0
        print(f"  {sec}  {name:<28}  avg {avg:>6.1f}  "
              f"(max {mx:,}  |  {cnt:,} patents)")


# ====================== SECTION 2: CSV EXPORTS ======================
print(f"\n[{_elapsed()}]")
print(SEP2)
print(" CSV EXPORTS")
print(SEP2)

# Small result sets — already in memory, write directly.
save_csv(q1, "top_inventors.csv")
save_csv(q2, "top_companies.csv")
save_csv(q3, "top_countries.csv")
save_csv(q4, "patents_per_year.csv")
save_csv(q5, "patents_join_preview.csv")
save_csv(q6, "countries_by_decade.csv")
save_csv(q7, "top_inventor_rankings.csv")
if a2: save_csv(a2, "grant_lag_by_country.csv")
if a3: save_csv(a3, "claims_per_year.csv")
if a4: save_csv(a4, "grant_lag_trend.csv")

if cpc_available:
    if e1: save_csv(e1, "cpc_section_distribution.csv")
    if e3: save_csv(e3, "top_companies_by_cpc.csv")
    if e4: save_csv(e4, "top_countries_by_cpc.csv")
    if a1: save_csv(a1, "grant_lag_by_cpc.csv")
    if a5: save_csv(a5, "claims_by_cpc.csv")

# Large result sets — stream directly to CSV without loading into RAM.

# country_trends: year × country breakdown.
# Uses the same DISTINCT-CTE pattern as Q3 to avoid double-counting patents
# with inventors from the same country, and COUNT(DISTINCT) overhead.
_COUNTRY_TRENDS_SQL = """
WITH cp AS (
    SELECT DISTINCT p.year,
                    i.country,
                    p.patent_id
    FROM   patents         p
    JOIN   patent_inventor pi ON p.patent_id   = pi.patent_id
    JOIN   inventors       i  ON pi.inventor_id = i.inventor_id
    WHERE  i.country NOT IN ('Unknown', '')
      AND  p.year BETWEEN 1976 AND 2025
)
SELECT year,
       country,
       COUNT(*) AS patents
FROM   cp
GROUP  BY year, country
ORDER  BY year DESC, patents DESC
"""
save_query_to_csv(_COUNTRY_TRENDS_SQL, "country_trends.csv")

if cpc_available:
    _e2_sql = QUERIES.get("E2", "")
    if _e2_sql:
        save_query_to_csv(_e2_sql, "cpc_section_trends.csv")

    _e5_sql = QUERIES.get("E5", "")
    if _e5_sql:
        save_query_to_csv(_e5_sql, "recent_patents_by_cpc.csv")


# ====================== SECTION 3: JSON REPORT ======================
print(f"\n[{_elapsed()}]")
print(SEP2)
print(" JSON REPORT")
print(SEP2)

report = {
    # ── Required flat keys ────────────────────────────────────────────
    "total_patents"  : total_patents,
    "total_inventors": total_inventors,
    "total_companies": total_companies,
    "year_range"     : {"from": year_min, "to": year_max},

    "top_inventors": [
        {"name": r["name"], "patents": _safe_int(r["patent_count"]),
         "country": r.get("country")}
        for r in q1[:10]
    ],
    "top_companies": [
        {"name": r["name"], "patents": _safe_int(r["patent_count"]),
         "assignee_type": r.get("assignee_type")}
        for r in q2[:10]
    ],
    "top_countries": [
        {"country": r["country"],
         "patents": _safe_int(r["patents"]),
         "share"  : float(r["share"])}
        for r in top_country_share
    ],
    "patents_per_year": [
        {"year": _safe_int(r["year"]),
         "patent_count": _safe_int(r["patent_count"])}
        for r in q4
    ],
    "top_inventor_rankings": [
        {"rank": r["rank"], "name": r["name"],
         "country": r.get("country"),
         "patents": _safe_int(r["patent_count"])}
        for r in q7
    ],

    # ── CPC ───────────────────────────────────────────────────────────
    "cpc_section_distribution": [
        {"cpc_section": r["cpc_section"],
         "cpc_name"   : CPC_NAMES.get(r["cpc_section"], ""),
         "patents"    : _safe_int(r["patent_count"]),
         "percentage" : float(r.get("percentage") or 0)}
        for r in e1
    ],

    # ── Grant lag ─────────────────────────────────────────────────────
    "grant_lag_by_cpc": [
        {"cpc_section"       : r["cpc_section"],
         "cpc_name"          : CPC_NAMES.get(r["cpc_section"], ""),
         "patent_count"      : _safe_int(r["patent_count"]),
         "avg_grant_lag_days": _safe_int(r["avg_grant_lag_days"]),
         "avg_grant_lag_years": r.get("avg_grant_lag_years")}
        for r in a1
    ],
    "grant_lag_by_country": [
        {"country"           : r["country"],
         "patent_count"      : _safe_int(r["patent_count"]),
         "avg_grant_lag_days": _safe_int(r["avg_grant_lag_days"]),
         "avg_grant_lag_years": r.get("avg_grant_lag_years")}
        for r in a2[:20]
    ],

    # ── Claims ────────────────────────────────────────────────────────
    "claims_per_year": [
        {"year"         : _safe_int(r["year"]),
         "patent_count" : _safe_int(r["patent_count"]),
         "avg_claims"   : float(r.get("avg_claims") or 0)}
        for r in a3
    ],
    "claims_by_cpc": [
        {"cpc_section" : r["cpc_section"],
         "cpc_name"    : CPC_NAMES.get(r["cpc_section"], ""),
         "patent_count": _safe_int(r["patent_count"]),
         "avg_claims"  : float(r.get("avg_claims") or 0)}
        for r in a5
    ],
}

json_path = REPORTS_DIR / "patent_report.json"
try:
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  [OK]  patent_report.json")
except Exception as e:
    print(f"  [ERROR] Could not save patent_report.json: {e}")


# ====================== DONE ======================
conn.close()
total_time = time.perf_counter() - _t0_global
print(f"\n[{_elapsed()}]")
print(SEP)
print(f" ALL REPORTS GENERATED  ({total_time:.1f}s total)")
print(SEP)