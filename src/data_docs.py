"""Data dictionary and table diagram, generated from the published parquet files and docs/tables.toml.

    python src/data_docs.py fetch data/            # download the parquet files from Hugging Face into data/
    python src/data_docs.py check data/            # stop with an error if the columns differ from docs/tables.toml
    python src/data_docs.py write data/            # write docs/data_dictionary.md
    python src/data_docs.py write out/             # same, from a local build instead

Every column's type, non-null share and example value are read from the parquet files; descriptions come
from docs/tables.toml. `check` (and `write`) fail if a parquet column has no description or a described
column is not in the parquet, so the dictionary can't drift from the schema. card.py puts the same text
on the Hugging Face dataset card.

Copied from abigailhaddad/nlrb-decisions; nothing here is specific to one dataset apart from
docs/tables.toml. With no [[joins]] in the config (one table), the join diagram is left out.
"""
import os, sys, tomllib
from datetime import date
import pyarrow.compute as pc
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "..", "docs", "tables.toml")
OUT = os.path.join(HERE, "..", "docs", "data_dictionary.md")


def load_config(path=CONFIG):
    with open(path, "rb") as f:
        return tomllib.load(f)


def fetch(dest, cfg=None):
    """Download every table's file from the Hugging Face dataset at its current commit. Returns the commit."""
    from huggingface_hub import HfApi, hf_hub_download
    cfg = cfg or load_config()
    sha = HfApi().dataset_info(cfg["dataset"]).sha
    os.makedirs(dest, exist_ok=True)
    for t in cfg["tables"].values():
        hf_hub_download(cfg["dataset"], t["file"], repo_type="dataset", revision=sha, local_dir=dest)
    with open(os.path.join(dest, "REVISION"), "w") as f:
        f.write(sha + "\n")
    print(f"fetched {cfg['dataset']} at {sha} into {dest}")
    return sha


def revision(data_dir):
    p = os.path.join(data_dir, "REVISION")
    return open(p).read().strip() if os.path.exists(p) else None


def check(data_dir, cfg=None):
    """Columns in each parquet file must be exactly the columns described, in the same order."""
    cfg = cfg or load_config()
    problems = []
    for name, t in cfg["tables"].items():
        cols = pq.read_schema(os.path.join(data_dir, t["file"])).names
        described = list(t["columns"])
        missing = [c for c in cols if c not in described]
        extra = [c for c in described if c not in cols]
        if missing:
            problems.append(f"{name}: columns in {t['file']} with no description in docs/tables.toml: {missing}")
        if extra:
            problems.append(f"{name}: described in docs/tables.toml but not in {t['file']}: {extra}")
        if not missing and not extra and cols != described:
            problems.append(f"{name}: column order differs from {t['file']}; reorder docs/tables.toml")
        for c in t.get("unconfirmed", []):
            if c not in described:
                problems.append(f"{name}: unconfirmed column {c} is not described")
    for j in cfg.get("joins", []):
        for side in (j["left"], j["right"]):
            tbl, col = side.split(".")
            if col not in cfg["tables"].get(tbl, {}).get("columns", {}):
                problems.append(f"join {side}: no such table or column")
    if problems:
        sys.exit("SCHEMA DRIFT:\n  " + "\n  ".join(problems))
    print("schema matches docs/tables.toml:", ", ".join(f"{n} ({len(t['columns'])} columns)" for n, t in cfg["tables"].items()))


def simple_type(arrow_type):
    s = str(arrow_type)
    return {"large_string": "string", "double": "float64", "float": "float32"}.get(s, s)


def cell(v, width=60):
    s = str(v).replace("\n", " ").replace("|", "\\|")
    return (s[:width] + "...") if len(s) > width else s


def profile(path):
    """Per column: type, non-null count, non-blank count (non-null and not ''), first non-blank value."""
    table = pq.read_table(path)
    out = {}
    for name in table.column_names:
        col = table.column(name)
        nonnull = len(col) - col.null_count
        nonblank, example = nonnull, None
        if simple_type(col.type) == "string":
            nonblank = nonnull - pc.sum(pc.equal(col, "")).as_py() if nonnull else 0
            filled = col.filter(pc.and_(pc.is_valid(col), pc.not_equal(col, "")))
        else:
            filled = col.drop_null()
        if len(filled):
            example = filled[0].as_py()
        out[name] = {"type": simple_type(col.type), "nonnull": nonnull, "nonblank": nonblank, "example": example}
    return table.num_rows, out


