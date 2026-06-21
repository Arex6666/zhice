"""L1 申万一级行业映射（spec §4 L1 + 核验修正）。

纯解析/哑变量核心可脱网单测（importlib 加载被测模块，参照 test_finance_adapter.py 范式）；
真实 akshare 调用走薄包装 fetch_*（anyio 卸载），失败返 None/{}。
诚实约束：行业归属 PIT 不可得 → INDUSTRY_PIT_STATUS='today_snapshot_only' + caveat 随值同行。
"""
import importlib.util


def _im():
    s = importlib.util.spec_from_file_location(
        "industry_map", "services/mcp-tool-service/industry_map.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


# --- stock_board_industry_name_em 形态: 全市场一级行业列表(行业名 + 行业代码) ---
BOARD_ROWS = [
    {"板块名称": "银行", "板块代码": "BK0475"},
    {"板块名称": "白酒", "板块代码": "BK0477"},
    {"板块名称": "半导体", "板块代码": "BK1036"},
]

# --- stock_individual_info_em 形态: [{'item':..,'value':..}] 长表 ---
INFO_ROWS = [
    {"item": "总市值", "value": 2000000000000.0},
    {"item": "行业", "value": "白酒"},
    {"item": "上市时间", "value": 20010827},
]


def test_parse_industry_list_returns_name_to_code():
    im = _im()
    d = im.parse_industry_list(BOARD_ROWS)
    assert d == {"银行": "BK0475", "白酒": "BK0477", "半导体": "BK1036"}


def test_parse_industry_list_defensive_skips_malformed():
    """缺名称/代码的脏行被跳过，不崩溃、不编造。"""
    im = _im()
    rows = [{"板块名称": "银行", "板块代码": "BK0475"},
            {"板块名称": "", "板块代码": "BK9999"},       # 空名 → 跳
            {"板块名称": "煤炭"},                          # 缺代码 → 跳
            {"foo": "bar"}]                               # 完全不匹配 → 跳
    d = im.parse_industry_list(rows)
    assert d == {"银行": "BK0475"}


def test_parse_industry_list_alt_column_names():
    """兼容备用列名(symbol/name)。"""
    im = _im()
    d = im.parse_industry_list([{"name": "电力", "code": "BK0428"}])
    assert d == {"电力": "BK0428"}


def test_parse_symbol_industry_extracts_industry_field():
    im = _im()
    assert im.parse_symbol_industry(INFO_ROWS) == "白酒"


def test_parse_symbol_industry_missing_returns_none():
    """无'行业'字段 → None（诚实：不可得不编造）。"""
    im = _im()
    rows = [{"item": "总市值", "value": 1.0}, {"item": "上市时间", "value": 20200101}]
    assert im.parse_symbol_industry(rows) is None


def test_parse_symbol_industry_empty_value_returns_none():
    """'行业'存在但值为空/占位 → None。"""
    im = _im()
    assert im.parse_symbol_industry([{"item": "行业", "value": ""}]) is None
    assert im.parse_symbol_industry([{"item": "行业", "value": "-"}]) is None
    assert im.parse_symbol_industry([]) is None


def test_parse_symbol_industry_defensive_on_bad_rows():
    """畸形 rows(非 dict / 缺 item) 不崩溃。"""
    im = _im()
    assert im.parse_symbol_industry([{"value": "白酒"}]) is None         # 缺 item
    assert im.parse_symbol_industry(None) is None
    assert im.parse_symbol_industry("garbage") is None


def test_build_industry_dummies_basic_full_columns():
    """哑变量全列(不去列, 去共线交下游 preprocess/中性化)；行序=symbols 序。"""
    im = _im()
    symbols = ["600519", "601398", "000001"]
    sym2ind = {"600519": "白酒", "601398": "银行", "000001": "银行"}
    matrix, order = im.build_industry_dummies(symbols, sym2ind)
    # 全列 = 出现过的行业集合(确定性排序), 不丢任何列
    assert set(order) == {"白酒", "银行"}
    assert len(matrix) == 3                         # 每 symbol 一行
    for row in matrix:
        assert len(row) == len(order)              # 列数 = 行业数
        assert sum(row) == 1.0                     # one-hot
    bj = order.index("银行")
    bz = order.index("白酒")
    assert matrix[0][bz] == 1.0 and matrix[0][bj] == 0.0   # 600519=白酒
    assert matrix[1][bj] == 1.0                            # 601398=银行
    assert matrix[2][bj] == 1.0                            # 000001=银行


def test_build_industry_dummies_unknown_maps_to_other():
    """未知/缺归属 → 'OTHER'（不丢样本、不编造行业）。"""
    im = _im()
    symbols = ["600519", "999999"]
    sym2ind = {"600519": "白酒"}                   # 999999 缺归属
    matrix, order = im.build_industry_dummies(symbols, sym2ind)
    assert "OTHER" in order
    other = order.index("OTHER")
    assert matrix[1][other] == 1.0                 # 999999 → OTHER one-hot


def test_build_industry_dummies_carries_coverage():
    """返回结构带 coverage(有真实归属的占比)，诚实标随结构同行。"""
    im = _im()
    symbols = ["a", "b", "c", "d"]
    sym2ind = {"a": "银行", "b": "白酒"}            # 2/4 有归属
    matrix, order, meta = im.build_industry_dummies(symbols, sym2ind, with_meta=True)
    assert abs(meta["coverage"] - 0.5) < 1e-9
    assert meta["n"] == 4 and meta["n_known"] == 2
    assert meta["industry_pit_status"] == "today_snapshot_only"
    assert meta.get("caveat")                       # caveat 非空


def test_build_industry_dummies_empty_symbols():
    im = _im()
    matrix, order = im.build_industry_dummies([], {})
    assert matrix == [] and order == []


def test_pit_status_constant_and_caveat_exist():
    """PIT 常量 + caveat 必须存在且为诚实档(行业归属随时间变更, 无历史)。"""
    im = _im()
    assert im.INDUSTRY_PIT_STATUS == "today_snapshot_only"
    assert isinstance(im.INDUSTRY_CAVEAT, str) and im.INDUSTRY_CAVEAT


class _FakeAkOK:
    """注入的假 akshare：返回 fixture 行(脱网, 确定性)。"""
    def stock_board_industry_name_em(self):
        return BOARD_ROWS

    def stock_individual_info_em(self, symbol=None):
        return INFO_ROWS


class _FakeAkFail:
    """注入的假 akshare：抛错(模拟接口失效/缺库/网络故障)。"""
    def stock_board_industry_name_em(self):
        raise RuntimeError("akshare down")

    def stock_individual_info_em(self, symbol=None):
        raise RuntimeError("akshare down")


def test_fetch_symbol_industry_failure_returns_none():
    """薄包装失败安全降级：akshare 抛错 → None（绝不编造、不崩溃）。"""
    import functools

    import anyio
    im = _im()
    out = anyio.run(functools.partial(im.fetch_symbol_industry, "600519", ak=_FakeAkFail()))
    assert out is None


def test_fetch_symbol_industry_success_parses_industry():
    """薄包装成功路径(注入假 akshare, 脱网)：解析出'行业'字段。"""
    import functools

    import anyio
    im = _im()
    out = anyio.run(functools.partial(im.fetch_symbol_industry, "600519", ak=_FakeAkOK()))
    assert out == "白酒"


def test_fetch_industry_list_failure_returns_empty():
    """薄包装失败安全降级：失败 → {}（空映射, 而非崩溃）。"""
    import functools

    import anyio
    im = _im()
    out = anyio.run(functools.partial(im.fetch_industry_list, ak=_FakeAkFail()))
    assert out == {}


def test_fetch_industry_list_success_parses_map():
    """薄包装成功路径(注入假 akshare, 脱网)：解析出 {行业名: 代码}。"""
    import functools

    import anyio
    im = _im()
    out = anyio.run(functools.partial(im.fetch_industry_list, ak=_FakeAkOK()))
    assert out == {"银行": "BK0475", "白酒": "BK0477", "半导体": "BK1036"}
