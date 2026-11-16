"""Fakes for the gateway tests: a small world, a deterministic backtest, a scripted trial."""
import hashlib
import json
import time

import numpy as np

from court.types import (BacktestResult, Charge, Event, Exhibit, Metrics, TrialRecord, Verdict, Finding)
from gateway.service import GatewayService, load_config
from gateway.store import Store


class FakeWorld:
    def __init__(self, name):
        self.world_id, self.seed, self.T, self.N, self.research_end, self.params = f"fake-{name}", 1, 50, 5, 40, {}
        self.fields = {"close": np.ones((50, 5)), "ret": np.zeros((50, 5))}
        self.field_info = {"close": {"description": "Close price.", "documented_availability": "same bar"},
                           "ret": {"description": "Daily return.", "documented_availability": "same bar"}}


def spec_hash(spec):
    return hashlib.sha256(json.dumps(spec.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:12]


def fake_backtest(spec, world):
    h = spec_hash(spec)
    sharpe = (int(h[:4], 16) % 300) / 100.0
    m = Metrics(sharpe=sharpe, ann_return=0.1, ann_vol=0.1, max_drawdown=0.2, turnover=0.3, hit_rate=0.5, n_days=40)
    return BacktestResult(spec_hash=h, mode="naive", period="research", metrics=m, equity=[0.0, 1.0],
                          equity_index=[0, 1])


def make_trial(ruling="deploy", delay=0.0, fail=False, stream=True):
    def trial(case, world, log, *, system, staffing, on_event=None, budget=None):
        if fail:
            raise RuntimeError("model server down")
        evs = [Event(t=time.time(), role="clerk", kind="case", data={"case_id": case.case_id}),
               Event(t=time.time(), role="prosecution", kind="exhibit", data={"id": "EX-1"})]
        if stream and on_event:
            for e in evs:
                on_event(e)
        time.sleep(delay)
        ex = Exhibit(id="EX-1", test="trial_haircut", numbers={"sharpe_after": 0.1}, summary="Haircut leaves 0.1.",
                     hint="damaging")
        v = Verdict(ruling=ruling, findings=[Finding(sin="selection", sustained=True, exhibits=["EX-1"])],
                    capital_allowed=250_000.0 if ruling == "deploy" else 0.0, opinion="Tried.")
        return TrialRecord(case=case, system=system, staffing=staffing, exhibits=[ex],
                           charges=[Charge(sin="selection", exhibits=["EX-1"])], verdict=v,
                           events=[] if stream else evs, calls=3, seconds=0.1)
    return trial


def make_service(tmp_path, **kw):
    cfg = load_config()
    cfg.update(kw.pop("config", {}))
    trial = kw.pop("trial_fn", None) or make_trial()
    return GatewayService(Store(tmp_path), cfg, world_loader=FakeWorld, backtest_fn=fake_backtest,
                          spec_hash_fn=spec_hash, trial_fn=trial, pages_fn=kw.pop("pages_fn", lambda u: None),
                          prompt_version="test-v0", **kw)
