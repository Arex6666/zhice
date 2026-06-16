import importlib.util


def _load_db(path):
    spec = importlib.util.spec_from_file_location("zdb", "services/storage-service/db.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.init_db(path)
    return m


def test_add_and_get(tmp_path):
    p = str(tmp_path / "t.db")
    db = _load_db(p)
    rid = db.add_document(p, "http://a", "T", "hello world")
    doc = db.get_document(p, rid)
    assert doc["url"] == "http://a" and doc["content"] == "hello world"
    assert doc["content_length"] == 11


def test_search(tmp_path):
    p = str(tmp_path / "t.db")
    db = _load_db(p)
    db.add_document(p, "http://a", "AI news", "machine learning rocks")
    db.add_document(p, "http://b", "Cooking", "pasta recipe")
    res = db.search_documents(p, "machine", 10)
    assert len(res) == 1 and res[0]["url"] == "http://a"


def test_stats(tmp_path):
    p = str(tmp_path / "t.db")
    db = _load_db(p)
    db.add_document(p, "http://a", "T", "x")
    s = db.stats(p)
    assert s["count"] == 1


def test_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "api.db"))
    import importlib
    import sys
    sys.path.insert(0, "services/storage-service")
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as cli:
        assert cli.get("/health").json()["status"] == "ok"
        r = cli.post("/documents", json={"url": "http://a", "title": "T", "content": "deep learning"})
        assert r.status_code == 200
        doc_id = r.json()["id"]
        assert cli.get(f"/documents/{doc_id}").json()["content"] == "deep learning"
        assert len(cli.get("/documents", params={"q": "deep"}).json()) == 1
        assert cli.get("/stats").json()["count"] == 1
