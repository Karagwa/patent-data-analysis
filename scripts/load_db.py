"""
load_db.py — Load clean CSVs into patents.db
"""

import pandas as pd
import sqlite3
import os
import sys
import time
import numpy as np

# ====================== CONFIG ======================

CLEAN_DIR = "data/clean"
DB_PATH = "patents.db"

CHUNK = 50_000

CSV_TABLE_MAP = [
    {
        "file": f"{CLEAN_DIR}/clean_patents.csv",
        "table": "patents",
        "columns": [
            "patent_id",
            "title",
            "abstract",
            "filing_date",
            "patent_date",
            "year",
            "patent_year",
            "patent_type",
            "num_claims",
            "grant_lag_days",
        ],
        "dtype": {
            "patent_id": str,
            "title": str,
            "abstract": str,
            "filing_date": str,
            "patent_date": str,
            "year": object,
            "patent_year": object,
            "patent_type": str,
            "num_claims": object,
            "grant_lag_days": object,
        },
    },

    {
        "file": f"{CLEAN_DIR}/clean_inventors.csv",
        "table": "inventors",
        "columns": ["inventor_id", "name", "country"],
        "dtype": {
            "inventor_id": str,
            "name": str,
            "country": str,
        },
    },

    {
        "file": f"{CLEAN_DIR}/clean_companies.csv",
        "table": "companies",
        "columns": ["company_id", "name", "assignee_type"],
        "dtype": {
            "company_id": str,
            "name": str,
            "assignee_type": str,
        },
    },

    {
        "file": f"{CLEAN_DIR}/patent_inventor.csv",
        "table": "patent_inventor",
        "columns": ["patent_id", "inventor_id"],
        "dtype": {
            "patent_id": str,
            "inventor_id": str,
        },
    },

    {
        "file": f"{CLEAN_DIR}/patent_company.csv",
        "table": "patent_company",
        "columns": ["patent_id", "company_id"],
        "dtype": {
            "patent_id": str,
            "company_id": str,
        },
    },
]

CPC_CSV = f"{CLEAN_DIR}/clean_cpc.csv"
CPC_AGG_CSV = f"{CLEAN_DIR}/cpc_section_agg.csv"


# ====================== HELPERS ======================

def check_csvs_exist():
    missing = []

    for entry in CSV_TABLE_MAP:
        if not os.path.exists(entry["file"]):
            missing.append(entry["file"])

    for path in (CPC_CSV, CPC_AGG_CSV):
        if not os.path.exists(path):
            missing.append(path)

    if missing:
        print("\n[ERROR] Missing CSV files:")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)


def convert_value(v):
    """
    Convert pandas/numpy values into native Python types
    so SQLite stores proper INTEGER/REAL/TEXT values.
    """

    if pd.isna(v):
        return None

    # numpy integer -> Python int
    if isinstance(v, np.integer):
        return int(v)

    # numpy float -> Python float
    if isinstance(v, np.floating):
        return float(v)

    # pandas timestamp -> ISO string
    if isinstance(v, pd.Timestamp):
        return v.isoformat()

    return v


def row_generator(chunk, columns):
    """
    Yield rows as tuples of native Python types.
    """

    chunk = chunk[columns]

    for row in chunk.itertuples(index=False, name=None):
        yield tuple(convert_value(v) for v in row)


def load_csv_chunked(conn, file_path, table_name, columns, dtype):

    placeholders = ", ".join(["?"] * len(columns))
    col_names = ", ".join(columns)

    sql = f"""
    INSERT OR IGNORE INTO {table_name}
    ({col_names})
    VALUES ({placeholders})
    """

    total = 0

    for chunk in pd.read_csv(
        file_path,
        usecols=columns,
        dtype=dtype,
        chunksize=CHUNK,
        low_memory=False,
    ):

        conn.executemany(
            sql,
            row_generator(chunk, columns)
        )

        total += len(chunk)

    return total


# ====================== MAIN ======================

def main():

    start = time.time()

    print("\n=== PRE-FLIGHT CHECK ===")
    check_csvs_exist()
    print("  [OK] CSVs found")

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"  [OK] Removed old DB")

    conn = None

    try:

        print("\n=== CREATING DATABASE ===")

        conn = sqlite3.connect(DB_PATH)

        # SQLite performance tuning
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-131072")
        conn.execute("PRAGMA mmap_size=536870912")

        schema_path = "database/schema.sql"

        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

        print("  [OK] Schema created")

        # Drop indexes temporarily
        idx_rows = conn.execute("""
            SELECT name, sql
            FROM sqlite_master
            WHERE type='index'
            AND sql IS NOT NULL
        """).fetchall()

        create_stmts = [r[1] + ";" for r in idx_rows]

        for name, _ in idx_rows:
            conn.execute(f"DROP INDEX IF EXISTS {name}")

        conn.commit()

        print(f"  [OK] Dropped {len(idx_rows)} indexes")

        # ================= LOAD TABLES =================

        print("\n=== LOADING TABLES ===")

        for entry in CSV_TABLE_MAP:

            t0 = time.time()

            rows = load_csv_chunked(
                conn,
                entry["file"],
                entry["table"],
                entry["columns"],
                entry["dtype"],
            )

            conn.commit()

            print(
                f"  [OK] {entry['table']:20s}"
                f"{rows:>12,} rows"
                f"   ({time.time()-t0:.1f}s)"
            )

        # ================= CPC =================

        if os.path.exists(CPC_CSV):

            t0 = time.time()

            sql = """
            INSERT OR IGNORE INTO patent_cpc
            (
                patent_id,
                cpc_section,
                cpc_class,
                cpc_subclass,
                cpc_group,
                cpc_type
            )
            VALUES (?, ?, NULL, NULL, NULL, NULL)
            """

            total = 0

            for chunk in pd.read_csv(
                CPC_CSV,
                usecols=["patent_id", "cpc_section"],
                dtype={
                    "patent_id": str,
                    "cpc_section": str,
                },
                chunksize=CHUNK,
                low_memory=False,
            ):

                conn.executemany(
                    sql,
                    chunk[
                        ["patent_id", "cpc_section"]
                    ].itertuples(index=False, name=None)
                )

                total += len(chunk)

            conn.commit()

            print(
                f"  [OK] patent_cpc"
                f"{total:>18,} rows"
                f"   ({time.time()-t0:.1f}s)"
            )

        # ================= REBUILD INDEXES =================

        print("\n=== REBUILDING INDEXES ===")

        t0 = time.time()

        for stmt in create_stmts:
            conn.execute(stmt)

        conn.commit()

        print(f"  [OK] Index rebuild complete ({time.time()-t0:.1f}s)")

        # ================= FTS =================

        print("\n=== BUILDING FTS5 ===")

        t0 = time.time()

        conn.execute(
            "INSERT INTO patents_fts(patents_fts) VALUES('rebuild')"
        )

        conn.commit()

        print(f"  [OK] FTS5 built ({time.time()-t0:.1f}s)")

        # ================= VALIDATION =================

        print("\n=== VALIDATION ===")

        result = conn.execute("""
            SELECT
                MIN(year),
                MAX(year),
                typeof(MIN(year)),
                typeof(MAX(year))
            FROM patents
        """).fetchone()

        print("\nYear Validation:")
        print(result)

        print("\nDatabase created successfully.")

    except Exception as e:

        import traceback

        print(f"\n[ERROR] {e}")
        traceback.print_exc()

    finally:

        if conn:
            conn.close()

    print(f"\n=== COMPLETE ({time.time()-start:.1f}s) ===")


if __name__ == "__main__":
    main()