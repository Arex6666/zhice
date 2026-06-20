"""确定性新闻断言分类器（规则 + 词典，非 LLM）。

把一句新闻/证据文本判为 事实(fact) / 情绪(sentiment) / 推断(inference)。
用途：委员会**不轻信 LLM 自报的证据类型**——对引用文本独立重核，发现"标 fact 实为推断/情绪"
则改判，从而让治理 R6（仅情绪/推断证据不得支撑强结论）真正点火。

优先级（高→低）：推断标记 > 情绪标记 > 含数字/事实关键词 → 事实；否则保守归为情绪
（不可验证的文本不应被当作事实）。
"""
import re

# 推断/预期/传闻：不可证实的前瞻或道听途说
INFERENCE = ("预计", "预期", "有望", "或将", "料将", "将会", "可能", "估计", "推测",
             "传闻", "据传", "传言", "暗示", "意味着", "若", "假设", "展望", "看起来",
             "应该会", "恐", "拟", "计划")
# 情绪/态度：带方向性褒贬但非客观事实
SENTIMENT = ("利好", "利空", "看好", "看空", "看多", "看跌", "乐观", "悲观", "担忧",
             "强势", "弱势", "暴涨", "暴跌", "大涨", "大跌", "情绪", "热情", "恐慌",
             "追捧", "炒作", "感觉", "信心")
# 事实关键词：客观、可核验的披露类用语
FACT_KW = ("公告", "财报", "营收", "净利", "净利润", "签署", "中标", "发布", "收购",
           "增持", "减持", "回购", "分红", "上市", "停牌", "复牌", "成交", "持股",
           "季度", "年报", "同比", "环比", "亿元", "万元", "万股")
_NUM = re.compile(r"\d")


def classify_claim(text):
    """返回 'fact' | 'sentiment' | 'inference'。"""
    t = str(text or "")
    if any(k in t for k in INFERENCE):
        return "inference"
    if any(k in t for k in SENTIMENT):
        return "sentiment"
    if _NUM.search(t) or any(k in t for k in FACT_KW):
        return "fact"
    return "sentiment"  # 不可验证 → 保守归为情绪，绝不冒充事实


_EV_TYPE = {"fact": "news_fact", "sentiment": "news_sentiment", "inference": "news_inference"}


def to_evidence_type(label):
    return _EV_TYPE.get(label, "news_sentiment")
