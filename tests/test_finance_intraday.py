"""分时（盘中一天走势）解析——纯函数脱网可测。

A股：东财 trends2/get（data.prePrice + data.trends 每分钟 "时间,开,收,高,低,量,额,均价"）。
港股：腾讯 minute/query（qt[4]=昨收；data.data 每分钟 "HHMM 价 累计量 累计额"，均价=累计额/累计量 VWAP）。
两源统一产出 {name, prev_close, trade_date, points:[{t,price,avg,volume}]}，分时图据此画 价/均价线 + 昨收基准。
"""
import importlib.util


def _fin():
    s = importlib.util.spec_from_file_location("fin", "services/mcp-tool-service/finance.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


# 实测 A股 trends2（每行：日期时间,开,收(现价),高,低,量,额,均价）
EM = {"data": {"code": "600519", "name": "贵州茅台", "prePrice": 1215.0, "preClose": 1215.0,
      "trends": [
        "2026-06-22 09:30,1214.31,1214.31,1214.31,1214.31,694,84273114.00,1214.310",
        "2026-06-22 11:00,1232.39,1232.98,1232.98,1232.39,108,13310837.00,1220.966"]}}

# 实测 港股 tencent minute（qt[4]=昨收；data.data 每行 "HHMM 价 累计量 累计额"）
TX = {"data": {"hk00700": {
        "qt": {"hk00700": ["100", "腾讯控股", "00700", "436.200", "440.200", "439.000", "12883377.0"]},
        "data": {"date": "20260622", "data": [
            "0930 439.000 1873628 822999989.600",
            "1100 436.200 12424952 5401117554.200"]}}}}


def test_parse_em_trends_points_and_prevclose():
    fin = _fin()
    r = fin.parse_em_trends(EM)
    assert r["name"] == "贵州茅台"
    assert r["prev_close"] == 1215.0
    assert r["trade_date"] == "2026-06-22"
    assert len(r["points"]) == 2
    p0 = r["points"][0]
    assert p0["t"] == "09:30" and p0["price"] == 1214.31 and p0["avg"] == 1214.31 and p0["volume"] == 694.0
    assert r["points"][1]["price"] == 1232.98 and r["points"][1]["avg"] == 1220.966


def test_parse_tencent_minute_vwap_and_per_minute_volume():
    fin = _fin()
    r = fin.parse_tencent_minute(TX, "00700")
    assert r["name"] == "腾讯控股"
    assert r["prev_close"] == 440.2          # qt[4]
    assert r["trade_date"] == "2026-06-22"
    p0, p1 = r["points"]
    assert p0["t"] == "09:30" and p0["price"] == 439.0
    assert p0["volume"] == 1873628.0          # 首点取累计量
    assert round(p0["avg"], 2) == 439.25      # VWAP = 累计额/累计量
    assert p1["t"] == "11:00" and p1["price"] == 436.2
    assert p1["volume"] == 10551324.0         # 每分钟量 = 累计差(12424952-1873628)
    assert round(p1["avg"], 2) == 434.70      # VWAP = 5401117554.2 / 12424952 = 434.6993…


def test_parse_em_trends_empty_graceful():
    fin = _fin()
    r = fin.parse_em_trends({})
    assert r["points"] == [] and r["prev_close"] is None


def test_parse_tencent_minute_empty_graceful():
    fin = _fin()
    r = fin.parse_tencent_minute({}, "00700")
    assert r["points"] == [] and r["prev_close"] is None
