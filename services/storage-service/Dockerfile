# storage-service：智策金融数据持久化（FastAPI + SQLite）
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# 创建非 root 用户，并预置 /data 目录归属（保证命名卷首次挂载时可写）
RUN useradd -m -u 1000 mcpuser && mkdir -p /data && chown -R mcpuser:mcpuser /app /data
USER mcpuser
ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/zhice.db
EXPOSE 8003
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
