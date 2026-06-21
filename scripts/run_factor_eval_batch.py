#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 离线因子评估批（offline）：拉中证池 K 线 → 构造横截面面板 → factor_report → POST /pit/factor_eval。

spec §3.4 的 offline 重计算路径：由本脚本(或 scheduler 直调)执行、结果落库, 绝不进委员会 SSE。
价量因子(history_native)立即可评估；估值/另类因子待 PIT 累积(§14.2 成熟度门)。
失败逐项隔离。`run_batch` 依赖注入(脱网可测), `main` 接真实 akshare + storage。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE_VOLUME_FACTORS = ["Mom_12_1", "Rev_5", "TotalVol", "Amihud"]


def parse_universe(rows, limit=None):
    """中证成分 df 行 → 6 位代码列表（防御兼容多列名；limit 截断便于测试/限流）。"""
    out = []
    for r in rows:
        s = (r.get("成分券代码") or r.get("品种代码") or r.get("证券代码")
             or r.get("symbol") or r.get("con_code"))
        if s is not None and str(s).strip():
            out.append(str(s).strip().split(".")[0].zfill(6))
    return out[:limit] if limit else out


def _fetch_universe(index="000300", limit=None, fetch_fn=None):
    """拉指数成分（默认中证300 via akshare index_stock_cons_csindex）。fetch_fn 注入以脱网测。"""
    if fetch_fn is None:
        import akshare as ak
        def fetch_fn():
            return ak.index_stock_cons_csindex(symbol=index)
    df = fetch_fn()
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    return parse_universe(rows, limit)


def run_batch(klines_by_symbol, factor_report_fn, build_panels_fn, post_fn,
              factors, as_of, universe_filter="lsy"):
    """依赖注入的批核心：逐因子建面板→评估→post。返回 {posted, failures, results}。"""
    posted, failures, results = 0, 0, []
    for f in factors:
        try:
            fp, wp = build_panels_fn(klines_by_symbol, f)
            rep = factor_report_fn(fp, wp)
            row = {"factor_name": f, "as_of": as_of, "universe_filter": universe_filter,
                   "family": "price_volume", "computed_at": as_of, **rep}
            post_fn(row)
            posted += 1
            results.append({"factor": f, "significant": rep.get("significant"),
                            "mean_rank_ic": rep.get("mean_rank_ic")})
        except Exception as e:  # noqa: BLE001 - 单因子失败隔离
            failures += 1
            results.append({"factor": f, "error": str(e)[:80]})
    return {"posted": posted, "failures": failures, "results": results}


def _load_env():
    envp = os.path.join(ROOT, "deploy", ".env")
    if os.path.exists(envp):
        for line in open(envp, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))


def main(symbols=None, as_of=None, post=True):
    import asyncio
    import datetime
    import httpx
    _load_env()
    sys.path.insert(0, os.path.join(ROOT, "services", "mcp-tool-service"))
    import finance
    import factor_eval
    import zoo
    factors = list(zoo.FACTORS)   # 评估全部 history_native 价量因子(随 zoo 扩展自动同步)
    if symbols is None:           # 默认评估池：中证300 全池(UNIVERSE_LIMIT 可截断, 限流/测试用)
        index = os.getenv("UNIVERSE_INDEX", "000300")
        lim = os.getenv("UNIVERSE_LIMIT")
        try:
            symbols = _fetch_universe(index, int(lim) if lim else None)
            print(f"universe={index}: {len(symbols)} symbols (limit={lim or 'none'})")
        except Exception as e:  # noqa: BLE001 - 取池失败回退小样本(不崩)
            print(f"  universe fetch failed ({type(e).__name__}); fallback small set")
            symbols = ["600519", "000001", "600036", "601318", "000858", "600000"]
    as_of = as_of or datetime.date.today().isoformat()
    storage = os.getenv("STORAGE_URL", "http://localhost:8003").rstrip("/")

    async def _fetch():
        ad = finance.get_adapter("ASHARE")
        out = {}
        for s in symbols:
            try:
                out[s] = await ad.get_kline(s, "daily", 400)   # >252 才能算长窗动量(Mom_12_1/Hi52)
            except Exception as e:  # noqa: BLE001
                print(f"  {s}: skip ({type(e).__name__})")
        return out

    klines = asyncio.run(_fetch())

    def post_fn(row):
        if not post:
            return
        try:
            httpx.post(f"{storage}/pit/factor_eval", json=row, timeout=10).raise_for_status()
        except Exception as e:  # noqa: BLE001 - storage 未起则仅打印
            print(f"  post {row['factor_name']} failed: {type(e).__name__}")

    res = run_batch(klines, factor_eval.factor_report, factor_eval.build_factor_panels,
                    post_fn, factors, as_of)
    print(f"factor_eval batch as_of={as_of}: posted={res['posted']} failures={res['failures']}")
    for r in res["results"]:
        print(" ", r)


if __name__ == "__main__":
    main(post=False)   # 默认仅计算打印(storage 未起); 部署时 post=True