def mermaid(cfg, profiles):
    """ER diagram showing each table's primary key and join columns. PK = primary key; FK = the right-hand
    side of an exact join (a join whose `kind` has no dotted line)."""
    joins = cfg.get("joins", [])
    lines = ["```mermaid", "erDiagram"]
    for name, t in cfg["tables"].items():
        lines.append(f"    {name} {{")
        for col in t["columns"]:
            marks = []
            if col == t.get("primary_key"):
                marks.append("PK")
            if any(j["right"] == f"{name}.{col}" and ".." not in j["kind"] for j in joins):
                marks.append("FK")
            in_join = any(f"{name}.{col}" in (j["left"], j["right"]) for j in joins)
            if marks or in_join:
                lines.append(f"        {profiles[name][1][col]['type']} {col} {','.join(marks)}".rstrip())
        lines.append("    }")
    for j in cfg.get("joins", []):
        lt, rt = j["left"].split(".")[0], j["right"].split(".")[0]
        lines.append(f'    {lt} {j["kind"]} {rt} : "{j["label"]}"')
    lines.append("```")
    return "\n".join(lines)


def markdown(data_dir, cfg=None, level=1, source=None):
    """The data dictionary as markdown. `level` is the heading level of its title."""
    cfg = cfg or load_config()
    check(data_dir, cfg)
    h = "#" * level
    profiles = {n: profile(os.path.join(data_dir, t["file"])) for n, t in cfg["tables"].items()}
    rev = revision(data_dir)
    src = source or (f"Hugging Face `{cfg['dataset']}` at commit `{rev[:8]}`" if rev else f"`{data_dir}`")
    out = [f"{h} Data dictionary", "",
           f"Generated by `src/data_docs.py` on {date.today().isoformat()} from {src}. Types, row counts, "
           f"non-null shares and examples are read from the parquet files; descriptions are in `docs/tables.toml` in the "
           f"GitHub repo. Columns marked **(meaning not confirmed)** are ones whose meaning the source does not define.", "",
           "| table | file | Hugging Face config | rows | one row is |", "|---|---|---|---|---|"]
    for n, t in cfg["tables"].items():
        out.append(f"| `{n}` | `{t['file']}` | `{t['config']}` | {profiles[n][0]:,} | {t['grain']} |")
    if cfg.get("joins"):
        out += ["", f"{h}# How the tables join", "", mermaid(cfg, profiles), ""]
        for j in cfg["joins"]:
            out.append(f"- `{j['left']}` to `{j['right']}`: {j['note']}")
    for n, t in cfg["tables"].items():
        rows, prof = profiles[n]
        out += ["", f"{h}# `{n}` (`{t['file']}`, config `{t['config']}`)", "", t["grain"], "",
                "Non-null and non-blank are shares of the table's rows; non-blank also leaves out empty strings.", "",
                "| column | type | description | non-null | non-blank | example |", "|---|---|---|---|---|---|"]
        for col, desc in t["columns"].items():
            p = prof[col]
            mark = " **(meaning not confirmed)**" if col in t.get("unconfirmed", []) else ""
            pk = " Primary key." if col == t.get("primary_key") else ""
            pct = lambda x: f"{100 * x / rows:.1f}%" if rows else "n/a"
            ex = f"`{cell(p['example'])}`" if p["example"] is not None else ""
            desc = desc.replace("|", "\\|")  # a bare | would end the table cell
            out.append(f"| `{col}` | {p['type']} | {desc}{pk}{mark} | {pct(p['nonnull'])} | {pct(p['nonblank'])} | {ex} |")
    return "\n".join(out) + "\n"


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("fetch", "check", "write"):
        sys.exit(__doc__)
    what, data_dir = sys.argv[1], sys.argv[2]
    if what == "fetch":
        fetch(data_dir)
    elif what == "check":
        check(data_dir)
    else:
        md = "<!-- Generated by src/data_docs.py; edit docs/tables.toml instead. -->\n" + markdown(data_dir)
        with open(OUT, "w") as f:
            f.write(md)
        print("wrote", os.path.relpath(OUT))


if __name__ == "__main__":
    main()
