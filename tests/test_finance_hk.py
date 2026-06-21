"""港股行情解析（新浪 HK 19 字段布局，实测抓包）——纯函数脱网可测。"""
import importlib.util


def _fin():
    s = importlib.util.spec_from_file_location("fin", "services/mcp-tool-service/finance.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


# 实测格式：英文名,中文名,今开,昨收,最高,最低,现价,涨跌额,涨跌幅,买,卖,成交额,成交量,...,日期(YYYY/MM/DD),时间(HH:MM)
HK = ('var hq_str_hk00700="TENCENT,腾讯控股,440.000,445.400,446.200,435.600,440.200,'
      '-5.200,-1.167,440.00000,440.20001,13215630970,30119117,0.000,0.000,675.134,'
      '420.400,2026/06/18,16:08";')
HK2 = ('var hq_str_hk09988="BABA-W,阿里巴巴-W,118.000,120.000,119.500,116.800,117.300,'
       '-2.700,-2.250,117.20,117.30,5000000000,42000000,0,0,150.0,70.0,2026/06/18,16:08";')


def test_parse_sina_hk_fields():
    fin = _fin()
    q = fin.parse_sina_hk(HK)
    assert q["name"] == "腾讯控股"
    assert q["price"] == 440.200          # f[6] 现价
    assert q["prev_close"] == 445.400     # f[3] 昨收
    assert q["open"] == 440.000           # f[2]
    assert q["high"] == 446.200 and q["low"] == 435.600
    assert q["volume"] == 30119117.0      # f[12]
    assert q["source"] == "sina"


def test_parse_sina_hk_real_timestamp():
    """日期 f[17]=YYYY/MM/DD + 时间 f[18]=HH:MM → 真实成交时间(供 assess 判过期)。"""
    import time
    fin = _fin()
    q = fin.parse_sina_hk(HK)
    assert q["ts"] is not None
    assert time.time() - q["ts"] > 1000   # 明显早于当前 → 可被判 stale


def test_parse_sina_hk_multi():
    fin = _fin()
    out = fin.parse_sina_hk_multi(HK + "\n" + HK2)
    assert set(out) == {"hk00700", "hk09988"}
    assert out["hk09988"]["name"] == "阿里巴巴-W" and out["hk09988"]["price"] == 117.300


def test_get_adapter_hk():
    fin = _fin()
    ad = fin.get_adapter("HK")
    assert ad.__class__.__name__ == "HkAdapter"
    assert fin._hk_sina_code("00700") == "hk00700"
