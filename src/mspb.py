"""Load MSPB decision manifests into one de-duplicated list of records.

No model, no network. Everything here comes from manifest fields only.

A manifest is JSON: {"DOCUMENT_TYPE": "PRECEDENTIAL"|"NON-PRECEDENTIAL",
"data": [row, ...]}. The same decision appears in several manifests, so rows
are keyed by lower-cased FILE_NAME and the first manifest (in PRIORITY order)
to carry a file wins. Rows that cannot be keyed or dated are not dropped
silently: load_snapshot_report() returns them in `excluded`.
"""
import glob
import json
import os
import re
from datetime import date, datetime
from urllib.parse import quote

BASES = {
    "precedential": "https://www.mspb.gov/decisions/precedential/",
    "nonprecedential": "https://www.mspb.gov/decisions/nonprecedential/",
}
TYPE_OF_DOCUMENT = {"PRECEDENTIAL": "precedential",
                    "NON-PRECEDENTIAL": "nonprecedential"}
FIRST_DATE = date(1979, 1, 1)

# Lower number = read first. The current listing manifests come first because
# they are the ones MSPB keeps updating.
PRIORITY = [
    "PrecedentialDecisions_Manifest.json",
    "NonPrecedentialDecisions_Manifest.json",
    "PrecedentialDecisions_Manifest_updMar2025.json",
    "NonPrecedentialDecisions_Manifest-updmar2025.json",
    "PrecedentialDecisions_Manifest_Table.json",
    "NonPrecedentialDecisions_Manifest_Table.json",
]

# Docket case-type codes we are sure of (chapter/part of title 5 or statute).
# Anything else is reported by its raw code.
CASE_CODES = {
    "0752": "adverse action (ch. 75)",
    "752P": "adverse action (ch. 75)",
    "0432": "performance-based (ch. 43)",
    "1221": "whistleblower IRA",
    "315H": "probationary termination",
    "4324": "USERRA",
    "3330": "VEOA",
    "0353": "restoration after injury",
    "0714": "VA accountability (38 USC 714)",
    "0831": "retirement (CSRS)",
    "0841": "retirement (FERS)",
    "0845": "retirement (FERS overpayment)",
    "844E": "retirement (FERS disability)",
}

DOC_TITLES = {  # normalised DOCTITLE -> label
    "final order": "Final Order", "finalorder": "Final Order",
    "remand order": "Remand Order", "opinion and order": "Opinion and Order",
    "opinion & order": "Opinion and Order", "final decision": "Final Decision",
    "order": "Order",
}

DOCKET_RE = re.compile(r"^\s*([A-Za-z]{2})-?([0-9A-Za-z]{3,4})-")


