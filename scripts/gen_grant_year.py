"""
gen_grant_year.py — Generate patents_by_grant_year.csv
Run once after load_db.py completes.

Usage:
    python scripts/gen_grant_year.py
"""

import sqlite3
import pandas as pd
from pathlib import Path

BASE_DIR   = Path(__file__).resolve().parent.parent
DB_PATH    = BASE_DIR / "patents.db"
REPORT_DIR = BASE_DIR / "report"
OUT_PATH   = REPORT_DIR / "patents_by_grant_year.csv"

if not DB_PATH.exists():
    print(f"[ERROR] Database not found: {DB_PATH}")
    raise SystemExit(1)

REPORT_DIR.mkdir(exist_ok=True)

conn = sqlite3.connect(str(DB_PATH))
df = pd.read_sql_query(
    """
    SELECT patent_year      AS yr,
           COUNT(*)         AS patent_count
    FROM   patents
    WHERE  patent_year BETWEEN 1976 AND 2025
    GROUP  BY patent_year
    ORDER  BY patent_year ASC
    """,
    conn,
)
conn.close()

df.to_csv(OUT_PATH, index=False)
print(f"[OK] {OUT_PATH}  ({len(df)} rows)")