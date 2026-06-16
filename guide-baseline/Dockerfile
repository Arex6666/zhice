# 使用官方 Python 镜像（《MCP实验指导书》第六步原样）
FROM python:3.11-slim
# 设置工作目录
WORKDIR /app
# 安装系统依赖
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*
# 复制 requirements 文件
COPY requirements.txt .
# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt
# 复制应用代码
COPY web_content_mcp.py .
# 创建非 root 用户
RUN useradd -m -u 1000 mcpuser && chown -R mcpuser:mcpuser /app
USER mcpuser
# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
# 启动 MCP 服务器
CMD ["python", "web_content_mcp.py"]
