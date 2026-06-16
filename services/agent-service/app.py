"""agent-service: 智能体大脑的 HTTP 入口。"""
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import agent

logger = logging.getLogger("agent-service")
app = FastAPI(title="zhiyue-agent-service")


class ChatIn(BaseModel):
    message: str
    session_id: str = "default"


@app.get("/health")
def health():
    return {"status": "ok", "service": "agent-service"}


@app.post("/chat")
async def chat(body: ChatIn):
    try:
        return await agent.run_agent(body.message)
    except Exception:
        # 记录详细异常到服务端日志；对外只返回通用错误，避免泄露密钥/主机等细节
        logger.exception("智能体处理失败")
        raise HTTPException(status_code=502, detail="智能体处理失败，请稍后重试")
