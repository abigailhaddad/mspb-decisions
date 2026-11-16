# mspb-decisions

A copy of the decision listing the Merit Systems Protection Board publishes, as one table on Hugging Face: https://huggingface.co/datasets/abigailhaddad/mspb-decisions. Not affiliated with MSPB.

It reads the JSON manifests behind https://www.mspb.gov/decisions/ (dates, docket, appellant, agency, order title, PDF link). The manifests have no outcome and no posted date, so the table can't say who won. Browse it at the explorer site (see HANDOFF.md).

A GitHub Action runs every day, adds new decisions, and uploads only if something was added. The dataset never shrinks: a decision MSPB drops from its manifests stays.

## Run it

    pip install -r requirements-dev.txt
    python -m pytest tests
    python src/refresh.py --dry-run     # fetch and merge, write out/decisions.parquet, upload nothing
    HF_TOKEN=... python src/refresh.py  # the real thing

`src/mspb.py` turns the manifests into rows. Several MSPB manifests stopped updating in September 2026, so the current listing manifests are read first and the stale ones are unioned in by file name.

## Data dictionary

[`docs/data_dictionary.md`](docs/data_dictionary.md) lists every column of the table with its type, a description, the share of rows that have a value, and an example. Types, counts and examples are read from the published parquet files; descriptions are in [`docs/tables.toml`](docs/tables.toml), written from the code that builds each column. Regenerate it with

    python src/data_docs.py fetch data   # download the current files from Hugging Face
    python src/data_docs.py write data   # write docs/data_dictionary.md

`src/refresh.py` puts the same section on the Hugging Face dataset card. Both stop with an error if a parquet column has no description in `docs/tables.toml` or a described column is gone, and the daily workflow runs that check too.

## SQLite download

The daily workflow builds `mspb-decisions.sqlite` from the files on Hugging Face (table `decisions`, plus `_source`, which records the Hugging Face commit) and attaches it to the GitHub release [`latest-data`](https://github.com/abigailhaddad/mspb-decisions/releases/tag/latest-data). The release is replaced whenever the Hugging Face commit changes. To build it yourself:

    python src/build_sqlite.py data mspb-decisions.sqlite
