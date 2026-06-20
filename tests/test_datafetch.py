"""ingestion datafetch：真实新鲜度时间戳 + 数据新鲜度分级（不再硬编码 fresh）。"""
import asyncio
import importlib.util


def _df():
    s = importlib.util.spec_from_file_location("df", "services/ingestion-service/datafetch.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


FULL = ('var hq_str_sh600519="贵州茅台,1688.0,1685.0,1700.0,1710.0,1680.0,1699.0,1700.0,'
        '123456,200000000.0,' + ','.join(['0'] * 20) + ',2024-01-15,15:00:00,00";')


def test_parse_sina_includes_real_ts():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    df = _df()
    q = df._parse_sina(FULL, "sh600519")
    expected = datetime(2024, 1, 15, 15, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    assert abs(q["ts"] - expected) < 2.0


def test_freshness_windows():
    df = _df()
    now = 1_000_000.0
    assert df.freshness(now - 100, now, "ASHARE") == "fresh"     # <=300s
    assert df.freshness(now - 1000, now, "ASHARE") == "delayed"  # 300<age<=1200
    assert df.freshness(now - 100000, now, "ASHARE") == "stale"  # >1200
    assert df.freshness(None, now, "ASHARE") == "delayed"        # 未知 → 保守(非 fresh)


def test_lexicon_sentiment():
    df = _df()
    assert df.lexicon_sentiment("公司利好，业绩大涨创新高") > 0
    assert df.lexicon_sentiment("公司利空，业绩暴跌遭处罚") < 0
    assert df.lexicon_sentiment("公司发布日常公告") == 0.0


def test_enrich_news_adds_sentiment_and_hash():
    df = _df()
    e = df.enrich_news({"title": "X公司中标大单利好", "url": "u", "ts": "t", "source": "em"})
    assert float(e["sentiment"]) > 0
    assert e["hash"] and e["summary"]


def test_parse_news_json_defensive():
    df = _df()
    data = {"data": {"web": [
        {"title": "<em>贵州茅台</em>业绩大增", "url": "http://x", "date": "2024-01-15"},
        {"title": "公司公告回购", "url": "http://y", "date": "2024-01-14"}]}}
    out = df.parse_news_json(data)
    assert len(out) == 2
    assert out[0]["title"] == "贵州茅台业绩大增"      # <em> 高亮标签被剥离
    assert out[0]["source"] == "eastmoney"


def test_fetch_quote_sets_data_status(monkeypatch):
    """fetch_quote 必须依据真实 ts 计算 data_status，不再恒为 fresh。"""
    df = _df()
    old_ts = 1000.0  # 远古时间 → stale

    async def fake_fetch(code):
        return {"name": "x", "prev_close": 10.0, "price": 11.0, "volume": 5.0, "ts": old_ts}

    monkeypatch.setattr(df, "_fetch_sina", fake_fetch)
    q = asyncio.run(df.fetch_quote("ASHARE:600519"))
    assert q["ts"] == old_ts
    assert q["data_status"] == "stale"
