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
