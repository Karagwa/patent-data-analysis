import pandas as pd
import sqlite3
import os
import zipfile
import sys
import time

pipeline_start = time.time() # For overall timing of the pipeline run



# ====================== CONFIG ======================
RAW_DIR        = "data/raw"
CLEAN_DIR      = "data/clean"
DB_PATH        = "patents.db"
SAMPLE_SIZE    = None       # None = full dataset

#  Strict date bounds matching the dataset specification
MIN_DATE = pd.Timestamp("1976-01-01")
MAX_DATE = pd.Timestamp("2025-09-30")
MIN_YEAR = MIN_DATE.year   # 1976
MAX_YEAR = MAX_DATE.year   # 2025

CPC_CHUNK_SIZE = 100_000
CPC_STAGE_DB   = os.path.join(CLEAN_DIR, "cpc_stage.db")

os.makedirs(CLEAN_DIR, exist_ok=True)


# Load data from TSV files
def resolve_data_file(base_name: str) -> str:
    """Return path to a .tsv source file, unzipping first if needed."""
    tsv_path = os.path.join(RAW_DIR, base_name)
    zip_path = tsv_path + ".zip"

    if os.path.exists(tsv_path):
        return tsv_path
    if os.path.exists(zip_path):
        print(f"  Unzipping {os.path.basename(zip_path)}...")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(RAW_DIR)
        if os.path.exists(tsv_path):
            return tsv_path
    raise FileNotFoundError(
        f"Required source file is missing. Expected: {tsv_path}"
    )


def parse_and_clamp_dates(series: pd.Series) -> pd.Series:
    """
    Parse a date column and enforce the dataset's valid range.

    """
    parsed = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce")

    # Some rows use non-standard separators or month/day ordering — retry those
    bad_mask = parsed.isna() & series.notna() & (series.str.strip() != "")
    if bad_mask.any():
        retry = pd.to_datetime(series[bad_mask], infer_datetime_format=True, errors="coerce")
        parsed = parsed.copy()
        parsed[bad_mask] = retry

    # THE FIX: null out every date outside the valid window 
    out_of_range = ~parsed.between(MIN_DATE, MAX_DATE, inclusive="both")
    parsed[out_of_range] = pd.NaT
    return parsed


# ====================== LOAD RAW DATA ======================
cpc_stage_ready = False
cpc_total_rows  = 0

