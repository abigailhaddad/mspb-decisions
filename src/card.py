"""The Hugging Face dataset card, with every count computed from the table being uploaded.

The card used to be uploaded by hand once (2026-11-08) and the daily refresh never touched it, so its
counts and date range fell behind the data after the first refresh.
"""
import pandas as pd


def _excluded_line(excluded):
    if not excluded:
        return "Left out: nothing in this run's manifests."
    shown = "; ".join(f"`{e.get('date') or e.get('docket') or '?'}` ({e['reason']}, {e['manifest']})"
                      for e in excluded[:5])
    more = f", and {len(excluded) - 5:,} more" if len(excluded) > 5 else ""
    return (f"Left out of this run's manifests: {len(excluded):,} rows with no usable file name or date: "
            f"{shown}{more}.")


def render(df: pd.DataFrame, excluded: list, as_of: str) -> str:
    n = len(df)
    by_type = df["type"].value_counts()
    prec, nonprec = int(by_type.get("precedential", 0)), int(by_type.get("nonprecedential", 0))
    n_text = int(df["has_text"].sum())
    text_line = ("No manifest row carried any text (`has_text` is false on every row)" if n_text == 0
                 else f"{n_text:,} of {n:,} manifest rows carried any text (`has_text`)")
    return f"""---
license: cc0-1.0
pretty_name: MSPB decisions (manifest metadata)
---

# MSPB decisions: manifest metadata

One row per decision file listed in the JSON manifests that the Merit Systems Protection Board publishes under https://www.mspb.gov/decisions/. Last refreshed {as_of}. Not affiliated with MSPB.

This is metadata only: date, docket, appellant name, agency, a coarse order title, and the link to the PDF. The manifests carry no outcome and no posted date, so this file can't say who won. {text_line}.

{n:,} decisions ({prec:,} precedential, {nonprec:,} nonprecedential), {df["date"].min()} to {df["date"].max()}. Rows from several manifests are merged on lower-cased file name; the first manifest in priority order wins (`manifest` column).

{_excluded_line(excluded)} Appellant names are as MSPB lists them. `case_kind` is a plain-language label for the case-type codes we were sure of; for any other code it repeats the code from `case_code`, and it is `(unknown)` when there is no code.

Several manifests stopped updating in September 2026; the current listing manifests are read first, then the stale ones are unioned by file name. A daily job adds new decisions and never removes any: https://github.com/abigailhaddad/mspb-decisions
"""
