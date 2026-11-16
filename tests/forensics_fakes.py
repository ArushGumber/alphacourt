"""Small fake world and fake engine, used only while the real engine does not exist."""
from __future__ import annotations

import math
import sys
import types
from types import SimpleNamespace

import numpy as np

from court.types import BacktestResult, Metrics


def make_fake_world(seed=0, T=900, N=60, leaky=True):
    rng = np.random.default_rng(seed)
    feat = np.zeros((T, N))
    for t in range(1, T):
        feat[t] = 0.9 * feat[t - 1] + rng.normal(size=N) * 0.5
    ret = rng.normal(0, 0.01, (T, N))
    ret[1:] += 0.0006 * feat[:-1]
    ret[0] = 0
    asof_feat = feat.copy()
    leaky_feat = feat.copy()
    leaky_feat[:-1] = feat[:-1] + 8 * ret[1:]  # includes next bar's return
    alive = np.ones((T, N), bool)
    alive[2000 // 3 :, :6] = False
    ret_f = np.where(alive, ret, np.nan)
    regime = (np.arange(T) % 300 > 220).astype(int)
    allm = np.ones(N, bool)
    surv = alive[int(0.75 * T) - 1].copy()
    return SimpleNamespace(
        world_id="fake", seed=seed, T=T, N=N, research_end=int(0.75 * T),
        fields={"ret": ret_f, "feat": feat, "lfeat": leaky_feat},
        field_info={}, asof={"ret": ret_f, "feat": asof_feat, "lfeat": feat.copy()},
        alive=alive, universe_files={"all": allm, "survivors": surv, "default": surv},
        regime=regime, cost_bps_true=5.0, params={},
    )


class FakeExpr:
    pass


def _rank(x):
    r = np.argsort(np.argsort(np.where(np.isnan(x), np.inf, x), axis=1), axis=1).astype(float)
    return r / x.shape[1]


def _ts_mean(x, w):
    w = int(w)
    c = np.cumsum(np.nan_to_num(x), axis=0)
    out = c.copy()
    out[w:] = c[w:] - c[:-w]
    return out / w


def _delay(x, d):
    d = int(d)
    out = np.full_like(x, np.nan)
    out[d:] = x[:-d] if d else x
    return out


def install(monkeypatch):
    expr = types.ModuleType("court.expr")

    def parse(s):
        if "(" in s and s.count("(") != s.count(")"):
            raise ValueError("unbalanced")
        return s

    def evaluate(e, world, *, mode, upto):
        ns = {"rank": _rank, "ts_mean": _ts_mean, "delay": _delay, "zscore_full": lambda x: x,
              "np": np}
        src = world.asof if mode == "strict" else world.fields
        for k, v in src.items():
            ns[k] = v[:upto]
        return np.asarray(eval(e, {"__builtins__": {}}, ns), float)

    expr.parse, expr.evaluate = parse, evaluate
    eng = types.ModuleType("court.engine")

    def run_backtest(spec, world, *, mode="naive", period="research", cost_bps=None, lag_extra=0, universe=None, sample=None):
        S = evaluate(parse(spec.signal), world, mode=mode, upto=world.T)
        u = np.asarray(world.universe_files[universe or spec.universe], bool)
        S = S.copy(); S[:, ~u] = np.nan; S[~world.alive] = np.nan
        valid = np.isfinite(S); nv = valid.sum(1)
        order = np.argsort(np.where(valid, S, np.inf), axis=1)
        W = np.zeros_like(S)
        nl = np.maximum(1, (0.2 * nv).astype(int))
        for t in range(world.T):
            if nv[t] < 4:
                continue
            idx = order[t, : nv[t]]
            W[t, idx[: nl[t]]] = -0.5 / nl[t]
            W[t, idx[nv[t] - nl[t]:]] = 0.5 / nl[t]
        lag = spec.lag + lag_extra
        Wl = np.zeros_like(W); Wl[lag:] = W[: world.T - lag] if lag else W
        ret = np.nan_to_num(world.fields["ret"])
        dW = np.abs(np.diff(Wl, axis=0, prepend=0)).sum(1)
        c = spec.costs_bps if cost_bps is None else cost_bps
        pnl = (Wl * ret).sum(1) - c / 1e4 * dW
        a, b = (0, world.research_end) if period == "research" else (world.research_end, world.T)
        a = max(a, 60)
        p = pnl[a:b]
        sh = float(p.mean() / p.std(ddof=1) * math.sqrt(252))
        eq = np.cumsum(p)
        ys = {f"year {i // 252 + 1}": float(p[i:i + 252].mean() / p[i:i + 252].std(ddof=1) * math.sqrt(252)) for i in range(0, len(p), 252) if len(p[i:i + 252]) > 10}
        reg = world.regime[a:b]
        rs = {n: float(p[reg == v].mean() / p[reg == v].std(ddof=1) * math.sqrt(252)) for n, v in (("calm", 0), ("stressed", 1)) if (reg == v).sum() > 10}
        m = Metrics(sharpe=sh, ann_return=float(p.mean() * 252), ann_vol=float(p.std() * 16), max_drawdown=0.1, turnover=float(dW[a:b].mean() / 2), hit_rate=float((p > 0).mean()), n_days=len(p))
        return BacktestResult(spec_hash="x", mode=mode, period=period, metrics=m, equity=[float(v) for v in eq[:: max(1, len(eq) // 300)]], equity_index=list(range(a, b))[:: max(1, len(eq) // 300)], yearly_sharpe=ys, regime_sharpe=rs)

    eng.run_backtest = run_backtest
    monkeypatch.setitem(sys.modules, "court.expr", expr)
    monkeypatch.setitem(sys.modules, "court.engine", eng)
    import court
    monkeypatch.setattr(court, "expr", expr, raising=False)
    monkeypatch.setattr(court, "engine", eng, raising=False)
