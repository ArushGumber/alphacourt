"""Precompute the Flaw Lab's recorded walk-through: backtests and truth for six scenarios, no trials.

Run: PYTHONPATH=. uv run python scripts/export_lab.py   ->  web/public/data/lab.json
The strategy forms mirror web/src/pages/Lab.tsx (buildSpec)."""
from __future__ import annotations

import json
from pathlib import Path

from court.engine import run_backtest, true_edge
from court.market import make_world
from court.types import StrategySpec

OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "data" / "lab.json"
SEED = 1  # the "demo" world
SLOW = "rank(eps_reported) + rank(delay(ts_sum(ret,231),21))"
FAST = "rank(-ts_sum(ret,3))"

# name, label, flaws, base signal, flawed signal, lag, costs, universe
SCENARIOS = [
    ("honest", "Honest strategy", [], SLOW, SLOW, 1, 10, "all"),
    ("same_bar", "Trade on the same bar", ["same_bar"], SLOW, SLOW + " + 0.005*rank(ret)", 0, 10, "all"),
    ("no_costs", "Ignore costs (fast signal)", ["no_costs"], FAST, FAST, 1, 0, "all"),
    ("survivors", "Only today's survivors", ["survivors"], SLOW, SLOW, 1, 10, "survivors"),
    ("revised", "Use revised data", ["revised"], SLOW, SLOW.replace("eps_reported", "eps_restated"), 1, 10, "all"),
    ("two", "Same bar and revised data", ["same_bar", "revised"], SLOW,
     SLOW.replace("eps_reported", "eps_restated") + " + 0.005*rank(ret)", 0, 10, "all"),
]


def spec(name, signal, lag, costs, universe):
    return StrategySpec(name=name, signal=signal, lag=lag, costs_bps=costs, universe=universe)


def bt(sp, world):
    r = run_backtest(sp, world)
    return {"metrics": r.metrics.model_dump(), "equity": [round(v, 5) for v in r.equity], "notes": r.notes}


def main() -> None:
    w = make_world(SEED)
    out = {"world": "demo", "seed": SEED, "scenarios": []}
    for key, label, flaws, base, sig, lag, costs, uni in SCENARIOS:
        flawed = spec(label, sig, lag, costs, uni)
        honest = spec("Honest", base, 1, 10, "all")
        truth = true_edge(flawed, w)
        out["scenarios"].append({
            "key": key, "label": label, "flaws": flaws, "spec": flawed.model_dump(mode="json"),
            "honest_spec": honest.model_dump(mode="json"), "claimed": bt(flawed, w), "honest": bt(honest, w),
            "truth": {"sharpe": truth["sharpe"], "per_seed": truth["per_seed"], "how": truth["how"]},
        })
        print(key, round(out["scenarios"][-1]["claimed"]["metrics"]["sharpe"], 2), "truth", round(truth["sharpe"], 2))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))


if __name__ == "__main__":
    main()
