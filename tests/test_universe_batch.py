"""③b 评估池扩到中证300：成分解析 + 取池(依赖注入脱网可测)。"""
import importlib.util


def _rb():
    s = importlib.util.spec_from_file_location("rb", "scripts/run_factor_eval_batch.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_parse_universe_handles_column_variants_and_pads():
    rb = _rb()
    rows = [{"成分券代码": "600519"}, {"品种代码": 858}, {"证券代码": "300750.SZ"}, {"x": None}]
    out = rb.parse_universe(rows)
    assert out == ["600519", "000858", "300750"]   # 补零 + 去交易所后缀 + 跳空


def test_parse_universe_limit():
    rb = _rb()
    rows = [{"symbol": f"60000{i}"} for i in range(10)]
    assert len(rb.parse_universe(rows, limit=3)) == 3


def test_fetch_universe_injectable():
    rb = _rb()

    class _DF:
        def to_dict(self, _):
            return [{"成分券代码": "600519"}, {"成分券代码": "000001"}]

    syms = rb._fetch_universe(fetch_fn=lambda: _DF(), limit=None)
    assert syms == ["600519", "000001"]
