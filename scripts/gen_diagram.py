#!/usr/bin/env python3
"""生成系统架构图 (报告/diagrams/architecture.png)。"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

JADE = "#1f8f63"
JADE_L = "#e6f5ee"
SLATE = "#2b3a33"
AMBER = "#b6862a"
GREY = "#6a7d72"

fig, ax = plt.subplots(figsize=(11, 7.6), dpi=170)
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")


def box(x, y, w, h, title, lines, fc="white", ec=JADE, tc=SLATE):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=2.2",
                                fc=fc, ec=ec, lw=1.8, mutation_aspect=1))
    ax.text(x + w / 2, y + h - 5.0, title, ha="center", va="top",
            fontsize=11.5, fontweight="bold", color=tc)
    ax.text(x + w / 2, y + h - 11.5, "\n".join(lines), ha="center", va="top",
            fontsize=8.3, color=GREY, linespacing=1.5)


def arrow(x1, y1, x2, y2, label="", color=JADE, style="-|>", ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=16,
                                 color=color, lw=1.7, linestyle=ls,
                                 connectionstyle="arc3,rad=0"))
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 1.6, label, ha="center", va="bottom",
                fontsize=8.2, color=color, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none"))


# Docker / compose 边框
ax.add_patch(FancyBboxPatch((2, 3), 96, 78, boxstyle="round,pad=0.6,rounding_size=2",
                            fc="#fbfdfc", ec="#c8d6cd", lw=1.4, ls=(0, (6, 4))))
ax.text(4.5, 80.5, "Docker Compose 网络  zhiyue-net （4 个容器 · 镜像推送至阿里云 ACR）",
        fontsize=9, color="#8aa295", fontweight="bold")

# 浏览器
box(36, 86, 28, 11, "浏览器 / Web Chat UI", ["自然语言对话界面"], fc=JADE_L, ec=JADE)

# gateway
box(33, 64, 34, 15, "api-gateway  :8080", ["FastAPI · 唯一入口", "Web UI · 转发 · /metrics"], fc="white")

# agent
box(33, 42, 34, 15, "agent-service  :8001", ["智能体大脑 · MCP 客户端", "DeepSeek LLM 工具规划循环"], fc="white", ec=AMBER, tc=SLATE)

# mcp-tool
box(8, 16, 40, 17, "mcp-tool-service  :8002", ["FastMCP · stdio + SSE 双传输",
    "get_web_content / extract_links", "crawl_structured / save / search"], fc=JADE_L, ec=JADE)

# storage
box(58, 16, 34, 17, "storage-service  :8003", ["FastAPI + SQLite", "文档持久化与检索", "持久卷 zhiyue-data"], fc="white")

# 外部
ax.text(90, 49.5, "DeepSeek\nAPI", ha="center", va="center", fontsize=8.5, color=AMBER,
        fontweight="bold", bbox=dict(boxstyle="round,pad=0.4", fc="#fdf6e8", ec=AMBER, lw=1.4))
ax.text(28, 8.5, "互联网网页\n(requests/bs4)", ha="center", va="center", fontsize=8, color=GREY,
        bbox=dict(boxstyle="round,pad=0.35", fc="#f2f5f3", ec="#c8d6cd"))

# 箭头
arrow(50, 86, 50, 79.2, "HTTP")
arrow(50, 64, 50, 57.2, "HTTP /api/chat")
arrow(45, 42, 32, 33.4, "MCP (SSE)", color=JADE)
arrow(67, 60, 84, 52, "OpenAI 兼容", color=AMBER, ls=(0, (4, 3)))
arrow(40, 16, 30, 12.6, "抓取", color=GREY)
arrow(48, 24.5, 58, 24.5, "HTTP 转调", color=JADE)
# gateway 历史浏览直连 storage
arrow(67, 67, 86, 33, "GET /api/documents", color="#9bb0a4", ls=(0, (3, 3)))

ax.text(50, 98.6, "智阅 ZhiYue · 基于 MCP 的智能网页采集分析智能体平台 — 系统架构",
        ha="center", va="top", fontsize=13.5, fontweight="bold", color=SLATE)

os.makedirs("报告/diagrams", exist_ok=True)
out = "报告/diagrams/architecture.png"
plt.savefig(out, bbox_inches="tight", facecolor="white")
print("saved", out)
