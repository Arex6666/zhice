"""L0 业绩真披露日接线进快照（snapshot_earnings, 依赖注入脱网可测）。"""
import asyncio
import importlib.util
import sys


def _ps():
    sys.path.insert(0, "services/ingestion-service")
    s = importlib.util.spec_from_file_location("ps", "services/ingestion-service/pit_snapshot.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_snapshot_earnings_posts_disclosed_date():
    ps = _ps()
    posts = []

    async def fetch(period):
        return [{"symbol": "600519", "period": period, "disclosed_date": "2024-01-31",
                 "legal_deadline": "2024-04-30", "announce_date": "2024-01-31",
                 "pit_status": "lagged_disclosed"}]

    async def post(p):
        posts.append(p)

    out = asyncio.run(ps.snapshot_earnings(fetch, post, ["2023Q4"]))
    assert out["posted"] == 1 and out["failures"] == 0
    p = posts[0]
    assert p["disclosed_date"] == "2024-01-31" and p["legal_deadline"] == "2024-04-30"
    assert p["pit_status"] == "lagged_disclosed" and p["field"] == "earnings_disclosed"


def test_snapshot_earnings_isolates_fetch_failure():
    ps = _ps()

    async def fetch(period):
        raise RuntimeError("ak boom")

    async def post(p):
        pass

    out = asyncio.run(ps.snapshot_earnings(fetch, post, ["2023Q4", "2024Q1"]))
    assert out["failures"] == 2 and out["posted"] == 0   # 两期取数失败各计一次, 不抛


def test_recent_periods_and_ak_date():
    ps = _ps()
    ps_periods = ps.recent_periods("2024-06-21")
    assert ps_periods == ["2023Q4", "2024Q1", "2024Q2", "2024Q3"]
    assert ps._ak_report_date("2023Q4") == "20231231"
    assert ps._ak_report_date("2024Q2") == "20240630"
