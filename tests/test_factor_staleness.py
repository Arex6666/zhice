"""committee.factor_member_vote 的 staleness 弃权（陈旧 factor_eval → abstain）。"""
import datetime
import importlib.util
import sys


def _cm():
    sys.path.insert(0, "services/agent-service")
    s = importlib.util.spec_from_file_location("cm", "services/agent-service/committee.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _fe(computed_at):
    return {"factor_name": "Mom_12_1", "family_verdict": "有效稳定", "significant": 1,
            "direction": "+", "mean_rank_ic": 0.05, "computed_at": computed_at}


def test_stale_factor_eval_abstains():
    cm = _cm()
    now = datetime.date(2026, 6, 21)
    out = cm.factor_member_vote(_fe("2026-05-01"), 4, 4, n_quantiles=5, now=now)  # 51 天前
    assert out["abstain"] is True and out["abstain_reason"] == "insufficient_history"


def test_fresh_factor_eval_passes_through_to_mapping():
    cm = _cm()
    now = datetime.date(2026, 6, 21)
    out = cm.factor_member_vote(_fe("2026-06-18"), 4, 4, n_quantiles=5, now=now)  # 3 天前
    assert out["abstain"] is False and out["verdict"] == "偏多"


def test_missing_computed_at_does_not_block():
    cm = _cm()
    fe = _fe(None)
    out = cm.factor_member_vote(fe, 4, 4, n_quantiles=5, now=datetime.date(2026, 6, 21))
    assert out["abstain"] is False     # 无 computed_at 不因 staleness 弃权(交给其它闸)
