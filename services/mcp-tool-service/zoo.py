"""L1 因子库（zoo）：价量因子公式注册表 + DSL 计算。

只放 history_native（K线即可立即计算、立即可回测）的价量因子；估值/质量/另类因子分别由
preprocess/altfactors + PIT 数据层供数（forward_pit_only，初期弃权，见 spec §5）。
每因子带 direction/family/pit_status 元数据，随值穿全链路（诚实标签）。
"""
import factor_dsl

# formula 为 DSL 字符串，变量取自 K 线 {C,O,H,L,V}
FACTORS = {
    "Mom_12_1": {"formula": "Ref(C,21)/Ref(C,252)-1", "direction": "+",
                 "family": "momentum", "pit_status": "history_native",
                 "desc": "12-1月动量(跳一月)"},
    "Rev_5": {"formula": "-(C/Ref(C,5)-1)", "direction": "+",
              "family": "reversal", "pit_status": "history_native",
              "desc": "短期反转(近5日涨幅取负)"},
    "TotalVol": {"formula": "ts_std(delta(Log(C),1),20)", "direction": "-",
                 "family": "low_vol", "pit_status": "history_native",
                 "desc": "20日对数收益波动"},
    "Amihud": {"formula": "ts_mean(Abs(delta(C,1)/Ref(C,1))/(C*V),21)", "direction": "+",
               "family": "liquidity", "pit_status": "history_native",
               "desc": "Amihud 非流动性(近似:|ret|/成交额)"},
    # ---- 扩展价量族（history_native，K线+DSL 立即可计算/可评估）----
    "Mom_6_1": {"formula": "Ref(C,21)/Ref(C,126)-1", "direction": "+",
                "family": "momentum", "pit_status": "history_native", "desc": "6-1月动量(跳一月)"},
    "Rev_1": {"formula": "-(C/Ref(C,1)-1)", "direction": "+",
              "family": "reversal", "pit_status": "history_native", "desc": "1日反转(隔夜涨幅取负)"},
    "Rev_21": {"formula": "-(C/Ref(C,21)-1)", "direction": "+",
               "family": "reversal", "pit_status": "history_native", "desc": "1月反转(近21日涨幅取负)"},
    "Vol_60": {"formula": "ts_std(delta(Log(C),1),60)", "direction": "-",
               "family": "low_vol", "pit_status": "history_native", "desc": "60日对数收益波动"},
    "DownVol": {"formula": "ts_std(If(delta(Log(C),1)<0,delta(Log(C),1),0),20)", "direction": "-",
                "family": "low_vol", "pit_status": "history_native", "desc": "20日下行波动(只计负收益)"},
    "HiLoRange": {"formula": "ts_mean((H-L)/C,20)", "direction": "-",
                  "family": "low_vol", "pit_status": "history_native", "desc": "20日日内高低幅(Parkinson 代理)"},
    "MaxRet": {"formula": "ts_max(delta(C,1)/Ref(C,1),20)", "direction": "-",
               "family": "lottery", "pit_status": "history_native", "desc": "近20日最大单日涨幅(MAX 效应, Bali 2011)"},
    "Hi52": {"formula": "C/ts_max(C,252)", "direction": "+",
             "family": "trend", "pit_status": "history_native", "desc": "52周高点接近度(George-Hwang 2004)"},
    "MA_Trend": {"formula": "ts_mean(C,5)/ts_mean(C,20)-1", "direction": "+",
                 "family": "trend", "pit_status": "history_native", "desc": "MA5/MA20 趋势强度"},
    "RangePos": {"formula": "(C-ts_min(L,20))/(ts_max(H,20)-ts_min(L,20))", "direction": "+",
                 "family": "trend", "pit_status": "history_native", "desc": "20日区间相对位置(随机指标 %K)"},
    "VolRatio": {"formula": "ts_mean(V,5)/ts_mean(V,60)", "direction": "-",
                 "family": "volume", "pit_status": "history_native", "desc": "量比(5/60日均量), 异常放量→谨慎"},
    "PVCorr": {"formula": "corr(delta(C,1),delta(V,1),20)", "direction": "+",
               "family": "volume", "pit_status": "history_native", "desc": "20日量价相关(量能确认趋势)"},
}


def compute(name, data):
    """计算命名因子的时序值（返回 numpy 数组，预热期 NaN）。"""
    if name not in FACTORS:
        raise KeyError(f"未知因子: {name}")
    return factor_dsl.evaluate(FACTORS[name]["formula"], data)


def list_factors():
    return [{"factor_name": k, **{kk: vv for kk, vv in v.items() if kk != "formula"}}
            for k, v in FACTORS.items()]
