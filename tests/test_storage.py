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


def test_pit_endpoints(tmp_path, monkeypatch):
    """L0 PIT REST：成分写入/读取 + 财务写入 + asof 防前视读取。"""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "pit_api.db"))
    import importlib
    import sys
    sys.path.insert(0, "services/storage-service")
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as cli:
        assert cli.post("/pit/membership", json={
            "date": "2024-01-01", "symbol": "600519", "weight": 1.0,
            "index_code": "000906", "universe_pit_status": "today_snapshot_only"}).status_code == 200
        u = cli.get("/pit/universe", params={"date": "2024-06-01"}).json()
        assert any(x["symbol"] == "600519" for x in u)
        assert cli.post("/pit/fundamental", json={
            "symbol": "600519", "period": "2023Q4", "field": "roe", "value": 0.2,
            "legal_deadline": "2024-04-30", "disclosed_date": "2024-01-31",
            "source": "x", "pit_status": "lagged_disclosed"}).status_code == 200
        r = cli.get("/pit/asof", params={"symbol": "600519", "field": "roe",
                                         "date": "2024-02-15", "kind": "fundamental"}).json()
        assert r["value"] == 0.2
        # 防前视：早于披露日不可见
        r0 = cli.get("/pit/asof", params={"symbol": "600519", "field": "roe",
                                          "date": "2024-01-01", "kind": "fundamental"}).json()
        assert r0["value"] is None and r0["abstain_reason"] == "data_missing"


def test_pit_factor_eval_and_portfolio_endpoints(tmp_path, monkeypatch):
    """L2/L4 离线产物落库 + 委员会只读端点。"""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "feapi.db"))
    import importlib
    import sys
    sys.path.insert(0, "services/storage-service")
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as cli:
        assert cli.post("/pit/factor_eval", json={
            "factor_name": "Mom", "as_of": "2024-06-01", "universe_filter": "lsy",
            "mean_rank_ic": 0.05, "significant": 1, "family_verdict": "有效稳定"}).status_code == 200
        r = cli.get("/pit/factor_eval", params={"factor_name": "Mom", "universe_filter": "lsy"}).json()
        assert r["mean_rank_ic"] == 0.05 and r["family_verdict"] == "有效稳定"
        miss = cli.get("/pit/factor_eval", params={"factor_name": "Zzz"}).json()
        assert miss["significant"] is None and miss["abstain_reason"] == "data_missing"
        assert cli.post("/pit/portfolio", json={"portfolio_id": "x", "as_of": "2024-06-01",
                                                "method": "erc", "weights_json": "{}"}).status_code == 200
        assert cli.get("/pit/portfolio", params={"portfolio_id": "x"}).json()["method"] == "erc"


def test_watchlist_write_and_delete(tmp_path, monkeypatch):
    """自选股写路径：POST 新增 / DELETE 删除（此前只有 GET，标的硬编码）。"""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "wl.db"))
    import importlib
    import sys
    sys.path.insert(0, "services/storage-service")
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as cli:
        r = cli.post("/watchlist", json={"items": [
            {"symbol": "ASHARE:600519", "market": "ASHARE"},
            {"symbol": "US:AAPL", "market": "US"}]})
        assert r.status_code == 200
        assert len(cli.get("/watchlist").json()) == 2
        d = cli.delete("/watchlist/US:AAPL")
        assert d.status_code == 200
        wl = cli.get("/watchlist").json()
        assert len(wl) == 1 and wl[0]["symbol"] == "ASHARE:600519"


def test_by_member_from_committee_json(tmp_path):
    """review_stats 应从已持久化的 committee_json 计算逐委员历史命中率(by_member)。"""
    import importlib.util
    import json
    s = importlib.util.spec_from_file_location("zdb_bm", "services/storage-service/db.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    p = str(tmp_path / "bm.db")
    m.init_db(p)
    cj = json.dumps({"members": [
        {"lens": "技术面", "verdict": "偏多", "confidence": 0.8},
        {"lens": "宏观面", "verdict": "偏空", "confidence": 0.7},
        {"lens": "XGBoost风险信号(波动)", "verdict": "中性", "confidence": 0.0}]},
        ensure_ascii=False)
    i = m.add_analysis(p, "ASHARE:600519", "deep", "偏多", 0.6, cj, 100.0)
    m.fill_review(p, i, 0.02, 0.0, 0.0, True)  # ret_1d=+2% → 偏多对、偏空错
    st = m.review_stats(p)
    bm = st["by_member"]
    assert bm["技术面"]["hits"] == 1 and bm["技术面"]["hit_rate"] == 1.0
    assert bm["宏观面"]["hits"] == 0 and bm["宏观面"]["hit_rate"] == 0.0
    assert "wilson_low" in bm["技术面"]
    assert "XGBoost风险信号(波动)" not in bm  # 非方向风险票不计入逐委员方向命中
    assert any(abs(c - 0.6) < 1e-9 and o == 1 for c, o in st["confidence_points"])


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
