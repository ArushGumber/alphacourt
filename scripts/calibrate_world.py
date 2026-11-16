"""Print the calibration table and write results/calibration.json.

naive = mean Sharpe over research periods of worlds with seeds NAIVE_SEEDS (spec's own costs, as a careless backtest);
true  = court.engine.true_edge (strict, lag>=1, full universe, 10 bps, sealed period, seeds 101-103);
true6 = the same over seeds 101-106 (less noisy).
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from court.engine import run_backtest, true_edge  # noqa: E402
from court.market import make_world  # noqa: E402
from court.types import StrategySpec  # noqa: E402

NAIVE_SEEDS = (1, 2, 3, 4, 5, 6)
MOM = "rank(delay(ts_sum(ret,231),21))"
COMB = MOM + "+rank(eps_reported)-0.5*rank(ts_std(ret,60))"

# name, signal, lag, costs_bps, universe, target text
ROWS = [
    ("momentum 12-1, quintile L/S, lag 1, 10 bps", MOM, 1, 10, "default", "naive 0.6-1.2, true similar"),
    ("post-earnings drift, point-in-time eps", "rank(eps_reported)", 1, 10, "default", "naive 0.8-1.6, true similar"),
    ("combined honest signal", COMB, 1, 10, "default", "naive 1.2-2.0, true similar"),
    ("reversal, 0 bps", "rank(-ret)", 1, 0, "default", "naive >=3, true <=0.2 (true is net of 10 bps)"),
    ("lag 0 on the same-bar return (rank(ret))", "rank(ret)", 0, 10, "default", "naive >=4"),
    ("lag 0 on reversal (rank(-ret)); sign makes it lose", "rank(-ret)", 0, 10, "default", "n/a (see report)"),
    ("sentiment_revised", "rank(sentiment_revised)", 1, 10, "default", "naive >=4, true ~0"),
    ("honest sentiment", "rank(sentiment)", 1, 10, "default", "weak"),
    ("drift using eps_restated", "rank(eps_restated)", 1, 10, "default", "naive >=2.5, true <=0.3 (see report)"),
    ("momentum on survivors", MOM, 1, 10, "survivors", "0.5-1.0 above momentum on all"),
    ("slow level signal, -zscore_full(log(close))", "-zscore_full(log(close))", 1, 10, "default", "visibly inflated"),
    ("momentum with zscore_full(ts_mean(ret,252))", "zscore_full(ts_mean(ret,252))", 1, 10, "default", "inflated? (see report)"),
    ("low volatility", "rank(-ts_std(ret,60))", 1, 10, "default", "small"),
    ("index_member_now (leaky membership)", "rank(index_member_now)", 1, 10, "default", "leaky"),
]


def subtle_lookahead(base: str, weight: float, component: str = "rank(ret)") -> str:
    """Blend a small same-bar component into an honest signal. Run it at lag 0: the honest part is unharmed and
    the tiny weight on the bar's own return lifts the claimed Sharpe to 2-4 while the true edge stays at the honest level."""
    return f"{base}+{weight:g}*{component}"


LOOKAHEAD_WEIGHTS = (0.001, 0.002, 0.004, 0.006, 0.01)


def main():
    worlds = [make_world(s) for s in NAIVE_SEEDS]
    base = worlds[0]
    out = {"seeds": list(NAIVE_SEEDS), "n_delisted_by_research_end": [w.params["n_delisted_research"] for w in worlds],
           "stressed_share": [round(w.params["stressed_share"], 3) for w in worlds], "effects": base.params["effects"], "rows": []}
    print(f"{'strategy':54s} {'naive':>7s} {'true':>7s} {'true6':>7s}   target")
    for name, sig, lag, bps, uni, target in ROWS:
        spec = StrategySpec(name=name[:80], signal=sig, lag=lag, costs_bps=bps, universe=uni)
        res = [run_backtest(spec, w) for w in worlds]
        naive = [r.metrics.sharpe for r in res]
        te = true_edge(spec, base)
        te6 = true_edge(spec, base, seeds=(101, 102, 103, 104, 105, 106))
        row = {"name": name, "signal": sig, "lag": lag, "costs_bps": bps, "universe": uni, "naive": float(np.mean(naive)),
               "naive_per_seed": [round(x, 3) for x in naive], "true": te["sharpe"], "true_per_seed": te["per_seed"],
               "true6": te6["sharpe"], "target": target, "notes": res[0].notes}
        out["rows"].append(row)
        print(f"{name:54s} {row['naive']:7.2f} {row['true']:7.2f} {row['true6']:7.2f}   {target}")
    out["lookahead_recipe"] = []
    print("subtle look-ahead: COMB + w*rank(ret), lag 0, 10 bps")
    for wgt in LOOKAHEAD_WEIGHTS:
        sig = subtle_lookahead(COMB, wgt)
        spec = StrategySpec(name=f"subtle {wgt:g}", signal=sig, lag=0, costs_bps=10)
        cl = [run_backtest(spec, w).metrics.sharpe for w in worlds]
        te = true_edge(spec, base)
        out["lookahead_recipe"].append({"signal": sig, "weight": wgt, "claimed_per_seed": [round(x, 2) for x in cl],
                                        "claimed": float(np.mean(cl)), "true": te["sharpe"]})
        print(f"  w={wgt:<6g} claimed {np.mean(cl):5.2f} {[round(x, 1) for x in cl]}  true {te['sharpe']:5.2f}")
    # timing on a loaded world
    spec = StrategySpec(name="timing", signal=COMB, lag=1, costs_bps=10)
    run_backtest(spec, base)
    ts = []
    for _ in range(30):
        t0 = time.perf_counter()
        run_backtest(spec, base)
        ts.append((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    w = make_world(9001, cache=False)
    gen = time.perf_counter() - t0
    out["timing"] = {"backtest_ms_median": statistics.median(ts), "backtest_ms_max": max(ts), "world_generation_s": gen,
                     "signal": COMB}
    print(f"backtest median {statistics.median(ts):.0f} ms, max {max(ts):.0f} ms; world generation {gen:.2f} s")
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "calibration.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
