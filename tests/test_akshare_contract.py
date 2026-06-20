"""M0 接口契约：固化已实测的 akshare 接口存在性（防纸面接口漂移）。"""
import inspect

import pytest

ak = pytest.importorskip("akshare")

EXIST = ["stock_zh_valuation_baidu", "stock_a_all_pb", "stock_zh_a_spot_em",
         "index_stock_cons_csindex", "stock_hsgt_hold_stock_em", "stock_yjyg_em",
         "stock_yjkb_em", "stock_zh_a_gdhs_detail_em", "index_option_300etf_qvix",
         "stock_board_industry_name_em", "stock_individual_info_em",
         "stock_financial_analysis_indicator", "stock_individual_fund_flow",
         "stock_gpzy_pledge_ratio_em", "stock_restricted_release_queue_em",
         "tool_trade_date_hist_sina"]


def test_dead_interface_absent():
    assert not hasattr(ak, "stock_a_indicator_lg")  # 决策书纸面接口, 实测失效


def test_required_interfaces_exist():
    missing = [f for f in EXIST if not hasattr(ak, f)]
    assert missing == [], f"missing akshare interfaces: {missing}"


def test_baidu_valuation_has_indicator_period():
    params = set(inspect.signature(ak.stock_zh_valuation_baidu).parameters)
    assert {"symbol", "indicator", "period"} <= params
