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
}


def compute(name, data):
    """计算命名因子的时序值（返回 numpy 数组，预热期 NaN）。"""
    if name not in FACTORS:
        raise KeyError(f"未知因子: {name}")
    return factor_dsl.evaluate(FACTORS[name]["formula"], data)


def list_factors():
    return [{"factor_name": k, **{kk: vv for kk, vv in v.items() if kk != "formula"}}
            for k, v in FACTORS.items()]
