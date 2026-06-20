# agent-service：智能体大脑（LLM tool-use 循环 + MCP 客户端 + XGBoost 风险信号）
# 使用 3.12 以匹配训练端的 xgboost 3.3.0（其要求 Python>=3.12），保证模型 pickle 跨端可加载
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m -u 1000 mcpuser && chown -R mcpuser:mcpuser /app
USER mcpuser
ENV PYTHONUNBUFFERED=1
EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
