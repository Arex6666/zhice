"""mcp-tool pit_panel：realtime 只读工具的纯函数层（离线可测）。"""
import importlib.util


def _pp():
    s = importlib.util.spec_from_file_location("pp", "services/mcp-tool-service/pit_panel.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_universe_from_rows_lsy():
    pp = _pp()
    rows = [{"symbol": "600519"}, {"symbol": "ST康美"}]
    assert {r["symbol"] for r in pp.universe_from_rows(rows, "on")} == {"600519"}
    assert {r["symbol"] for r in pp.universe_from_rows(rows, "off")} == {"600519", "ST康美"}


def test_execution_mode_realtime():
    pp = _pp()
    assert pp.EXECUTION_MODE == "realtime"
