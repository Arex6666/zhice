"""L1 因子 DSL：时序算子 + AST 安全求值（白名单，拒 eval/属性访问/任意调用）。"""
import importlib.util

import numpy as np
import pytest


def _fd():
    s = importlib.util.spec_from_file_location("fd", "services/mcp-tool-service/factor_dsl.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_ts_mean_and_delay():
    fd = _fd()
    x = [1, 2, 3, 4, 5]
    assert np.allclose(fd.OPS["ts_mean"](x, 2)[1:], [1.5, 2.5, 3.5, 4.5])
    d = fd.OPS["delay"](x, 1)
    assert np.isnan(d[0]) and np.allclose(d[1:], [1, 2, 3, 4])


def test_delta():
    fd = _fd()
    out = fd.OPS["delta"]([10, 12, 9], 1)
    assert np.isnan(out[0]) and np.allclose(out[1:], [2, -3])


def test_evaluate_arithmetic():
    fd = _fd()
    out = fd.evaluate("C - O", {"C": np.array([3.0, 4.0]), "O": np.array([1.0, 1.0])})
    assert np.allclose(out, [2.0, 3.0])


def test_evaluate_momentum_formula():
    fd = _fd()
    C = np.array([100 * (1.001 ** i) for i in range(300)])  # 单调上涨
    out = fd.evaluate("Ref(C,21)/Ref(C,252)-1", {"C": C})
    assert out[-1] > 0                                       # 动量为正
    assert np.isnan(out[0])                                  # 预热期 NaN


def test_evaluate_rejects_unsafe():
    fd = _fd()
    with pytest.raises(Exception):
        fd.evaluate("__import__('os').system('x')", {"C": [1.0]})
    with pytest.raises(Exception):
        fd.evaluate("C.__class__", {"C": [1.0]})            # 属性访问
    with pytest.raises(Exception):
        fd.evaluate("open('x')", {"C": [1.0]})              # 非白名单调用
    with pytest.raises(Exception):
        fd.evaluate("Z + 1", {"C": [1.0]})                  # 未知变量
