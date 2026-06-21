"""L7 AlphaEval 五维(无回测)证伪机核心：预测力/扰动稳定性/多样性熵。"""
import importlib.util

import numpy as np


def _ae():
    s = importlib.util.spec_from_file_location("ae", "services/mcp-tool-service/alpha_eval.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_pps_informative_vs_noise():
    ae = _ae()
    rng = np.random.RandomState(0)
    r = rng.randn(200)
    assert ae.pps(r + 0.3 * rng.randn(200), r) > 0.5         # 信息因子预测力高
    assert abs(ae.pps(rng.randn(200), rng.randn(200))) < 0.2  # 噪声≈0


def test_pfs_stable_factor_robust_to_noise():
    ae = _ae()
    assert ae.pfs(np.arange(200.0), noise_scale=0.01) > 0.9   # 小扰动下排序稳定


def test_diversity_entropy_orthogonal_gt_duplicated():
    ae = _ae()
    rng = np.random.RandomState(0)
    orth = rng.randn(100, 5)
    dup = np.repeat(rng.randn(100, 1), 5, axis=1) + 1e-6 * rng.randn(100, 5)
    assert ae.diversity_entropy(orth) > ae.diversity_entropy(dup)


def test_evaluate_combines_and_gates():
    ae = _ae()
    rng = np.random.RandomState(1)
    r = rng.randn(200)
    good = ae.evaluate(r + 0.3 * rng.randn(200), r)
    assert {"pps", "pfs", "diversity_entropy", "passes"} <= set(good)
    assert good["passes"] is True
    assert ae.evaluate(rng.randn(200), rng.randn(200))["passes"] is False  # 噪声不过关
