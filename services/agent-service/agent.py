"""智能体大脑：在 MCP 工具之上的 LLM tool-use 循环。

run_loop 把 LLM 客户端、工具列举/调用函数都做成可注入参数，因此可以用 fake 在
无网络、无密钥的情况下做单元测试；run_agent 负责接线真实的 DeepSeek（异步客户端）
与 MCP 客户端。
"""
import inspect
import json
import os

SYSTEM_PROMPT = (
    "你是'智阅'智能网页助手。你可以调用以下工具："
    "get_web_content(抓取网页正文)、extract_links(提取链接)、crawl_structured(按CSS选择器结构化爬取)、"
    "save_document(把内容存入记忆库)、search_documents(检索历史抓取)。"
    "请规划合理的工具调用来完成用户请求；抓取到正文后，若用户要求总结/分析，请基于正文作答，"
    "并在合适时调用 save_document 保存。用中文简洁作答，并在末尾标注信息来源 URL。"
    "若某次工具调用返回以『[工具调用失败]』开头，说明该工具出错，请如实告知用户，不要编造内容。"
)

# 仅这些“读取类”工具的 url 才算信息来源（save_document 等不算）
READ_TOOLS = {"get_web_content", "extract_links", "crawl_structured"}
ERROR_PREFIX = "[工具调用失败]"


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


async def run_loop(message, llm, model, session, list_tools, call_tool, max_iters=5):
    """核心 tool-use 循环。

    依赖注入：
      llm        — OpenAI 兼容客户端（含 .chat.completions.create，可同步或异步）
      list_tools — async (session) -> OpenAI tools schema
      call_tool  — async (session, name, args) -> str（失败时以 ERROR_PREFIX 开头）
    """
    tools_schema = await list_tools(session)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]
    used = []
    sources = []
    last_content = ""
    for _ in range(max_iters):
        resp = llm.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools_schema or None,
            tool_choice="auto" if tools_schema else "none",
            temperature=0.3,
        )
        if inspect.isawaitable(resp):  # 支持 AsyncOpenAI（真实）与同步 fake（测试）
            resp = await resp
        msg = resp.choices[0].message
        if msg.content:
            last_content = msg.content
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            return {"answer": msg.content or "", "tool_calls": used, "sources": _dedup(sources)}

        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
                result = f"{ERROR_PREFIX} 参数不是合法 JSON：{tc.function.arguments!r}"
            else:
                try:
                    result = await call_tool(session, name, args)
                except Exception as e:  # SSE 中断/工具异常不应拖垮整个循环
                    result = f"{ERROR_PREFIX} {type(e).__name__}: {e}"
            ok = not str(result).startswith(ERROR_PREFIX)
            if ok and name in READ_TOOLS and isinstance(args, dict) and args.get("url"):
                sources.append(args["url"])
            used.append({"name": name, "args": args, "ok": ok})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": str(result)[:4000],
                }
            )
    # 达到最大轮数：尽量返回已生成的内容，而非空洞兜底
    answer = last_content or "（已达到最大工具调用轮数，请缩小问题范围后重试）"
    return {"answer": answer, "tool_calls": used, "sources": _dedup(sources)}


async def run_agent(message):
    """接线真实 DeepSeek LLM（异步）+ 远端 MCP 工具服务。"""
    from openai import AsyncOpenAI

    import mcp_client

    llm = AsyncOpenAI(
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        api_key=os.getenv("LLM_API_KEY", ""),
    )
    model = os.getenv("LLM_MODEL", "deepseek-chat")
    async with mcp_client.open_session() as session:
        return await run_loop(
            message, llm, model, session,
            mcp_client.list_tools_openai, mcp_client.call_tool,
        )
