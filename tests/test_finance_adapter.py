import importlib.util


def _fin():
    s = importlib.util.spec_from_file_location("fin", "services/mcp-tool-service/finance.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


SINA = 'var hq_str_sh600519="贵州茅台,1200.0,1215.0,1208.0,1220.0,1198.0,100,200,3000,4000000";'


def test_parse_sina():
    fin = _fin()
    q = fin.parse_sina_quote(SINA)
    assert q["name"] == "贵州茅台"
    assert q["price"] == 1208.0
    assert q["prev_close"] == 1215.0
    assert q["open"] == 1200.0
    assert q["volume"] == 3000.0
    assert q["source"] == "sina"


def test_split_symbol():
    fin = _fin()
    assert fin.split_symbol("ASHARE:600519") == ("ASHARE", "600519")
    assert fin.split_symbol("CRYPTO:BTCUSDT") == ("CRYPTO", "BTCUSDT")


def test_get_adapter_unknown():
    fin = _fin()
    import pytest
    with pytest.raises(ValueError):
        fin.get_adapter("FOREX")
