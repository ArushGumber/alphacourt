import json

import pytest

from court import forensics, roles, trial
from court.types import CaseFile, Claim, Exhibit, StrategySpec
from llm import client


@pytest.fixture
def case():
    return CaseFile(case_id="c1", world_id="w1-a", spec=StrategySpec(name="s", signal="rank(ret)", lag=0),
                    claim=Claim(sharpe=2.9), log_summary={"n_trials": 3, "best_of": 3})


@pytest.fixture(autouse=True)
def fake_lab(monkeypatch):
    def run_tool(name, args, case, world, log, *, exhibit_id, called_by):
        return Exhibit(id=exhibit_id, test=name, params=args, numbers={"sharpe_after": 0.1}, summary=f"{name} ran.",
                       hint="damaging", called_by=called_by)
    monkeypatch.setattr(forensics, "run_tool", run_tool)
    monkeypatch.setattr(forensics, "TOOLS", {"lag_test": {"description": "d", "args": {"k": {"type": "int", "default": 1}}}})


def script(*replies):
    it = iter(replies)
    seen = []

    def fn(messages):
        seen.append(messages)
        return next(it)
    return fn, seen


def J(x):
    return json.dumps(x)


def test_parse_lenient():
    assert roles.parse_action('```json\n{"tool": "a", "args": {"k": 1}}\n```') == {"tool": "a", "args": {"k": 1}}
    assert roles.parse_action('Sure! {"final": {"x": 1}} thanks') == {"final": {"x": 1}}
    assert roles.parse_action("<think>{\"tool\":\"no\"}</think>{\"final\": {}}") == {"final": {}}
    assert roles.parse_action("no json here") is None
    assert roles.parse_action('{"other": 1}') is None


def test_court_sustained_with_exhibit(case):
    fn, _ = script(J({"tool": "lag_test", "args": {"k": 1}}), J({"final": {"charges": [{"sin": "lookahead", "exhibits": ["EX-1"], "argument": "a"}]}}),
                   J({"final": {"rebuttals": [{"sin": "lookahead", "concede": True, "exhibits": [], "argument": "ok"}]}}),
                   J({"final": {"ruling": "reject", "findings": [{"sin": "lookahead", "sustained": True, "exhibits": ["EX-1"]}], "capital_allowed": 0, "opinion": "o"}}))
    client.register_fake("t1", fn)
    ev = []
    rec = trial.run_trial(case, None, None, system="court", staffing={"default": "fake:t1"}, on_event=ev.append)
    assert rec.verdict.ruling == "reject" and not rec.verdict.unsupported
    assert rec.calls == 4 and len(rec.exhibits) == 1 and rec.charges[0].sin == "lookahead"
    assert [e.kind for e in ev][:3] == ["case", "tool_call", "exhibit"] and ev[-1].kind == "verdict"


def test_exhibit_rule_strikes_and_converts(case):
    fn, _ = script(J({"final": {"charges": [{"sin": "costs", "exhibits": ["EX-9"], "argument": "a"}]}}),
                   J({"final": {"rebuttals": []}}),
                   J({"final": {"ruling": "reject", "findings": [{"sin": "costs", "sustained": True, "exhibits": ["EX-9"]}], "opinion": "o"}}))
    client.register_fake("t2", fn)
    rec = trial.run_trial(case, None, None, system="court", staffing={"prosecution": "fake:t2", "defence": "fake:t2", "judge": "fake:t2"})
    assert rec.verdict.ruling == "deploy" and rec.verdict.unsupported
    assert rec.verdict.findings[0].struck


def test_repair_then_no_action(case):
    fn, seen = script("garbage", "still garbage", J({"final": {"ruling": "deploy", "findings": [], "capital_allowed": 1, "opinion": "fine"}}))
    client.register_fake("t3", fn)
    rec = trial.run_trial(case, None, None, system="court", staffing={"default": "fake:t3"})
    # prosecutor: 2 calls, no action -> no charges -> defence skipped -> judge 1 call
    assert rec.calls == 3 and rec.charges == [] and rec.verdict.ruling == "deploy"
    assert any(e.kind == "error" for e in rec.events)


def test_tool_budget(case):
    calls = [J({"tool": "lag_test", "args": {}})] * 8 + [J({"final": {"charges": []}})]
    fn, _ = script(*calls, J({"final": {"ruling": "deploy", "findings": [], "opinion": ""}}))
    client.register_fake("t4", fn)
    rec = trial.run_trial(case, None, None, system="court", staffing={"default": "fake:t4"}, budget={"prosecutor_tools": 2})
    assert len(rec.exhibits) == 2


def test_debate_and_single_and_none(case):
    fn, _ = script(J({"final": {"charges": [{"sin": "lookahead", "exhibits": [], "argument": "lag 0"}]}}),
                   J({"final": {"rebuttals": []}}),
                   J({"final": {"ruling": "reject", "findings": [{"sin": "lookahead", "sustained": True, "exhibits": []}], "opinion": "o"}}))
    client.register_fake("t5", fn)
    rec = trial.run_trial(case, None, None, system="debate", staffing={"default": "fake:t5"})
    assert rec.verdict.ruling == "reject" and rec.exhibits == []
    fn, _ = script(J({"final": {"ruling": "paper", "findings": [], "opinion": "o"}}))
    client.register_fake("t6", fn)
    assert trial.run_trial(case, None, None, system="single", staffing={"judge": "fake:t6"}).verdict.ruling == "paper"
    assert trial.run_trial(case, None, None, system="none", staffing={}).verdict.ruling == "deploy"


def test_prompts_do_not_leak_answers():
    for p in (roles.PROSECUTOR_SYSTEM, roles.DEFENCE_SYSTEM, roles.JUDGE_SYSTEM, roles.SINGLE_SYSTEM):
        assert "lag 0" not in p.lower() and "guilty" not in p.lower()
    assert isinstance(roles.PROMPT_VERSION, str)


def test_cache_and_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "CACHE_DIR", tmp_path / "c")
    monkeypatch.setattr(client, "BUDGET_FILE", tmp_path / "b.json")
    (tmp_path / "b.json").write_text('{"claude": {"cap": 1, "used": 1}, "codex": {"cap": 100, "used": 0}}')
    with pytest.raises(client.LLMError):
        client.chat("claude:haiku", [{"role": "user", "content": "x"}])
    with pytest.raises(ValueError):
        client.chat("codex:gpt-6-astra", [{"role": "user", "content": "x"}])
    k = client.cache_key("local:qwen3-8b", [{"role": "user", "content": "x"}], 10, 0.0)
    client._cache_put(k, {"text": "hi", "tokens_in": 1, "tokens_out": 1})
    monkeypatch.setattr(client, "_local", lambda *a: (_ for _ in ()).throw(AssertionError("called")))
    r = client.chat("local:qwen3-8b", [{"role": "user", "content": "x"}], max_tokens=10)
    assert r.cached and r.text == "hi"
