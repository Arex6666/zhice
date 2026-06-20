"""新闻去重/聚类（防重复头条伪造共识）+ 新闻新鲜度衰减。"""
import importlib.util


def _nc():
    s = importlib.util.spec_from_file_location("nc", "services/mcp-tool-service/news_cluster.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_jaccard_identical_and_different():
    nc = _nc()
    assert nc.jaccard("贵州茅台业绩大增", "贵州茅台业绩大增") == 1.0
    assert nc.jaccard("贵州茅台业绩大增", "平安银行计划回购股份") < 0.3


def test_cluster_collapses_cross_source_duplicates():
    nc = _nc()
    items = [{"title": "贵州茅台一季度营收大增35%", "source": "sina"},
             {"title": "贵州茅台一季度营收大增35%", "source": "eastmoney"},
             {"title": "贵州茅台一季度营收大增 35%", "source": "yahoo"},
             {"title": "央行宣布全面降准0.5个百分点", "source": "sina"}]
    cl = nc.cluster_news(items, threshold=0.6)
    assert len(cl) == 2
    top = cl[0]
    assert top["count"] == 3 and top["n_sources"] == 3


def test_dedupe_adds_corroboration():
    nc = _nc()
    items = [{"title": "X公司中标百亿大单", "source": "a"},
             {"title": "X公司中标百亿大单", "source": "b"}]
    out = nc.dedupe_and_enrich(items)
    assert len(out) == 1 and out[0]["corroboration"] == 2 and out[0]["n_sources"] == 2


def test_news_status_decay():
    nc = _nc()
    now = 1_000_000.0
    fresh = nc.news_status(now - 3600, now)        # 1 小时前
    assert fresh["news_status"] == "fresh" and 0.9 < fresh["decay_weight"] < 1.0
    stale = nc.news_status(now - 3600 * 100, now)  # 100 小时前
    assert stale["news_status"] == "stale" and stale["decay_weight"] < 0.1


def test_news_status_unknown_ts():
    nc = _nc()
    out = nc.news_status(None, 1_000_000.0)
    assert out["news_status"] == "unknown"
