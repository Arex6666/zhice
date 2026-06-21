"""批量行情解析（一次 sina list= 调用返回多标的，含个股与指数）——纯函数，脱网可测。"""
import importlib.util


def _fin():
    s = importlib.util.spec_from_file_location("fin", "services/mcp-tool-service/finance.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


# 两只个股 + 一个指数（实测：指数与个股同字段布局 名称,今开,昨收,现价,…）
MULTI = (
    'var hq_str_sh600519="贵州茅台,1200.0,1215.0,1208.0,1220.0,1198.0,100,200,3000,4000000";\n'
    'var hq_str_sz000858="五粮液,150.0,152.0,148.5,153.0,147.0,100,200,5000,800000";\n'
    'var hq_str_sh000001="上证指数,3200.0,3198.16,3210.50,3215.0,3190.0,1,2,3,4";\n'
)


def test_parse_sina_multi_returns_each_stock():
    fin = _fin()
    out = fin.parse_sina_multi(MULTI)
    assert set(out) == {"sh600519", "sz000858", "sh000001"}
    mt = out["sh600519"]
    assert mt["name"] == "贵州茅台" and mt["price"] == 1208.0 and mt["prev_close"] == 1215.0
    wly = out["sz000858"]
    assert wly["name"] == "五粮液" and wly["price"] == 148.5 and wly["prev_close"] == 152.0


def test_parse_sina_multi_parses_index_same_layout_as_stock():
    """指数与个股同布局：现价=f[3]、昨收=f[2]，仅额外打 is_index 标记（change_pct 由下游 _enrich 计算）。"""
    fin = _fin()
    out = fin.parse_sina_multi(MULTI)
    idx = out["sh000001"]
    assert idx["is_index"] is True
    assert idx["name"] == "上证指数"
    assert abs(idx["price"] - 3210.50) < 1e-6
    assert abs(idx["prev_close"] - 3198.16) < 1e-6


def test_parse_sina_multi_skips_garbage_lines():
    fin = _fin()
    out = fin.parse_sina_multi('\n\njunk\nvar hq_str_sh600519="贵州茅台,1,2,3,4,5,6,7,8";\n')
    assert set(out) == {"sh600519"}
