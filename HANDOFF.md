# Handoff

## What runs
`.github/workflows/refresh.yml`, daily 10:40 UTC. Six requests to mspb.gov, two seconds apart, honest User-Agent, stops on a 403 or 429. Merges into `decisions.parquet` on Hugging Face and uploads only when rows were added.

## What you need
- A GitHub repo (fork this one) and a Hugging Face dataset to write to. Change `REPO` in `src/refresh.py`.
- A repo secret `HF_TOKEN` with write access to that dataset. No LLM, no other key.
- The explorer site is a config in the `dataset-explorer` repo (`configs/mspb.json`), deployed to Cloudflare Pages by that repo's workflow. It reads the parquet from Hugging Face when the page loads, so it never needs a refresh.

## What breaks
- **The one manifest that carries new precedential decisions** is `precedential/PrecedentialDecisions_Manifest.json`. If MSPB stops updating it, nothing here notices: new precedential decisions just stop arriving. Check the newest precedential date on the site now and then.
- **MSPB changes the manifest layout or blocks the fetch.** The run fails (JSON check, minimum row counts, 403/429 stop) and GitHub emails you. Nothing is uploaded on a failed run.
- **The run would shrink the dataset.** It refuses to upload.

## What the data is not
No outcome, no posted date (the issue date is not when MSPB posted it), no full text. `order_kind` is a coarse guess from title fields. Two rows with impossible dates in the stale precedential manifest are left out.
