"""L3-bug: 因子除零产 ±Inf 不得穿透进 MCP 返回(非法 JSON Infinity)。"""
import importlib.util
import json
import math
import sys


def _fd():
    sys.path.insert(0, "services/mcp-tool-service")
    s = importlib.util.spec_from_file_location("fd_inf", "services/mcp-tool-service/factor_dsl.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_safe_div_zero_denominator_is_nan_not_inf():
    fd = _fd()
    import numpy as np
    out = fd.evaluate("C / O", {"C": np.array([1.0, 2.0]), "O": np.array([0.0, 2.0])})
    assert math.isnan(out[0]) and out[1] == 1.0          # 0 分母→NaN, 非 inf


def test_rev5_zero_close_no_inf_leak():
    fd = _fd()
    import numpy as np
    C = np.array([10.0, 0.0, 0.0, 0.0, 0.0, 5.0, 6.0, 7.0])  # 含 0 收盘
    out = fd.evaluate("-(C/Ref(C,5)-1)", {"C": C})
    assert not any(math.isinf(v) for v in out if v == v)  # 无 inf 穿透
    # 模拟 mcp_server 序列化清洗后是合法 JSON
    cleaned = [None if not math.isfinite(v) else float(v) for v in out]
    json.loads(json.dumps(cleaned))                       # 不抛
