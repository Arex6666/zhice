"""L0 PIT 数据层：schema + 可见日对齐 + asof 防前视 + universe。"""
import importlib.util
import sqlite3


def _db():
    s = importlib.util.spec_from_file_location("zdb_pit", "services/storage-service/db.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_pit_tables_created(tmp_path):
    db = _db()
    p = str(tmp_path / "pit.db")
    db.init_db(p)
    c = sqlite3.connect(p)
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ["panel_daily", "fundamentals_pit", "index_membership", "events",
              "factor_meta", "factor_eval", "portfolios"]:
        assert t in names, t
    db.init_db(p)  # 幂等


def test_visible_date_min_semantics():
    db = _db()
    assert db.visible_date("2024-04-30", "2024-01-31") == "2024-01-31"  # 真披露日提前
    assert db.visible_date("2024-04-30", None) == "2024-04-30"          # 无披露日回退法定
    assert db.visible_date(None, "2024-01-31") == "2024-01-31"
    assert db.visible_date(None, None) is None


def test_asof_returns_visible_version_only(tmp_path):
    db = _db()
    p = str(tmp_path / "asof.db")
    db.init_db(p)
    db.add_fundamental(p, "600519", "2023Q4", "roe", 0.20, "2024-04-30", "2024-01-31", "x", "lagged_disclosed")
    db.add_fundamental(p, "600519", "2024Q1", "roe", 0.22, "2024-04-30", None, "x", "lagged_legal_deadline")
    r = db.asof_fundamental(p, "600519", "roe", "2024-02-15")
    assert r is not None and r["value"] == 0.20 and r["announce_date"] == "2024-01-31"
    assert db.asof_fundamental(p, "600519", "roe", "2024-01-01") is None  # 都不可见


def test_asof_tiebreak_same_announce_date_returns_newest_period(tmp_path):
    """M10: 年报(Q4)与一季报(Q1)常同日披露 → 同 announce_date 须确定性返回较新报告期。"""
    db = _db()
    p = str(tmp_path / "tie.db")
    db.init_db(p)
    db.add_fundamental(p, "600519", "2024Q1", "roe", 0.22, "2024-04-30", None, "x", "lagged_legal_deadline")
    db.add_fundamental(p, "600519", "2023Q4", "roe", 0.20, "2024-04-30", None, "x", "lagged_legal_deadline")
    r = db.asof_fundamental(p, "600519", "roe", "2024-06-01")
    assert r["value"] == 0.22 and r["period"] == "2024Q1"   # period DESC tie-break


def test_asof_panel(tmp_path):
    db = _db()
    p = str(tmp_path / "pn.db")
    db.init_db(p)
    db.add_panel(p, "600519", "2024-01-10", "pe", 30.0, "baidu", "2024-01-10")
    db.add_panel(p, "600519", "2024-01-20", "pe", 28.0, "baidu", "2024-01-20")
    assert db.asof_panel(p, "600519", "pe", "2024-01-15")["value"] == 30.0
    assert db.asof_panel(p, "600519", "pe", "2024-01-25")["value"] == 28.0


def test_universe_membership_and_lsy(tmp_path):
    db = _db()
    p = str(tmp_path / "u.db")
    db.init_db(p)
    # 真实形态: symbol 是数字代码, ST 标记在 name 上
    db.add_membership(p, "2024-01-01", "600519", 1.0, "000906", "today_snapshot_only", name="贵州茅台")
    db.add_membership(p, "2024-01-01", "000408", 0.1, "000906", "today_snapshot_only", name="*ST藏格")
    allu = db.universe(p, "2024-06-01")
    assert {x["symbol"] for x in allu} == {"600519", "000408"}
    lsy = db.universe(p, "2024-06-01", lsy_filter="on")
    assert {x["symbol"] for x in lsy} == {"600519"}   # ST 按名称剔除(对数字代码生效)
    assert db.universe(p, "2023-01-01") == []          # 早于任何快照
