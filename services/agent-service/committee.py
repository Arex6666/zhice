"""证据链投研委员会：4 位 LLM 分析师 + XGBoost 一票 → 治理引擎 → 主席汇总。

依赖注入（gather_fn / llm）使其可脱网单测。每位委员强制结构化输出（含 evidence /
counter_evidence / abstain）。治理引擎(§7.5)在主席之前对意见施加规则并产出置信度天花板。
"""
import asyncio
import inspect
import json

import governance
import news_nlp

_NEWS_TYPES = ("news_fact", "news_sentiment", "news_inference")


def _reverify_evidence_types(members):
    """独立重核委员引用的新闻证据类型：LLM 标 news_fact 但文本实为推断/情绪 → 改判。

    保留原标注于 type_reverified 供审计。让治理 R6 对"伪装成事实的观点"生效。
    """
    for m in members:
        for e in (m.get("evidence") or []):
            if not isinstance(e, dict) or e.get("type") not in _NEWS_TYPES:
                continue
            text = f"{e.get('value', '')} {e.get('interpretation', '')}".strip()
            if not text:
                continue
            mapped = news_nlp.to_evidence_type(news_nlp.classify_claim(text))
            if mapped != e["type"]:
                e["type_reverified"] = e["type"]
                e["type"] = mapped
    return members

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
    # 风险分级优先用模型自身分位（数据驱动），旧模型无分位时回退绝对 0.6/0.4
    q_ext = ml.get("q_extreme")
    q_ele = ml.get("q_elevated")
    hi = q_ext if isinstance(q_ext, (int, float)) else 0.6
    mid = q_ele if isinstance(q_ele, (int, float)) else 0.4
    level = "高" if p >= hi else ("中" if p >= mid else "低")
    return {"lens": "XGBoost风险信号(波动)", "verdict": "中性", "confidence": 0.0,
            "reasons": [f"模型预测次日大波动概率≈{p:.0%}(样本外 AUC={ml.get('auc')})，属{level}风险；"
                        "仅校准不确定性、不指示涨跌方向"],
            "evidence": [{"type": "model", "source": "ml_signal",
                          "value": f"prob_big_move={p:.2f}, AUC={ml.get('auc')}",
                          "interpretation": f"{level}波动风险"}],
            "counter_evidence": ["波动预测不指示方向；模型为统计弱信号"],
            "risks": ["高波动期方向更难判定，应降低置信度"],
            "abstain": False, "abstain_reason": None, "risk_prob": p}


def factor_member_vote(factor_eval, stock_quantile, residual_quantile, n_quantiles=5):
    """§10.3 因子级证据 → 个股级 stat 证据映射（三闸同时成立才出证据，否则弃权）。

    防"横截面排名当个股 alpha 故事"：必须 (1) family 通过闸门(有效稳定 AND significant)
    AND (2) 个股处极端分位 AND (3) 控制风格后残差仍极端(同侧)。空头方向仅作 view，研究型。
    """
    fe = factor_eval or {}
    name = fe.get("factor_name", "?")
    if not (fe.get("family_verdict") == "有效稳定" and fe.get("significant") == 1):
        return {"lens": f"量化因子:{name}", "verdict": "中性", "confidence": 0.0,
                "evidence": [], "abstain": True, "abstain_reason": "family_not_significant"}
    top, bottom = n_quantiles - 1, 0
    if stock_quantile not in (top, bottom):
        return {"lens": f"量化因子:{name}", "verdict": "中性", "confidence": 0.0,
                "evidence": [], "abstain": True, "abstain_reason": "not_extreme_quantile"}
    if residual_quantile != stock_quantile:   # 控制风格后不再同侧极端 → 被风格解释
        return {"lens": f"量化因子:{name}", "verdict": "中性", "confidence": 0.0,
                "evidence": [], "abstain": True, "abstain_reason": "style_explained"}
    if "direction" not in fe:                  # 方向元数据缺失 → 弃权(勿默认 '+' 致负向因子反号)
        return {"lens": f"量化因子:{name}", "verdict": "中性", "confidence": 0.0,
                "evidence": [], "abstain": True, "abstain_reason": "missing_metadata"}
    side = 1 if stock_quantile == top else -1
    eff = side * (1 if fe.get("direction") == "+" else -1)
    verdict = "偏多" if eff > 0 else "偏空"
    ev = [{"type": "stat", "source": "factor_eval",
           "value": f"{name} 极端分位{stock_quantile}/{n_quantiles}, RankIC={fe.get('mean_rank_ic')}",
           "interpretation": f"family={fe.get('family_verdict')}, 控制风格后仍极端"}]
    return {"lens": f"量化因子:{name}", "verdict": verdict, "confidence": 0.4,
            "evidence": ev, "counter_evidence": [], "risks": ["因子级排名非个股保证, 受R10封顶"],
            "abstain": False, "abstain_reason": None}


