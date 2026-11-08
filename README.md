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
