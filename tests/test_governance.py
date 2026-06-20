import importlib.util


def _g():
    s = importlib.util.spec_from_file_location("gov", "services/agent-service/governance.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _ev(t="indicator"):
    return {"type": t, "source": "get_indicators", "value": "MA5>MA20", "interpretation": "多头"}


def test_no_evidence_downgraded_and_neutral_direction():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["members_adjusted"][0]["verdict"] == "中性"  # R1
    assert r["allowed_verdicts"] == {"中性"}  # 无存活强结论 → 方向限定中性


def test_empty_typed_evidence_is_not_substantive():
    g = _g()
    # evidence 有条目但缺 source/value → 不算实质证据 → R1 降级
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [{"type": "indicator"}], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["members_adjusted"][0]["verdict"] == "中性"


def test_stale_caps_confidence():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    r = g.govern(m, "stale", None, True)
    assert r["ceiling"] <= 0.4 and any("R2" in x for x in r["report"])
    assert "偏多" in r["allowed_verdicts"]  # 证据充分 → 方向保留


def test_conflict_flagged():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.8, "evidence": [_ev()], "abstain": False},
         {"verdict": "偏空", "confidence": 0.8, "evidence": [_ev("market")], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["conflict"] is True and r["ceiling"] <= 0.55
    assert {"偏多", "偏空", "中性"} == r["allowed_verdicts"]


def test_unanimous_direction_allowed_set():
    g = _g()
    m = [{"verdict": "偏空", "confidence": 0.7, "evidence": [_ev()], "abstain": False},
         {"verdict": "偏空", "confidence": 0.6, "evidence": [_ev("backtest")], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["allowed_verdicts"] == {"偏空", "中性"}


def test_only_sentiment_downgraded_R6():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.8,
          "evidence": [_ev("news_sentiment"), _ev("news_inference")], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["members_adjusted"][0]["verdict"] == "中性" and any("R6" in x for x in r["report"])


def test_rule_order_no_false_conflict():
    g = _g()
    # 一个偏多(实质证据) + 一个偏空(仅情绪) → R6 先把偏空降为中性 → 不应判为冲突
    m = [{"verdict": "偏多", "confidence": 0.8, "evidence": [_ev()], "abstain": False},
         {"verdict": "偏空", "confidence": 0.8, "evidence": [_ev("news_sentiment")], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["conflict"] is False  # R6 在 R3 之前执行
    assert r["allowed_verdicts"] == {"偏多", "中性"}


def test_ml_abstain_and_unstable_backtest():
    g = _g()
    m = [{"verdict": "中性", "confidence": 0.5, "evidence": [_ev()], "abstain": False}]
    r = g.govern(m, "fresh", {"abstain": True}, False)
    assert any("R4" in x for x in r["report"]) and r["ceiling"] <= 0.6


def test_high_volatility_caps_confidence_R7():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    r = g.govern(m, "fresh", {"abstain": False, "prob_big_move": 0.75}, True)
    assert r["ceiling"] <= 0.6 and any("R7" in x for x in r["report"])
