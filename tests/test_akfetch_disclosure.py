"""L0 业绩预告/快报真披露日解析（可见日 = min(法定截止日, 真披露日)）。"""
import importlib.util


def _ak():
    s = importlib.util.spec_from_file_location("ak", "services/ingestion-service/akfetch.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_disclosed_earlier_than_legal_advances_visible_date():
    ak = _ak()
    # 2023 年报(Q4) 法定截止 2024-04-30；真披露 2024-01-31 → 可见日提前
    rows = ak.parse_earnings_disclosure(
        [{"股票代码": "600519", "公告日期": "2024-01-31"}], "2023Q4")
    r = rows[0]
    assert r["legal_deadline"] == "2024-04-30"
    assert r["disclosed_date"] == "2024-01-31"
    assert r["announce_date"] == "2024-01-31"      # min(披露, 法定)
    assert r["pit_status"] == "lagged_disclosed"


def test_no_disclosed_falls_back_to_legal_deadline():
    ak = _ak()
    rows = ak.parse_earnings_disclosure([{"股票代码": "000001"}], "2023Q4")
    r = rows[0]
    assert r["announce_date"] == "2024-04-30" and r["pit_status"] == "lagged_legal_deadline"


def test_malformed_disclosed_ignored():
    ak = _ak()
    rows = ak.parse_earnings_disclosure([{"股票代码": "1", "公告日期": "暂无"}], "2023Q2")
    assert rows[0]["announce_date"] == "2023-08-31"     # 脏披露日剔除→回退法定
    assert rows[0]["disclosed_date"] is None


def test_skips_rows_without_symbol():
    ak = _ak()
    rows = ak.parse_earnings_disclosure([{"公告日期": "2024-01-31"}], "2023Q4")
    assert rows == []
