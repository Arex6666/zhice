"""ingestion PIT 快照 job：依赖注入(fake fetch/post)可测，失败隔离。"""
import asyncio
import importlib.util


def _ps():
    s = importlib.util.spec_from_file_location("ps", "services/ingestion-service/pit_snapshot.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_snapshot_universe_posts_membership():
    ps = _ps()
    posted = []

    async def fetch_cons(code):
        return [{"symbol": "600519", "weight": 1.0, "index_code": code,
                 "universe_pit_status": "today_snapshot_only"},
                {"symbol": "000001", "weight": 0.5, "index_code": code,
                 "universe_pit_status": "today_snapshot_only"}]

    async def post(payload):
        posted.append(payload)

    out = asyncio.run(ps.snapshot_universe(fetch_cons, post, index_code="000906", as_of="2024-06-01"))
    assert out["posted"] == 2 and all(p["date"] == "2024-06-01" for p in posted)


def test_snapshot_valuation_posts_last_value():
    ps = _ps()
    posted = []

    async def fetch_val(sym, ind, per):
        return [{"date": "2024-05-31", "value": 30.0}, {"date": "2024-06-01", "value": 28.0}]

    async def post(p):
        posted.append(p)

    out = asyncio.run(ps.snapshot_valuation(fetch_val, post, ["600519"], indicator="市盈率(动)"))
    assert out["posted"] == 1 and posted[0]["value"] == 28.0 and posted[0]["field"] == "市盈率(动)"


def test_snapshot_isolates_per_symbol_failure():
    ps = _ps()
    posted = []

    async def fetch_val(sym, ind, per):
        if sym == "BAD":
            raise RuntimeError("network")
        return [{"date": "2024-06-01", "value": 10.0}]

    async def post(p):
        posted.append(p)

    out = asyncio.run(ps.snapshot_valuation(fetch_val, post, ["GOOD", "BAD", "GOOD2"]))
    assert out["posted"] == 2 and out["failures"] == 1   # BAD 隔离, 其余成功
