# Patent Intelligence Data Pipeline

A full end-to-end data engineering and analytics project that transforms raw USPTO PatentsView data (9.4 million patents, 1976–2025) into a cleaned database, pre-computed reports, and an interactive Streamlit dashboard.

## Links

| Resource | URL |
|---|---|
| Live Dashboard | https://patent-data-analysis-ygnkndq4nssravke3h6dre.streamlit.app/ |
| GitHub | https://github.com/Karagwa/patent-data-analysis |
| Kaggle Clean Datasets (inventor, company, etc) | https://www.kaggle.com/datasets/karagwaanntreasure/clean-patent-data |
| clean_patents.csv | Uploading soon — 7 GB file |

---

## What It Does

1. **Cleans** raw USPTO PatentsView TSV files — validates dates, resolves assignees, disambiguates inventors
2. **Loads** normalized data into a SQLite database with full-text search (FTS5)
3. **Generates** pre-computed CSV and JSON reports so the dashboard never queries the DB on load
4. **Renders** an interactive Streamlit dashboard with 8 analysis pages

## Scale

| Metric | Value |
|---|---|
| Patents | 9,454,161 |
| Inventors (disambiguated) | 4,294,032 |
| Companies / Assignees | 572,495 |
| CPC patent-section rows | 12,942,157 |
| Year range | 1976 – 2025 |
| Database size | ~19 GB |
| Clean CSV total | ~9 GB |

---

## Project Layout

```
patent-data-processing-pipeline/
├── data/
│ ├── raw/ # Raw PatentsView TSV zip files (download separately)
│ └── clean/ # Cleaned CSV exports from pipeline.py
├── database/
│ ├── schema.sql # Table definitions, indexes, FTS5, views
│ └── queries.sql # All named SQL queries (Q1–Q7, E1–E5, A1–A6)
├── scripts/
│ ├── pipeline.py # ETL: cleans raw TSVs → clean CSVs
│ ├── load_db.py # Loads clean CSVs → patents.db
│ ├── reports.py # Runs queries → report/ CSVs and JSON
│ └── gen_grant_year.py # Quick standalone: generates patents_by_grant_year.csv
├── report/ # Pre-computed CSV and JSON outputs (read by dashboard)
├── dashboard/
│ └── app.py # Streamlit dashboard (8 pages)
├── patents.db # SQLite database (~19 GB, not in repo)
└── requirements.txt
```

---

## Setup

**Requirements:** Python 3.12+, Git, ~50 GB free disk space (raw + clean + database)

```bash
# Clone the repository
git clone https://github.com/Karagwa/patent-data-analysis.git
cd patent-data-analysis

# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\Activate.ps1

# macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

> **Windows PowerShell execution policy:** if activation fails, run:
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
> ```

---

## Raw Data

