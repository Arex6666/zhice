"""akshare 采集适配层（双粒度）。

解析为纯函数（离线 fixture 可测）；真正的网络调用经 anyio.to_thread 卸载（沿用 finance.py 范式）。
区分 cross_section（一次拿全市场）与 per_symbol（逐标的循环）两类调用粒度。
"""
CROSS_SECTION_APIS = {
    "index_stock_cons_csindex": "symbol=指数代码, 无 date 参 → 今日成分快照",
    "stock_zh_a_spot_em": "全市场快照(动态PE/PB/总市值/换手/量比)",
    "stock_yjyg_em": "date=报告期 → 全市场业绩预告(真披露日)",
    "stock_yjkb_em": "date=报告期 → 全市场业绩快报(真披露日)",
    "stock_hsgt_hold_stock_em": "market+indicator → 全市场北向排名快照",
    "stock_board_industry_name_em": "全市场一级行业列表",
}
PER_SYMBOL_APIS = {
    "stock_zh_valuation_baidu": "symbol+indicator+period → 单指标 date+value 时序",
    "stock_financial_analysis_indicator": "symbol → 多年财务(报告期末索引)",
    "stock_individual_info_em": "symbol → 个股行业归属",
    "stock_zh_a_gdhs_detail_em": "symbol → 股东户数明细",
    "stock_individual_fund_flow": "symbol → 资金流",
}

# 法定披露截止日：年报(Q4)落次年 4/30，一季 4/30，半年 8/31，三季 10/31
_LEGAL = {"Q1": ("04", "30"), "Q2": ("08", "31"), "Q3": ("10", "31"), "Q4": ("04", "30")}


def legal_deadline_for(period):
    """报告期 '2023Q4' → 法定截止日字符串；年报(Q4)落次年 4/30。"""
    yr = int(period[:4])
    q = period[-2:]
    mm, dd = _LEGAL[q]
    if q == "Q4":
        yr += 1
    return f"{yr}-{mm}-{dd}"


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def parse_baidu_valuation(df):
    """百度估值单指标返回 → [{date, value}]；脏值(-/空)剔除。"""
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    out = []
    for r in rows:
        d = r.get("date")
        v = _num(r.get("value"))
        if d and v is not None:
            out.append({"date": str(d)[:10], "value": v})
    return out


def parse_csindex_cons(df, index_code):
    """中证成分 → membership 行（无历史 date，统一标 today_snapshot_only）。"""
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    out = []
    for r in rows:
        sym = r.get("品种代码") or r.get("成分券代码") or r.get("symbol")
        if not sym:
            continue
        out.append({"date": None, "symbol": str(sym),
                    "name": str(r.get("品种名称") or r.get("成分券名称") or ""),  # ST 过滤依赖名称
                    "weight": _num(r.get("权重")) or 0.0,
                    "index_code": index_code, "universe_pit_status": "today_snapshot_only"})
    return out
