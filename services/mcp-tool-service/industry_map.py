"""L1 申万一级行业映射（spec §4 L1 + 核验修正）。

中性化第 3 步需"申万一级行业哑变量"。本模块提供：
  - parse_industry_list  : stock_board_industry_name_em 形态 → {行业名: 行业代码}
  - parse_symbol_industry: stock_individual_info_em 长表([{'item':..,'value':..}]) → 行业名 | None
  - build_industry_dummies: (symbols, sym2ind) → (dummy_matrix, industry_order[, meta])
                            全列哑变量(去共线交下游 preprocess/中性化)，未知→'OTHER'，结构带 coverage
  - fetch_symbol_industry / fetch_industry_list: 真实 akshare 薄包装(anyio 卸载)，失败返 None/{}

诚实约束（spec §0 / §4 L1 §3.4 行业映射 PIT）：
  akshare 无历史行业归属 → 行业映射只能 forward 累积，启动前历史段不可重建。
  行业归属本身随时间变更(行业重分类/调整) → PIT 不可得 → INDUSTRY_PIT_STATUS='today_snapshot_only'，
  中性化结果带 caveat；映射缺失/覆盖率不足由下游(preprocess)按截面弃权(data_quality=degraded)。
  核心解析/哑变量为纯函数(脱网可测)，真实网络调用全在 fetch_* 薄包装内、失败安全降级，绝不编造归属。
"""

# --- PIT 诚实常量(随结构同行, 任一跳剥离视为违规) ---
INDUSTRY_PIT_STATUS = "today_snapshot_only"
INDUSTRY_CAVEAT = (
    "行业归属为今日快照：akshare 无历史行业归属，行业重分类/调整无法时点重建，"
    "启动前历史段的中性化基底带前视偏差，未消除。"
)

# stock_board_industry_name_em 行业名/代码可能出现的列名(防御兼容)
_NAME_KEYS = ("板块名称", "行业名称", "name", "板块", "行业")
_CODE_KEYS = ("板块代码", "行业代码", "code", "symbol", "代码")
# 空值/占位符(视为缺失，不当真实归属)
_EMPTY = {"", "-", "--", "—", "none", "None", "nan", "null", "暂无"}


def _first(row, keys):
    """取 row 中首个命中 keys 且非空的值；防御 None/非 dict。"""
    if not isinstance(row, dict):
        return None
    for k in keys:
        if k in row:
            v = row[k]
            if v is not None and str(v).strip() not in _EMPTY:
                return str(v).strip()
    return None


def parse_industry_list(rows):
    """stock_board_industry_name_em 形态 → {行业名: 行业代码}。

    防御解析：缺名称或缺代码的脏行跳过(不编造)；兼容备用列名。
    """
    out = {}
    if not rows:
        return out
    for r in rows:
        name = _first(r, _NAME_KEYS)
        code = _first(r, _CODE_KEYS)
        if name and code:
            out.setdefault(name, code)
    return out


def parse_symbol_industry(info_rows):
    """stock_individual_info_em 长表 [{'item':..,'value':..}] → 行业名 | None。

    诚实：无'行业'字段或值为空/占位 → None，绝不编造归属。畸形输入(非列表/非 dict 行)安全返 None。
    """
    if not isinstance(info_rows, (list, tuple)):
        return None
    for r in info_rows:
        if not isinstance(r, dict):
            continue
        item = r.get("item")
        if item is not None and str(item).strip() == "行业":
            v = r.get("value")
            if v is None:
                return None
            s = str(v).strip()
            return s if s not in _EMPTY else None
    return None


def build_industry_dummies(symbols, sym2ind, with_meta=False):
    """构造行业哑变量矩阵（全列，不去列——去共线交下游中性化）。

    参数:
      symbols : 截面标的代码序列(行序即此序)
      sym2ind : {symbol: 行业名}；缺失/未知 → 归入 'OTHER'(不丢样本)
    返回:
      (dummy_matrix, industry_order)              默认
      (dummy_matrix, industry_order, meta)        with_meta=True
        dummy_matrix : list[list[float]]，row=symbol，col=industry_order(one-hot)
        industry_order: 确定性排序的行业名列表(全列)
        meta : {coverage, n, n_known, industry_pit_status, caveat}  诚实标随结构同行
    """
    syms = list(symbols or [])
    s2i = dict(sym2ind or {})

    # 逐 symbol 解析归属(未知→OTHER)，同时统计真实覆盖率(诚实)
    eff = []
    n_known = 0
    for s in syms:
        ind = s2i.get(s)
        if ind is not None and str(ind).strip() not in _EMPTY:
            eff.append(str(ind).strip())
            n_known += 1
        else:
            eff.append("OTHER")

    # 全列：出现过的行业集合，确定性排序(OTHER 殿后，保证可复现)
    present = set(eff)
    others = sorted(c for c in present if c != "OTHER")
    order = others + (["OTHER"] if "OTHER" in present else [])

    col_idx = {c: j for j, c in enumerate(order)}
    matrix = []
    for c in eff:
        row = [0.0] * len(order)
        row[col_idx[c]] = 1.0
        matrix.append(row)

    if not with_meta:
        return matrix, order

    n = len(syms)
    meta = {
        "coverage": (n_known / n) if n else 0.0,
        "n": n,
        "n_known": n_known,
        "industry_pit_status": INDUSTRY_PIT_STATUS,
        "caveat": INDUSTRY_CAVEAT,
    }
    return matrix, order, meta


# --------------------------------------------------------------------------- #
# 真实取数薄包装(anyio 卸载同步 akshare；失败安全降级，绝不编造)。
# 核心逻辑(上方纯函数)接收已取好的数据；网络/akshare 仅在此层。
# --------------------------------------------------------------------------- #
def _to_rows(df):
    return df.to_dict("records") if hasattr(df, "to_dict") else list(df)


async def fetch_industry_list(ak=None):
    """stock_board_industry_name_em → {行业名: 代码}。失败返 {}（空映射，下游可弃权）。

    ak 可注入(测试/脱网)；默认 import akshare。网络/akshare 经 anyio.to_thread 卸载。
    """
    def _f():
        mod = ak
        if mod is None:
            import akshare as mod  # noqa: F811
        return parse_industry_list(_to_rows(mod.stock_board_industry_name_em()))

    try:
        import anyio
        return await anyio.to_thread.run_sync(_f)
    except Exception:
        return {}


async def fetch_symbol_industry(symbol, ak=None):
    """stock_individual_info_em(symbol) 的'行业'字段 → 行业名 | None。失败返 None（不编造）。

    ak 可注入(测试/脱网)；默认 import akshare。网络/akshare 经 anyio.to_thread 卸载。
    """
    def _f():
        mod = ak
        if mod is None:
            import akshare as mod  # noqa: F811
        return parse_symbol_industry(_to_rows(mod.stock_individual_info_em(symbol=symbol)))

    try:
        import anyio
        return await anyio.to_thread.run_sync(_f)
    except Exception:
        return None
