#!/usr/bin/env bash
# 把本地构建的 6 个 zhice 镜像推送到阿里云 ACR 的**单个仓库**，用 tag 区分服务。
# （个人版 ACR 只建了一个仓库 zhice_agent 时用这个；一服务一仓库请用 push_aliyun.sh）
#
# 用法:
#   1) 先登录(交互, 需在真终端):
#        docker login --username=<阿里云账号全名> <registry域名>
#   2) 运行:
#        ./push_acr.sh [ACR仓库全路径]
#      默认: crpi-zjwfywe3f3bt7ie4.cn-hangzhou.personal.cr.aliyuncs.com/arex_666/zhice_agent
set -e

ACR="${1:-crpi-zjwfywe3f3bt7ie4.cn-hangzhou.personal.cr.aliyuncs.com/arex_666/zhice_agent}"
SVCS="api-gateway agent-service mcp-tool-service storage-service ingestion-service offline-runner"

for s in $SVCS; do
  echo ">> tag+push  zhice/$s:latest  ->  $ACR:$s"
  docker tag  "zhice/$s:latest" "$ACR:$s"
  docker push "$ACR:$s"
done

# :latest 指向 agent-service（仓库名为 *_agent）
docker tag  "zhice/agent-service:latest" "$ACR:latest"
docker push "$ACR:latest"

echo ">> 完成。可用 deploy/docker-compose.acr.yml 直接拉取运行。"
