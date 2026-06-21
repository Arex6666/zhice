"""L6 因子家族闸门：BH-FDR + Harvey 联合判定（family verdict）。"""
import importlib.util
import sys


def _fg():
    sys.path.insert(0, "services/mcp-tool-service")  # imports multi_test
    s = importlib.util.spec_from_file_location("fg", "services/mcp-tool-service/factor_gate.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_family_gate_bh_and_harvey():
    fg = _fg()
    reports = [
        {"factor_name": "good", "ic_block_boot_p": 0.001, "ic_t_hac": 4.0, "significant": 1},
        {"factor_name": "weak", "ic_block_boot_p": 0.04, "ic_t_hac": 2.2, "significant": 1},
        {"factor_name": "noise", "ic_block_boot_p": 0.6, "ic_t_hac": 0.5, "significant": 0},
    ]
    out = fg.family_gate(reports, alpha=0.05)
    g = {r["factor_name"]: r for r in out}
    assert g["good"]["passed"] is True and g["good"]["harvey_passed"] is True
    assert g["noise"]["passed"] is False
    assert g["weak"]["harvey_passed"] is False        # t=2.2 < 3.0


def test_family_gate_handles_abstained():
    fg = _fg()
    reports = [{"factor_name": "ab", "ic_block_boot_p": None, "ic_t_hac": None, "significant": None}]
    out = fg.family_gate(reports)
    assert out[0]["passed"] is False and out[0]["family_verdict"] == "样本不足"
