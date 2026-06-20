#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M0 接口实测：联网逐接口验证签名/返回形态。失败接口打印后继续，绝不抛。

用途：进入 M1 实现前，对 spec §16 声明的 akshare 接口做一次真实端到端核验，
把"纸面接口"漂移（如已失效的 stock_a_indicator_lg）尽早暴露。
"""
import akshare as ak

IFACES = {
    "index_stock_cons_csindex": dict(symbol="000906"),   # 中证800
    "stock_zh_a_spot_em": {},
    "stock_zh_valuation_baidu": dict(symbol="600519", indicator="市盈率(动)", period="近一年"),
    "stock_yjyg_em": dict(date="20240331"),
    "stock_hsgt_hold_stock_em": dict(market="北向", indicator="今日排行"),
    "stock_zh_a_gdhs_detail_em": dict(symbol="600519"),
    "stock_individual_info_em": dict(symbol="600519"),
    "stock_board_industry_name_em": {},
    "index_option_300etf_qvix": {},
}


def main():
    for fn, kw in IFACES.items():
        f = getattr(ak, fn, None)
        if f is None:
            print(f"[MISS] {fn}")
            continue
        try:
            df = f(**kw)
            cols = list(df.columns) if hasattr(df, "columns") else type(df).__name__
            n = len(df) if hasattr(df, "__len__") else "?"
            print(f"[OK]   {fn} rows={n} cols={cols}")
        except Exception as e:  # noqa: BLE001 - 核验脚本: 单接口失败不影响其余
            print(f"[ERR]  {fn}: {type(e).__name__}: {str(e)[:80]}")


if __name__ == "__main__":
    main()