Download these files from [PatentsView](https://data.uspto.gov/bulkdata/datasets/pvgpatdis?fileDataFromDate=1976-01-01&fileDataToDate=2025-09-30) and place them in `data/raw/`:

| File | Required | Used for |
|---|---|---|
| `g_patent.tsv.zip` | Yes | Core patent metadata |
| `g_patent_abstract.tsv.zip` | Yes | Full-text search |
| `g_application.tsv.zip` | Yes | Filing dates, grant lag |
| `g_inventor_disambiguated.tsv.zip` | Yes | Inventor names and countries |
| `g_assignee_disambiguated.tsv.zip` | Yes | Companies and individual assignees |
| `g_location_disambiguated.tsv.zip` | Yes | Inventor country mapping |
| `g_cpc_current.tsv.zip` | Optional | Technology section analysis |

---

## Running the Pipeline

The pipeline has three stages. Run them in order.

### Stage 1 — Clean the raw data

```bash
python scripts/pipeline.py
```

Reads the raw TSV zips, validates and clamps dates to 1976–2025, resolves assignee names, and writes cleaned CSVs to `data/clean/`. Also stages CPC data into a temporary SQLite file.

**Output:** `data/clean/*.csv`

> To test with a smaller dataset first, set `SAMPLE_SIZE = 100_000` at the top of `pipeline.py`.

### Stage 2 — Load the database

```bash
python scripts/load_db.py
```

Reads the clean CSVs in 50k-row chunks, inserts into `patents.db` (schema from `database/schema.sql`), rebuilds all indexes, and populates the FTS5 full-text search index.

**Output:** `patents.db`

### Stage 3 — Generate reports

```bash
python scripts/reports.py
```

Runs all named SQL queries against `patents.db` and writes pre-computed CSVs and a JSON summary to `report/`. These files are what the dashboard reads — the dashboard does not query the database during normal use.

**Output:** `report/*.csv`, `report/patent_report.json`

> Reports take ~2–3 hours on the full dataset due to complex aggregations across 24M+ relationship rows.

### Optional — Generate the filing vs grant year chart data

If you don't want to wait for the full reports run:

```bash
python scripts/gen_grant_year.py
```

Runs a single fast query and writes `report/patents_by_grant_year.csv` in under a second. This powers the reporting lag visualization on the dashboard's Patent Trends page.

---

## Report Outputs

| File | Description |
|---|---|
| `patent_report.json` | Top-level summary (counts, top inventors/companies/countries) |
| `patents_per_year.csv` | Patent count by filing year |
| `patents_by_grant_year.csv` | Patent count by grant year (for lag visualization) |
| `top_inventors.csv` | Top 20 inventors by patent count |
| `top_companies.csv` | Top 20 companies by patent count |
| `top_countries.csv` | Top 30 countries by patent count |
| `top_inventor_rankings.csv` | Ranked inventor table |
| `country_trends.csv` | Patent counts by year × country |
| `countries_by_decade.csv` | Top 5 countries per decade |
| `cpc_section_distribution.csv` | Patent share by CPC section |
| `cpc_section_trends.csv` | CPC section counts by year |
| `top_companies_by_cpc.csv` | Top 5 companies per CPC section |
| `top_countries_by_cpc.csv` | Top 5 countries per CPC section |
| `recent_patents_by_cpc.csv` | 5 most recent patents per CPC section |
| `grant_lag_by_cpc.csv` | Avg days filing→grant by CPC section |
| `grant_lag_by_country.csv` | Avg days filing→grant by country |
| `grant_lag_trend.csv` | Avg grant lag by filing year |
| `claims_per_year.csv` | Avg patent claims by filing year |
| `claims_by_cpc.csv` | Avg claims by CPC section |

---

## Dashboard

```bash
streamlit run dashboard/app.py
```

Opens at `http://localhost:8501`. The dashboard has 8 pages:

| Page | What it shows |
|---|---|
| Overview | Key metrics, annual trend, CPC donut, top inventors/companies/countries |
| Patent Trends | Filing vs grant year lag chart, country comparison, decade view |
| Inventors & Companies | Ranked charts and tables with country filter |
| Country Analysis | Patent totals, grant lag by country, country × CPC breakdown |
| CPC Technology | Technology section distribution, trends, top companies/countries per section |
| Grant Duration Analytics | Avg prosecution time by CPC section, by country, and over time |
| Claims Analysis | Avg claim count by year and CPC; grant lag vs claims scatter |
| Patent Search | FTS5 full-text search across 9M+ patents with result export |

The dashboard is deployed at: https://patent-data-analysis-ygnkndq4nssravke3h6dre.streamlit.app/

> The live deployment runs from pre-computed CSVs only. Patent search is unavailable on the hosted version (requires the local database).

---

## Database

The SQLite database (`patents.db`) is not stored in the repository due to its 19 GB size. Build it locally using the pipeline steps above, or download the clean CSVs from Kaggle and run `load_db.py` directly.

### Schema overview

| Table | Rows | Description |
|---|---|---|
| `patents` | 9,454,161 | Core patent metadata including dates, claims, grant lag |
| `inventors` | 4,294,032 | Disambiguated inventor names and countries |
| `companies` | 572,495 | Assignee organisations and individuals |
| `patent_inventor` | 24,035,239 | Many-to-many: patents ↔ inventors |
| `patent_company` | 8,748,737 | Many-to-many: patents ↔ companies |
| `patent_cpc` | 12,942,157 | CPC technology section assignments |
| `cpc_section_agg` | — | Cached JSON array of sections per patent |
| `patents_fts` | — | FTS5 full-text index on title + abstract |


## Performance Notes

These timings are on the full 9.4M patent dataset:

| Stage | Time |
|---|---|
| `pipeline.py` — clean raw data | ~30–60 min |
| `load_db.py` — load database | ~2 hrs (7,269 s) |
| `reports.py` — generate all reports | ~2.4 hrs (8,656 s) |
| `gen_grant_year.py` — grant year CSV only | < 1 s |
| Dashboard cold start | < 2 s (CSV reads only) |

**RAM:** at peak the pipeline holds ~8–10 GB of DataFrames in memory. Close other applications before running on a machine with 16 GB RAM or less.

---

## Troubleshooting

**Database not found**
```bash
python scripts/load_db.py
```

**Missing raw files**
Confirm the `.zip` files are inside `data/raw/` with the exact filenames listed in the Raw Data table above.

**Streamlit not installed**
```bash
pip install -r requirements.txt
```

**Out of memory during pipeline**
Set `SAMPLE_SIZE = 500_000` in `pipeline.py` to process a subset, or close other applications and retry with the full dataset.

**Reports take too long**
Run `gen_grant_year.py` for the most important missing file, then deploy with whatever CSVs you have. The dashboard shows an info message for any missing file rather than crashing.

---

## Problems Faced

**Processing time**
The full dataset of 9.4 million patents is large enough that every stage of the pipeline takes significant time. Loading the database took ~2 hours, generating reports took ~2.4 hours, and the total wall-clock time from raw files to a working dashboard exceeded 7 hours. Queries that used `COUNT(DISTINCT patent_id)` across 24-million-row join tables initially ran for 200–800 seconds each and had to be rewritten to aggregate on bridge tables first before joining to dimension tables.

**Memory constraints**
At peak, the pipeline holds multiple large DataFrames in memory simultaneously that is patent core data, abstracts, filing dates, inventors, and assignees  which pushed RAM usage above 16 GB. This caused out-of-memory failures during development that required closing all other applications and restarting the pipeline from scratch.

**Data size and upload constraints**
The clean CSV exports total over 9 GB and the database is 19 GB, making it impossible to store in a GitHub repository. The Kaggle upload for the clean datasets consumed significant mobile data and time. The `clean_patents.csv` file alone is 7 GB and is still pending upload due to its size.

**Streamlit Community Cloud deployment**
The database is too large to include in the deployed app. The dashboard was restructured so that all analysis pages read from small pre-computed CSVs (totalling under 10 MB), leaving only the patent search feature dependent on the local database. This allowed the dashboard to be deployed on Streamlit Community Cloud while remaining fully functional for all chart and analytics pages.

---

## License

MIT License. See [LICENSE](LICENSE).