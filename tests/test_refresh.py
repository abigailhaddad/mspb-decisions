import json, os, sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import refresh


def df(*ids, date="2026-01-01"):
    return pd.DataFrame({"id": list(ids), "date": [date] * len(ids), "appellant": ["x"] * len(ids)})


def test_merge_first_run():
    merged, added, kept = refresh.merge(None, df("a", "b"))
    assert (len(merged), added, kept) == (2, 2, 0)


def test_merge_keeps_rows_that_left_the_manifests():
    merged, added, kept = refresh.merge(df("a", "b"), df("b", "c"))
    assert sorted(merged["id"]) == ["a", "b", "c"]
    assert (added, kept) == (1, 1)


def test_merge_new_row_replaces_old_by_id():
    old, new = df("a"), df("a")
    new["appellant"] = "changed"
    merged, added, _ = refresh.merge(old, new)
    assert list(merged["appellant"]) == ["changed"] and added == 0


class FakeResp:
    def __init__(self, status=200, payload=None, text_json=True):
        self.status_code, self._p, self._j = status, payload, text_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        if not self._j:
            raise ValueError("html")
        return self._p


def run_fetch(monkeypatch, tmp_path, resp):
    monkeypatch.setattr(refresh.requests, "get", lambda *a, **k: resp)
    refresh.fetch(str(tmp_path), pause=0)


def test_fetch_stops_on_429(monkeypatch, tmp_path):
    with pytest.raises(refresh.Blocked):
        run_fetch(monkeypatch, tmp_path, FakeResp(429))


def test_fetch_rejects_html(monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        run_fetch(monkeypatch, tmp_path, FakeResp(200, text_json=False))


def test_fetch_rejects_small_manifest(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="only 3 rows"):
        run_fetch(monkeypatch, tmp_path, FakeResp(200, {"DOCUMENT_TYPE": "PRECEDENTIAL", "data": [1, 2, 3]}))


def test_published_read_error_is_not_first_run(monkeypatch):
    import urllib.error

    def boom(code):
        def f(url):
            raise urllib.error.HTTPError(url, code, "x", None, None)
        return f

    monkeypatch.setattr(refresh.pd, "read_parquet", boom(503))
    with pytest.raises(urllib.error.HTTPError):
        refresh.load_published()
    monkeypatch.setattr(refresh.pd, "read_parquet", boom(404))
    assert refresh.load_published() is None