try:
    print("\n=== LOADING PATENT DATA ===")

    # --- Core patents ---
    print("Loading patent core data...")
    patents = pd.read_csv(
        resolve_data_file("g_patent.tsv"),
        sep="\t",
        usecols=["patent_id", "patent_title", "patent_date",
                 "patent_type", "num_claims"],
        nrows=SAMPLE_SIZE,
        low_memory=False,
        dtype={"patent_id": "string", "patent_type": "string"},
    )
    print(f"  Patents: {len(patents):,} records")

    # --- Abstracts ---
    print("Loading abstracts...")
    abstracts = pd.read_csv(
        resolve_data_file("g_patent_abstract.tsv"),
        sep="\t",
        usecols=["patent_id", "patent_abstract"],
        nrows=SAMPLE_SIZE,
        low_memory=False,
        dtype={"patent_id": "string"},
    )
    print(f"  Abstracts: {len(abstracts):,} records")

    # --- Filing dates ---
    print("Loading filing dates...")
    applications = pd.read_csv(
        resolve_data_file("g_application.tsv"),
        sep="\t",
        usecols=["patent_id", "filing_date"],
        nrows=SAMPLE_SIZE,
        low_memory=False,
        dtype={"patent_id": "string"},
    )
    print(f"  Applications: {len(applications):,} records")

    # --- Inventors ---
    print("Loading inventors...")
    inv_nrows = None if SAMPLE_SIZE is None else SAMPLE_SIZE * 3
    inventors_raw = pd.read_csv(
        resolve_data_file("g_inventor_disambiguated.tsv"),
        sep="\t",
        usecols=["patent_id", "inventor_id",
                 "disambig_inventor_name_first",
                 "disambig_inventor_name_last",
                 "location_id"],
        nrows=inv_nrows,
        low_memory=False,
        dtype={"patent_id": "string", "inventor_id": "string"},
    )
    print(f"  Inventors: {len(inventors_raw):,} records")

    # --- Assignees ---
    print("Loading assignees (companies)...")
    ass_nrows = None if SAMPLE_SIZE is None else SAMPLE_SIZE * 2
    assignees_raw = pd.read_csv(
        resolve_data_file("g_assignee_disambiguated.tsv"),
        sep="\t",
        usecols=["patent_id", "assignee_id",
                 "disambig_assignee_organization",
                 "disambig_assignee_individual_name_first",
                 "disambig_assignee_individual_name_last"],
        nrows=ass_nrows,
        low_memory=False,
        dtype={"patent_id": "string", "assignee_id": "string"},
    )
    print(f"  Assignees: {len(assignees_raw):,} records")

    # --- Locations ---
    print("Loading locations...")
    locations = pd.read_csv(
        resolve_data_file("g_location_disambiguated.tsv"),
        sep="\t",
        usecols=["location_id", "disambig_country"],
        low_memory=False,
    )
    print(f"  Locations: {len(locations):,} records")

    # --- CPC classifications (chunked into staging DB) ---
    print("Loading classification data (chunked)...")
    valid_sections = {"A", "B", "C", "D", "E", "F", "G", "H", "Y"}
    cpc_conn = None
    try:
        cpc_conn = sqlite3.connect(CPC_STAGE_DB)
        cpc_conn.execute("PRAGMA journal_mode=WAL")
        cpc_conn.execute("PRAGMA synchronous=NORMAL")
        cpc_conn.execute("DROP TABLE IF EXISTS cpc_stage")
        cpc_conn.execute(
            """
            CREATE TABLE cpc_stage (
                patent_id   TEXT NOT NULL,
                cpc_section TEXT NOT NULL,
                PRIMARY KEY (patent_id, cpc_section)
            )
            """
        )
        cpc_conn.commit()

        cpc_iter = pd.read_csv(
            resolve_data_file("g_cpc_current.tsv"),
            sep="\t",
            usecols=["patent_id", "cpc_section"],
            chunksize=CPC_CHUNK_SIZE,
            dtype={"patent_id": "string", "cpc_section": "string"},
            on_bad_lines="skip",
            engine="python",
            low_memory=True,
        )

        for i, chunk in enumerate(cpc_iter, start=1):
            chunk = chunk.dropna(subset=["patent_id", "cpc_section"])
            chunk["patent_id"]   = chunk["patent_id"].str.strip()
            chunk["cpc_section"] = (
                chunk["cpc_section"].str.strip().str.upper().str[0]
            )
            chunk = chunk[chunk["cpc_section"].isin(valid_sections)]
            chunk = chunk[["patent_id", "cpc_section"]].drop_duplicates()

            rows = list(chunk.itertuples(index=False, name=None))
            if rows:
                cpc_conn.executemany(
                    "INSERT OR IGNORE INTO cpc_stage VALUES (?, ?)", rows
                )
            if i % 10 == 0:
                cpc_conn.commit()
                print(f"  CPC chunks processed: {i}")

        cpc_conn.commit()
        cpc_total_rows = cpc_conn.execute(
            "SELECT COUNT(*) FROM cpc_stage"
        ).fetchone()[0]
        cpc_stage_ready = cpc_total_rows > 0
        print(f"  [OK] CPC staged: {cpc_total_rows:,} unique patent-section rows")
    finally:
        if cpc_conn:
            cpc_conn.close()

except FileNotFoundError as e:
    print(f"\n[ERROR] {e}")
    print("Ensure required .tsv or .tsv.zip files are in data/raw/")
    sys.exit(1)
except Exception as e:
    print(f"\n[ERROR] Data loading failed: {e!r}")
    sys.exit(1)