def parse_date(value, today=None):
    """Return a date or None. Accepts YYYY/M/D, M/D/YYYY, YYYY-MM-DD.
    None for blank, unparseable, or outside 1979..today."""
    today = today or date.today()
    v = (value or "").strip()
    for fmt in ("%Y/%m/%d", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(v, fmt).date()
        except ValueError:
            continue
        return d if FIRST_DATE <= d <= today else None
    return None


def clean(s):
    return " ".join((s or "").split())


def norm_doc_title(row):
    t = clean(row.get("DOCTITLE")).replace("_", " ")
    t = re.sub(r"\s*\[.*?\]", "", t).strip().lower()
    return DOC_TITLES.get(t, clean(row.get("DOCTITLE")).replace("_", " ") or "(blank)")


ORDER_KINDS = [  # (substring in lower-cased text, label); first match wins
    ("settled", "Dismissed as settled"),
    ("dismissed as withdrawn", "Dismissed as withdrawn"),
    ("withdrawn", "Dismissed as withdrawn"),
    ("untimely", "Untimely petition order"),
    ("remand", "Remand order"),
    ("stay", "Stay order"),
    ("quorum", "Lack-of-quorum order"),
    ("opinion", "Opinion and order"),
    ("final order", "Final order"),
    ("final decision", "Final order"),
]


def order_kind(row):
    """Coarse kind of order from the title fields and file name.

    This is the only disposition-like signal in the manifests. META_TITLE
    holds a clean order title only for decisions issued since about
    2026-09-18; before that it is mostly a file name or blank, so the kind is
    read from whichever of META_TITLE, DOCTITLE, FILE_NAME says it. A
    "Final order" is just the Board's closing order: it says nothing about who
    won.
    """
    text = " ".join(clean(row.get(k)) for k in ("META_TITLE", "DOCTITLE", "FILE_NAME"))
    text = text.replace("_", " ").lower()
    for needle, label in ORDER_KINDS:
        if needle in text:
            return label
    return "Other or unknown"


def norm_agency(a):
    a = clean(a)
    if a.isupper():  # old rows are ALL CAPS
        a = a.title().replace(" Of ", " of ").replace(" The ", " the ").replace(" And ", " and ")
    return a or "(blank)"


def make_record(row, doc_type, manifest, today=None):
    # Keep the file name byte-for-byte (apart from outer whitespace): a few
    # contain double spaces or non-breaking spaces that the URL needs.
    fn = (row.get("FILE_NAME") or "").strip()
    d = parse_date(row.get("ISSUED_DATE"), today)
    docket = clean(re.split(r"[,/]", row.get("DOCKET_NBR") or "")[0])
    m = DOCKET_RE.match(docket)
    code = m.group(2).upper() if m else ""
    first, last = clean(row.get("APL_FIRST_NAME")), clean(row.get("APL_LAST_NAME"))
    agency = norm_agency(row.get("AGENCY"))
    appellant = clean(f"{first} {last}")
    return {
        "id": fn.lower(),
        "file": fn,
        "type": doc_type,
        "date": d.isoformat() if d else None,
        "raw_date": row.get("ISSUED_DATE"),
        "docket": docket,
        "region": m.group(1).upper() if m else "",
        "case_code": code,
        "case_kind": CASE_CODES.get(code, code or "(unknown)"),
        "appellant": appellant,
        "agency": agency,
        "doc_title": norm_doc_title(row),
        "order_kind": order_kind(row),
        "decision_number": clean(row.get("DECISION_NUMBER")),
        "citation": clean(row.get("LEGAL_CITATION")),
        "docnumber": clean(row.get("DOCNUMBER")),
        "has_text": bool(clean(row.get("DOCUMENT_CONTENT"))),
        "url": BASES[doc_type] + quote(fn),
        "manifest": manifest,
    }


def _is_search(name):
    return "SEARCH_MANIFESTS" in name


def _order(path):
    """Sort key: listing manifests in PRIORITY order, then the rest.
    Matches on the end of the file name so a saved copy may carry a prefix
    (fetch.sh saves 'precedential_<name>.json')."""
    name = os.path.basename(path)
    for i, p in enumerate(PRIORITY):
        if name.endswith(p) and not _is_search(name):
            return (i, name)
    return (len(PRIORITY), name)


def load_snapshot_report(mdir, today=None, include_search=False):
    """Read every *.json manifest in mdir.

    Only the listing manifests (the ones MSPB's own listing and search-by-
    metadata pages load) count as the set of decisions. Rows found only in a
    SEARCH_MANIFESTS (full-text) file are returned in report["search_only"]
    and are not counted unless include_search=True.

    Returns (records, report). records: de-duplicated list, one per file name.
    report: counts of rows read, duplicates merged, and excluded rows (each
    with the reason), so nothing disappears unreported.
    """
    seen, records = {}, []
    report = {"rows_read": 0, "duplicates_merged": 0, "excluded": [],
              "per_manifest": {}, "search_only": []}
    for path in sorted(glob.glob(os.path.join(mdir, "*.json")), key=_order):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc_type = TYPE_OF_DOCUMENT.get(doc.get("DOCUMENT_TYPE"))
        name = os.path.basename(path)
        if doc_type is None or "data" not in doc:
            raise ValueError(f"{name}: not a decision manifest")
        pm = report["per_manifest"][name] = {"rows": 0, "new": 0}
        for row in doc["data"]:
            report["rows_read"] += 1
            pm["rows"] += 1
            if not (row.get("FILE_NAME") or "").strip():
                report["excluded"].append({"manifest": name, "reason": "no FILE_NAME",
                    "docket": row.get("DOCKET_NBR"), "date": row.get("ISSUED_DATE"),
                    "type": doc_type})
                continue
            rec = make_record(row, doc_type, name, today)
            if rec["date"] is None:
                report["excluded"].append({"manifest": name, "reason": "bad or blank date",
                    "file": rec["file"], "date": rec["raw_date"], "type": doc_type})
                continue
            key = (doc_type, rec["id"])
            if key in seen:
                report["duplicates_merged"] += 1
                if rec["has_text"] and not seen[key]["has_text"]:
                    seen[key]["has_text"] = True
                continue
            if _is_search(name) and not include_search:
                report["search_only"].append({"manifest": name, "type": doc_type,
                    "file": rec["file"], "date": rec["date"], "docket": rec["docket"]})
                continue
            seen[key] = rec
            records.append(rec)
            pm["new"] += 1
    return records, report


def load_snapshot(mdir, today=None):
    return load_snapshot_report(mdir, today)[0]


def manifest_health(mdir, today=None, stale_days=7):
    """Newest issued date in each listing manifest, and which manifests lag.

    A manifest is called stale when its newest decision is more than
    stale_days older than the newest decision in any listing manifest of the
    same type. This is how a manifest that has stopped updating shows up
    without any network call.
    """
    out = {}
    for path in sorted(glob.glob(os.path.join(mdir, "*.json")), key=_order):
        name = os.path.basename(path)
        if _is_search(name):
            continue
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        t = TYPE_OF_DOCUMENT.get(doc.get("DOCUMENT_TYPE"))
        ds = [parse_date(r.get("ISSUED_DATE"), today) for r in doc.get("data", [])]
        ds = [d for d in ds if d]
        out[name] = {"type": t, "rows": len(doc.get("data", [])),
                     "newest": max(ds).isoformat() if ds else None}
    lead = {}
    for v in out.values():
        if v["newest"] and (v["type"] not in lead or v["newest"] > lead[v["type"]]):
            lead[v["type"]] = v["newest"]
    for v in out.values():
        if v["newest"] is None:
            v["stale"] = True
        else:
            gap = (date.fromisoformat(lead[v["type"]]) - date.fromisoformat(v["newest"])).days
            v["stale"] = gap > stale_days
            v["days_behind_lead"] = gap
    return out
