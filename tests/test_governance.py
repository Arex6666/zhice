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


def test_R10_non_pit_factor_caps():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    ff = [{"factor": "EP", "pit_status": "forward_pit_only", "history_depth": 300, "bh_passed": True}]
    r = g.govern(m, "fresh", None, True, factor_flags=ff)
    assert r["ceiling"] <= 0.65 and any("R10" in x for x in r["report"])


def test_R11_ic_decay_caps():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    ff = [{"factor": "Mom", "pit_status": "history_native", "history_depth": 1000,
           "bh_passed": True, "ic_verdict": "衰减中"}]
    r = g.govern(m, "fresh", None, True, factor_flags=ff)
    assert r["ceiling"] <= 0.6 and any("R11" in x for x in r["report"])


def test_R12_excludes_invalid_factor():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    ff = [{"factor": "junk", "bh_passed": False}]
    r = g.govern(m, "fresh", None, True, factor_flags=ff)
    assert any("R12" in x and "排除" in x for x in r["report"])


def test_R10_history_depth_none_caps_no_crash():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    ff = [{"factor": "X", "pit_status": "history_native", "history_depth": None, "bh_passed": True}]
    r = g.govern(m, "fresh", None, True, factor_flags=ff)   # 不得抛 TypeError(→502)
    assert r["ceiling"] <= 0.65 and any("R10" in x for x in r["report"])


def test_zero_confidence_dissenter_still_caps_R3():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.0, "evidence": [_ev()], "abstain": False},
         {"verdict": "偏空", "confidence": 0.7, "evidence": [_ev("market")], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["conflict"] is True and r["ceiling"] < 0.85 and any("R3" in x for x in r["report"])


def test_R13_portfolio_not_beat_one_over_n():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    r = g.govern(m, "fresh", None, True, portfolio_flags={"beats_1overN": None, "capacity_flag": "ok"})
    assert any("R13" in x for x in r["report"])


def test_R10_R13_backward_compatible():
    g = _g()  # 新参数默认 None → 不触发, 与既有 R1-R8 行为一致
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert not any(("R10" in x or "R11" in x or "R12" in x or "R13" in x) for x in r["report"])


def test_R8_volatility_regime_caps():
    """已实现波动 extreme/elevated → R8 封顶置信度；normal 不触发。"""
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    r = g.govern(m, "fresh", None, True, vol_regime="extreme")
    assert r["ceiling"] <= 0.6 and any("R8" in x for x in r["report"])
    r2 = g.govern(m, "fresh", None, True, vol_regime="elevated")
    assert r2["ceiling"] <= 0.7 and any("R8" in x for x in r2["report"])
    r3 = g.govern(m, "fresh", None, True, vol_regime="normal")
    assert not any("R8" in x for x in r3["report"])


def test_disagreement_index_balanced_opposition():
    """势均力敌的对立 → 分歧指数≈1 → R3 梯度天花板降至 0.55。"""
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.8, "evidence": [_ev()], "abstain": False},
         {"verdict": "偏空", "confidence": 0.8, "evidence": [_ev("market")], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["disagreement"] >= 0.9
    assert r["ceiling"] <= 0.55


def test_disagreement_index_lopsided_milder_ceiling():
    """两强偏多 + 一弱偏空 → 分歧低 → 天花板介于 0.55 与 0.85（比死的 0.55 更诚实）。"""
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False},
         {"verdict": "偏多", "confidence": 0.9, "evidence": [_ev("market")], "abstain": False},
         {"verdict": "偏空", "confidence": 0.2, "evidence": [_ev("backtest")], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["conflict"] is True
    assert 0.55 < r["ceiling"] <= 0.85
    assert r["disagreement"] < 0.5


def test_disagreement_index_unanimous_zero():
    g = _g()
    m = [{"verdict": "偏空", "confidence": 0.7, "evidence": [_ev()], "abstain": False},
         {"verdict": "偏空", "confidence": 0.6, "evidence": [_ev("backtest")], "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["disagreement"] == 0.0


def test_R7_uses_model_quantile_when_present():
    """校准概率被压缩时，R7 应按模型自身高分位触发（数据驱动），而非死的 0.6。"""
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    ml = {"abstain": False, "prob_big_move": 0.45, "q_extreme": 0.42}  # 超过自身极端分位
    r = g.govern(m, "fresh", ml, True)
    assert r["ceiling"] <= 0.6 and any("R7" in x for x in r["report"])


def test_R7_quantile_not_triggered_below():
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    ml = {"abstain": False, "prob_big_move": 0.30, "q_extreme": 0.42}  # 低于自身分位
    r = g.govern(m, "fresh", ml, True)
    assert not any("R7" in x for x in r["report"])


def test_R7_fallback_absolute_when_no_quantile():
    """旧模型(无分位)向后兼容：回退绝对阈值 0.6。"""
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    ml = {"abstain": False, "prob_big_move": 0.75}
    r = g.govern(m, "fresh", ml, True)
    assert r["ceiling"] <= 0.6 and any("R7" in x for x in r["report"])


def test_model_and_stat_evidence_are_substantive():
    """ML(model) 与统计检验(stat) 证据应被视为实质证据，不被 R1/R6 降级。"""
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.8,
          "evidence": [{"type": "model", "source": "ml_signal",
                        "value": "prob_big_move=0.7", "interpretation": "高波动风险"}],
          "abstain": False}]
    r = g.govern(m, "fresh", None, True)
    assert r["members_adjusted"][0]["verdict"] == "偏多"
    m2 = [{"verdict": "偏空", "confidence": 0.8,
           "evidence": [{"type": "stat", "source": "block_bootstrap",
                         "value": "p=0.03", "interpretation": "边际显著"}],
           "abstain": False}]
    r2 = g.govern(m2, "fresh", None, True)
    assert r2["members_adjusted"][0]["verdict"] == "偏空"


def test_delayed_and_fallback_capped_R2():
    """delayed/fallback 数据应被 R2 中间档(<=0.65)封顶；fresh 不受影响。"""
    g = _g()
    m = [{"verdict": "偏多", "confidence": 0.9, "evidence": [_ev()], "abstain": False}]
    for st in ("delayed", "fallback"):
        r = g.govern(m, st, None, True)
        assert r["ceiling"] <= 0.65, st
        assert any("R2" in x for x in r["report"]), st
    assert g.govern(m, "fresh", None, True)["ceiling"] == 0.85
