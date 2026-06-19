import importlib.util


def _g():
    s = importlib.util.spec_from_file_location("gov", "services/agent-service/governance.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_no_evidence_downgraded():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["members_adjusted"][0]["verdict"] == "中性"  # R1


def test_stale_caps_confidence():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [{"type": "indicator"}], "abstain": False}]
    r = g.govern(m, "stale", None, True)
    assert r["ceiling"] <= 0.4 and any("R2" in x for x in r["report"])


def test_conflict_flagged():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.8, "evidence": [{"type": "indicator"}], "abstain": False},
         {"verdict": "偏空", "confidence": 0.8, "evidence": [{"type": "market"}], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["conflict"] is True and r["ceiling"] <= 0.55


def test_ml_abstain_reported():
    g = _g()
    m = [{"verdict": "中性", "confidence": 0.5, "evidence": [{"type": "indicator"}], "abstain": False}]
    r = g.govern(m, "fresh", {"abstain": True}, True)
    assert any("R4" in x for x in r["report"])


def test_unstable_backtest_caps():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [{"type": "backtest"}], "abstain": False}]
    r = g.govern(m, "fresh", None, False)
    assert r["ceiling"] <= 0.6 and any("R5" in x for x in r["report"])


def test_only_sentiment_downgraded():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.8,
          "evidence": [{"type": "news_sentiment"}, {"type": "news_inference"}], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["members_adjusted"][0]["verdict"] == "中性" and any("R6" in x for x in r["report"])
