#!/usr/bin/env bash
# 将本地构建的镜像推送至阿里云容器镜像服务 (ACR)。
# 用法: ./push_aliyun.sh <registry> <namespace> [tag]
#   例: ./push_aliyun.sh registry.cn-hangzhou.aliyuncs.com myns latest
set -e

REGISTRY="${1:?需要 registry，如 registry.cn-hangzhou.aliyuncs.com}"
NS="${2:?需要命名空间 namespace}"
TAG="${3:-latest}"

SVCS="storage-service mcp-tool-service agent-service ingestion-service api-gateway"

echo ">> 登录阿里云镜像仓库：$REGISTRY"
docker login "$REGISTRY"

for s in $SVCS; do
  echo ">> 推送 zhice/$s -> $REGISTRY/$NS/$s:$TAG"
  docker tag "zhice/$s:latest" "$REGISTRY/$NS/$s:$TAG"
  docker push "$REGISTRY/$NS/$s:$TAG"
done

# 《MCP实验指导书》第七步：单文件爬虫镜像
if docker image inspect mcp-web-scraper:latest >/dev/null 2>&1; then
  echo ">> 推送指导书原样镜像 mcp-web-scraper"
  docker tag mcp-web-scraper:latest "$REGISTRY/$NS/mcp-web-scraper:$TAG"
  docker push "$REGISTRY/$NS/mcp-web-scraper:$TAG"
fi

echo ">> 完成。请在阿里云控制台「容器镜像服务 -> 镜像仓库」查看。"
