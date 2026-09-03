# Care Home Data Engineering Pipeline

An end-to-end Azure data engineering portfolio project using privacy-safe
synthetic care-home logs. Weekly CSV files move through Bronze, Silver and Gold
layers before the reporting tables are imported into Power BI.

## Architecture

```text
CSV in Azure Blob Storage
        ↓
Azure Data Factory Copy Data
        ↓
bronze.care_logs
        ↓
LoadBronzeToSilverLogEvent
        ↓
silver.log_event
        ↓
LoadSilverLogEventToSilverTables
        ↓
typed Silver tables
        ↓
LoadSilverTablesToGold
        ↓
Gold reporting tables → Power BI
```

ADF also records each file load through `audit.log_pipeline_run`. Validation
problems found during Bronze-to-Silver processing are stored in
`audit.data_exception`.

![Azure Data Factory pipeline](adf/adf_pipeline_overview.png)

## Repository structure

```text
care-logs-analytics-data-pipeline/
├── README.md
├── .gitignore
├── azure_functions/
│   ├── .funcignore
│   ├── function_app.py
│   ├── database.py
│   ├── silver_loader.py
│   ├── gold_loader.py
│   ├── requirements.txt
│   ├── host.json
│   └── local.settings.example.json
├── adf/
│   ├── README.md
│   ├── adf_pipeline_overview.png
│   └── pipeline1.reference.json
├── sql/
│   ├── ddl_statement/
│   │   ├── 01_bronze.sql
│   │   ├── 02_audit.sql
│   │   ├── 03_silver.sql
│   │   ├── 04_gold_dimensions.sql
│   │   └── 05_gold_facts.sql
│   └── validation/
│       └── layer_row_counts.sql
├── data/
│   ├── README.md
│   └── synthetic_data_sample.png
├── powerbi/
│   └── README.md
├── docs/
│   └── implementation-notes.md
└── tests/
    └── test_silver_loader.py
```

## Core Python files

- `function_app.py` exposes the three HTTP-triggered Azure Functions.
- `silver_loader.py` validates Bronze records, prevents duplicate source IDs,
  replaces same-file reloads transactionally and loads the typed Silver tables.
- `gold_loader.py` creates reporting-ready facts and aggregates using seven
  residents, appointment-event grain and source-file idempotency.
- `database.py` retrieves the audit run created by ADF before transformation.

## Bronze ingestion

There is no custom Python program for copying CSV rows into Bronze. The built-in
ADF Copy Data activity reads the Blob CSV and writes it to
`bronze.care_logs`. The reproducible activity settings and expressions are in
the `adf` folder.

## Azure Functions

| Function | HTTP route |
|---|---|
| `LoadBronzeToSilverLogEvent` | `load-bronze-to-silver-log-event` |
| `LoadSilverLogEventToSilverTables` | `load-silver-log-event-to-silver-tables` |
| `LoadSilverTablesToGold` | `load-silver-tables-to-gold` |

Each endpoint expects:

```json
{
  "source_file": "logs_2024-12-30_2025-01-05.csv"
}
```

## Database setup

For a new database, run the scripts in this order:

1. `sql/ddl_statement/01_bronze.sql`
2. `sql/ddl_statement/02_audit.sql`
3. `sql/ddl_statement/03_silver.sql`
4. `sql/ddl_statement/04_gold_dimensions.sql`
5. `sql/ddl_statement/05_gold_facts.sql`

The Gold loader seeds the date, resident, staff and log-type dimensions before
loading the reporting tables.

## Function configuration

Copy `azure_functions/local.settings.example.json` to `local.settings.json` for
local development and replace the placeholders. In Azure, store the same names
under Function App environment variables. Never commit SQL passwords,
connection strings, Function keys or `local.settings.json`.

Deploy from the `azure_functions` directory so `host.json`, `requirements.txt`
and `function_app.py` are at the Function project root.

## Tests

Run the Silver transformation tests from the repository root:

```bash
python -m unittest discover -s tests
```

The final modelling decisions are recorded in
[`docs/implementation-notes.md`](docs/implementation-notes.md).
