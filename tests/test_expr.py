import dataclasses

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from court.expr import evaluate, parse
from court.market import make_world

BAD = [
    ("", "empty"),
    ("rank(", "ends too early"),
    ("rank(ret", "expected ')'"),
    ("foo(ret, 3)", "unknown operator 'foo'"),
    ("rnk(ret)", "unknown operator"),
    ("price", "unknown field 'price'"),
    ("ts_mean(ret, 0)", "between 1 and 252"),
    ("ts_mean(ret, 253)", "between 1 and 252"),
    ("ts_mean(ret, 2.5)", "whole number"),
    ("ts_mean(ret, ret)", "plain number"),
    ("ts_mean(ret)", "takes 2"),
    ("rank(ret, 3)", "takes 1"),
    ("delta(ret, 0)", "between 1 and 252"),
    ("delay(ret, -1)", "between 0 and 252"),
    ("winsor(ret, 0.6)", "between 0 and 0.5"),
    ("ret + ", "ends too early"),
    ("ret ret", "unexpected"),
    ("ret $ 2", "unexpected"),
    ("__import__('os')", "unknown operator"),
    ("rank", "operator"),
    ("(" * 40 + "ret" + ")" * 40, "nested"),
]


@pytest.mark.parametrize("text,msg", BAD)
def test_parse_errors(text, msg):
    with pytest.raises(ValueError) as e:
        parse(text)
    assert msg in str(e.value)


def test_parse_ok():
    for s in ["rank(ts_mean(ret, 20) - ts_mean(ret, 120))", "-zscore_full(log(close))", "delay(ret, 0) * 2 / (1 + abs(sentiment))",
              "winsor(zscore(ret, 60), 0.05)", "sign(delta(close, 5)) + 1.5"]:
        parse(s)


@pytest.fixture(scope="module")
def small():
    return make_world(5, T=500, N=60)


def _copy_with_ret(w, ret):
    f = dict(w.fields)
    a = dict(w.asof)
    f["ret"] = ret
    a["ret"] = ret
    return dataclasses.replace(w, fields=f, asof=a)


SIGS = ["rank(delay(ts_sum(ret,100),10))", "zscore(ret,30)", "zscore_full(ts_mean(ret,20))", "winsor_full(ret,0.05)",
        "rank(ts_std(ret,40))-rank(sentiment_revised)", "rank(eps_restated)+delta(close,5)"]


@settings(max_examples=12, deadline=None)
@given(sig=st.sampled_from(SIGS), t=st.integers(150, 460), seed=st.integers(0, 1000))
def test_strict_uses_no_future(small, sig, t, seed):
    w = small
    ret2 = np.array(w.fields["ret"], copy=True)
    rng = np.random.default_rng(seed)
    ret2[t + 1:] = rng.normal(0, 0.05, ret2[t + 1:].shape).astype(np.float32)
    w2 = _copy_with_ret(w, ret2)
    a = evaluate(parse(sig), w, mode="strict", upto=w.T)
    b = evaluate(parse(sig), w2, mode="strict", upto=w.T)
    np.testing.assert_allclose(a[: t + 1], b[: t + 1], rtol=1e-9, atol=1e-9, equal_nan=True)


def test_upto_hides_later_bars(small):
    w = small
    e = parse("rank(ts_mean(ret,10))")
    full = evaluate(e, w, mode="naive", upto=w.T)
    part = evaluate(e, w, mode="naive", upto=300)
    np.testing.assert_allclose(full[:300], part[:300], equal_nan=True)
    assert np.isnan(part[300:]).all()


def test_naive_full_sample_sees_future(small):
    w = small
    e = parse("zscore_full(ts_mean(ret,20))")
    a = evaluate(e, w, mode="naive", upto=w.T)
    ret2 = np.array(w.fields["ret"], copy=True)
    ret2[400:] += 0.05
    b = evaluate(e, _copy_with_ret(w, ret2), mode="naive", upto=w.T)
    assert not np.allclose(a[100:300], b[100:300], equal_nan=True)


def test_rank_range_and_nan(small):
    r = evaluate(parse("rank(ret)"), small, mode="naive", upto=small.T)
    v = r[np.isfinite(r)]
    assert v.min() == 0.0 and v.max() == 1.0
    assert np.isnan(r[np.isnan(small.fields["ret"])]).all()
