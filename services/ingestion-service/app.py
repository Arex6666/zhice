"""ingestion-service：智策 ZhiCe 平台的"数据采集与自审"微服务。

职责：周期性自动采集 A 股行情、回填研判复盘、扫描异动告警。
所有持久化都委托 storage-service（http://storage-service:8003），
本服务不直接读写数据库，也不 import 其它服务的 Python 模块。

监听端口 8004（Dockerfile CMD 通过 uvicorn 启动）。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

import scheduler

SERVICE_NAME = "ingestion-service"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动调度器（三个周期 job）。watchlist 的兜底由 scheduler 内部处理：
    # storage 未提供批量写入接口，若 /watchlist 为空则使用 DEFAULT_WATCHLIST。
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="zhice-ingestion-service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/status")
def status():
    return {"service": SERVICE_NAME, **scheduler.get_status()}
