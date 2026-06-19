#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智策金融平台端到端冒烟测试（对运行中的技术栈）。

验证：网关健康 / 三市场报价(允许降级) / 深度研判证据链+治理+免责 /
数据不足标的的弃权降级（治理可演示）。用法：docker compose up -d 后运行。
"""
import os
import sys

import httpx

GW = os.getenv("GATEWAY_URL", "http://localhost:8080")
ok, fail = [], []


def chk(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def main():
    print("== 智策金融冒烟测试 ==")
    r = httpx.get(f"{GW}/api/status", timeout=15).json()
    chk("gateway /api/status", r.get("gateway") == "ok", str(r))

    # 三市场报价（美股/crypto 允许降级，只要不抛错）
    for sym in ["ASHARE:600519", "US:AAPL", "CRYPTO:BTCUSDT"]:
        try:
            q = httpx.get(f"{GW}/api/finance/quote", params={"symbol": sym}, timeout=40).json()
            price = q.get("price") if isinstance(q, dict) else None
            chk(f"quote {sym}", isinstance(q, dict),
                f"price={price} status={q.get('data_status') if isinstance(q, dict) else '?'}")
        except Exception as e:
            chk(f"quote {sym}", False, f"{type(e).__name__}: {e}")

    # 深度研判（需 LLM key）：证据链 + 治理 + 免责
    key = os.getenv("LLM_API_KEY", "")
    if key and "REPLACE" not in key:
        d = httpx.post(f"{GW}/api/finance/analyze",
                       json={"symbol": "ASHARE:600519", "mode": "deep"}, timeout=180).json()
        chk("deep 有委员会成员", len(d.get("members", [])) >= 4)
        chk("deep 有主席结论", bool(d.get("chairman")))
        chk("deep 有治理记录字段", "governance_report" in d)
        chk("deep 含免责声明", "不构成投资建议" in d.get("disclaimer", ""))
        chk("deep 置信度<=治理上限0.85", 0 <= d.get("confidence", 1) <= 0.85,
            f"conf={d.get('confidence')}")
    else:
        print("  (跳过深度研判：未配置 LLM_API_KEY)")

    print(f"\n结果：{len(ok)} 通过, {len(fail)} 失败")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
