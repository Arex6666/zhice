"""offline-runner：离线重计算批的容器化调度器（§3.4——offline 工具由此直调，结果落库）。

为什么独立成服务：factor_eval/train_xsec 批同时需要 akshare(取数) + mcp-tool 纯计算模块 +
agent 的 xsec_model，三者不在任一既有容器共存；委员会 SSE 热路径又禁跑重计算。故此处集中跑、
结果经 HTTP 落 storage（factor_eval）/共享卷（xsec 模型），与实时热路径彻底解耦。

- factor_eval 批（默认周频）：拉中证池 K 线→横截面面板→Rank-IC/ICIR/HAC-t/DSR→POST /pit/factor_eval。
  这是把"PIT 累积"兑现成"真实有效性"的传动轴：价量族(history_native)立刻可评估并喂委员会+仪表盘。
- train_xsec（默认月频）：训练横截面 GBDT 排序器，落共享卷 /models（供未来 L3 推理接线消费）。

支持一次性 CLI：`python runner.py factor_eval|train_xsec|all`（CI/手动/host cron）。
"""
import datetime
import os
import sys

ROOT = "/app"
sys.path.insert(0, os.path.join(ROOT, "scripts"))
XSEC_DIR = os.getenv("XSEC_MODEL_DIR", "/models")


def run_factor_eval():
    import run_factor_eval_batch as rb
    rb.main(post=True)


def run_train_xsec():
    import train_xsec as tx
    os.makedirs(XSEC_DIR, exist_ok=True)
    tx.main(out=os.path.join(XSEC_DIR, "xsec_ASHARE.pkl"))


JOBS = {"factor_eval": run_factor_eval, "train_xsec": run_train_xsec}


def _safe(fn, name):
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"[offline-runner] {name} start {ts}", flush=True)
    try:
        fn()
        print(f"[offline-runner] {name} done", flush=True)
    except Exception as e:  # noqa: BLE001 - 单批失败隔离, 不拖垮调度器
        print(f"[offline-runner] {name} FAILED: {type(e).__name__}: {str(e)[:200]}", flush=True)


def main():
    if len(sys.argv) > 1:                      # 一次性模式
        arg = sys.argv[1]
        targets = list(JOBS) if arg == "all" else [arg]
        for t in targets:
            _safe(JOBS[t], t) if t in JOBS else print(f"unknown job: {t}", flush=True)
        return
    from apscheduler.schedulers.blocking import BlockingScheduler
    sched = BlockingScheduler(timezone="Asia/Shanghai")
    fe_sec = int(os.getenv("FACTOR_EVAL_SEC", str(7 * 86400)))
    tx_sec = int(os.getenv("XSEC_TRAIN_SEC", str(30 * 86400)))
    sched.add_job(lambda: _safe(run_factor_eval, "factor_eval"), "interval", seconds=fe_sec,
                  id="factor_eval", max_instances=1, coalesce=True)
    sched.add_job(lambda: _safe(run_train_xsec, "train_xsec"), "interval", seconds=tx_sec,
                  id="train_xsec", max_instances=1, coalesce=True)
    if os.getenv("RUN_ON_START", "0") == "1":   # 启动即跑一轮（默认关，避免每次重启都打外部源）
        _safe(run_factor_eval, "factor_eval")
    print(f"[offline-runner] scheduler up (factor_eval {fe_sec}s / train_xsec {tx_sec}s)", flush=True)
    sched.start()


if __name__ == "__main__":
    main()
