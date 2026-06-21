# 离线重计算 runner（§3.4 offline 工具的容器化执行点）。
# 构建上下文 = 仓库根（需同时拷 scripts/ + mcp-tool + agent 的纯计算模块）。
# Python 3.12 与 agent-service 同栈 → xsec pickle 跨容器契约(§3.3)可对齐。
FROM python:3.12-slim
WORKDIR /app
COPY services/offline-runner/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# 离线批依赖的代码：脚本 + mcp-tool 纯计算(finance/factor_eval/zoo/…) + agent(xsec_model)
COPY scripts/ ./scripts/
COPY services/mcp-tool-service/ ./services/mcp-tool-service/
COPY services/agent-service/ ./services/agent-service/
COPY services/offline-runner/runner.py .
CMD ["python", "runner.py"]
