# mcp-tool-service：FastMCP 工具服务器（SSE 传输，供智能体跨容器调用）
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m -u 1000 mcpuser && chown -R mcpuser:mcpuser /app
USER mcpuser
ENV PYTHONUNBUFFERED=1
ENV MCP_TRANSPORT=sse
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8002
EXPOSE 8002
CMD ["python", "mcp_server.py"]
