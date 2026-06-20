"""新闻去重 / 聚类 + 新鲜度衰减（纯函数，零额外依赖）。

跨源转载的近重复头条会让委员会把"6 份同一新闻"误当 6 条独立证据，伪造共识。
本模块用字符三元组 Jaccard 单链聚类把它们折叠成一簇，"k 源报道"反而成为可信度信号。
另提供基于发布时间的 news_status / 指数衰减权重，供新闻新鲜度治理使用。
"""
import math
import re


def _norm(t):
    return re.sub(r"[\s\W_]+", "", str(t or "").lower())


def _trigrams(s):
    if len(s) < 3:
        return {s} if s else set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def jaccard(a, b):
    ta, tb = _trigrams(_norm(a)), _trigrams(_norm(b))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def cluster_news(items, threshold=0.6):
    """对新闻按标题相似度单链聚类。items: list[{title, source, ...}]。"""
    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(items[i].get("title"), items[j].get("title")) >= threshold:
                parent[find(i)] = find(j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    clusters = []
    for idxs in groups.values():
        srcs = sorted({items[k].get("source") for k in idxs if items[k].get("source")})
        clusters.append({"representative": items[idxs[0]].get("title"),
                         "count": len(idxs), "sources": srcs, "n_sources": len(srcs),
                         "members": idxs})
    clusters.sort(key=lambda c: -c["count"])
    return clusters


def dedupe_and_enrich(items, threshold=0.6):
    """折叠近重复头条：每簇保留一条代表，附 corroboration(转载条数) 与 n_sources。"""
    out = []
    for c in cluster_news(items, threshold):
        rep = dict(items[c["members"][0]])
        rep["corroboration"] = c["count"]
        rep["sources"] = c["sources"]
        rep["n_sources"] = c["n_sources"]
        out.append(rep)
    return out


def news_status(ts, now_ts, half_life_h=24.0, fresh_h=6.0, stale_h=48.0):
    """按发布时间判定 news_status∈{fresh,aging,stale,unknown} 与指数衰减权重。"""
    try:
        age_h = max(0.0, (float(now_ts) - float(ts)) / 3600.0)
    except (TypeError, ValueError):
        return {"news_status": "unknown", "decay_weight": 0.0, "age_hours": None}
    weight = math.exp(-math.log(2) * age_h / half_life_h)
    status = "fresh" if age_h <= fresh_h else ("aging" if age_h <= stale_h else "stale")
    return {"news_status": status, "decay_weight": round(weight, 3), "age_hours": round(age_h, 1)}
