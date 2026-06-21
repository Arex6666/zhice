"""ingestion akfetch：双粒度采集的纯解析函数（离线 fixture 可测）。"""
import importlib.util

import pandas as pd


def _af():
    s = importlib.util.spec_from_file_location("af", "services/ingestion-service/akfetch.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_legal_deadline():
    af = _af()
    assert af.legal_deadline_for("2023Q4") == "2024-04-30"   # 年报→次年4/30
    assert af.legal_deadline_for("2024Q1") == "2024-04-30"
    assert af.legal_deadline_for("2024Q2") == "2024-08-31"
    assert af.legal_deadline_for("2024Q3") == "2024-10-31"


def test_parse_baidu_valuation():
    af = _af()
    df = pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "value": ["30.5", "28.1"]})
    out = af.parse_baidu_valuation(df)
    assert out == [{"date": "2024-01-02", "value": 30.5}, {"date": "2024-01-03", "value": 28.1}]
    assert af.parse_baidu_valuation(pd.DataFrame({"date": ["x"], "value": ["-"]})) == []  # 脏值剔除


def test_parse_baidu_valuation_drops_nan_inf():
    af = _af()
    import numpy as np
    df = pd.DataFrame({"date": ["d1", "d2", "d3", "d4"],
                       "value": [np.nan, "nan", float("inf"), "12.5"]})
    assert af.parse_baidu_valuation(df) == [{"date": "d4", "value": 12.5}]  # NaN/inf 全剔


def test_parse_csindex_cons():
    af = _af()
    df = pd.DataFrame({"品种代码": ["600519", "000001"], "品种名称": ["贵州茅台", "平安银行"],
                       "权重": [1.2, 0.8]})
    out = af.parse_csindex_cons(df, "000906")
    assert len(out) == 2 and out[0]["symbol"] == "600519"
    assert out[0]["name"] == "贵州茅台"   # 名称必须带出(ST 过滤依赖)
    assert all(r["universe_pit_status"] == "today_snapshot_only" for r in out)
