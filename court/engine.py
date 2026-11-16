"""Backtest engine. pnl[t] = sum_i w[t - lag, i] * ret[t, i] - costs[t].

Weights are set at the close of bar s from the signal at s, over assets that are alive at s, in the universe and have a
valid signal. They are recomputed every `rebalance` bars (bar index divisible by k) and held fixed in between (no drift
adjustment). One-way turnover is 0.5 * sum |change in weights|; costs = costs_bps / 1e4 * turnover.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from .expr import evaluate, parse, uses_full_sample
from .market import ASOF_OF, World, make_world
from .types import BacktestResult, Metrics, Sample, StrategySpec

LEAKY_FIELDS = tuple(ASOF_OF)  # eps_restated, sentiment_revised, index_member_now
MIN_ASSETS = 10


def spec_hash(spec: StrategySpec) -> str:
    """sha256 of the canonical JSON of the spec (sorted keys, no spaces), first 12 hex characters."""
    blob = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _weights(sig: np.ndarray, mask: np.ndarray, ptype: str, q: float, gross: float, rows: np.ndarray) -> np.ndarray:
    """Target weights at the decision bars `rows` (others zero)."""
    T, N = sig.shape
    W = np.zeros((T, N))
    if len(rows) == 0:
        return W
    s = sig[rows]
    ok = np.isfinite(s) & mask[rows]
    n = ok.sum(axis=1)
    key = np.where(ok, s, np.inf)
    order = np.argsort(key, axis=1)
    rank = np.empty(s.shape, dtype=np.int32)
    np.put_along_axis(rank, order, np.broadcast_to(np.arange(N, dtype=np.int32), s.shape), axis=1)
    k = np.maximum(1, np.rint(q * n).astype(np.int32))
    good = (n >= MIN_ASSETS)[:, None]
    top = ok & (rank >= (n - k)[:, None]) & good
    if ptype == "long_only_top":
        w = np.where(top, gross / np.maximum(k, 1)[:, None], 0.0)
    else:
        bot = ok & (rank < k[:, None]) & good
        w = np.where(top, 0.5 * gross / k[:, None], 0.0) - np.where(bot, 0.5 * gross / k[:, None], 0.0)
    W[rows] = w
    return W


def _period_bounds(world: World, period: str, sample: Sample):
    re = world.research_end
    if period == "research":
        start, end = sample.start, re if sample.end is None else min(sample.end, re)
        start = min(max(start, 0), re)
    elif period == "sealed":
        start, end = re, world.T
    elif period == "full":
        start, end = 0, world.T
    else:
        raise ValueError("period must be 'research', 'sealed' or 'full'")
    return start, max(end, start)


def _sharpe(x):
    if len(x) < 2:
        return 0.0
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(252)) if sd > 1e-12 else 0.0


def run_backtest(spec: StrategySpec, world: World, *, mode: str = "naive", period: str = "research",
                 cost_bps: float | None = None, lag_extra: int = 0, universe: str | None = None,
                 sample: Sample | None = None) -> BacktestResult:
    """Run one backtest. Defaults to the spec's own costs, lag (plus lag_extra), universe and sample.
    period 'research' sees only bars below world.research_end; 'sealed' and 'full' are for the court and the truth scorer."""
    sample = sample if sample is not None else spec.sample
    expr = parse(spec.signal)
    lag = spec.lag + lag_extra
    if lag < 0 or lag > 40:
        raise ValueError("lag out of range")
    bps = spec.costs_bps if cost_bps is None else cost_bps
    uni_name = universe or spec.universe
    if uni_name not in world.universe_files:
        raise ValueError(f"unknown universe '{uni_name}'")
    start, end = _period_bounds(world, period, sample)
    upto = world.research_end if period == "research" else world.T
    T, N = world.T, world.N

    sig = evaluate(expr, world, mode=mode, upto=upto)
    mask = world.universe_files[uni_name][None, :] & world.alive
    k = spec.rebalance
    last_dec = end - 1 - lag  # last decision bar that earns a bar inside the period
    rows = np.arange(0, max(last_dec + 1, 0))
    rows = rows[rows % k == 0]
    Wd = _weights(sig, mask, spec.portfolio.type, spec.portfolio.quantile, spec.portfolio.gross, rows)
    if k > 1 and len(rows):  # hold weights between rebalances
        idx = np.arange(T)
        src = (idx // k) * k
        Wd = Wd[np.minimum(src, T - 1)] * (src <= last_dec)[:, None]
    Wd = Wd * world.alive  # a delisted asset's position disappears
    ret = np.nan_to_num(np.asarray(world.fields["ret"], dtype=np.float64))
    ts = np.arange(start, end)
    src_t = ts - lag
    valid = src_t >= 0
    Wt = np.zeros((len(ts), N))
    Wt[valid] = Wd[src_t[valid]]
    Wprev = np.zeros_like(Wt)
    Wprev[1:] = Wt[:-1]
    first_src = src_t[0] - 1 if len(ts) and src_t[0] >= 1 else None
    if first_src is not None:
        Wprev[0] = Wd[first_src]
    turn = 0.5 * np.abs(Wt - Wprev).sum(axis=1)
    gross_pnl = (Wt * ret[start:end]).sum(axis=1)
    pnl = gross_pnl - bps / 1e4 * turn
    active = np.flatnonzero(np.abs(Wt).sum(axis=1) > 0)
    notes = []
    if len(active) < 30:
        notes.append("fewer than 30 active days; metrics are not meaningful")
        a0 = 0 if len(active) == 0 else active[0]
    else:
        a0 = active[0]
    pnl, turn, ts = pnl[a0:], turn[a0:], ts[a0:]
    n = len(pnl)
    sharpe = _sharpe(pnl)
    eq = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    mdd = float((peak - eq).max()) if n else 0.0
    m = Metrics(sharpe=sharpe, ann_return=float(pnl.mean() * 252) if n else 0.0,
                ann_vol=float(pnl.std(ddof=1) * np.sqrt(252)) if n > 1 else 0.0, max_drawdown=max(mdd, 0.0),
                turnover=float(turn.mean()) if n else 0.0, hit_rate=float((pnl > 0).mean()) if n else 0.0, n_days=int(n))
    if n > 400:
        pick = np.unique(np.linspace(0, n - 1, 400).round().astype(int))
    else:
        pick = np.arange(n)
    yearly = {f"year {j + 1}": _sharpe(pnl[a:a + 252]) for j, a in enumerate(range(0, n, 252)) if n - a >= 63}
    rg = world.regime[ts] if n else np.array([], dtype=int)
    regime = {}
    for nm, v in (("calm", 0), ("stressed", 1)):
        sel = pnl[rg == v] if n else pnl
        if len(sel) >= 20:
            regime[nm] = _sharpe(sel)
    fields = expr.fields()
    if uses_full_sample(expr):
        notes.append("signal uses a full-sample operator (zscore_full or winsor_full)"
                     + ("; strict mode evaluates it on expanding windows" if mode == "strict" else ""))
    for f in sorted(fields & set(LEAKY_FIELDS)):
        notes.append(f"signal uses leaky field '{f}'" + ("; strict mode replaces it with its point-in-time version" if mode == "strict" else ""))
    if lag == 0:
        notes.append("lag is 0: the signal trades on the bar that produced it (same-bar look-ahead)")
    if uni_name == "survivors" or (uni_name == "default" and world.universe_files["default"] is world.universe_files["survivors"]):
        notes.append("universe is survivors only (assets alive at the end of the research period)")
    if bps == 0:
        notes.append("costs are zero")
    return BacktestResult(spec_hash=spec_hash(spec), mode=mode, period=period, metrics=m,
                          equity=[float(v) for v in eq[pick]], equity_index=[int(v) for v in ts[pick]],
                          yearly_sharpe=yearly, regime_sharpe=regime, notes=notes)


def true_edge(spec: StrategySpec, world: World, *, seeds=(101, 102, 103), period: str = "sealed") -> dict:
    """Ground truth: Sharpe in strict point-in-time mode, lag at least 1, full universe, realistic costs
    (world.cost_bps_true), on the sealed period, averaged over fresh worlds with the same params and variant.
    No model is involved."""
    variant = world.params.get("variant") or None
    per_seed = []
    s2 = spec.model_copy(update={"lag": max(spec.lag, 1)})
    for sd in seeds:
        w = make_world(sd, variant=variant, T=world.T, N=world.N)
        r = run_backtest(s2, w, mode="strict", period=period, cost_bps=w.cost_bps_true, universe="all")
        per_seed.append(round(r.metrics.sharpe, 4))
    return {"sharpe": float(np.mean(per_seed)), "per_seed": per_seed,
            "how": f"strict point-in-time, lag>={max(spec.lag, 1)}, full universe, {world.cost_bps_true:g} bps, {period} period, "
                   f"mean over seeds {list(seeds)} with the same params and variant"}