# ====================== CLEAN & MERGE ======================
try:
    print("\n=== CLEANING DATA ===")

    # ── Patents ────────────────────────────────────────────────────────────────
    patents = patents.merge(applications, on="patent_id", how="left")
    patents = patents.merge(abstracts,    on="patent_id", how="left")
    patents.rename(
        columns={"patent_title": "title", "patent_abstract": "abstract"},
        inplace=True,
    )

    # Parse and strictly validate dates
    patents["filing_date_ts"] = parse_and_clamp_dates(patents["filing_date"])
    patents["patent_date_ts"] = parse_and_clamp_dates(patents["patent_date"])

    # Year columns derived solely from the already-validated Timestamps 
    # secondary range check required because NaT maps cleanly to pd.NA.
    patents["filing_year"] = patents["filing_date_ts"].dt.year.astype("Int64")
    patents["patent_year"] = patents["patent_date_ts"].dt.year.astype("Int64")

    # Canonical 'year' column = filing year (INTEGER in DB)
    patents["year"] = patents["filing_year"]

    # Grant lag only when both validated dates are present
    patents["grant_lag_days"] = (
        (patents["patent_date_ts"] - patents["filing_date_ts"]).dt.days
    ).astype("Int64")

    # Store dates as ISO text strings for the DB TEXT columns
    patents["filing_date"] = patents["filing_date_ts"].dt.strftime("%Y-%m-%d")
    patents["patent_date"] = patents["patent_date_ts"].dt.strftime("%Y-%m-%d")

    # num_claims: coerce to nullable integer, drop negatives
    patents["num_claims"] = pd.to_numeric(
        patents["num_claims"], errors="coerce"
    ).astype("Int64")
    patents.loc[patents["num_claims"] < 0, "num_claims"] = pd.NA

    # Drop records with no title
    patents = patents.dropna(subset=["title"]).drop_duplicates("patent_id")

    # Remove Timestamp helper columns (not needed beyond this point)
    patents.drop(columns=["filing_date_ts", "patent_date_ts"], inplace=True)

    # Diagnostic: how many patents have valid filing / grant dates?
    valid_filing = patents["filing_date"].notna().sum()
    valid_grant  = patents["patent_date"].notna().sum()
    print(
        f"  [OK] Patents cleaned: {len(patents):,} records  "
        f"| valid filing dates: {valid_filing:,}  "
        f"| valid grant dates: {valid_grant:,}"
    )

    #  Inventors
    inventors_raw["name"] = (
        inventors_raw["disambig_inventor_name_first"].fillna("") + " " +
        inventors_raw["disambig_inventor_name_last"].fillna("")
    ).str.strip()

    inventors_merged = inventors_raw.merge(locations, on="location_id", how="left")

    clean_inventors = (
        inventors_merged[["inventor_id", "name", "disambig_country"]]
        .drop_duplicates("inventor_id")
        .rename(columns={"disambig_country": "country"})
        .copy()
    )
    clean_inventors["country"] = clean_inventors["country"].fillna("Unknown")
    clean_inventors = clean_inventors[
        clean_inventors["name"].notna() & (clean_inventors["name"] != "")
    ]
    print(f"  [OK] Inventors cleaned: {len(clean_inventors):,} records")

    #  Assignees 
    assignees_raw = assignees_raw.copy()
    assignees_raw["individual_name"] = (
        assignees_raw["disambig_assignee_individual_name_first"].fillna("") + " " +
        assignees_raw["disambig_assignee_individual_name_last"].fillna("")
    ).str.strip()

    assignees_raw["assignee_name"] = assignees_raw[
        "disambig_assignee_organization"
    ].where(
        assignees_raw["disambig_assignee_organization"].notna(),
        other=assignees_raw["individual_name"],
    )

    assignees_raw["assignee_type"] = assignees_raw[
        "disambig_assignee_organization"
    ].apply(
        lambda x: "organisation"
        if pd.notna(x) and str(x).strip() != ""
        else "individual"
    )

    clean_companies = (
        assignees_raw[["assignee_id", "assignee_name", "assignee_type"]]
        .drop_duplicates("assignee_id")
        .rename(columns={"assignee_id": "company_id", "assignee_name": "name"})
        .copy()
    )
    clean_companies = clean_companies[
        clean_companies["name"].notna() & (clean_companies["name"] != "")
    ]
    print(f"  [OK] Assignees cleaned: {len(clean_companies):,} records")

    #  Relationship tables 
    patent_inventor = (
        inventors_raw[["patent_id", "inventor_id"]].drop_duplicates()
    )
    patent_company = (
        assignees_raw[["patent_id", "assignee_id"]]
        .rename(columns={"assignee_id": "company_id"})
        .drop_duplicates()
    )
    print(f"  [OK] Patent-inventor links: {len(patent_inventor):,}")
    print(f"  [OK] Patent-company links:  {len(patent_company):,}")

    if cpc_stage_ready:
        print(f"  [OK] CPC staged: {cpc_total_rows:,} records (ready to load)")

