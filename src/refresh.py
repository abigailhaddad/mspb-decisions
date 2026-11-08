"""Fetch MSPB's decision manifests, merge them into the Hugging Face dataset, upload.

    python src/refresh.py            # fetch, merge, upload (needs HF_TOKEN)
    python src/refresh.py --dry-run  # fetch and merge, write out/decisions.parquet, no upload

The dataset only grows. Rows already published are kept even if MSPB drops them from its
manifests, and a run that would shrink the dataset or that fetched a suspiciously small
manifest stops without uploading.
"""
import argparse
import json
import os
import sys
import time
from datetime import date

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(__file__))
import mspb

BASE = "https://www.mspb.gov/decisions/"
UA = "abigailhaddad-research (github.com/abigailhaddad/mspb-decisions)"
REPO = "abigailhaddad/mspb-decisions"
FILE = "decisions.parquet"
LISTING = [
    "precedential/PrecedentialDecisions_Manifest.json",
    "precedential/PrecedentialDecisions_Manifest_updMar2025.json",
    "precedential/PrecedentialDecisions_Manifest_Table.json",
    "nonprecedential/NonPrecedentialDecisions_Manifest.json",
    "nonprecedential/NonPrecedentialDecisions_Manifest-updmar2025.json",
    "nonprecedential/NonPrecedentialDecisions_Manifest_Table.json",
]
# A manifest much smaller than this was truncated or replaced. Sizes on 2026-11-08: 10,799 and 108.
MIN_ROWS = {"nonprecedential/NonPrecedentialDecisions_Manifest.json": 9000,
            "precedential/PrecedentialDecisions_Manifest_updMar2025.json": 15000}


class Blocked(Exception):
    pass


def fetch(outdir, pause=2.0):
    os.makedirs(outdir, exist_ok=True)
    for name in LISTING:
        time.sleep(pause)
        r = requests.get(BASE + name, headers={"User-Agent": UA}, timeout=120)
        if r.status_code in (403, 429):
            raise Blocked(f"{r.status_code} on {name}")
        r.raise_for_status()
        doc = r.json()  # raises if an HTML page came back
        if "data" not in doc or doc.get("DOCUMENT_TYPE") not in mspb.TYPE_OF_DOCUMENT:
            raise ValueError(f"{name}: not a decision manifest")
        if len(doc["data"]) < MIN_ROWS.get(name, 1):
            raise ValueError(f"{name}: only {len(doc['data'])} rows")
        with open(os.path.join(outdir, name.replace("/", "_")), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)


def merge(old, new):
    """New rows win by id; rows only in old are kept. Returns (merged, added, kept_only_old)."""
    if old is None or old.empty:
        return new, len(new), 0
    newids = set(new["id"])
    kept = old[~old["id"].isin(newids)]
    added = len(newids - set(old["id"]))
    merged = pd.concat([new, kept], ignore_index=True).sort_values(["date", "id"], ascending=[False, True])
    return merged.reset_index(drop=True), added, len(kept)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--manifests", default="raw/manifests")
    args = ap.parse_args()

    fetch(args.manifests)
    records, report = mspb.load_snapshot_report(args.manifests)
    new = pd.DataFrame(records)
    try:
        old = pd.read_parquet(f"https://huggingface.co/datasets/{REPO}/resolve/main/{FILE}")
    except Exception as e:  # first run only
        print("no published file yet:", e)
        old = None
    merged, added, kept_old = merge(old, new)
    if old is not None and len(merged) < len(old):
        sys.exit(f"would shrink the dataset: {len(old)} -> {len(merged)}; not uploading")
    if merged["id"].duplicated().any():
        sys.exit("duplicate ids; not uploading")
    os.makedirs("out", exist_ok=True)
    merged.to_parquet(f"out/{FILE}", index=False)
    summary = {"as_of": date.today().isoformat(), "rows": len(merged), "added": added,
               "kept_only_in_old": kept_old, "excluded": report["excluded"],
               "newest": str(merged["date"].max())}
    json.dump(summary, open("out/summary.json", "w"), indent=1)
    print({k: v for k, v in summary.items() if k != "excluded"}, "excluded:", len(report["excluded"]))
    if args.dry_run or added == 0 and old is not None:
        print("nothing uploaded" if not args.dry_run else "dry run: nothing uploaded")
        return
    from huggingface_hub import HfApi
    a = HfApi()
    a.upload_file(path_or_fileobj=f"out/{FILE}", path_in_repo=FILE, repo_id=REPO, repo_type="dataset",
                  commit_message=f"Refresh {summary['as_of']}: +{added} decisions, newest {summary['newest']}")


if __name__ == "__main__":
    try:
        main()
    except Blocked as e:
        sys.exit(f"MSPB blocked the fetch ({e}); stopping")
