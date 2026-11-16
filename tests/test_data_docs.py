"""Offline tests for the data dictionary and the SQLite build.

"""
import hashlib, os, sqlite3, sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import build_sqlite, data_docs

CFG = {
    "dataset": "someone/example",
    "tables": {
        "parent": {"file": "parent.parquet", "config": "default", "grain": "one parent", "primary_key": "id",
                   "columns": {"id": "row id", "n": "a number", "flag": "a flag"}},
        "child": {"file": "child.parquet", "config": "child", "grain": "one child", "primary_key": "cid",
                  "unconfirmed": ["note"], "columns": {"cid": "row id", "id": "parent id | pipe", "note": "a note"}},
    },
    "joins": [{"left": "parent.id", "right": "child.id", "kind": "||--o{", "label": "id", "note": "exact"}],
}


@pytest.fixture
def data(tmp_path):
    pd.DataFrame({"id": ["a", "b", "c"], "n": [1, None, 3], "flag": [True, False, True]}).astype({"n": "Int64"}) \
        .to_parquet(tmp_path / "parent.parquet", index=False)
    pd.DataFrame({"cid": ["x", "y"], "id": ["a", None], "note": ["", "hi"]}).to_parquet(tmp_path / "child.parquet", index=False)
    return tmp_path


def test_check_catches_drift(data):
    data_docs.check(str(data), CFG)
    bad = {**CFG, "tables": {**CFG["tables"], "parent": {**CFG["tables"]["parent"], "columns": {"id": "x", "n": "y"}}}}
    with pytest.raises(SystemExit, match="no description"):
        data_docs.check(str(data), bad)


def test_markdown(data):
    md = data_docs.markdown(str(data), CFG)
    assert "| `parent` | `parent.parquet` | `default` | 3 |" in md
    assert "parent ||--o{ child" in md and "string id FK" in md
    assert "| `n` | int64 | a number | 66.7% | 66.7% | `1` |" in md
    assert "| `note` | string | a note **(meaning not confirmed)** | 100.0% | 50.0% | `hi` |" in md
    assert "parent id \\| pipe" in md


def test_sqlite_matches_parquet(data, tmp_path):
    out = tmp_path / "x.sqlite"
    assert build_sqlite.build(str(data), str(out), CFG) == {"parent": 3, "child": 2}
    con = sqlite3.connect(out)
    assert con.execute("select id, n, flag from parent order by id").fetchall() == [("a", 1, 1), ("b", None, 0), ("c", 3, 1)]
    assert con.execute("select count(*) from child join parent using (id)").fetchone() == (1,)


def test_one_table_no_joins(data):
    cfg = {"dataset": "someone/example", "tables": {"parent": CFG["tables"]["parent"]}}
    md = data_docs.markdown(str(data), cfg)
    assert "How the tables join" not in md and "| `flag` | bool | a flag |" in md
