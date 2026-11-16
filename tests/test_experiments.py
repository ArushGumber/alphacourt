import json
import math

import pytest

from court.types import CaseFile, Claim, Exhibit, Finding, StrategySpec, TrialRecord, Verdict
from experiments import runner, score
from experiments.runner import Meta, run_cases


def raw_case(i, role, sin=None, twin=None):
    return {"case_id": f"c{i}", "role": role, "sin": sin, "level": "L1", "family": "momentum", "twin_id": twin,
            "spec": {"name": f"s{i}", "signal": "rank(ret)"}, "claim": {"sharpe": 2.0}, "truth": {"sharpe": 0.1}}


CASES = [raw_case(0, "guilty", "lookahead", "c1"), raw_case(1, "innocent", None, "c0"),
         raw_case(2, "guilty", "costs", "c3"), raw_case(3, "innocent", None, "c2"),
         raw_case(4, "unusual")]


def fake_trial_factory(calls):
    def trial(case, world, log, *, system, staffing, **kw):
        calls.append(case.case_id)
        guilty = int(case.case_id[1:]) in (0, 2)
        ex = [Exhibit(id="EX-1", test="lag_test" if case.case_id == "c0" else "survivorship_test", summary="x", hint="damaging")]
        if guilty:
            v = Verdict(ruling="reject", findings=[Finding(sin="lookahead" if case.case_id == "c0" else "costs", sustained=True, exhibits=["EX-1"])])
        else:
            v = Verdict(ruling="deploy", capital_allowed=1.0)
        return TrialRecord(case=case, system=system, staffing=staffing, exhibits=ex if guilty else [], verdict=v, calls=2, tokens_in=10,
                           tokens_out=5, seconds=1.0)
    return trial


def run(tmp_path, calls, cases=CASES):
    return run_cases(cases, "court", {"default": "fake:x"}, tmp_path / "court" / "t", concurrency=3, exp="test",
                     trial_fn=fake_trial_factory(calls), world_fn=lambda r: type("W", (), {"world_id": "w"})(),
                     log_fn=lambda r: None)


def test_runner_resumes_and_records_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "LOGS", tmp_path / "logs")
    calls = []
    r1 = run(tmp_path, calls)
    assert r1["ran"] == 5 and r1["failed"] == 0 and len(calls) == 5
    r2 = run(tmp_path, calls)
    assert r2["skipped"] == 5 and r2["ran"] == 0 and len(calls) == 5          # nothing reruns
    (tmp_path / "court" / "t" / "c4.json").unlink()
    run(tmp_path, calls)
    assert calls.count("c4") == 2 and calls.count("c0") == 1

    def boom(case, *a, **k):
        raise RuntimeError("model down")
    r = run_cases([raw_case(9, "guilty", "costs")], "court", {}, tmp_path / "f", concurrency=1, exp="test", trial_fn=boom,
                  world_fn=lambda r: type("W", (), {"world_id": "w"})(), log_fn=lambda r: None)
    assert r["failed"] == 1 and (tmp_path / "f" / "c9.failed.json").exists()
    assert "model down" in json.loads((tmp_path / "f" / "c9.failed.json").read_text())["error"]
    assert runner.load_records(tmp_path / "f") == {}


def test_wilson_known_values():
    lo, hi = score.wilson(8, 10)
    assert (round(lo, 3), round(hi, 3)) == (0.49, 0.943)
    assert score.wilson(0, 10)[0] == 0.0 and score.wilson(10, 10)[1] == 1.0
    assert math.isnan(score.wilson(0, 0)[0])
    assert score.rate(3, 4)["j"] == 3 and score.rate(0, 0)["rate"] is None


def metas():
    return {m.case_id: m for m in (runner.norm(c) for c in CASES)}


def records(deploy_ids=(), reason_ok=True):
    out = {}
    for c in CASES:
        i = c["case_id"]
        guilty = c["role"] == "guilty"
        if guilty and i not in deploy_ids:
            sin = c["sin"] if reason_ok else "other"
            tests = {"lookahead": "lag_test", "costs": "cost_test"}
            v = Verdict(ruling="paper", findings=[Finding(sin=sin, sustained=True, exhibits=["EX-1"])])
            ex = [Exhibit(id="EX-1", test=tests[c["sin"]], summary="x", hint="damaging")]
        else:
            v, ex = Verdict(ruling="deploy", capital_allowed=0.5), []
        cf = CaseFile(case_id=i, world_id="w", spec=StrategySpec(name="s", signal="rank(ret)"), claim=Claim(sharpe=2.0))
        out[i] = TrialRecord(case=cf, system="court", verdict=v, exhibits=ex, calls=4, tokens_in=100, tokens_out=20, seconds=2.0)
    return out


def test_scorer_counts():
    m = metas()
    m["c0"].sealed_return = -0.2
    cell = score.score_cell(records(deploy_ids=("c0",)), m)
    assert (cell["guilty_stopped"]["j"], cell["guilty_stopped"]["k"]) == (1, 2)
    assert (cell["innocent_deployed"]["j"], cell["innocent_deployed"]["k"]) == (3, 3)
    assert (cell["unusual_innocent_deployed"]["j"], cell["unusual_innocent_deployed"]["k"]) == (1, 1)
    assert cell["right_reason"]["j"] == 1 and cell["right_reason"]["k"] == 2
    assert cell["sealed"]["capital_lost"] == 0.5 * 1_000_000 * 0.2
    assert cell["cost_per_case"]["calls"] == {"mean": 4.0, "n": 5}
    assert cell["by_sin"]["lookahead"]["guilty_stopped"]["k"] == 1 and cell["by_sin"]["lookahead"]["innocent_deployed"]["k"] == 1
    assert cell["by_role"]["unusual"]["innocent_deployed"]["j"] == 1


def test_right_reason_needs_matching_exhibit():
    r = records()
    assert score.right_reason(r["c0"], "lookahead")
    assert not score.right_reason(r["c0"], "costs")
    bad = records(reason_ok=False)
    assert not score.right_reason(bad["c0"], "lookahead") and score.right_reason(bad["c0"], "lookahead", need_exhibit=False) is False


def test_bootstrap_deterministic_and_correct():
    m = metas()
    a, b = records(), records(deploy_ids=("c0", "c2"))
    d1 = score.paired_bootstrap(a, b, m, "guilty_stopped")
    d2 = score.paired_bootstrap(a, b, m, "guilty_stopped")
    assert d1 == d2
    assert d1["diff"] == 1.0 and d1["a"] == {"j": 2, "k": 2} and d1["b"] == {"j": 0, "k": 2}
    assert d1["lo"] == 1.0 and d1["hi"] == 1.0 and d1["n_pairs"] == 3
    d3 = score.paired_bootstrap(a, b, m, "innocent_deployed")
    assert d3["diff"] == 0.0


def test_clusters_pair_twins():
    m = metas()
    assert score.clusters(list(m), m) == [["c0", "c1"], ["c2", "c3"], ["c4"]]


def test_sin_tests_cover_all_planted_sins():
    from court.types import SINS
    assert set(SINS) <= set(score.SIN_TESTS)
