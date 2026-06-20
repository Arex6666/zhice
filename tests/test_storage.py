import importlib.util


def test_finance_api(tmp_path, monkeypatch):
    """API 级回归：storage 的金融端点（/health + /quotes 往返）。"""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "api.db"))
    import importlib
    import sys
    sys.path.insert(0, "services/storage-service")
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as cli:
        assert cli.get("/health").json()["status"] == "ok"
        r = cli.post("/quotes", json={"symbol": "ASHARE:600519", "price": 1500.0,
                                      "change_pct": 1.1, "ts": "t",
                                      "data_status": "fresh", "source": "sina"})
        assert r.status_code == 200
        rows = cli.get("/quotes", params={"symbol": "ASHARE:600519"}).json()
        assert rows and rows[0]["price"] == 1500.0


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