except Exception as e:
    import traceback
    print(f"\n[ERROR] Data cleaning failed: {e}")
    traceback.print_exc()
    sys.exit(1)


# ====================== SAVE CLEAN CSVs ======================
try:
    print("\n=== SAVING CLEAN DATA ===")

    patents[[
        "patent_id", "title", "abstract",
        "filing_date", "patent_date",
        "year", "filing_year", "patent_year",
        "patent_type", "num_claims", "grant_lag_days",
    ]].to_csv(f"{CLEAN_DIR}/clean_patents.csv", index=False)
    print(f"  [OK] {CLEAN_DIR}/clean_patents.csv")

    clean_inventors.to_csv(f"{CLEAN_DIR}/clean_inventors.csv", index=False)
    print(f"  [OK] {CLEAN_DIR}/clean_inventors.csv")

    clean_companies.to_csv(f"{CLEAN_DIR}/clean_companies.csv", index=False)
    print(f"  [OK] {CLEAN_DIR}/clean_companies.csv")

    patent_inventor.to_csv(f"{CLEAN_DIR}/patent_inventor.csv", index=False)
    print(f"  [OK] {CLEAN_DIR}/patent_inventor.csv")

    patent_company.to_csv(f"{CLEAN_DIR}/patent_company.csv", index=False)
    print(f"  [OK] {CLEAN_DIR}/patent_company.csv")

    if cpc_stage_ready:
        cpc_conn = sqlite3.connect(CPC_STAGE_DB)
        cpc_conn.execute("PRAGMA journal_mode=WAL")

        CPC_LABEL = {
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

        clean_cpc_path = f"{CLEAN_DIR}/clean_cpc.csv"
        first_chunk = True
        for chunk in pd.read_sql_query(
            "SELECT patent_id, cpc_section FROM cpc_stage ORDER BY patent_id, cpc_section",
            cpc_conn,
            chunksize=CPC_CHUNK_SIZE,
        ):
            chunk["cpc_section_name"] = chunk["cpc_section"].map(CPC_LABEL)
            chunk.to_csv(
                clean_cpc_path,
                index=False,
                mode="w" if first_chunk else "a",
                header=first_chunk,
            )
            first_chunk = False
        print(f"  [OK] {CLEAN_DIR}/clean_cpc.csv")

        cpc_agg_path = f"{CLEAN_DIR}/cpc_section_agg.csv"
        first_chunk = True
        for chunk in pd.read_sql_query(
            """
            SELECT
                patent_id,
                '[' || GROUP_CONCAT('"' || cpc_section || '"') || ']' AS cpc_sections
            FROM (
                SELECT patent_id, cpc_section
                FROM cpc_stage
                ORDER BY patent_id, cpc_section
            )
            GROUP BY patent_id
            ORDER BY patent_id
            """,
            cpc_conn,
            chunksize=CPC_CHUNK_SIZE,
        ):
            chunk.to_csv(
                cpc_agg_path,
                index=False,
                mode="w" if first_chunk else "a",
                header=first_chunk,
            )
            first_chunk = False
        print(f"  [OK] {CLEAN_DIR}/cpc_section_agg.csv")
        cpc_conn.close()

except Exception as e:
    print(f"\n[ERROR] Saving CSV files failed: {e}")
    sys.exit(1)

print(f"Total pipeline time: {time.time() - pipeline_start:.2f} seconds")

# Loading to the DB is done in a separate step (see load_db.py) to allow for more flexible error handling and faster iteration on the DB schema and queries without needing to re-run the entire pipeline.