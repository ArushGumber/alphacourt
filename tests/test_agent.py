import json
import time

import pytest
from fastapi.testclient import TestClient

from agent import briefs
from agent.research import parse_action, run_session
from alphaweb import pages
from gateway.app import create_app
from gateway.studio import Studio, make_router
from llm.client import ChatResult, register_fake
from .test_gateway_fakes import make_service


def scripted(steps):
    it = iter(steps)

    def fn(messages):
        return next(it)
    return fn


def A(tool, **args):
    return json.dumps({"tool": tool, "args": args})


SPEC = {"name": "mom", "signal": "rank(ts_mean(ret, 20))", "params": {"w": 20}}
STEPS = [A("list_fields"), A("read_page", url="https://alphaweb.example/"), A("run_backtest", spec=SPEC),
         "```json\n" + A("submit_strategy", spec=SPEC, claim={"sharpe": 1.0, "text": "ok"}) + "\n```"]


def fresh(tmp_path, steps, name):
    register_fake(name, scripted(steps))
    return make_service(tmp_path, pages_fn=pages.get_text)


def test_pages():
    assert len(pages.PAGES) >= 11
    assert all(u.endswith(".example") or ".example/" in u for u in pages.PAGES)
    assert pages.read_page("https://nope.example/") == "no such page"
    assert pages.get_text("https://quantforum.example/t/1951").count("automated reviewers") == 1
    assert "sentiment_revised" in pages.get_text("https://alphablog.example/sharpe-3-recipe")
    index = pages.get_text(pages.INDEX)
    assert all(u in index for u in pages.PAGES if u != pages.INDEX)
    assert {p["kind"] for p in pages.list_pages()} >= {"blog", "forum", "paper", "docs", "index"}


def test_parse_action():
    assert parse_action('noise {"tool": "x", "args": {}} tail')["tool"] == "x"
    assert parse_action('{"final": "done"}')["final"] == "done"
    assert parse_action("no json") is None


def test_session_in_process(tmp_path):
    svc = fresh(tmp_path, STEPS, "h1")
    events = []
    r = run_session(briefs.PRESSURE, "fake:h1", gateway=svc, on_event=events.append, out_dir=tmp_path / "r",
                    poll_interval=0.02, verdict_timeout=10)
    assert r.status == "finished" and r.n_backtests == 1 and r.pages_read == ["https://alphaweb.example/"]
    assert r.case_id == "AC-0001" and r.spec["name"] == "mom" and r.verdict["status"] == "ruled"
    assert r.verdict["verdict"]["ruling"] == "deploy" and r.model_calls == 4
    assert any(e["kind"] == "verdict" for e in events) and events[-1]["kind"] == "end"
    saved = json.loads((tmp_path / "r" / f"{r.session_id}.json").read_text())
    assert saved["case_id"] == "AC-0001"
    assert "court" not in saved["transcript"][0]["content"].lower().replace("it is tried", "")
    svc.shutdown()


def test_repair_and_budget(tmp_path):
    svc = fresh(tmp_path, ["garbage", A("list_fields")] * 5, "h2")
    r = run_session("neutral", "fake:h2", gateway=svc, max_calls=3, out_dir=None)
    assert r.status == "budget" and r.tool_calls == 3
    svc2 = fresh(tmp_path / "b", ["x", "y"], "h3")
    assert run_session("neutral", "fake:h3", gateway=svc2, out_dir=None).status == "error"
    svc3 = fresh(tmp_path / "c", ['{"final": "no edge found"}'], "h4")
    r3 = run_session("neutral", "fake:h4", gateway=svc3, out_dir=None)
    assert r3.status == "no_submission" and r3.case_id is None


def test_session_over_http(tmp_path):
    svc = fresh(tmp_path, STEPS, "h5")
    app = create_app(svc, dist=None)
    tc = TestClient(app, base_url="http://127.0.0.1:8787")

    class Shim:      # route the agent's httpx client through the test client
        def post(self, url, json=None, headers=None):
            return tc.post("/mcp", json=json, headers=headers)
    import agent.research as ar
    link = ar.Http.__new__(ar.Http)
    link.url, link.client, link._n = "http://x/mcp", Shim(), 0
    r0 = link._post({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"clientInfo": {"name": "t"}}})
    link.sid = r0.headers["mcp-session-id"]
    text, data, bad = link.call("list_fields", {})
    assert not bad and "close" in text
    svc.shutdown()


def test_studio(tmp_path):
    svc = fresh(tmp_path, STEPS, "h6")
    app = create_app(svc, dist=None)
    c = TestClient(app)
    ok = {"brief": "pressure", "model": "local:qwen3-8b", "world": "demo"}
    assert c.post("/api/studio/start", json={**ok, "model": "local:nope"}).status_code == 400
    assert c.post("/api/studio/start", json={**ok, "user_key": "A" * 30}).status_code == 400   # not a google model
    assert c.post("/api/studio/start", json={**ok, "brief": ""}).status_code == 400
    svc.shutdown()


def test_studio_limits_and_stream(tmp_path):
    svc = fresh(tmp_path, STEPS, "h7")
    gate = {"go": False}

    def run_fn(brief, model, *, world, gateway, max_calls, on_event, session_id, chat_fn, **kw):
        on_event({"t": 0, "kind": "note", "text": "hi"})
        while not gate["go"]:
            time.sleep(0.01)
        chat_fn("fake:h7", [{"role": "user", "content": "x"}])
        on_event({"t": 1, "kind": "end", "status": "finished"})

    st = Studio(svc, run_fn=run_fn, calls_per_hour=1, per_ip_per_day=2)
    body = {"brief": "neutral", "model": "local:qwen3-8b"}
    s1 = st.start(body, "1.1.1.1", secure=True, local=False)
    with pytest.raises(Exception, match="already have"):
        st.start(body, "1.1.1.1", secure=True, local=False)
    s2 = st.start(body, "2.2.2.2", secure=True, local=False)
    with pytest.raises(Exception, match="busy"):
        st.start(body, "3.3.3.3", secure=True, local=False)
    # own key: needs https or local
    kb = {**body, "model": "google:gemini-2.5-flash", "user_key": "K" * 30}
    gate["go"] = True
    time.sleep(0.3)
    with pytest.raises(Exception, match="HTTPS"):
        st.start(kb, "4.4.4.4", secure=False, local=False)
    evs, done = st.agent_events_since(s1, 0)
    assert evs[0]["text"] == "hi"
    assert st._calls_left() <= 0          # the hourly cap is spent, so the next start is refused
    with pytest.raises(Exception, match="hourly"):
        st.start(body, "5.5.5.5", secure=True, local=False)
    svc.shutdown()


def test_studio_sse(tmp_path):
    svc = fresh(tmp_path, [], "h8")
    app = create_app(svc, dist=None)
    done_evs = [{"t": 0, "kind": "end", "status": "finished"}]
    st = Studio(svc, run_fn=lambda *a, on_event, **k: [on_event(e) for e in done_evs])
    app2 = create_app(svc, dist=None)
    app2.include_router(make_router(svc, st))     # a second router with the stub runner, first match wins below
    app2.router.routes.insert(0, app2.router.routes.pop())
    c = TestClient(app2)
    sid = c.post("/api/studio/start", json={"brief": "neutral", "model": "local:qwen3-8b"}).json()["session_id"]
    time.sleep(0.2)
    body = c.get(f"/api/studio/{sid}/events").text
    assert "event: agent" in body and "event: end" in body
    svc.shutdown()