def _conf(m):
    try:
        return float(m.get("confidence"))
    except (TypeError, ValueError):
        return 0.5


def _has_substantive(m):
    ev = governance._valid_evidence(m.get("evidence"))
    return any(e["type"] not in governance.SENTIMENT for e in ev)


def _find_dominant_contested(members):
    """冲突时找"被实质证据反对的最高置信度强结论委员"，作为交叉质询对象；否则 None。"""
    actives = [m for m in members if not m.get("abstain") and m.get("verdict") in governance.STRONG]
    dirs = {m["verdict"] for m in actives}
    if not (("偏多" in dirs) and ("偏空" in dirs)):
        return None
    dom = max(actives, key=_conf)
    opponents = [m for m in actives if m["verdict"] != dom["verdict"]]
    return dom if any(_has_substantive(o) for o in opponents) else None


async def _cross_examine(members, llm, model):
    """R9：对支配性强结论委员发**恰好一次**结构化质询——要么用新实质证据反驳，要么降级。

    返回治理报告补充行(或 None)。封顶 1 次 LLM 调用以控成本。
    """
    dom = _find_dominant_contested(members)
    if dom is None or llm is None:
        return None
    prompt = (f"你先前的结论是「{dom.get('verdict')}」(置信度{dom.get('confidence')})，"
              "但其他委员以实质证据持相反观点。请用**新的实质证据(技术指标/量价/回测/可核实事实，"
              "不接受单纯情绪或推断)**反驳对立观点；若拿不出，请把 verdict 改为「中性」。\n"
              + _MEMBER_INSTRUCT)
    try:
        raw = await _call_llm(llm, model, "你是被质询的委员，需以新实质证据捍卫结论或主动降级。", prompt)
    except Exception:
        return None
    resp = _parse_json(raw)
    if isinstance(resp, dict):
        _reverify_evidence_types([{"evidence": resp.get("evidence") or []}])
        if _has_substantive({"evidence": resp.get("evidence") or []}) \
                and (resp.get("verdict") in governance.STRONG):
            return f"R9: 交叉质询「{dom.get('lens', '?')}」→ 其提供新实质证据，维持「{dom.get('verdict')}」"
    dom["verdict"] = "中性"
    dom["cross_examined"] = True
    return f"R9: 交叉质询「{dom.get('lens', '?')}」→ 未能以新实质证据反驳对立观点，降级为中性"


async def run_committee(symbol, gather_fn, llm, model, ml=None,
                        factor_votes=None, factor_flags=None, portfolio_flags=None):
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
    # 量化因子/另类/盈利修正分析师（§10.3 stat 票，离线 factor_eval 产物经依赖注入）
    for fv in (factor_votes or []):
        if fv and not fv.get("abstain"):
            members.append(fv)

    # 独立重核新闻证据类型（不轻信 LLM 自报）
    _reverify_evidence_types(members)
    # R9：冲突时对支配性委员发一次结构化交叉质询（在治理裁决之前）
    xexam_note = await _cross_examine(members, llm, model)

    gov = governance.govern(members, data.get("data_status", "fresh"), ml,
                            bool(data.get("backtest_stable", True)),
                            vol_regime=data.get("vol_regime"),
                            factor_flags=factor_flags, portfolio_flags=portfolio_flags)
    if xexam_note:
        gov["report"].append(xexam_note)
    governed = gov["members_adjusted"]

    chair_blob = "已治理的委员意见：\n" + json.dumps(governed, ensure_ascii=False)[:3500] + \
                 "\n治理记录：" + "；".join(gov["report"])
    chair_raw = await _call_llm(llm, model, _CHAIR_INSTRUCT, chair_blob)
    chair = _parse_json(chair_raw)
    if not isinstance(chair, dict):  # 解析失败或返回非 dict(数组/数字/字符串) → 保守中性，杜绝 502
        chair = {"final": "中性", "confidence": 0.3,
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
            "disagreement": gov.get("disagreement"),
            "verdict": final_verdict, "confidence": final_conf,
            "data_status": data.get("data_status", "fresh"), "disclaimer": DISCLAIMER}
