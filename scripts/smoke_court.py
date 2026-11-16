"""End-to-end smoke test: one honest and one guilty case through the court. Saves TrialRecords to results/smoke/."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from court.market import make_world
from court.engine import run_backtest
from court.trial import run_trial
from court.types import CaseFile, Claim, ResearchLog, StrategySpec, Trial

OUT = Path(__file__).resolve().parents[1] / "results" / "smoke"; OUT.mkdir(parents=True, exist_ok=True)
world = make_world(1)

def build(case_id, spec):
    bt = run_backtest(spec, world, mode="naive")
    h = bt.spec_hash
    log = ResearchLog(session_id=case_id, agent="smoke", trials=[Trial(t=time.time(), spec_hash=h, spec=spec, metrics=bt.metrics)], submitted_spec_hash=h)
    case = CaseFile(case_id=case_id, world_id=world.world_id, spec=spec,
                    claim=Claim(sharpe=bt.metrics.sharpe, ann_return=bt.metrics.ann_return, max_drawdown=bt.metrics.max_drawdown, text="Daily cross-sectional strategy."),
                    log_summary={"n_trials": 1, "n_distinct_specs": 1, "best_of": 1, "is_best": True})
    return case, log, bt.metrics.sharpe

honest = StrategySpec(name="sentiment tilt", signal="rank(sentiment)", lag=1, rebalance=5, costs_bps=5, universe="all")
guilty = StrategySpec(name="three-day signal", signal="rank(ts_mean(ret, 3))", lag=0, costs_bps=0)
cases = {"honest": build("smoke-honest", honest), "guilty": build("smoke-guilty", guilty)}
models = sys.argv[1:] or ["local:qwen3-8b"]
summary = []
for model in models:
    for label, (case, log, sh) in cases.items():
        t = time.time()
        rec = run_trial(case, world, log, system="court", staffing={"default": model})
        tag = model.replace(":", "_").replace("/", "_")
        (OUT / f"{label}_{tag}.json").write_text(rec.model_dump_json(indent=1))
        row = {"model": model, "case": label, "claimed_sharpe": round(sh, 2), "ruling": rec.verdict.ruling, "unsupported": rec.verdict.unsupported,
               "findings": [(f.sin, f.sustained, f.struck, f.exhibits) for f in rec.verdict.findings], "tools": [e.test for e in rec.exhibits],
               "calls": rec.calls, "tokens": [rec.tokens_in, rec.tokens_out], "seconds": round(time.time() - t, 1),
               "errors": [e.data.get("error") for e in rec.events if e.kind == "error"]}
        summary.append(row); print(json.dumps(row), flush=True)
(OUT / "summary.json").write_text(json.dumps(summary, indent=1))
