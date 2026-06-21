"""L2 离线批 run_batch（依赖注入核心，脱网可测）。"""
import importlib.util


def _rb():
    s = importlib.util.spec_from_file_location("rb", "scripts/run_factor_eval_batch.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_run_batch_posts_each_factor():
    rb = _rb()
    posted = []
    out = rb.run_batch(
        {"A": [1]},
        factor_report_fn=lambda fp, wp: {"significant": 1, "mean_rank_ic": 0.05},
        build_panels_fn=lambda kl, f: ([[1, 2]], [[0.1, 0.2]]),
        post_fn=lambda row: posted.append(row),
        factors=["Mom_12_1", "Rev_5"], as_of="2024-06-01")
    assert out["posted"] == 2 and out["failures"] == 0
    assert posted[0]["factor_name"] == "Mom_12_1" and posted[0]["as_of"] == "2024-06-01"
    assert posted[0]["family"] == "price_volume" and posted[0]["significant"] == 1


def test_run_batch_isolates_failure():
    rb = _rb()

    def report_fn(fp, wp):
        raise RuntimeError("compute boom")

    out = rb.run_batch({"A": [1]}, report_fn, lambda k, f: ([], []), lambda r: None,
                       ["Mom_12_1"], "2024-06-01")
    assert out["failures"] == 1 and out["posted"] == 0
