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


def test_analysis_review(tmp_path):
    import importlib.util
    s = importlib.util.spec_from_file_location("zdb2", "services/storage-service/db.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    p = str(tmp_path / "fin.db")
    m.init_db(p)
    i = m.add_analysis(p, "ASHARE:600519", "deep", "偏多", 0.6, "{}", 1200.0)
    assert len(m.pending_reviews(p)) == 1
    m.fill_review(p, i, 0.01, 0.02, -0.01, True)
    st = m.review_stats(p)
    assert st["reviewed"] == 1 and st["hit_rate"] == 1.0
    assert len(m.pending_reviews(p)) == 0


def test_quotes_news_watchlist(tmp_path):
    import importlib.util
    s = importlib.util.spec_from_file_location("zdb3", "services/storage-service/db.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    p = str(tmp_path / "fin2.db")
    m.init_db(p)
    m.add_quote(p, "CRYPTO:BTCUSDT", 63000.0, 1.2, "t", "fresh", "binance")
    assert m.get_quotes(p, "CRYPTO:BTCUSDT")[0]["price"] == 63000.0
    m.add_news(p, "ASHARE:600519", "title", "http://x", "em", "t")
    assert len(m.get_news(p, "ASHARE:600519")) == 1
    m.set_watchlist(p, [{"symbol": "ASHARE:600519", "market": "ASHARE"}])
    assert len(m.get_watchlist(p)) == 1
