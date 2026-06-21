"""L2 purged + embargoed 时序 CV（防标签重叠泄漏，López de Prado）。"""
import importlib.util


def _pc():
    s = importlib.util.spec_from_file_location("pc", "services/mcp-tool-service/panel_cv.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_purged_split_removes_overlap():
    pc = _pc()
    folds = pc.purged_split(100, n_splits=5, embargo=3, horizon=5)
    assert len(folds) == 5
    for tr, te in folds:
        lo, hi = min(te) - 3, max(te) + 5            # purge+embargo 区
        assert all(not (lo <= i <= hi) for i in tr)  # 训练集不含 purge 区任何样本
        assert set(te).isdisjoint(set(tr))           # 训练/测试不相交
        assert te == sorted(te) and tr == sorted(tr)  # 时序保持


def test_purged_split_covers_all_test_indices():
    pc = _pc()
    folds = pc.purged_split(50, n_splits=5, embargo=0, horizon=0)
    covered = sorted(i for _, te in folds for i in te)
    assert covered == list(range(50))                # 各 test 折并集=全样本


def test_too_few_samples_returns_empty():
    pc = _pc()
    assert pc.purged_split(3, n_splits=5, embargo=2, horizon=2) == []


def test_purged_split_no_lookahead_label_leak():
    """H1: 左侧按 horizon purge——任何训练样本的标签窗 [i,i+horizon] 不得伸入测试期。"""
    pc = _pc()
    horizon, embargo = 5, 3                     # embargo<horizon, 暴露旧 bug
    folds = pc.purged_split(100, n_splits=5, embargo=embargo, horizon=horizon)
    assert len(folds) == 5
    for tr, te in folds:
        start = min(te)
        for i in tr:
            assert not (i < start and i + horizon >= start), f"label leak: train {i}"
    # 钉死: embargo<horizon 时 idx 15/16(标签窗伸入测试折2起点20)必被剔除
    tr2, _ = folds[1]
    assert 15 not in tr2 and 16 not in tr2


def test_embargo_applied_to_future_side_only():
    """H2: embargo 施加在测试块未来侧, 过去侧仅按 horizon。"""
    pc = _pc()
    tr, te = pc.purged_split(100, n_splits=5, embargo=3, horizon=0)[1]   # test=[20..39]
    assert 40 not in tr and 41 not in tr and 42 not in tr   # 未来侧被 embargo 剔除
    assert 17 in tr and 18 in tr and 19 in tr               # 过去侧(horizon=0)保留


def test_horizon_purges_past_side():
    pc = _pc()
    tr, te = pc.purged_split(100, n_splits=5, embargo=0, horizon=3)[1]   # test=[20..39]
    assert 17 not in tr and 18 not in tr and 19 not in tr   # 标签窗[i,i+3]伸入测试起点20→purge
    assert 16 in tr                                          # 标签窗[16,19]不及20→保留
