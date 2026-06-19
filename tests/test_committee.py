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

    ml = {"prob_up": 0.7, "abstain": False, "auc": 0.62}
    out = asyncio.run(com.run_committee("US:AAPL", gather, llm, "m", ml=ml))
    lenses = [m["lens"] for m in out["members"]]
    assert "XGBoost信号校准器" in lenses  # 5th vote present
