import json
import time

from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.guard import Guard, Limits, RateLimiter, check_lengths
from .test_gateway_fakes import make_service, make_trial


def rpc(client, method, params=None, mid=1, headers=None):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}},
                    headers=headers or {})
    return r


def call(client, sid, name, args):
    r = rpc(client, "tools/call", {"name": name, "arguments": args}, headers={"mcp-session-id": sid})
    assert r.status_code == 200
    return r.json()["result"]


def spec(i, **kw):
    return {"name": f"mom{i}", "signal": f"rank(ts_mean(ret, {i}))", "params": {"window": i}, **kw}


def wait_ruled(client, cid, tries=200):
    for _ in range(tries):
        s = client.get(f"/api/cases/{cid}").json()
        if s["status"] in ("ruled", "failed"):
            return s
        time.sleep(0.02)
    raise AssertionError("not ruled")


def test_mcp_end_to_end(tmp_path):
    svc = make_service(tmp_path)
    c = TestClient(create_app(svc, dist=None))
    r = rpc(c, "initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "tester"}, "world": "demo"})
    sid = r.headers["mcp-session-id"]
    assert r.json()["result"]["serverInfo"]["name"] == "alphacourt-gateway"
    assert rpc(c, "ping").json()["result"] == {}
    assert c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    names = [t["name"] for t in rpc(c, "tools/list").json()["result"]["tools"]]
    assert names == ["list_fields", "field_info", "read_page", "run_backtest", "submit_strategy", "get_verdict"]
    assert not call(c, sid, "list_fields", {})["isError"]
    assert call(c, sid, "field_info", {"name": "close"})["structuredContent"]["description"] == "Close price."
    assert call(c, sid, "field_info", {"name": "nope"})["isError"]
    page = call(c, sid, "read_page", {"url": "https://alpha.web/x"})
    assert page["structuredContent"]["found"] is False and "No such page" in page["content"][0]["text"]
    for i in (5, 10, 20):
        res = call(c, sid, "run_backtest", {"spec": spec(i)})
        assert res["structuredContent"]["trial_number"] == (5, 10, 20).index(i) + 1
    bad = call(c, sid, "run_backtest", {"spec": {"name": "x"}})
    assert bad["isError"] and "signal" in bad["content"][0]["text"]
    sub = call(c, sid, "submit_strategy", {"spec": spec(10), "claim": {"sharpe": 2.0, "text": "good"},
                                           "requested_capital": 500000})
    cid = sub["structuredContent"]["case_id"]
    assert cid == "AC-0001" and sub["structuredContent"]["status"] == "held"
    assert sub["structuredContent"]["watch_url"] == "/#/court/AC-0001"
    assert svc.wait_idle()
    v = call(c, sid, "get_verdict", {"case_id": cid})["structuredContent"]
    assert v["status"] == "ruled" and v["verdict"]["ruling"] == "deploy"
    assert v["exhibits"][0]["id"] == "EX-1" and v["broker_action"]["capital"] == 250_000.0
    assert svc.broker.account(sid)["live_capital"] == 250_000.0
    assert svc.session(sid)["log"].agent == "tester"


def test_log_summary_counts(tmp_path):
    svc = make_service(tmp_path)
    for i in (5, 10, 15, 5):                       # one repeat of a spec
        svc.run_backtest("s1", spec(i))
    svc.run_backtest("s1", {"name": "other", "signal": "rank(ret)", "params": {"window": 15, "k": "a"}})
    r = svc.submit_strategy("s1", spec(10), {"sharpe": 1.0})
    case = svc.get_case(r["case_id"])["case"]
    ls = case["log_summary"]
    assert ls["n_trials"] == 5 and ls["n_distinct_specs"] == 4
    assert ls["grid"]["window"] == [5, 10, 15] and ls["grid"]["k"] == ["a"]
    from .test_gateway_fakes import fake_backtest, spec_hash
    from court.types import StrategySpec
    sharpes = {i: fake_backtest(StrategySpec(**spec(i)), None).metrics.sharpe for i in (5, 10, 15)}
    sharpes["o"] = fake_backtest(StrategySpec(name="other", signal="rank(ret)", params={"window": 15, "k": "a"}),
                                 None).metrics.sharpe
    rank = 1 + sum(1 for k, s in sharpes.items() if k != 10 and s > sharpes[10])
    assert ls["best_of"] == rank and ls["is_best"] == (rank == 1)
    # a spec never backtested is ranked but not logged
    r2 = svc.submit_strategy("s1", spec(33), {"sharpe": 1.0})
    ls2 = svc.get_case(r2["case_id"])["case"]["log_summary"]
    assert ls2["n_trials"] == 5 and ls2["best_of"] is not None
    assert svc.wait_idle()


def test_http_mirror_audit_and_failure(tmp_path):
    svc = make_service(tmp_path)
    c = TestClient(create_app(svc, dist=None))
    assert c.get("/api/health").json()["ok"]
    assert {w["name"] for w in c.get("/api/worlds").json()["worlds"]} >= {"demo"}
    h = {"X-Session": "web1"}
    r = c.post("/api/backtest", json={"spec": spec(7)}, headers=h)
    assert r.status_code == 200 and r.json()["result"]["metrics"]["n_days"] == 40
    assert c.post("/api/backtest", json={"spec": {"name": "x", "signal": "a", "lag": 99}}, headers=h).status_code == 400
    r = c.post("/api/submit", json={"spec": spec(7), "claim": {"sharpe": 1.5}, "requested_capital": 1e6}, headers=h)
    cid = r.json()["case_id"]
    s = wait_ruled(c, cid)
    assert s["status"] == "ruled"
    audit = json.loads((tmp_path / "audit" / f"{cid}.json").read_text())
    for k in ("submission", "log_summary", "staffing", "model_ids", "exhibits", "charges", "rebuttals", "verdict",
              "timings", "prompt_version", "hashes", "broker_action"):
        assert k in audit
    assert audit["prompt_version"] == "test-v0" and len(audit["model_ids"]) == 1  # the configured staffing
    assert len(audit["hashes"]["spec"]) == 12 and len(audit["hashes"]["world"]) == 12
    assert audit["broker_action"]["simulated"] is True
    assert cid in [x["case_id"] for x in c.get("/api/cases").json()["cases"]]
    assert c.get("/api/cases/AC-9999").status_code == 404
    # a failing trial books nothing and is audited
    svc2 = make_service(tmp_path / "f", trial_fn=make_trial(fail=True))
    c2 = TestClient(create_app(svc2, dist=None))
    cid2 = c2.post("/api/submit", json={"spec": spec(7), "claim": {"sharpe": 1}}, headers=h).json()["case_id"]
    assert wait_ruled(c2, cid2)["status"] == "failed"
    assert svc2.broker.account("web1")["live_capital"] == 0
    assert json.loads((tmp_path / "f" / "audit" / f"{cid2}.json").read_text())["error"]


def test_reject_and_paper_book(tmp_path):
    for ruling, live, paper in (("reject", 0, 0), ("paper", 0, 1e6), ("deploy", 250_000.0, 0)):
        svc = make_service(tmp_path / ruling, trial_fn=make_trial(ruling))
        svc.submit_strategy("s", spec(5), {"sharpe": 1}, 1e6)
        assert svc.wait_idle()
        a = svc.broker.account("s")
        assert (a["live_capital"], a["paper_capital"]) == (live, paper)


def test_sse_replay(tmp_path):
    svc = make_service(tmp_path)
    c = TestClient(create_app(svc, dist=None))
    cid = c.post("/api/submit", json={"spec": spec(7), "claim": {"sharpe": 1.5}}).json()["case_id"]
    assert svc.wait_idle()

    def stream():
        out = []
        with c.stream("GET", f"/api/cases/{cid}/events") as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            name = None
            for line in r.iter_lines():
                if line.startswith("event:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    out.append((name, json.loads(line.split(":", 1)[1])))
        return out
    first = stream()
    kinds = [k for k, _ in first]
    assert kinds[0] == "case" and kinds[-1] == "end" and "exhibit" in kinds and "note" in kinds
    assert stream() == first                      # a second watcher replays the same events
    # after a restart the events replay from disk
    svc2 = make_service(tmp_path)
    evs, done = svc2.events_since(cid, 0)
    assert done and len(evs) == len(first) - 1


def test_site_trial_endpoint(tmp_path):
    svc = make_service(tmp_path)
    c = TestClient(create_app(svc, Limits(trials_per_hour=100), dist=None))
    cid = c.post("/api/submit", json={"spec": spec(7), "claim": {"sharpe": 1.5}}).json()["case_id"]
    assert svc.wait_idle()
    r = c.post("/api/trial", json={"case_id": cid, "system": "single", "staffing": {"judge": "local:phi4-mini"}})
    tid = r.json()["case_id"]
    assert tid.startswith("TR-")
    s = wait_ruled(c, tid)
    assert s["system"] == "single" and s["staffing"]["judge"] == "local:phi4-mini" and s["broker_action"] is None
    assert c.post("/api/trial", json={"case_id": cid, "system": "bogus"}).status_code == 400
    assert c.post("/api/trial", json={"case_id": cid, "staffing": {"judge": "claude:opus"}}).status_code == 400
    assert c.post("/api/trial", json={}).status_code == 400


def test_queue_is_bounded(tmp_path):
    svc = make_service(tmp_path, trial_fn=make_trial(delay=0.4), config={"max_concurrent_trials": 1, "queue_max": 1})
    svc.submit_strategy("s", spec(5), {"sharpe": 1})
    svc.submit_strategy("s", spec(6), {"sharpe": 1})
    try:
        svc.submit_strategy("s", spec(7), {"sharpe": 1})
        raise AssertionError("expected busy")
    except Exception as e:
        assert getattr(e, "code", None) == 503
    assert svc.wait_idle(10)


def test_world_choice_and_pages(tmp_path):
    svc = make_service(tmp_path, pages_fn=lambda u: "Hello" if u == "u1" else None)
    assert svc.read_page("a", "u1")["found"] and svc.session("a")["log"].pages_read == ["u1"]
    svc.session("b", "backfilled")
    svc.list_fields("b", "demo")                   # fixed at the first choice
    assert svc.session("b")["world"] == "backfilled"
    try:
        svc.session("c", "nowhere")
        raise AssertionError
    except Exception as e:
        assert "No such world" in str(e)


def test_guard_limits(tmp_path):
    t = [0.0]
    rl = RateLimiter(60, 3, clock=lambda: t[0])
    assert [rl.take("a") for _ in range(3)] == [0, 0, 0] and rl.take("a") > 0 and rl.take("b") == 0
    t[0] += 2
    assert rl.take("a") == 0
    lim = Limits(backtests_per_minute=30, trials_per_hour=3, local_exempt=False)
    assert all(lim.backtest_wait("s") == 0 for _ in range(30)) and lim.backtest_wait("s") > 0
    assert lim.backtest_wait("other") == 0
    assert [lim.trial_wait("1.2.3.4") for _ in range(3)] == [0, 0, 0] and lim.trial_wait("1.2.3.4") > 0
    assert Limits().trial_wait("127.0.0.1") == 0           # this machine is exempt by default
    assert check_lengths({"signal": "x" * 401}) and check_lengths({"signal": "x", "notes": "y" * 2001})
    assert check_lengths({"signal": "x"}, {"text": "z" * 2001}) and check_lengths({"signal": "x"}) is None
    slots = Limits().streams
    leases = [slots.acquire("ip")[0] for _ in range(4)]
    assert None not in leases and slots.acquire("ip")[0] is None
    slots.release(leases[0])
    assert slots.acquire("ip")[0] is not None


def test_http_guard_caps(tmp_path):
    svc = make_service(tmp_path)
    lim = Limits(general=RateLimiter(60, 5), backtests_per_minute=2)
    c = TestClient(create_app(svc, lim, dist=None))
    big = c.post("/api/backtest", content=b"{" + b" " * 70000 + b"}")
    assert big.status_code == 413
    long_sig = c.post("/api/backtest", json={"spec": {"name": "x", "signal": "a" * 500}})
    assert long_sig.status_code == 400 and "400" in long_sig.json()["detail"]
    codes = [c.post("/api/backtest", json={"spec": spec(i)}, headers={"X-Session": "q"}).status_code
             for i in (3, 4, 5)]
    assert 429 in codes
    assert c.get("/api/health").status_code in (200, 429)


def test_public_trial_limit_on_mcp(tmp_path):
    svc = make_service(tmp_path)
    lim = Limits(trials_per_hour=1, local_exempt=False)
    c = TestClient(create_app(svc, lim, dist=None))
    sid = rpc(c, "initialize").headers["mcp-session-id"]
    ok = call(c, sid, "submit_strategy", {"spec": spec(5), "claim": {"sharpe": 1}})
    assert not ok["isError"]
    again = call(c, sid, "submit_strategy", {"spec": spec(6), "claim": {"sharpe": 1}})
    assert again["isError"] and "Too many trials" in again["content"][0]["text"]
    assert svc.wait_idle()


def test_static_site(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>site</html>")
    (dist / "a.js").write_text("x")
    c = TestClient(create_app(make_service(tmp_path / "s"), dist=dist))
    assert c.get("/").text == "<html>site</html>" and c.get("/a.js").text == "x"
    assert c.get("/court/AC-1").text == "<html>site</html>"
    assert c.get("/..%2f..%2fetc/passwd").text == "<html>site</html>"
    assert c.get("/api/nothing").status_code == 404


def test_truth_endpoint_caches(tmp_path):
    svc = make_service(tmp_path)
    calls = []

    def fake_true_edge(sp, w):
        calls.append(sp.name)
        return {"sharpe": 0.4, "per_seed": [0.3, 0.4, 0.5], "how": "fake"}
    svc._true_edge = fake_true_edge
    c = TestClient(create_app(svc, dist=None))
    body = {"spec": spec(10), "world": "demo"}
    a = c.post("/api/truth", json=body)
    b = c.post("/api/truth", json=body)
    assert a.status_code == 200 and a.json()["sharpe"] == 0.4 and a.json() == b.json() and len(calls) == 1
    assert c.post("/api/truth", json={"spec": {"name": "x"}}).status_code == 400
    assert c.post("/api/truth", json={"spec": spec(10), "world": "nope"}).status_code == 400
