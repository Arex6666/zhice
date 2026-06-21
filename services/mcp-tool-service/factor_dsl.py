"""因子 DSL（纯函数 + AST 安全求值）。

Qlib 式时序算子（仅单标的时序 + 算术/比较/If）。求值经 **手写 AST 遍历 + 白名单**，
严禁 eval / 属性访问 / 任意函数调用 / 未知变量 —— 杜绝注入与隐含未来函数算子。
横截面算子（Rank/zscore/中性化）交给 preprocess 逐截面执行以防泄漏。
"""
import ast

import numpy as np
import pandas as pd


def _arr(x):
    return np.asarray(x, dtype=float)


def _delay(x, n):
    x = _arr(x)
    n = int(n)
    if n <= 0:
        return x.copy()
    out = np.full(len(x), np.nan)
    if n < len(x):
        out[n:] = x[:len(x) - n]
    return out


def _delta(x, n):
    return _arr(x) - _delay(x, n)


def _roll(x, n, how):
    s = pd.Series(_arr(x)).rolling(int(n))
    return getattr(s, how)().to_numpy()


def _ema(x, n):
    return pd.Series(_arr(x)).ewm(span=int(n), adjust=False).mean().to_numpy()


def _corr(x, y, n):
    return pd.Series(_arr(x)).rolling(int(n)).corr(pd.Series(_arr(y))).to_numpy()


def _slope(x, n):
    """滚动对时间索引的 OLS 斜率。"""
    x = _arr(x)
    n = int(n)
    out = np.full(len(x), np.nan)
    t = np.arange(n, dtype=float)
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    if denom == 0:
        return out
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        out[i] = float((tc * (w - w.mean())).sum() / denom)
    return out


def _scale(x):
    x = _arr(x)
    s = np.nansum(np.abs(x))
    return x / s if s else x


def _if(cond, a, b):
    return np.where(_arr(cond) != 0, _arr(a), _arr(b))


OPS = {
    "ts_mean": lambda x, n: _roll(x, n, "mean"),
    "ts_std": lambda x, n: pd.Series(_arr(x)).rolling(int(n)).std(ddof=0).to_numpy(),
    "ts_max": lambda x, n: _roll(x, n, "max"),
    "ts_min": lambda x, n: _roll(x, n, "min"),
    "delay": _delay, "Ref": _delay, "delta": _delta, "ema": _ema,
    "corr": _corr, "slope": _slope, "scale": _scale, "If": _if,
    "Abs": lambda x: np.abs(_arr(x)), "Log": lambda x: np.log(_arr(x)),
    "Sign": lambda x: np.sign(_arr(x)),
}

_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
_CMPOPS = {ast.Gt: lambda a, b: (_arr(a) > _arr(b)).astype(float),
           ast.Lt: lambda a, b: (_arr(a) < _arr(b)).astype(float)}


def _ev(node, data):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"非法常量: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in data:
            return _arr(data[node.id])
        raise ValueError(f"未知变量: {node.id}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_ev(node.operand, data)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_ev(node.left, data), _ev(node.right, data))
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMPOPS:
        return _CMPOPS[type(node.ops[0])](_ev(node.left, data), _ev(node.comparators[0], data))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in OPS:
            raise ValueError(f"非白名单调用: {getattr(node.func, 'id', node.func)}")
        if node.keywords:
            raise ValueError("不允许关键字参数")
        return OPS[node.func.id](*[_ev(a, data) for a in node.args])
    raise ValueError(f"不允许的语法节点: {type(node).__name__}")


def evaluate(formula, data):
    """对公式字符串安全求值。data: {'C':收盘, 'O':开, 'H':高, 'L':低, 'V':量} 时序数组。"""
    tree = ast.parse(str(formula), mode="eval")
    return _ev(tree.body, data)
