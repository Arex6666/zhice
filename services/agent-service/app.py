"""agent-service: 智能体大脑的 HTTP 入口。"""
from fastapi import FastAPI
from pydantic import BaseModel

import agent

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
    except Exception as e:  # 安全网：不让现场演示因瞬时错误崩溃
        return {"answer": f"智能体出错：{e}", "tool_calls": [], "sources": []}
