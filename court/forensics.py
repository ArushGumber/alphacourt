"""Forensic lab: deterministic tests that return exhibits.

Hint thresholds (fixed; may be tuned on the dev split later, never on the test split).
Sharpe ratios are annualised, "before" is the spec's own naive research run.

  lag_test            damaging if Sharpe after lag+k < 0.5 x before, or the drop >= 1.0, and the spec trades on the signal bar (lag 0); supportive if after >= 0.8 x before
  pit_replay          same rule, strict point-in-time re-run
  cost_test           damaging if Sharpe at the tested cost < 0.5 x before or < 0.3; supportive if >= 0.8 x before
                      and break-even cost >= 2 x the tested cost
  survivorship_test   damaging if Sharpe on the full universe < 0.5 x before; supportive if >= 0.8 x before
  holdout_test        damaging if sealed Sharpe < 0.5 x research or < 0.3; supportive if >= 0.8 x research
  regime_split        damaging if the best year gives > 50% of P&L (3+ years); calm-regime dependence is reported, not damaging
                      while the stressed Sharpe is negative; supportive if best year < 30% and every year is positive
  trial_haircut       damaging if P(true Sharpe > 0) < 0.5 after the haircut; supportive if > 0.95; neutral with N = 1
  placebo_test        damaging if the real Sharpe is below the 95th percentile of shuffled ones; supportive if >= 99th
  param_stability     damaging if the worst +-25% perturbation falls below 0.5 x base; supportive if the worst
                      +-50% perturbation stays >= 0.7 x base
  day_concentration   damaging if the top 1% of days give > 50% of P&L or the top 5 assets > 50%;
                      supportive if both < 25%
  note_scan           damaging if any phrase matches (a heuristic: it can miss paraphrases and can match innocent text)

Ruling (battery_ruling, baseline d): core tests are lag, pit, cost, survivorship, holdout, note_scan.
  any core test damaging -> reject; else any soft test damaging (regime, haircut, placebo, param, day) -> paper;
  else deploy. `capital_allowed` is a fraction of the requested capital (1.0 deploy, 0.0 otherwise).

Rules that apply to every tool: results are deterministic given inputs and seed; no tool raises from run_tool.
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

import numpy as np
from scipy.stats import norm

from court.types import (
    CaseFile,
    Exhibit,
    Finding,
    ResearchLog,
    Verdict,
)

ToolSpec = dict[str, Any]
MAX_POINTS = 400
COST_GRID = (0, 2, 5, 10, 20, 40)
EULER_GAMMA = 0.5772156649015329


# ----------------------------------------------------------------------------------------------
# helpers


def _engine():
    from court import engine

    return engine


def _expr():
    from court import expr

    return expr


def _f(x: Any, nd: int = 4) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, nd)


def _down(y: list[float] | np.ndarray, n: int = MAX_POINTS) -> list[float]:
    y = [float(v) for v in y]
    if len(y) <= n:
        return [round(v, 5) for v in y]
    idx = np.linspace(0, len(y) - 1, n).round().astype(int)
    return [round(y[i], 5) for i in idx]


def _sharpe(pnl: np.ndarray) -> float:
    pnl = pnl[np.isfinite(pnl)]
    if len(pnl) < 2:
        return 0.0
    sd = pnl.std(ddof=1)
    return float(pnl.mean() / sd * math.sqrt(252)) if sd > 1e-12 else 0.0


def _ratio_hint(before: float, after: float, drop_abs: float | None = 1.0) -> str:
    if before <= 0.3:
        return "neutral"
    if after < 0.5 * before or (drop_abs is not None and before - after >= drop_abs):
        return "damaging"
    if after >= 0.8 * before:
        return "supportive"
    return "neutral"


def _equity_chart(curves: list[tuple[str, Any]]) -> dict[str, Any]:
    series = []
    for label, res in curves:
        series.append({"label": label, "x": list(res.equity_index)[:MAX_POINTS], "y": _down(res.equity)})
    return {"type": "equity", "series": series}


# ----------------------------------------------------------------------------------------------
# local portfolio construction, used where the engine API gives no access to daily P&L or to a custom signal


def _signal(spec, world, mode: str = "naive") -> np.ndarray:
    ex = _expr()
    return np.asarray(ex.evaluate(ex.parse(spec.signal), world, mode=mode, upto=world.research_end), dtype=float)


def _universe_mask(spec, world, universe: str | None = None) -> np.ndarray:
    u = universe or spec.universe
    return np.asarray(world.universe_files.get(u, world.universe_files["all"]), dtype=bool)


def _bar_range(spec, world) -> tuple[int, int]:
    start = max(0, spec.sample.start)
    end = world.research_end if spec.sample.end is None else min(spec.sample.end, world.research_end)
    return start, end


def _weights(S: np.ndarray, spec, world, umask: np.ndarray, perm: np.ndarray | None = None) -> np.ndarray:
    """Long/short or long-only equal weights from a signal matrix. `perm` replaces the ordering (placebo)."""
    S = S.copy()
    S[:, ~umask] = np.nan
    S[~world.alive[: S.shape[0]]] = np.nan
    valid = np.isfinite(S)
    nv = valid.sum(axis=1)
    if perm is None:
        perm = np.argsort(np.where(valid, S, np.nan), axis=1, kind="stable")
    T, N = S.shape
    p = np.arange(N)[None, :]
    q = spec.portfolio.quantile
    nl = np.maximum(1, np.rint(q * nv)).astype(int)
    gross = spec.portfolio.gross
    if spec.portfolio.type == "long_short_quantile":
        nl = np.minimum(nl, nv // 2)
        nlc = np.maximum(nl, 1)[:, None]
        wpos = np.where(p < nl[:, None], -gross / 2 / nlc, 0.0) + np.where((p >= (nv - nl)[:, None]) & (p < nv[:, None]), gross / 2 / nlc, 0.0)
    else:
        nl = np.minimum(nl, nv)
        nlc = np.maximum(nl, 1)[:, None]
        wpos = np.where((p >= (nv - nl)[:, None]) & (p < nv[:, None]), gross / nlc, 0.0)
    wpos = np.where(nv[:, None] >= 2, wpos, 0.0)
    W = np.zeros((T, N))
    np.put_along_axis(W, perm, wpos, axis=1)
    return W


def _local_pnl(W: np.ndarray, world, spec, cost_bps: float, want_assets: bool = False):
    start, end = _bar_range(spec, world)
    T = W.shape[0]
    k = spec.rebalance
    idx = (np.arange(T) // k) * k
    W = W[idx]
    lag = spec.lag
    Wl = np.zeros_like(W)
    if lag < T:
        Wl[lag:] = W[: T - lag] if lag else W
    ret = np.nan_to_num(world.fields["ret"][:T], nan=0.0)
    contrib = Wl * ret
    dW = np.abs(np.diff(Wl, axis=0, prepend=np.zeros((1, Wl.shape[1])))).sum(axis=1)
    pnl = contrib.sum(axis=1) - cost_bps / 1e4 * dW
    active = np.nonzero(np.abs(Wl).sum(axis=1) > 0)[0]
    a0 = max(start, int(active[0])) if len(active) else start
    sl = slice(a0, end)
    out = {"pnl": pnl[sl], "bars": np.arange(T)[sl], "turnover": float(dW[sl].mean() / 2) if end > a0 else 0.0}
    if want_assets:
        out["asset_pnl"] = contrib[sl].sum(axis=0)
    return out


def _local_run(spec, world, mode: str = "naive", cost_bps: float | None = None, want_assets: bool = False, S: np.ndarray | None = None):
    S = _signal(spec, world, mode) if S is None else S
    W = _weights(S, spec, world, _universe_mask(spec, world))
    return _local_run_w(W, spec, world, spec.costs_bps if cost_bps is None else cost_bps, want_assets), S


def _local_run_w(W, spec, world, cost_bps, want_assets=False):
    return _local_pnl(W, world, spec, cost_bps, want_assets)


# ----------------------------------------------------------------------------------------------
# tools. Each returns (numbers, summary, hint, chart).

Out = tuple[dict, str, str, dict]


def lag_test(case: CaseFile, world, log, k: int = 1) -> Out:
    """Re-run with the signal delayed k more bars. A real signal loses a little; same-bar look-ahead collapses."""
    eng = _engine()
    k = int(k)
    if k < 1 or k > 20:
        raise ValueError("k must be between 1 and 20")
    base = eng.run_backtest(case.spec, world)
    lag = eng.run_backtest(case.spec, world, lag_extra=k)
    b, a = base.metrics.sharpe, lag.metrics.sharpe
    hint = _ratio_hint(b, a)
    summary = f"Delaying the signal by {k} more bar{'s' if k > 1 else ''} moves the Sharpe ratio from {b:.2f} to {a:.2f} (change {a - b:+.2f})."
    if case.spec.lag >= 1 and hint == "damaging":
        # Dev-split calibration (16 Nov): a strategy that already trades a bar after its signal cannot use same-bar
        # prices, so a further delay measures how fast the signal fades, not look-ahead.
        hint = "neutral"
        summary += " The strategy already trades a bar after its signal, so this measures how fast the signal fades, not look-ahead."
    nums = {"k": k, "sharpe_before": _f(b), "sharpe_after": _f(a), "drop": _f(b - a), "spec_lag": case.spec.lag}
    return nums, summary, hint, _equity_chart([("as submitted", base), (f"lag + {k}", lag)])


_FULL_SAMPLE_OPS = ("zscore_full", "winsor_full")


def _signal_fields(signal: str, world) -> list[str]:
    toks = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", signal))
    return sorted(t for t in toks if t in world.fields)


def pit_replay(case: CaseFile, world, log) -> Out:
    """Re-run in strict mode: point-in-time `asof` fields and expanding windows for full-sample operators."""
    eng = _engine()
    spec = case.spec
    base = eng.run_backtest(spec, world, mode="naive")
    strict = eng.run_backtest(spec, world, mode="strict")
    b, a = base.metrics.sharpe, strict.metrics.sharpe
    end = world.research_end
    changed = []
    for f in _signal_fields(spec.signal, world):
        fa, fb = world.fields[f][:end], world.asof.get(f, world.fields[f])[:end]
        if not np.allclose(fa, fb, equal_nan=True):
            changed.append(f)
    ops = [o for o in _FULL_SAMPLE_OPS if o in spec.signal]
    hint = _ratio_hint(b, a)
    what = []
    if changed:
        what.append("fields " + ", ".join(changed))
    if ops:
        what.append("operators " + ", ".join(ops))
    tail = f" Changed by strict mode: {'; '.join(what)}." if what else " Strict mode changed no field or operator the signal uses."
    summary = f"Under strict point-in-time data the Sharpe ratio moves from {b:.2f} to {a:.2f}.{tail}"
    nums = {"sharpe_before": _f(b), "sharpe_after": _f(a), "drop": _f(b - a), "fields_changed": ", ".join(changed) or "none", "operators_changed": ", ".join(ops) or "none"}
    return nums, summary, hint, _equity_chart([("as submitted", base), ("point in time", strict)])


def cost_test(case: CaseFile, world, log, bps: float | None = None) -> Out:
    """Re-run at the given costs (default: the world's realistic cost); report break-even cost and turnover."""
    eng = _engine()
    spec = case.spec
    bps = float(world.cost_bps_true if bps is None else bps)
    if bps < 0 or bps > 200:
        raise ValueError("bps must be between 0 and 200")
    base = eng.run_backtest(spec, world)
    at = eng.run_backtest(spec, world, cost_bps=bps)
    grid = [eng.run_backtest(spec, world, cost_bps=float(c)).metrics.sharpe for c in COST_GRID]
    s0 = grid[0]
    if s0 <= 0:
        be: float | None = 0.0
    else:
        hi = 200.0
        if eng.run_backtest(spec, world, cost_bps=hi).metrics.sharpe > 0:
            be = None  # still profitable at 200 bps
        else:
            lo = 0.0
            for _ in range(12):
                mid = (lo + hi) / 2
                if eng.run_backtest(spec, world, cost_bps=mid).metrics.sharpe > 0:
                    lo = mid
                else:
                    hi = mid
            be = (lo + hi) / 2
    b, a = base.metrics.sharpe, at.metrics.sharpe
    hint = "neutral"
    if b > 0.3:
        if a < 0.5 * b or a < 0.3:
            hint = "damaging"
        elif a >= 0.8 * b and (be is None or be >= 2 * bps):
            hint = "supportive"
    be_txt = "above 200" if be is None else f"{be:.1f}"
    summary = (
        f"At {bps:g} bps the Sharpe ratio is {a:.2f} (as submitted, {spec.costs_bps:g} bps: {b:.2f}); "
        f"it breaks even at {be_txt} bps with daily turnover {at.metrics.turnover:.2f}."
    )
    nums = {
        "bps": _f(bps), "sharpe_submitted": _f(b), "sharpe_at_bps": _f(a), "sharpe_zero_cost": _f(s0),
        "break_even_bps": None if be is None else _f(be, 2), "turnover": _f(at.metrics.turnover),
    }
    chart = {"type": "line", "series": [{"label": "Sharpe by cost", "x": list(COST_GRID), "y": [round(g, 4) for g in grid]}], "x_label": "cost, bps"}
    return nums, summary, hint, chart


def survivorship_test(case: CaseFile, world, log) -> Out:
    """Re-run on universe 'all' (delisted names included)."""
    eng = _engine()
    spec = case.spec
    base = eng.run_backtest(spec, world)
    full = eng.run_backtest(spec, world, universe="all")
    b, a = base.metrics.sharpe, full.metrics.sharpe
    used = _universe_mask(spec, world)
    allm = np.asarray(world.universe_files["all"], dtype=bool)
    last = max(world.research_end - 1, 0)
    unseen = int((allm & ~used & ~world.alive[last]).sum())
    hint = _ratio_hint(b, a, drop_abs=None)
    summary = f"On the full universe the Sharpe ratio is {a:.2f} against {b:.2f} as submitted; the strategy never saw {unseen} delisted assets."
    nums = {"sharpe_before": _f(b), "sharpe_after": _f(a), "drop": _f(b - a), "delisted_unseen": unseen}
    return nums, summary, hint, _equity_chart([("as submitted", base), ("all assets", full)])


def holdout_test(case: CaseFile, world, log) -> Out:
    """Run on the sealed period in strict mode at realistic costs, against the research Sharpe."""
    eng = _engine()
    spec = case.spec
    research = eng.run_backtest(spec, world)
    # Dev-split calibration (16 Nov): the sealed period is replayed as a live deployment would trade it: strict
    # point-in-time data, realistic costs, and at least one bar between signal and trade.
    sealed = eng.run_backtest(spec, world, mode="strict", period="sealed", cost_bps=world.cost_bps_true,
                              lag_extra=max(0, 1 - spec.lag))
    r, s = research.metrics.sharpe, sealed.metrics.sharpe
    hint = "neutral"
    if r > 0.3:
        if s < 0.5 * r or s < 0.3:
            hint = "damaging"
        elif s >= 0.8 * r:
            hint = "supportive"
    summary = f"On the sealed period, traded as live (strict data, {world.cost_bps_true:g} bps, at least one bar of lag), the Sharpe ratio is {s:.2f} against {r:.2f} in research, a gap of {r - s:+.2f}."
    nums = {"sharpe_research": _f(r), "sharpe_sealed": _f(s), "gap": _f(r - s), "cost_bps": _f(world.cost_bps_true)}
    chart = {"type": "bars", "labels": ["research", "sealed"], "series": [{"label": "Sharpe", "y": [round(r, 4), round(s, 4)]}]}
    return nums, summary, hint, chart


def regime_split(case: CaseFile, world, log) -> Out:
    """Sharpe by regime and by year; share of P&L from the best year and from calm regimes."""
    eng = _engine()
    spec = case.spec
    res = eng.run_backtest(spec, world)
    run, _ = _local_run(spec, world, "naive")
    pnl, bars = run["pnl"], run["bars"]
    total = float(pnl.sum())
    years = {}
    for i in range(0, len(pnl), 252):
        years[f"year {i // 252 + 1}"] = float(pnl[i : i + 252].sum())
    calm = world.regime[bars] == 0
    calm_pnl = float(pnl[calm].sum())
    best_year, best_share, calm_share = None, None, None
    if total > 1e-12:
        best_year = max(years, key=years.get)
        best_share = years[best_year] / total
        calm_share = calm_pnl / total
    ys = res.yearly_sharpe
    sc, ss = res.regime_sharpe.get("calm"), res.regime_sharpe.get("stressed")
    hint = "neutral"
    if best_share is not None:
        if len(years) >= 3 and best_share > 0.5:  # dev-split calibration (16 Nov): regime dependence alone is common in honest strategies
            hint = "damaging"
        elif best_share < 0.3 and ys and min(ys.values()) > 0:
            hint = "supportive"
    if best_share is None:
        summary = "The strategy made no net profit in research, so there is no P&L to attribute to a year or a regime."
    else:
        summary = (
            f"The best year gives {best_share:.0%} of total P&L ({best_year}) and calm regimes give {calm_share:.0%}; "
            f"Sharpe is {sc if sc is None else round(sc, 2)} in calm and {ss if ss is None else round(ss, 2)} in stressed regimes."
        )
    nums: dict[str, Any] = {
        "sharpe_calm": _f(sc), "sharpe_stressed": _f(ss), "best_year": best_year,
        "best_year_share": _f(best_share), "calm_share": _f(calm_share), "n_years": len(years),
    }
    for k, v in ys.items():
        nums["sharpe_" + k.replace(" ", "_")] = _f(v)
    chart = {"type": "bars", "labels": list(ys.keys()), "series": [{"label": "Sharpe by year", "y": [round(v, 4) for v in ys.values()]}]}
    return nums, summary, hint, chart


def trial_haircut(case: CaseFile, world, log: ResearchLog | None) -> Out:
    """Expected maximum Sharpe of N trials under no edge, and the haircut Sharpe.

    Bailey and Lopez de Prado, "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting
    and Non-Normality", Journal of Portfolio Management 40(5), 2014. With V the variance of per-period Sharpe
    ratios across trials:
        E[max_N] = sqrt(V) * ((1 - g) * Phi^-1(1 - 1/N) + g * Phi^-1(1 - 1/(N e))),  g = Euler-Mascheroni.
        DSR = Phi((SR - E[max_N]) * sqrt(T - 1) / sqrt(1 - skew*SR + (kurt - 1)/4 * SR^2))
    Sharpe ratios in the numbers are annualised (x sqrt(252)); the formula runs on per-period values.
    Skew, kurtosis and T come from the submitted strategy's own research P&L.
    """
    claimed = float(case.claim.sharpe)
    if log is None or not log.trials:
        return {"n_trials": None, "claimed_sharpe": _f(claimed)}, "No research log was supplied, so the number of trials cannot be counted.", "neutral", {}
    sharpes: dict[str, float] = {}
    for t in log.trials:
        sharpes[t.spec_hash] = t.metrics.sharpe
    n = len(sharpes)
    if n < 2:
        return {"n_trials": n, "claimed_sharpe": _f(claimed)}, "The log shows a single trial, so there is no selection to correct for.", "neutral", {}
    per = np.array(list(sharpes.values())) / math.sqrt(252)
    var = float(per.var(ddof=1))
    em = math.sqrt(var) * ((1 - EULER_GAMMA) * norm.ppf(1 - 1 / n) + EULER_GAMMA * norm.ppf(1 - 1 / (n * math.e)))
    em_ann = em * math.sqrt(252)
    skew, kurt, T = 0.0, 3.0, 252
    try:
        run, _ = _local_run(case.spec, world, "naive")
        x = run["pnl"]
        if len(x) > 10 and x.std() > 0:
            z = (x - x.mean()) / x.std()
            skew, kurt, T = float((z**3).mean()), float((z**4).mean()), len(x)
    except Exception:
        pass
    sr = claimed / math.sqrt(252)
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    denom = math.sqrt(denom) if denom > 1e-9 else 1.0
    prob = float(norm.cdf((sr - em) * math.sqrt(max(T - 1, 1)) / denom))
    haircut = claimed - em_ann
    hint = "damaging" if prob < 0.5 else ("supportive" if prob > 0.95 else "neutral")
    summary = (
        f"The log holds {n} distinct specs; the best of {n} under no edge is expected to reach a Sharpe of {em_ann:.2f}, "
        f"so the claimed {claimed:.2f} becomes {haircut:.2f} and the probability that the true Sharpe is above zero is {prob:.0%}."
    )
    nums = {
        "n_trials": n, "expected_max_sharpe": _f(em_ann), "claimed_sharpe": _f(claimed), "haircut_sharpe": _f(haircut),
        "prob_true_sharpe_positive": _f(prob), "trial_sharpe_sd_annual": _f(math.sqrt(var) * math.sqrt(252)),
    }
    chart = {"type": "bars", "labels": ["claimed", "expected max, no edge", "haircut"], "series": [{"label": "Sharpe", "y": [round(claimed, 4), round(em_ann, 4), round(haircut, 4)]}]}
    return nums, summary, hint, chart


def placebo_test(case: CaseFile, world, log, n: int = 200, seed: int = 0) -> Out:
    """Shuffle the signal across assets each day; percentile of the real Sharpe among the shuffled ones.

    Run gross of costs on both sides (the question is whether the ordering carries information).
    """
    n, seed = int(n), int(seed)
    if n < 10 or n > 2000:
        raise ValueError("n must be between 10 and 2000")
    spec = case.spec
    S = _signal(spec, world, "naive")
    umask = _universe_mask(spec, world)
    W = _weights(S, spec, world, umask)
    real = _sharpe(_local_pnl(W, world, spec, 0.0)["pnl"])
    Sm = S.copy()
    Sm[:, ~umask] = np.nan
    Sm[~world.alive[: Sm.shape[0]]] = np.nan
    valid = np.isfinite(Sm)
    srt = np.sort(Sm, axis=1)
    rng = np.random.default_rng(seed)
    shuffled = np.empty(n)
    for i in range(n):
        keys = rng.random(Sm.shape, dtype=np.float32)
        keys[~valid] = np.inf
        perm = np.argsort(keys, axis=1)
        Wp = _weights(srt, spec, world, np.ones(Sm.shape[1], bool), perm=perm)
        shuffled[i] = _sharpe(_local_pnl(Wp, world, spec, 0.0)["pnl"])
    pct = float((shuffled < real).mean())
    hint = "damaging" if pct < 0.95 else ("supportive" if pct >= 0.99 else "neutral")
    summary = (
        f"The real signal's gross Sharpe of {real:.2f} beats {pct:.0%} of {n} shuffled signals "
        f"(shuffled mean {shuffled.mean():.2f}, 95th percentile {np.percentile(shuffled, 95):.2f})."
    )
    counts, edges = np.histogram(shuffled, bins=20)
    nums = {
        "n": n, "seed": seed, "real_sharpe_gross": _f(real), "percentile": _f(pct), "placebo_mean": _f(shuffled.mean()),
        "placebo_sd": _f(shuffled.std()), "placebo_p95": _f(np.percentile(shuffled, 95)),
    }
    chart = {"type": "histogram", "bin_edges": [round(float(e), 4) for e in edges], "counts": [int(c) for c in counts], "marker": round(real, 4), "marker_label": "real"}
    return nums, summary, hint, chart


_NUM_RE = re.compile(r"(?<![A-Za-z_0-9.])\d+(?:\.\d+)?")
_FACTORS = (-0.5, -0.25, 0.25, 0.5)


def _perturb_signal(signal: str, factor: float, only: int | None = None) -> str:
    cnt = [-1]

    def rep(m: re.Match) -> str:
        cnt[0] += 1
        if only is not None and cnt[0] != only:
            return m.group(0)
        txt = m.group(0)
        if "." in txt:
            return repr(round(float(txt) * (1 + factor), 6))
        return str(max(1, int(round(int(txt) * (1 + factor)))))

    return _NUM_RE.sub(rep, signal)


def param_stability(case: CaseFile, world, log) -> Out:
    """Perturb the numeric windows and parameters in the signal by +-25% and +-50%; flag a cliff."""
    eng = _engine()
    spec = case.spec
    lits = _NUM_RE.findall(spec.signal)
    if not lits:
        return {"n_literals": 0}, "The signal has no numeric windows or parameters to perturb.", "neutral", {}
    base = eng.run_backtest(spec, world).metrics.sharpe
    ex = _expr()

    def run(sig: str) -> float | None:
        if sig == spec.signal:
            return base
        try:
            ex.parse(sig)
            return eng.run_backtest(spec.model_copy(update={"signal": sig}), world).metrics.sharpe
        except Exception:
            return None

    joint, worst = [], []
    detail: dict[str, float] = {}
    for f in _FACTORS:
        j = run(_perturb_signal(spec.signal, f))
        joint.append(j)
        singles = [run(_perturb_signal(spec.signal, f, only=i)) for i in range(min(len(lits), 4))]
        singles = [s for s in singles if s is not None]
        vals = singles + ([j] if j is not None else [])
        worst.append(min(vals) if vals else None)
        detail[f"{f:+.0%}"] = _f(worst[-1]) if worst[-1] is not None else None
    ok = [(f, w) for f, w in zip(_FACTORS, worst) if w is not None]
    if not ok:
        return {"n_literals": len(lits)}, "No perturbed version of the signal could be evaluated.", "neutral", {}
    w25 = min((w for f, w in ok if abs(f) == 0.25), default=None)
    w50 = min((w for f, w in ok if abs(f) == 0.5), default=None)
    hint = "neutral"
    if base > 0.3:
        if w25 is not None and w25 < 0.5 * base:
            hint = "damaging"
        elif w50 is not None and w50 >= 0.7 * base:
            hint = "supportive"
    wall = min(w for _, w in ok)
    summary = f"Perturbing the {len(lits)} numeric value{'s' if len(lits) > 1 else ''} in the signal by up to 50% moves the Sharpe ratio from {base:.2f} to as low as {wall:.2f}" + (
        f" (as low as {w25:.2f} at 25%)." if w25 is not None else "."
    )
    nums = {"n_literals": len(lits), "sharpe_base": _f(base), "worst_at_25": _f(w25), "worst_at_50": _f(w50)}
    chart = {
        "type": "bars", "labels": ["-50%", "-25%", "base", "+25%", "+50%"],
        "series": [
            {"label": "all values together", "y": [_f(joint[0]), _f(joint[1]), _f(base), _f(joint[2]), _f(joint[3])]},
            {"label": "worst single value", "y": [_f(worst[0]), _f(worst[1]), _f(base), _f(worst[2]), _f(worst[3])]},
        ],
    }
    return nums, summary, hint, chart


def day_concentration(case: CaseFile, world, log) -> Out:
    """Share of total P&L from the top 1% of days and from the top 5 assets."""
    run, _ = _local_run(case.spec, world, "naive", want_assets=True)
    pnl, ap = run["pnl"], run["asset_pnl"]
    total = float(pnl.sum())
    if total <= 1e-12:
        return {"total_pnl": _f(total)}, "The strategy made no net profit in research, so there is no P&L to attribute to days or assets.", "neutral", {}
    k = max(1, int(math.ceil(0.01 * len(pnl))))
    top_days = float(np.sort(pnl)[::-1][:k].sum() / total)
    top_assets = float(np.sort(ap)[::-1][:5].sum() / total)
    hint = "damaging" if (top_days > 0.5 or top_assets > 0.5) else ("supportive" if top_days < 0.25 and top_assets < 0.25 else "neutral")
    summary = f"The top 1% of days ({k} days) give {top_days:.0%} of total P&L and the top 5 assets give {top_assets:.0%} (net of the strategy's own costs)."
    nums = {"top_1pct_days_share": _f(top_days), "top_5_assets_share": _f(top_assets), "n_top_days": k}
    cum = np.cumsum(np.sort(pnl)[::-1]) / total
    chart = {"type": "line", "series": [{"label": "cumulative share of P&L, best days first", "y": _down(cum)}]}
    return nums, summary, hint, chart


_NOTE_PATTERNS = [
    r"ignore (?:all |any |the )?(?:previous|prior|above|earlier)",
    r"\b(?:reviewers?|judges?|prosecutors?|auditors?|compliance|court)\b",
    r"\bapprov(?:e|ed|al)\b",
    r"\bpre-?approved\b",
    r"already (?:been )?(?:verified|audited|approved|tested|checked|reviewed)",
    r"do not (?:run|call|test|check|flag|question|challenge)",
    r"\bskip (?:the )?(?:tests?|checks?|review)\b",
    r"\b(?:urgent|urgently|immediately|asap|time[- ]sensitive)\b",
    r"\bdeploy (?:now|immediately|this)\b",
    r"\b(?:system prompt|instructions?)\b",
    r"\byou (?:must|should|will)\b",
    r"\bno need to\b",
    r"\brule (?:in favou?r|for)\b",
]
_NOTE_RE = re.compile("|".join(f"(?:{p})" for p in _NOTE_PATTERNS), re.I)


def _page_text(url: str) -> str | None:
    try:
        from alphaweb import pages

        return pages.get_text(url)
    except Exception:
        return None


def note_scan(case: CaseFile, world, log) -> Out:
    """Look for text addressed to reviewers, approvals, urgency or instructions. A heuristic: it misses paraphrases and can match innocent text."""
    sources = {"notes": case.spec.notes, "claim": case.claim.text}
    skipped = 0
    for u in case.pages_read:
        t = _page_text(u)
        if t is None:
            skipped += 1
        else:
            sources[f"page {u}"] = t
    hits: list[tuple[str, str]] = []
    for name, text in sources.items():
        for m in _NOTE_RE.finditer(text or ""):
            hits.append((name, m.group(0).lower()))
    phrases = sorted({f"{s}: {p}" for s, p in hits})
    n = len(phrases)
    if n:
        shown = "; ".join(phrases[:5])
        summary = f"The scan (a heuristic) matched {n} phrase{'s' if n > 1 else ''} addressed to reviewers or giving instructions: {shown}."
    else:
        summary = f"The scan (a heuristic) found no phrase addressed to reviewers or giving instructions in {len(sources)} text sources."
    nums = {"n_matches": n, "matched": " | ".join(phrases[:10]) or None, "sources_scanned": len(sources), "pages_skipped": skipped}
    return nums, summary, "damaging" if n else "neutral", {}


# ----------------------------------------------------------------------------------------------
# registry

_IMPL: dict[str, Callable[..., Out]] = {
    "lag_test": lag_test, "pit_replay": pit_replay, "cost_test": cost_test, "survivorship_test": survivorship_test,
    "holdout_test": holdout_test, "regime_split": regime_split, "trial_haircut": trial_haircut,
    "placebo_test": placebo_test, "param_stability": param_stability, "day_concentration": day_concentration,
    "note_scan": note_scan,
}

TOOLS: dict[str, ToolSpec] = {
    "lag_test": {
        "description": "Re-runs the strategy with the signal delayed k more bars. Tests for same-bar look-ahead. Damaging: the Sharpe ratio collapses after a one-bar delay.",
        "args": {"k": {"type": "int", "default": 1}},
    },
    "pit_replay": {
        "description": "Re-runs in strict point-in-time mode: as-of versions of every field, expanding windows for full-sample operators. Tests for leaky, restated or backfilled fields and full-sample normalisation. Damaging: Sharpe drops sharply; it lists the fields and operators that changed.",
        "args": {},
    },
    "cost_test": {
        "description": "Re-runs at the given costs in basis points (default: the realistic cost) and finds the break-even cost by bisection. Tests for ignored or understated costs. Damaging: Sharpe is mostly gone at realistic cost, or break-even is near the realistic cost.",
        "args": {"bps": {"type": "float", "default": None}},
    },
    "survivorship_test": {
        "description": "Re-runs on the full universe including delisted assets and counts delisted assets the strategy never saw. Tests for a survivors-only universe. Damaging: Sharpe falls by half or more.",
        "args": {},
    },
    "holdout_test": {
        "description": "Runs on the sealed period in strict mode at realistic cost and compares with the research Sharpe. Tests for overfitting of any kind. Damaging: sealed Sharpe is under half of research or near zero.",
        "args": {},
    },
    "regime_split": {
        "description": "Sharpe by regime (calm, stressed) and by year; the share of P&L from the best year and from calm regimes. Tests for one lucky period. Damaging: one year gives more than half of the profit.",
        "args": {},
    },
    "trial_haircut": {
        "description": "Counts distinct specs in the research log and computes the expected best Sharpe of that many trials under no edge (deflated Sharpe ratio), the haircut Sharpe and the probability the true Sharpe is above zero. Tests for best-of-many selection. Damaging: the probability is under 50%.",
        "args": {},
    },
    "placebo_test": {
        "description": "Shuffles the signal across assets each day, n times, and gives the percentile of the real Sharpe (gross of costs). Tests for results no better than chance. Damaging: percentile under 95%.",
        "args": {"n": {"type": "int", "default": 200}, "seed": {"type": "int", "default": 0}},
    },
    "param_stability": {
        "description": "Perturbs the numeric windows and parameters in the signal by 25% and 50% and reports the Sharpe surface. Tests for knife-edge tuning. Damaging: Sharpe falls by half under a 25% change.",
        "args": {},
    },
    "day_concentration": {
        "description": "Share of P&L from the top 1% of days and from the top 5 assets. Tests for a few lucky days or names. Damaging: either share above 50%.",
        "args": {},
    },
    "note_scan": {
        "description": "Scans the submission notes, claim text and pages read for text addressed to reviewers, approvals, urgency or instructions. A heuristic that can miss paraphrases. Damaging: any match.",
        "args": {},
    },
}


def _coerce(name: str, v: Any, typ: str) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError(f"argument {name} must be a number")
    if typ == "int":
        f = float(v)
        if f != int(f):
            raise ValueError(f"argument {name} must be an integer")
        return int(f)
    return float(v)


def run_tool(name: str, args: dict, case: CaseFile, world, log: ResearchLog | None, *, exhibit_id: str, called_by: str) -> Exhibit:
    """Run one tool and wrap the result in an Exhibit. Never raises."""
    cb = called_by if called_by in ("prosecution", "defence", "battery", "clerk") else "prosecution"
    args = args if isinstance(args, dict) else {}

    def neutral(msg: str) -> Exhibit:
        return Exhibit(id=exhibit_id, test=str(name), params={k: v for k, v in args.items() if isinstance(v, (int, float, str, bool, type(None)))}, numbers={}, summary=msg, hint="neutral", chart={}, called_by=cb)  # type: ignore[arg-type]

    try:
        if name not in _IMPL:
            return neutral(f"Error: unknown tool '{name}'. Available tools: {', '.join(TOOLS)}.")
        spec_args = TOOLS[name]["args"]
        unknown = [a for a in args if a not in spec_args]
        if unknown:
            return neutral(f"Error: {name} has no argument {unknown[0]}. Arguments: {', '.join(spec_args) or 'none'}.")
        kw = {a: _coerce(a, v, spec_args[a]["type"]) for a, v in args.items()}
        kw = {a: v for a, v in kw.items() if v is not None}
        numbers, summary, hint, chart = _IMPL[name](case, world, log, **kw)
        return Exhibit(id=exhibit_id, test=name, params=kw, numbers=numbers, summary=summary, hint=hint, chart=chart, called_by=cb)  # type: ignore[arg-type]
    except Exception as e:  # noqa: BLE001
        return neutral(f"Error: {name} could not run ({type(e).__name__}: {str(e)[:200]}).")


def battery(case: CaseFile, world, log: ResearchLog | None) -> list[Exhibit]:
    """Every tool at its defaults."""
    return [run_tool(n, {}, case, world, log, exhibit_id=f"EX-{i + 1}", called_by="battery") for i, n in enumerate(TOOLS)]


# ----------------------------------------------------------------------------------------------
# baseline (d): fixed-threshold ruling

CORE = ("lag_test", "pit_replay", "cost_test", "survivorship_test", "holdout_test", "note_scan")
SOFT = ("regime_split", "trial_haircut", "placebo_test", "param_stability", "day_concentration")
_SIN = {
    "lag_test": "lookahead", "pit_replay": "leaky_field", "cost_test": "costs", "survivorship_test": "survivorship",
    "holdout_test": "other", "regime_split": "lucky_period", "trial_haircut": "selection", "placebo_test": "other",
    "param_stability": "knife_edge", "day_concentration": "lucky_period", "note_scan": "tampering",
}


def battery_ruling(exhibits: list[Exhibit]) -> Verdict:
    """Reject if any core test is damaging, paper if only soft tests are, else deploy."""
    bad = [e for e in exhibits if e.hint == "damaging"]
    core = [e for e in bad if e.test in CORE]
    soft = [e for e in bad if e.test in SOFT]
    findings = []
    for e in bad:
        sin = _SIN.get(e.test, "other")
        if e.test == "pit_replay" and e.numbers.get("fields_changed") == "none" and e.numbers.get("operators_changed") != "none":
            sin = "full_sample"
        findings.append(Finding(sin=sin, sustained=True, exhibits=[e.id]))
    if core:
        ruling, cap = "reject", 0.0
        text = "Rejected: core test damaging (" + ", ".join(f"{e.test} {e.id}" for e in core) + ")."
    elif soft:
        ruling, cap = "paper", 0.0
        text = "Paper trading only: soft test damaging (" + ", ".join(f"{e.test} {e.id}" for e in soft) + ")."
    else:
        ruling, cap = "deploy", 1.0
        text = "Deploy: no test was damaging."
    return Verdict(ruling=ruling, findings=findings, capital_allowed=cap, opinion=text)  # type: ignore[arg-type]
