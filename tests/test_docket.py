"""Docket checks. They read the built docket under docket/cases/ and skip when it has not been built."""
import json
from pathlib import Path

import pytest

from docket import build as B

CASES = Path(B.CASES)


def _all(split=None):
    out = []
    for sp in ([split] if split else ["dev", "test"]):
        d = CASES / sp
        if d.exists():
            out += [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))]
    return out


pytestmark = pytest.mark.skipif(not _all(), reason="docket not built")


def test_every_case_meets_its_definition():
    for c in _all():
        cl, t = c["claim"]["sharpe"], c["truth"]["true_edge"]["sharpe"]
        if c["role"] == "guilty":
            assert cl - t >= 1.0 and t < 0.5, c["case_id"]
            lo = {"selection": 1.0, "knife_edge": 1.0}.get(c["sin"], B.CLAIM_LO)
            assert lo <= cl <= B.CLAIM_HI, c["case_id"]
        else:
            assert t >= 0.7 and abs(cl - t) <= 0.6, c["case_id"]


def test_twins_within_tolerance_and_linked():
    cs = {c["case_id"]: c for c in _all()}
    for c in cs.values():
        if c["role"] == "guilty" and not c.get("attack"):
            tw = cs[c["twin_id"]]
            assert tw["twin_id"] == c["case_id"]
            assert abs(tw["claim"]["sharpe"] - c["claim"]["sharpe"]) <= 0.3 + 1e-9, c["case_id"]


def test_l3_twins_have_identical_spec_text():
    cs = {c["case_id"]: c for c in _all()}
    n = 0
    for c in cs.values():
        if c.get("level") == "L3" and c["role"] == "guilty":
            assert c["spec"] == cs[c["twin_id"]]["spec"]
            assert c["world_id"] != cs[c["twin_id"]]["world_id"]
            n += 1
    assert n > 0


def test_get_case_and_world_for_round_trip():
    for c in _all()[:6]:
        dc = B.get_case(c["case_id"])
        assert dc["case_id"] == c["case_id"] and dc.case["spec"] == c["spec"]
        w = B.world_for(dc)
        assert w.world_id == c["world_id"]
        assert B.log_for(dc).submitted_spec_hash == c["spec_hash"] or c.get("attack")
    assert B.get_case("no-such-case") is None


def test_rebuild_is_deterministic_for_a_candidate():
    rng1, rng2 = B.rng_for("dev", "x", 1), B.rng_for("dev", "x", 1)
    a, b = B.c_lookahead_L1(rng1), B.c_lookahead_L1(rng2)
    assert a == b


def test_attacks_carry_text_or_page():
    for c in _all("test"):
        if c.get("attack"):
            assert c["attack"] == "judge_note"
            assert c["spec"]["notes"] != "" or c["pages_read"]
