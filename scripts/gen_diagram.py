#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

fig, ax = plt.subplots(figsize=(11.5, 8.6), dpi=170)
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")


def box(x, y, w, h, title, lines, fc="white", ec=JADE, tc=SLATE):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=2.2",
                                fc=fc, ec=ec, lw=1.8, mutation_aspect=1))
    ax.text(x + w / 2, y + h - 4.2, title, ha="center", va="top",
            fontsize=11, fontweight="bold", color=tc)
    if lines:
        ax.text(x + w / 2, y + h - 9.6, "\n".join(lines), ha="center", va="top",
                fontsize=7.8, color=GREY, linespacing=1.45)


def arrow(x1, y1, x2, y2, label="", color=JADE, ls="-", lx=None, ly=None):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=15,
                                 color=color, lw=1.6, linestyle=ls))
    if label:
        ax.text(lx if lx is not None else (x1 + x2) / 2,
                ly if ly is not None else (y1 + y2) / 2,
                label, ha="center", va="center", fontsize=8, color=color, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none"))


# Docker / compose 边框
ax.add_patch(FancyBboxPatch((1.5, 2.5), 97, 80, boxstyle="round,pad=0.6,rounding_size=2",
                            fc="#fbfdfc", ec="#c8d6cd", lw=1.4, ls=(0, (6, 4))))
ax.text(3.5, 81.2, "Docker Compose 网络  zhiyue-net （4 个容器 · 镜像推送至阿里云 ACR）",
        fontsize=9, color="#8aa295", fontweight="bold")

# 浏览器（顶部，框外）
box(34, 87.5, 32, 10, "浏览器 / Web Chat UI", ["自然语言对话界面"], fc=JADE_L, ec=JADE)

# gateway
box(34, 64, 32, 15, "api-gateway  :8080", ["FastAPI · 系统唯一入口", "托管 Web UI · 请求转发"], fc="white")

# agent
box(34, 42, 32, 15, "agent-service  :8001", ["智能体大脑 · MCP 客户端", "DeepSeek 工具规划循环"], fc="white", ec=AMBER)

# mcp-tool（左下）
box(5, 14.5, 38, 18, "mcp-tool-service  :8002", ["FastMCP · stdio + SSE 双传输", "get_web_content · extract_links",
    "crawl_structured", "save_document · search_documents"], fc=JADE_L, ec=JADE)

# storage（右下）
box(60, 14.5, 35, 18, "storage-service  :8003", ["FastAPI + SQLite", "文档持久化与全文检索", "持久卷 zhiyue-data"], fc="white")

# 外部依赖
ax.text(88, 49.5, "DeepSeek\nAPI", ha="center", va="center", fontsize=8.5, color=AMBER,
        fontweight="bold", bbox=dict(boxstyle="round,pad=0.4", fc="#fdf6e8", ec=AMBER, lw=1.4))
ax.text(15, 7.5, "互联网网页\n(requests / bs4)", ha="center", va="center", fontsize=7.6, color=GREY,
        bbox=dict(boxstyle="round,pad=0.35", fc="#f2f5f3", ec="#c8d6cd"))

# 箭头（标签偏置到一侧，避免压住框内文字）
arrow(50, 87.3, 50, 79.2, "HTTP", lx=56, ly=83.2)
arrow(50, 64, 50, 57.2, "HTTP /api/chat", lx=63, ly=60.6)
arrow(40, 42, 26, 32.7, "MCP (SSE)", color=JADE, lx=27, ly=38.5)
arrow(66, 58.5, 84.5, 52.5, "OpenAI 兼容", color=AMBER, ls=(0, (4, 3)), lx=78, ly=57)
arrow(43, 20, 60, 20, "HTTP 转调", color=JADE, lx=51.5, ly=22.3)
arrow(20, 14.5, 16, 10.4, "抓取", color=GREY, lx=23, ly=12.4)
# gateway 历史浏览直连 storage（只读）
arrow(66, 70, 88, 32.7, "GET /api/documents (历史)", color="#9bb0a4", ls=(0, (3, 3)), lx=82, ly=64)

ax.text(50, 99, "智阅 ZhiYue · 基于 MCP 的智能网页采集分析智能体平台 — 系统架构",
        ha="center", va="top", fontsize=13.5, fontweight="bold", color=SLATE)

os.makedirs("报告/diagrams", exist_ok=True)
out = "报告/diagrams/architecture.png"
plt.savefig(out, bbox_inches="tight", facecolor="white")
print("saved", out)
