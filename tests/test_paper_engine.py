# -*- coding: utf-8 -*-
"""AI 量化模拟引擎(横截面反转 top-K, 持续调仓)——纯函数、脱网可测。

守则测试:
  - 结账恒等: 每日 现金+持仓市值 == 权益。
  - 反转选股: 近端跌最多者被买入(top_k=1)。
  - **无未来函数不变量**: 改动"未来"某日价格, 不得改变该日之前的任何一笔交易。
"""
import copy
import importlib.util


def _eng():
    s = importlib.util.spec_from_file_location("pe", "services/mcp-tool-service/paper_engine.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def _panel(symbols_closes, name_prefix="股"):
    n = len(next(iter(symbols_closes.values())))
    return {"dates": [f"2026-01-{i+1:02d}" for i in range(n)],
            "symbols": {s: {"name": f"{name_prefix}{s}", "closes": c}
                        for s, c in symbols_closes.items()}}


PARAMS = {"lookback": 5, "rebalance": 5, "top_k": 1, "cost": 0.001,
          "principal": 10000.0, "warmup": 5}


def test_accounting_identity_and_structure():
    eng = _eng()
    panel = _panel({
        "A": [100, 102, 104, 106, 108, 110, 111, 112, 113, 114, 115, 116],
        "B": [100, 100, 100, 100, 100, 100, 101, 102, 103, 104, 105, 106],
        "C": [100, 98, 96, 94, 92, 90, 91, 92, 93, 94, 95, 96],
    })
    r = eng.simulate(panel, PARAMS)
    assert len(r["equity"]) == 12 - 5           # t = warmup..T-1
    for pt in r["equity"]:
        assert abs((pt["cash"] + pt["invested"]) - pt["equity"]) < 1e-6   # 结账恒等
    assert r["equity"][0]["equity"] <= 10000.0 + 1e-6                      # 起始≈本金(成本略减)
    assert r["equity"][0]["equity"] > 9900.0
    for tr in r["trades"]:
        for k in ("date", "action", "symbol", "name", "price", "shares", "value"):
            assert k in tr
        assert tr["action"] in ("buy", "sell")
    for k in ("final_equity", "total_return", "benchmark_return", "n_trades",
              "win_rate", "max_drawdown"):
        assert k in r["stats"]


def test_reversal_buys_the_biggest_loser():
    eng = _eng()
    # 到 t=5: A 涨10%, B 平, C 跌10% → 反转应买入 C(top_k=1)
    panel = _panel({
        "A": [100, 102, 104, 106, 108, 110, 110, 110, 110, 110, 110, 110],
        "B": [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100],
        "C": [100, 98, 96, 94, 92, 90, 90, 90, 90, 90, 90, 90],
    })
    r = eng.simulate(panel, PARAMS)
    first_buy = next(t for t in r["trades"] if t["action"] == "buy")
    assert first_buy["symbol"] == "C"


def test_no_lookahead_invariant():
    eng = _eng()
    base = {
        "A": [100, 101, 103, 102, 104, 103, 105, 104, 106, 108, 107, 109, 110, 108, 111, 112],
        "B": [100, 99, 98, 100, 101, 99, 97, 98, 100, 102, 101, 99, 98, 100, 101, 103],
        "C": [100, 102, 101, 99, 98, 100, 101, 103, 102, 100, 99, 101, 103, 104, 102, 101],
    }
    panel = _panel(base)
    r1 = eng.simulate(panel, PARAMS)
    # 篡改"最后一天"所有价格(纯未来信息)
    panel2 = copy.deepcopy(panel)
    last = len(panel2["dates"]) - 1
    for s in panel2["symbols"]:
        panel2["symbols"][s]["closes"][last] = panel2["symbols"][s]["closes"][last] * 1.5
    r2 = eng.simulate(panel2, PARAMS)
    last_date = panel["dates"][last]
    tr1 = [t for t in r1["trades"] if t["date"] != last_date]
    tr2 = [t for t in r2["trades"] if t["date"] != last_date]
    assert tr1 == tr2   # 未来价格不得影响过去任何交易 → 无前视
