import asyncio
import importlib.util
import json
import sys
import types


def _committee():
    # committee.py imports `governance`; ensure it resolves to the agent-service module
    sys.path.insert(0, "services/agent-service")
    s = importlib.util.spec_from_file_location("committee", "services/agent-service/committee.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


class FakeLLM:
    """Returns queued JSON dicts in order (4 members then chairman)."""

    def __init__(self, outs):
        self.outs = outs
        self.i = 0
        box = self

        class _Comp:
            @staticmethod
            def create(**kw):
                o = box.outs[min(box.i, len(box.outs) - 1)]
                box.i += 1
                msg = types.SimpleNamespace(content=json.dumps(o, ensure_ascii=False), tool_calls=None)
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

        self.chat = types.SimpleNamespace(completions=_Comp)


def test_committee_governs_confidence_and_disclaimer():
    com = _committee()
    member = {"verdict": "偏多", "confidence": 0.95, "reasons": ["MA多头"],
              "evidence": [{"type": "indicator", "source": "get_indicators",
                            "value": "MA5>MA20", "interpretation": "多头"}],
              "counter_evidence": ["RSI偏高"], "risks": ["回调"], "abstain": False, "abstain_reason": None}
    chair = {"final": "偏多", "confidence": 0.95, "majority": "偏多", "minority": "无",
             "disagreement": "无", "key_evidence": "MA5>MA20", "counter_evidence": "RSI偏高",
             "invalidation": "跌破MA20", "dissent": "无", "max_risk": "回调", "confidence_reason": "证据中等"}
    llm = FakeLLM([member, member, member, member, chair])

    async def gather(sym):
        return {"indicators": {}, "signals": {}, "news": [], "backtest": {},
                "market": {}, "data_status": "stale", "backtest_stable": True}

    out = asyncio.run(com.run_committee("ASHARE:600519", gather, llm, "m", ml=None))
    assert out["confidence"] <= 0.4  # stale → governance ceiling 0.4
    assert "不构成投资建议" in out["disclaimer"]
    assert "governance_report" in out
    assert out["verdict"] == "偏多"
    assert len(out["members"]) == 4


def test_chairman_direction_clamped_to_governance():
    """主席说偏多，但所有委员都无证据被降为中性 → 最终方向必须被治理强制为中性。"""
    com = _committee()
    no_ev = {"verdict": "偏多", "confidence": 0.9, "reasons": ["凭感觉"],
             "evidence": [], "counter_evidence": [], "risks": [],
             "abstain": False, "abstain_reason": None}
    chair = {"final": "偏多", "confidence": 0.9, "confidence_reason": "看多"}
    llm = FakeLLM([no_ev, no_ev, no_ev, no_ev, chair])

    async def gather(sym):
        return {"indicators": {}, "signals": {}, "news": [], "backtest": {},
                "market": {}, "data_status": "fresh", "backtest_stable": True}

    out = asyncio.run(com.run_committee("ASHARE:600519", gather, llm, "m", ml=None))
    assert out["verdict"] == "中性"  # 治理钳制：无据强结论被强制中性
    assert any("强制中性" in x for x in out["governance_report"])


def test_committee_includes_ml_vote():
    com = _committee()
    member = {"verdict": "中性", "confidence": 0.5, "reasons": [],
              "evidence": [{"type": "indicator", "source": "x", "value": "y", "interpretation": "z"}],
              "counter_evidence": [], "risks": [], "abstain": False, "abstain_reason": None}
    chair = {"final": "偏多", "confidence": 0.6, "confidence_reason": "弱信号支持"}
    llm = FakeLLM([member, member, member, member, chair])

    async def gather(sym):
        return {"indicators": {}, "signals": {}, "news": [], "backtest": {},
                "market": {}, "data_status": "fresh", "backtest_stable": True}

    ml = {"prob_big_move": 0.7, "abstain": False, "auc": 0.62}
    out = asyncio.run(com.run_committee("US:AAPL", gather, llm, "m", ml=ml))
    lenses = [m["lens"] for m in out["members"]]
    assert "XGBoost风险信号(波动)" in lenses  # 风险信号票 present
    assert out["confidence"] <= 0.6  # R7: 高波动预警→封顶


def test_chairman_non_dict_degrades_to_neutral():
    """主席输出为 JSON 数组等非 dict 时，必须降级为保守中性，而非抛 AttributeError(502)。"""
    com = _committee()
    member = {"verdict": "中性", "confidence": 0.5, "reasons": [],
              "evidence": [{"type": "indicator", "source": "x", "value": "y", "interpretation": "z"}],
              "counter_evidence": [], "risks": [], "abstain": False, "abstain_reason": None}
    chair_bad = ["not", "a", "dict"]  # 主席输出畸形（JSON 数组）
    llm = FakeLLM([member, member, member, member, chair_bad])

    async def gather(sym):
        return {"indicators": {}, "signals": {}, "news": [], "backtest": {},
                "market": {}, "data_status": "fresh", "backtest_stable": True}

    out = asyncio.run(com.run_committee("ASHARE:600519", gather, llm, "m", ml=None))
    assert out["verdict"] == "中性"
    assert out["confidence"] <= 0.3


def test_ml_member_evidence_tagged_model():
    """ML 风险票证据应标 type='model'（而非误标 'backtest'），以保证证据溯源正确。"""
    com = _committee()
    mlm = com._ml_member({"prob_big_move": 0.7, "abstain": False, "auc": 0.6})
    assert mlm is not None
    assert mlm["evidence"][0]["type"] == "model"


def test_factor_member_vote_three_gates_pass():
    """§10.3 三闸全过(family有效稳定+显著 AND 极端分位 AND 控制风格后仍极端)→出 stat 证据。"""
    com = _committee()
    fe = {"factor_name": "Mom", "family_verdict": "有效稳定", "significant": 1,
          "direction": "+", "mean_rank_ic": 0.05, "pit_status": "history_native"}
    v = com.factor_member_vote(fe, stock_quantile=4, residual_quantile=4, n_quantiles=5)
    assert v["abstain"] is False and v["verdict"] == "偏多"
    assert v["evidence"][0]["type"] == "stat"


def test_factor_member_vote_abstentions():
    com = _committee()
    base = {"factor_name": "Mom", "family_verdict": "有效稳定", "significant": 1, "direction": "+"}
    # 闸1: family 未显著
    assert com.factor_member_vote({**base, "significant": 0, "family_verdict": "失效"},
                                  4, 4)["abstain"] is True
    # 闸2: 非极端分位
    assert com.factor_member_vote(base, 2, 2)["abstain"] is True
    # 闸3: 控制风格后不再极端(残差分位非极端) → 被风格解释
    v = com.factor_member_vote(base, 4, 2)
    assert v["abstain"] is True and v["abstain_reason"] == "style_explained"


def test_factor_member_vote_direction_bottom_quantile():
    com = _committee()
    fe = {"factor_name": "IdioVol", "family_verdict": "有效稳定", "significant": 1, "direction": "-"}
    # 底部分位 + 负向因子 → 看多 (低特异波动好)
    v = com.factor_member_vote(fe, stock_quantile=0, residual_quantile=0, n_quantiles=5)
    assert v["abstain"] is False and v["verdict"] == "偏多"


def test_cross_examination_downgrades_unrebutted_dominant():
    """冲突时，对最高置信度强结论委员发一次交叉质询；其只拿得出情绪证据→R9 降级为中性。"""
    com = _committee()
    bull = {"verdict": "偏多", "confidence": 0.9, "reasons": [],
            "evidence": [{"type": "indicator", "source": "ind", "value": "MA5>MA20", "interpretation": "多头"}],
            "counter_evidence": [], "risks": [], "abstain": False, "abstain_reason": None}
    bear = {"verdict": "偏空", "confidence": 0.6, "reasons": [],
            "evidence": [{"type": "market", "source": "mkt", "value": "大盘跌2%", "interpretation": "空"}],
            "counter_evidence": [], "risks": [], "abstain": False, "abstain_reason": None}
    neutral = {"verdict": "中性", "confidence": 0.3,
               "evidence": [{"type": "indicator", "source": "x", "value": "y", "interpretation": "z"}],
               "counter_evidence": [], "risks": [], "abstain": False, "abstain_reason": None}
    # 交叉质询回复：只有情绪证据 → 未能以实质证据反驳 → 降级
    xexam = {"verdict": "偏多", "confidence": 0.9,
             "evidence": [{"type": "news_sentiment", "source": "n", "value": "市场看多情绪", "interpretation": "利好"}],
             "abstain": False}
    chair = {"final": "中性", "confidence": 0.4, "confidence_reason": "分歧未消"}
    llm = FakeLLM([bull, bear, neutral, neutral, xexam, chair])

    async def gather(sym):
        return {"indicators": {}, "signals": {}, "news": [], "backtest": {},
                "market": {}, "data_status": "fresh", "backtest_stable": True}

    out = asyncio.run(com.run_committee("ASHARE:600519", gather, llm, "m", ml=None))
    assert any("R9" in x and "降级" in x for x in out["governance_report"])
    # 被质询降级后，不应再有存活的偏多强结论委员
    assert "偏多" not in {m["verdict"] for m in out["members"] if not m.get("abstain")}


def test_evidence_type_reverified_triggers_R6():
    """委员把'推断'伪标为 news_fact 时，委员会独立重核类型→改判 news_inference→R6 降级。"""
    com = _committee()
    faker = {"verdict": "偏多", "confidence": 0.9, "reasons": ["看多"],
             "evidence": [{"type": "news_fact", "source": "news",
                           "value": "预计明年营收有望翻倍", "interpretation": "重大利好"}],
             "counter_evidence": [], "risks": [], "abstain": False, "abstain_reason": None}
    chair = {"final": "偏多", "confidence": 0.8, "confidence_reason": "看多"}
    llm = FakeLLM([faker, faker, faker, faker, chair])

    async def gather(sym):
        return {"indicators": {}, "signals": {}, "news": [], "backtest": {},
                "market": {}, "data_status": "fresh", "backtest_stable": True}

    out = asyncio.run(com.run_committee("ASHARE:600519", gather, llm, "m", ml=None))
    assert out["verdict"] == "中性"  # 重核改判 + R6 → 强制中性
    assert any("R6" in x for x in out["governance_report"])
    # 被改判的证据保留原标注以供审计
    ev = out["members"][0]["evidence"][0]
    assert ev["type"] == "news_inference" and ev.get("type_reverified") == "news_fact"
