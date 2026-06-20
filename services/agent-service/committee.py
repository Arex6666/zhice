"""证据链投研委员会：4 位 LLM 分析师 + XGBoost 一票 → 治理引擎 → 主席汇总。

依赖注入（gather_fn / llm）使其可脱网单测。每位委员强制结构化输出（含 evidence /
counter_evidence / abstain）。治理引擎(§7.5)在主席之前对意见施加规则并产出置信度天花板。
"""
import asyncio
import inspect
import json

import governance

DISCLAIMER = "仅供学习研究，不构成投资建议。市场有风险，决策需谨慎。"

LENSES = [
    ("技术面", "你是技术面分析师。基于技术指标(MA/MACD/RSI/BOLL)与形态信号判断多空。"),
    ("资金面", "你是资金面分析师。基于量价、量比、资金动向判断多空。"),
    ("新闻情绪面", "你是新闻情绪分析师。基于新闻判断利好/利空；务必区分事实(news_fact)、"
     "情绪(news_sentiment)与推断(news_inference)。"),
    ("宏观面", "你是宏观面分析师。基于大盘/指数/板块环境判断多空。"),
]

_MEMBER_INSTRUCT = (
    "请只输出 JSON：{\"verdict\":\"偏多/偏空/中性\",\"confidence\":0..1,\"reasons\":[],"
    "\"evidence\":[{\"type\":\"indicator|news_fact|news_sentiment|news_inference|backtest|market\","
    "\"source\":\"工具名\",\"value\":\"具体值\",\"interpretation\":\"解读\"}],"
    "\"counter_evidence\":[],\"risks\":[],\"abstain\":false,\"abstain_reason\":null}。"
    "若数据不足或证据不足，请 abstain=true 并填 abstain_reason。不得在无证据时给出强结论。"
)

_CHAIR_INSTRUCT = (
    "你是投研委员会主席。基于（已经过治理引擎校验的）委员意见，输出 JSON："
    "{\"final\":\"偏多/偏空/中性\",\"confidence\":0..1,\"majority\":\"\",\"minority\":\"\","
    "\"disagreement\":\"分歧来源\",\"key_evidence\":\"最关键证据\",\"counter_evidence\":\"主要反对证据\","
    "\"invalidation\":\"哪些条件会使结论失效\",\"dissent\":\"异议委员\",\"max_risk\":\"最大风险\","
    "\"confidence_reason\":\"为何不是0.9~1.0\"}。不要简单投票，要解释分歧与不确定性。"
)


def _parse_json(content):
    if not content:
        return None
    t = content.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t.strip("`")
        t = t[4:] if t.lower().startswith("json") else t
    try:
        return json.loads(t)
    except Exception:
        s, e = t.find("{"), t.rfind("}")
        if 0 <= s < e:
            try:
                return json.loads(t[s:e + 1])
            except Exception:
                return None
        return None


async def _call_llm(llm, model, system, user):
    resp = llm.chat.completions.create(
        model=model, temperature=0.3,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    if inspect.isawaitable(resp):
        resp = await resp
    return resp.choices[0].message.content


async def _member(llm, model, lens_name, lens_sys, data_blob):
    content = await _call_llm(llm, model, lens_sys, data_blob + "\n" + _MEMBER_INSTRUCT)
    parsed = _parse_json(content)
    if not isinstance(parsed, dict):
        return {"lens": lens_name, "verdict": "中性", "confidence": 0.0, "reasons": [],
                "evidence": [], "counter_evidence": [], "risks": ["解析失败"],
                "abstain": True, "abstain_reason": "委员输出非结构化"}
    parsed["lens"] = lens_name
    parsed.setdefault("evidence", [])
    parsed.setdefault("abstain", False)
    return parsed


def _ml_member(ml):
    """XGBoost 风险信号委员（非方向）：预测次日"大波动"概率，用于校准不确定性。"""
    if not ml or ml.get("abstain"):
        return None
    p = ml.get("prob_big_move")
    if not isinstance(p, (int, float)):  # 非弃权但概率缺失/非数值 → 视同弃权，避免崩溃
        return None
    level = "高" if p > 0.6 else ("中" if p > 0.4 else "低")
    return {"lens": "XGBoost风险信号(波动)", "verdict": "中性", "confidence": 0.0,
            "reasons": [f"模型预测次日大波动概率≈{p:.0%}(样本外 AUC={ml.get('auc')})，属{level}风险；"
                        "仅校准不确定性、不指示涨跌方向"],
            "evidence": [{"type": "backtest", "source": "ml_signal",
                          "value": f"prob_big_move={p:.2f}, AUC={ml.get('auc')}",
                          "interpretation": f"{level}波动风险"}],
            "counter_evidence": ["波动预测不指示方向；模型为统计弱信号"],
            "risks": ["高波动期方向更难判定，应降低置信度"],
            "abstain": False, "abstain_reason": None, "risk_prob": p}


async def run_committee(symbol, gather_fn, llm, model, ml=None):
    data = await gather_fn(symbol)
    blob = f"标的 {symbol}。数据(部分含data_status={data.get('data_status')}):\n" + json.dumps(
        {k: data.get(k) for k in ("indicators", "signals", "news", "backtest", "market")},
        ensure_ascii=False, default=str)[:3500]

    members = await asyncio.gather(*[
        _member(llm, model, name, sys, blob) for name, sys in LENSES])
    members = list(members)
    mlm = _ml_member(ml)
    if mlm:
        members.append(mlm)

    gov = governance.govern(members, data.get("data_status", "fresh"), ml,
                            bool(data.get("backtest_stable", True)))
    governed = gov["members_adjusted"]

    chair_blob = "已治理的委员意见：\n" + json.dumps(governed, ensure_ascii=False)[:3500] + \
                 "\n治理记录：" + "；".join(gov["report"])
    chair_raw = await _call_llm(llm, model, _CHAIR_INSTRUCT, chair_blob)
    chair = _parse_json(chair_raw) or {"final": "中性", "confidence": 0.3,
                                       "confidence_reason": "主席输出解析失败，保守中性"}

    # 置信度容错 + clamp 到 [0, ceiling]（confidence 可能为 null/非数值）
    try:
        raw_conf = float(chair.get("confidence"))
    except (TypeError, ValueError):
        raw_conf = 0.3
    final_conf = round(max(0.0, min(raw_conf, gov["ceiling"])), 3)

    # 方向治理：主席方向必须落在治理允许集合内，否则强制中性（杜绝无据强结论）
    allowed = gov.get("allowed_verdicts", {"中性"})
    final_verdict = chair.get("final", "中性")
    if final_verdict not in allowed:
        gov["report"].append(
            f"治理: 主席方向「{final_verdict}」无存活强结论支撑→强制中性")
        final_verdict = "中性"
        chair["final_governed"] = "中性"

    return {"symbol": symbol, "members": governed, "chairman": chair,
            "governance_report": gov["report"], "conflict": gov["conflict"],
            "verdict": final_verdict, "confidence": final_conf,
            "data_status": data.get("data_status", "fresh"), "disclaimer": DISCLAIMER}
