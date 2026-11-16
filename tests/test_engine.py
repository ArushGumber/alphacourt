import time

import numpy as np
import pytest

from court.engine import run_backtest, spec_hash, true_edge
from court.market import make_world
from court.types import Sample, StrategySpec

MOM = "rank(delay(ts_sum(ret,231),21))"


def sp(sig, **kw):
    kw.setdefault("costs_bps", 10)
    return StrategySpec(name="t", signal=sig, **kw)


@pytest.fixture(scope="module")
def worlds():
    return [make_world(s) for s in (1, 2, 3)]


def mean_sharpe(spec, worlds, **kw):
    return float(np.mean([run_backtest(spec, w, **kw).metrics.sharpe for w in worlds]))


def test_world_deterministic_and_cache_equal():
    a = make_world(77, T=600, N=50, cache=False)
    b = make_world(77, T=600, N=50, cache=False)
    c = make_world(77, T=600, N=50)  # writes cache
    d = make_world(77, T=600, N=50)  # reads cache
    for k in a.fields:
        np.testing.assert_array_equal(a.fields[k], b.fields[k])
        np.testing.assert_array_equal(c.fields[k], d.fields[k])
        np.testing.assert_array_equal(a.fields[k], d.fields[k])
        np.testing.assert_array_equal(a.asof[k], d.asof[k])
    assert a.world_id == d.world_id
    x = make_world(78, T=600, N=50, cache=False)
    assert not np.array_equal(np.nan_to_num(a.fields["ret"]), np.nan_to_num(x.fields["ret"]))


def test_world_structure(worlds):
    w = worlds[0]
    assert w.T == 3000 and w.N == 300 and w.research_end == 2250
    for k in ["close", "ret", "volume", "eps_reported", "eps_restated", "sentiment", "sentiment_revised",
              "index_member_pit", "index_member_now"]:
        assert w.fields[k].shape == (3000, 300) and k in w.field_info and k in w.asof
    assert 0.15 < w.regime.mean() < 0.26
    r = w.fields["ret"]
    assert 0.015 < np.nanstd(r) < 0.03
    assert np.isnan(r[~w.alive]).all() and np.isfinite(r[w.alive]).all()
    assert w.alive[w.research_end - 1].sum() < w.N and w.universe_files["survivors"].sum() == w.alive[w.research_end - 1].sum()
    assert w.asof["eps_restated"] is w.asof["eps_reported"] or np.array_equal(w.asof["eps_restated"], w.asof["eps_reported"], equal_nan=True)
    # announcement every about 63 bars, held in between
    e = w.fields["eps_reported"][:, 0]
    changes = np.flatnonzero(np.diff(e[np.isfinite(e)]) != 0)
    assert 55 <= np.median(np.diff(changes)) <= 70


def test_variants():
    plain = make_world(11, T=800, N=60, cache=False)
    bf = make_world(11, variant={"backfilled": ["eps_reported"]}, T=800, N=60, cache=False)
    assert plain.field_info == bf.field_info
    np.testing.assert_array_equal(bf.fields["eps_reported"], plain.fields["eps_restated"])
    np.testing.assert_array_equal(bf.asof["eps_reported"], plain.fields["eps_reported"])
    np.testing.assert_array_equal(bf.fields["ret"], plain.fields["ret"])  # same noise and effects
    sv = make_world(11, variant={"default_universe": "survivors"}, T=800, N=60, cache=False)
    assert sv.universe_files["default"] is sv.universe_files["survivors"]
    z = make_world(11, variant={"effect_scale": {"reversal": 0.0}}, T=800, N=60, cache=False)
    assert z.params["effects"]["reversal"] == 0.0
    with pytest.raises(ValueError):
        make_world(11, variant={"nonsense": 1}, T=800, N=60)


def test_spec_hash_stable():
    a, b = sp(MOM), sp(MOM)
    assert spec_hash(a) == spec_hash(b) and len(spec_hash(a)) == 12
    assert spec_hash(a) != spec_hash(sp(MOM, lag=2))


def test_result_shape(worlds):
    r = run_backtest(sp(MOM), worlds[0])
    assert len(r.equity) <= 400 and len(r.equity) == len(r.equity_index)
    assert r.metrics.n_days > 1000 and r.yearly_sharpe and set(r.regime_sharpe) <= {"calm", "stressed"}
    assert r.metrics.turnover < 0.2 and r.metrics.max_drawdown > 0
    r2 = run_backtest(sp(MOM), worlds[0])
    assert r.model_dump() == r2.model_dump()


