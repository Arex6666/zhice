"""L0 factor_meta CRUD + 时点面板/覆盖度/健康度（storage db.py 扩展）。"""
import importlib.util


def _db():
    s = importlib.util.spec_from_file_location("db", "services/storage-service/db.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_factor_meta_crud(tmp_path):
    db = _db()
    p = str(tmp_path / "z.db")
    db.init_db(p)
    db.add_factor_meta(p, {"factor_name": "Mom_12_1", "source": "kline", "pit_status": "history_native",
                           "direction": "+", "history_depth_days": 252})
    one = db.read_factor_meta(p, "Mom_12_1")
    assert one["pit_status"] == "history_native" and one["direction"] == "+"
    assert db.read_factor_meta(p, "NoSuch") is None
    db.add_factor_meta(p, {"factor_name": "EP", "pit_status": "forward_pit_only", "direction": "+"})
    names = [r["factor_name"] for r in db.list_factor_meta(p)]
    assert "Mom_12_1" in names and "EP" in names


def test_read_panel_is_pit_safe(tmp_path):
    db = _db()
    p = str(tmp_path / "z.db")
    db.init_db(p)
    # 同一 symbol/field 两个可见日：read_panel(t) 取 visible_date<=t 的最新
    db.add_panel(p, "600519", "2024-01-02", "pe", 30.0, "baidu", visible_date="2024-01-02")
    db.add_panel(p, "600519", "2024-01-10", "pe", 28.0, "baidu", visible_date="2024-01-10")
    m = db.read_panel(p, "2024-01-05")
    assert m["600519"]["pe"] == 30.0          # 不泄漏 01-10 的未来值
    m2 = db.read_panel(p, "2024-01-15")
    assert m2["600519"]["pe"] == 28.0


def test_coverage_and_health(tmp_path):
    db = _db()
    p = str(tmp_path / "z.db")
    db.init_db(p)
    db.add_panel(p, "600519", "2024-01-02", "pe", 30.0, "baidu", visible_date="2024-01-02")
    db.add_membership(p, "2024-01-02", "600519", 0.1, "csi800", "today_snapshot_only", name="贵州茅台")
    cov = db.data_coverage(p, "2024-01-05")
    assert cov["panel_symbols"] == 1 and cov["universe_rows"] == 1
    h = db.pit_data_health(p)
    assert "panel_daily" in h["table_counts"]
    assert "today_snapshot_only" in h["universe_pit_status"]
