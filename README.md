# Patent Intelligence Data Pipeline

This project turns raw PatentsView patent data into cleaned tables, summary reports, saved charts, and an interactive dashboard.
## Deployed Links

It is built as a simple end-to-end workflow:
- clean the raw TSV files
- store normalized data in SQLite
- generate CSV and JSON reports
- render static figures
- browse results in Streamlit

## What It Produces

- `patents.db` for the normalized database
- `data/clean/` for cleaned CSV exports
- `report/` for reusable CSV and JSON summaries
-
- `dashboard/app.py` for the interactive dashboard

## Project Layout

```
patent-data-processing-pipeline/
├── data/
│   ├── raw/        # Raw PatentsView TSV zip files
│   └── clean/      # Clean CSV outputs
├── database/       # schema.sql and queries.sql
├── scripts/        # pipeline, report, and data loading scripts
├── report/         # CSV and JSON summary outputs
├── dashboard/      # Streamlit dashboard
├── patents.db      # SQLite database
└── requirements.txt
```

## Setup

Requirements:
- Python 3.12 or later
- Git
- The PatentsView raw data files

Create a virtual environment and install dependencies:

```bash
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

On macOS or Linux:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Raw Data

Place these required files in `data/raw/`:

- `g_patent.tsv.zip`
- `g_patent_abstract.tsv.zip`
- `g_application.tsv.zip`
- `g_inventor_disambiguated.tsv.zip`
- `g_assignee_disambiguated.tsv.zip`
- `g_location_disambiguated.tsv.zip`

Optional for CPC analysis:

- `g_cpc_current.tsv.zip`

## Run the Pipeline

Generate cleaned data and the SQLite database:

```bash
python scripts/pipeline.py
```

This creates:
- `data/clean/*.csv`
- `patents.db`

If you want a smaller test run, edit `SAMPLE_SIZE` in `scripts/pipeline.py` first.

## Generate Reports

Create the report files in `report/`:

```bash
python scripts/report.py
```

Important outputs:
- `patent_report.json`
- `patents_per_year.csv`
- `top_inventors.csv`
- `top_companies.csv`
- `top_countries.csv`
- `country_trends.csv`
- `cpc_section_distribution.csv`
- `cpc_section_trends.csv`
- `top_companies_by_cpc.csv`
- `top_countries_by_cpc.csv`



## Open the Dashboard

Run:

```bash
streamlit run dashboard/app.py
```

The dashboard reads from the report files, so it does not need to query the SQLite database during normal use except for patent search.

It includes:
- total patent, inventor, and company counts
- year and country filters
- trend charts
- top inventor/company/country tables
- CPC analysis when CPC data exists

## Database Tables

Core tables:
- `patents`
- `inventors`
- `companies`
- `patent_inventor`
- `patent_company`

Optional CPC table:
- `patent_cpc`

## Working With the Data

Open the database directly if needed:

```bash
sqlite3 patents.db
```

Example queries:

```sql
SELECT COUNT(*) FROM patents;
SELECT name, COUNT(*) FROM inventors GROUP BY inventor_id LIMIT 5;
```

Or use Python:

```python
import sqlite3

conn = sqlite3.connect("patents.db")
cursor = conn.cursor()
cursor.execute("SELECT * FROM patents LIMIT 5")
print(cursor.fetchall())
```

## Troubleshooting

Database not found:

```bash
python scripts/pipeline.py
```

Missing raw files:
- confirm the `.zip` files are inside `data/raw/`

Streamlit missing:

```bash
pip install -r requirements.txt
```

Windows PowerShell activation issue:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
venv\Scripts\Activate.ps1
```

## Notes

- `report/` holds the summary files the dashboard uses.
- `report/figures/` holds the pre-rendered charts.
- CPC analysis appears only when `g_cpc_current.tsv.zip` is available and processed.

## License

MIT License. See [LICENSE](LICENSE).