def test_research_never_reads_sealed(worlds):
    import dataclasses
    w = worlds[0]
    ret2 = np.array(w.fields["ret"], copy=True)
    ret2[w.research_end:] = 0.3
    f = dict(w.fields); f["ret"] = ret2
    a = dict(w.asof); a["ret"] = ret2
    w2 = dataclasses.replace(w, fields=f, asof=a)
    s = sp("rank(-ts_std(ret,60))")
    assert run_backtest(s, w).model_dump() == run_backtest(s, w2).model_dump()
    assert run_backtest(s, w, period="sealed").metrics.sharpe != run_backtest(s, w2, period="sealed").metrics.sharpe


def test_lag_zero_inflates(worlds):
    s0 = sp("rank(ret)", lag=0)
    s1 = sp("rank(ret)", lag=1)
    assert mean_sharpe(s0, worlds) > 20
    assert mean_sharpe(s1, worlds) < 0  # the honest version of a same-bar signal is a costly reversal
    r = run_backtest(s0, worlds[0])
    assert any("lag is 0" in n for n in r.notes)
    # lag_extra restores honesty
    assert run_backtest(s0, worlds[0], lag_extra=1).metrics.sharpe < 0


def test_calibration_directions(worlds):
    comb = MOM + "+rank(eps_reported)-0.5*rank(ts_std(ret,60))"
    mom = mean_sharpe(sp(MOM), worlds)
    pead = mean_sharpe(sp("rank(eps_reported)"), worlds)
    assert 0.3 < mom < 1.6 and 0.4 < pead < 1.8
    assert mean_sharpe(sp(comb), worlds) > max(mom, pead) * 0.9
    rev0 = sp("rank(-ret)", costs_bps=0)
    assert mean_sharpe(rev0, worlds) > 3
    assert mean_sharpe(sp("rank(-ret)", costs_bps=10), worlds) < 0
    assert mean_sharpe(sp("rank(sentiment_revised)"), worlds) > 4
    assert mean_sharpe(sp("rank(sentiment_revised)"), worlds, mode="strict") < 1
    rest = sp("rank(eps_restated)")
    assert mean_sharpe(rest, worlds) > 2.5
    assert mean_sharpe(rest, worlds, mode="strict") < mean_sharpe(rest, worlds) - 1.5
    assert mean_sharpe(sp(MOM, universe="survivors"), worlds) > mean_sharpe(sp(MOM), worlds) + 0.3
    zf = sp("-zscore_full(log(close))")
    assert mean_sharpe(zf, worlds) > 3
    assert mean_sharpe(zf, worlds, mode="strict") < 1.5


def test_notes(worlds):
    w = worlds[0]
    r = run_backtest(sp("rank(sentiment_revised)", costs_bps=0, universe="survivors"), w)
    joined = " | ".join(r.notes)
    for frag in ["leaky field 'sentiment_revised'", "survivors", "costs are zero"]:
        assert frag in joined
    assert any("full-sample" in n for n in run_backtest(sp("zscore_full(ret)"), w).notes)
    assert run_backtest(sp(MOM), w).notes == []


def test_overrides(worlds):
    w = worlds[0]
    s = sp("rank(-ret)")
    assert run_backtest(s, w, cost_bps=0).metrics.sharpe > run_backtest(s, w).metrics.sharpe
    a = run_backtest(sp(MOM), w, sample=Sample(start=1000, end=1500))
    assert a.equity_index[-1] < 1500 and a.metrics.n_days <= 500
    assert run_backtest(sp(MOM, rebalance=21), w).metrics.turnover < run_backtest(sp(MOM), w).metrics.turnover
    lo = run_backtest(sp(MOM, portfolio={"type": "long_only_top"}), w)
    assert lo.metrics.n_days > 1000


def test_true_edge(worlds):
    w = worlds[0]
    t = true_edge(sp("rank(-ret)", costs_bps=0, lag=0), w)
    assert len(t["per_seed"]) == 3 and t["sharpe"] < 0.2 and "strict" in t["how"]
    assert true_edge(sp("rank(-ret)", costs_bps=0, lag=0), w) == t


def test_speed(worlds):
    w = worlds[0]
    s = sp(MOM + "+rank(eps_reported)-0.5*rank(ts_std(ret,60))")
    run_backtest(s, w)
    ts = []
    for _ in range(7):
        t0 = time.perf_counter()
        run_backtest(s, w)
        ts.append(time.perf_counter() - t0)
    assert np.median(ts) < 0.30  # 150 ms on an idle machine; the machine is shared
    t0 = time.perf_counter()
    make_world(31337, cache=False)
    assert time.perf_counter() - t0 < 3.0
