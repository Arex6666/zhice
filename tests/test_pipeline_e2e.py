"""端到端管线烟测：取因子(L1)→中性化(L1)→合成(L3)→IC评估(L2)→组合(L4)→对比1/N。

全合成数据、脱网；证明 L1–L4 引擎拼接正确（管线正确性，非 alpha 证据，对齐 spec §14.1）。
"""
import importlib.util
import sys

import numpy as np


def _load(name, path):
    sys.path.insert(0, "services/mcp-tool-service")
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_end_to_end_factor_to_portfolio():
    base = "services/mcp-tool-service/"
    zoo = _load("zoo_e2e", base + "zoo.py")
    pre = _load("pre_e2e", base + "preprocess.py")
    fc = _load("fc_e2e", base + "factor_combine.py")
    fe = _load("fe_e2e", base + "factor_eval.py")
    pf = _load("pf_e2e", base + "portfolio.py")
    rng = np.random.RandomState(0)

    # L1: 用 DSL 在合成上涨价格上算动量
    C = np.array([100 * (1.001 ** i) for i in range(300)])
    mom = zoo.compute("Mom_12_1", {"C": C, "V": np.full(300, 1e6)})
    assert mom[-1] > 0

    # L1: 一个截面预处理(中性化)
    n = 60
    ind = ["A" if i % 2 else "B" for i in range(n)]
    lnmc = rng.randn(n)
    vals = rng.randn(n) + 0.5 * lnmc
    neut = pre.neutralize(vals, ind, lnmc)
    assert neut["data_quality"] == "ok"

    # L3: 两因子线性合成
    score = fc.combine({"f1": rng.randn(n), "f2": rng.randn(n)},
                       {"f1": "+", "f2": "+"})
    assert len(score) == n

    # L2: 面板 IC 评估(信息因子→显著)
    fac, ret = [], []
    for _ in range(40):
        r = rng.randn(50)
        fac.append(r + 0.5 * rng.randn(50))
        ret.append(r)
    rep = fe.factor_report(fac, ret)
    assert rep["significant"] == 1

    # L4: ERC 组合 + 对比 1/N
    R = np.array(ret)                       # 40 obs × 50 assets
    syms = [f"S{i}" for i in range(50)]
    port = pf.build_portfolio(syms, scores=None, returns_panel=R, method="erc")
    w = np.array([port["weights"][s] for s in syms])
    assert abs(w.sum() - 1) < 1e-6
    b = pf.beats_one_over_n(R @ w, R @ (np.ones(50) / 50))
    assert "beats" in b                     # 端到端跑通
