"""Safe expression language for signals: a recursive-descent parser and a whitelisted numpy interpreter.

Grammar:  expr := term (('+'|'-') term)*;  term := unary (('*'|'/') unary)*;  unary := '-' unary | atom
          atom := number | name | name '(' args ')' | '(' expr ')'
No eval. Operators work on [T, N] arrays (time x asset). Rolling operators look back only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

FIELD_NAMES = (
    "close", "ret", "volume", "eps_reported", "eps_restated", "sentiment", "sentiment_revised",
    "index_member_pit", "index_member_now",
)
FULL_SAMPLE_OPS = ("zscore_full", "winsor_full")
MAX_WINDOW = 252
MAX_DEPTH = 24
MAX_NODES = 120

# name -> (number of args, kinds) ; kinds: x = series, w = integer window, p = fraction
FUNCS: dict[str, tuple[str, ...]] = {
    "rank": ("x",), "zscore": ("x", "w"), "ts_mean": ("x", "w"), "ts_std": ("x", "w"), "ts_sum": ("x", "w"),
    "delta": ("x", "d"), "delay": ("x", "z"), "winsor": ("x", "p"), "sign": ("x",), "abs": ("x",), "log": ("x",),
    "zscore_full": ("x",), "winsor_full": ("x", "p"),
}


class Expr:
    """Base class of AST nodes."""

    def fields(self) -> set[str]:
        return set()

    def funcs(self) -> set[str]:
        return set()


@dataclass(frozen=True)
class Num(Expr):
    value: float


@dataclass(frozen=True)
class Field(Expr):
    name: str

    def fields(self):
        return {self.name}


@dataclass(frozen=True)
class Neg(Expr):
    arg: Expr

    def fields(self):
        return self.arg.fields()

    def funcs(self):
        return self.arg.funcs()


@dataclass(frozen=True)
class BinOp(Expr):
    op: str
    left: Expr
    right: Expr

    def fields(self):
        return self.left.fields() | self.right.fields()

    def funcs(self):
        return self.left.funcs() | self.right.funcs()


@dataclass(frozen=True)
class Call(Expr):
    name: str
    args: tuple

    def fields(self):
        return set().union(*[a.fields() for a in self.args]) if self.args else set()

    def funcs(self):
        return {self.name}.union(*[a.funcs() for a in self.args])


_TOKEN = re.compile(r"\s*(?:(\d+\.\d*|\.\d+|\d+)|([A-Za-z_][A-Za-z_0-9]*)|(.))")


def _tokenize(s: str):
    out, pos = [], 0
    s = s.rstrip()
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m:
            break
        pos = m.end()
        if m.group(1) is not None:
            out.append(("num", m.group(1)))
        elif m.group(2) is not None:
            out.append(("name", m.group(2)))
        else:
            out.append(("op", m.group(3)))
    out.append(("end", ""))
    return out


class _Parser:
    def __init__(self, text: str):
        self.toks = _tokenize(text)
        self.i = 0
        self.nodes = 0

    def peek(self):
        return self.toks[self.i]

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, ch: str):
        t = self.take()
        if t != ("op", ch):
            got = "end of formula" if t[0] == "end" else repr(t[1])
            raise ValueError(f"expected '{ch}' but found {got}")

    def count(self, depth: int):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ValueError(f"formula is too large (more than {MAX_NODES} parts)")
        if depth > MAX_DEPTH:
            raise ValueError("formula is nested too deeply")

    def expr(self, d=0):
        node = self.term(d)
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            node = BinOp(op, node, self.term(d))
            self.count(d)
        return node

    def term(self, d):
        node = self.unary(d)
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            node = BinOp(op, node, self.unary(d))
            self.count(d)
        return node

    def unary(self, d):
        self.count(d)
        if self.peek() == ("op", "-"):
            self.take()
            return Neg(self.unary(d + 1))
        if self.peek() == ("op", "+"):
            self.take()
            return self.unary(d + 1)
        return self.atom(d)

    def atom(self, d):
        kind, val = self.take()
        if kind == "num":
            return Num(float(val))
        if kind == "name":
            if self.peek() == ("op", "("):
                return self.call(val, d)
            if val in FUNCS:
                raise ValueError(f"'{val}' is an operator; write {val}(...) with arguments")
            if val not in FIELD_NAMES:
                raise ValueError(f"unknown field '{val}'; fields are: {', '.join(FIELD_NAMES)}")
            return Field(val)
        if kind == "op" and val == "(":
            node = self.expr(d + 1)
            self.expect(")")
            return node
        if kind == "end":
            raise ValueError("formula ends too early; an operand is missing")
        raise ValueError(f"unexpected '{val}'")

    def call(self, name, d):
        if name not in FUNCS:
            raise ValueError(f"unknown operator '{name}'; operators are: {', '.join(FUNCS)}")
        self.expect("(")
        args = []
        if self.peek() != ("op", ")"):
            args.append(self.expr(d + 1))
            while self.peek() == ("op", ","):
                self.take()
                args.append(self.expr(d + 1))
        self.expect(")")
        kinds = FUNCS[name]
        if len(args) != len(kinds):
            raise ValueError(f"{name} takes {len(kinds)} argument(s) but got {len(args)}")
        for a, k in zip(args[1:], kinds[1:]):
            _check_param(name, a, k)
        return Call(name, tuple(args))


def _num_of(a: Expr):
    if isinstance(a, Num):
        return a.value
    if isinstance(a, Neg) and isinstance(a.arg, Num):
        return -a.arg.value
    return None


def _check_param(name: str, a: Expr, kind: str):
    v = _num_of(a)
    if v is None:
        what = "a fraction" if kind == "p" else "a whole number of bars"
        raise ValueError(f"{name}: the second argument must be a plain number ({what}), not a formula")
    if kind == "p":
        if not 0 < v < 0.5:
            raise ValueError(f"{name}: the fraction must be between 0 and 0.5 (exclusive), got {v:g}")
        return
    if v != int(v):
        raise ValueError(f"{name}: the window must be a whole number, got {v:g}")
    lo = 0 if kind == "z" else 1
    if not lo <= v <= MAX_WINDOW:
        raise ValueError(f"{name}: the window must be between {lo} and {MAX_WINDOW} bars, got {int(v)}")


def parse(signal: str) -> Expr:
    """Parse a signal formula into an AST. Raises ValueError with a plain-language message."""
    if not isinstance(signal, str) or not signal.strip():
        raise ValueError("the signal formula is empty")
    if len(signal) > 400:
        raise ValueError("the signal formula is longer than 400 characters")
    p = _Parser(signal)
    node = p.expr()
    t = p.peek()
    if t[0] != "end":
        raise ValueError(f"unexpected '{t[1]}' after the end of the formula")
    return node


def uses_full_sample(expr: Expr) -> bool:
    return any(f in FULL_SAMPLE_OPS for f in expr.funcs())


# ---------------------------------------------------------------------------------------------
# Interpreter (all arrays float64 [t, N], t = number of visible bars)


def _roll_sum(x, w, valid_mask=None):
    """Rolling sum over the last w bars; NaN unless all w values are finite."""
    ok = np.isfinite(x)
    z = np.where(ok, x, 0.0)
    cs = np.cumsum(z, axis=0)
    cc = np.cumsum(ok, axis=0)
    s = cs.copy()
    c = cc.copy()
    if w < len(x):
        s[w:] = cs[w:] - cs[:-w]
        c[w:] = cc[w:] - cc[:-w]
    out = np.where(c >= w, s, np.nan)
    out[: w - 1] = np.nan
    return out


def ts_mean(x, w):
    return _roll_sum(x, w) / w


def ts_std(x, w):
    if w < 2:
        return np.full_like(x, np.nan)
    y = x
    s1 = _roll_sum(y, w)
    s2 = _roll_sum(y * y, w)
    var = (s2 - s1 * s1 / w) / (w - 1)
    return np.sqrt(np.maximum(var, 0.0))


def _delay(x, d):
    if d == 0:
        return x
    out = np.full_like(x, np.nan)
    if d < len(x):
        out[d:] = x[:-d]
    return out


def _rank(x):
    """Cross-sectional rank scaled to [0, 1]; NaN stays NaN. Ties share the average rank."""
    t, n = x.shape
    ok = np.isfinite(x)
    filled = np.where(ok, x, np.inf)
    order = np.argsort(filled, axis=1)
    sorted_ = np.take_along_axis(filled, order, axis=1)
    pos = np.broadcast_to(np.arange(n, dtype=np.float64), (t, n))
    tie = (sorted_[:, 1:] == sorted_[:, :-1]) & np.isfinite(sorted_[:, 1:])
    if tie.any():  # average rank within groups of equal values
        newgrp = np.ones((t, n), dtype=bool)
        newgrp[:, 1:] = ~tie
        start = np.maximum.accumulate(np.where(newgrp, pos, 0.0), axis=1)
        endmark = np.zeros((t, n), dtype=bool)
        endmark[:, :-1] = newgrp[:, 1:]
        endmark[:, -1] = True
        end = np.minimum.accumulate(np.where(endmark, pos, n)[:, ::-1], axis=1)[:, ::-1]
        avg = (start + end) / 2.0
    else:
        avg = pos
    r = np.empty((t, n))
    np.put_along_axis(r, order, np.ascontiguousarray(avg), axis=1)
    cnt = ok.sum(axis=1, keepdims=True).astype(np.float64)
    out = np.where(ok, r / np.maximum(cnt - 1.0, 1.0), np.nan)
    out[(cnt[:, 0] < 2)] = np.where(ok[(cnt[:, 0] < 2)], 0.5, np.nan)
    return out


def _zscore(x, w):
    mu = ts_mean(x, w)
    sd = ts_std(x, w)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 1e-12, (x - mu) / sd, np.nan)


def _zscore_full(x, strict):
    """Per-asset standardisation. Naive: mean and std of all visible bars (looks into the future).
    Strict: expanding mean and std (past and present bars only)."""
    ok = np.isfinite(x)
    y = np.where(ok, x, 0.0)
    if strict:
        c = np.cumsum(ok, axis=0).astype(np.float64)
        s1 = np.cumsum(y, axis=0)
        s2 = np.cumsum(y * y, axis=0)
    else:
        c = np.broadcast_to(ok.sum(axis=0).astype(np.float64), x.shape)
        s1 = np.broadcast_to(y.sum(axis=0), x.shape)
        s2 = np.broadcast_to((y * y).sum(axis=0), x.shape)
    with np.errstate(divide="ignore", invalid="ignore"):
        mu = s1 / c
        var = (s2 - c * mu * mu) / (c - 1)
        sd = np.sqrt(np.maximum(var, 0.0))
        out = np.where((c > 2) & (sd > 1e-12) & ok, (x - mu) / sd, np.nan)
    return out


def _winsor(x, p):
    """Clip each bar's cross-section at its own p and 1-p quantiles (uses only that bar)."""
    lo = np.nanquantile(x, p, axis=1, keepdims=True)
    hi = np.nanquantile(x, 1 - p, axis=1, keepdims=True)
    return np.where(np.isfinite(x), np.clip(x, lo, hi), np.nan)


def _winsor_full(x, p, strict):
    """Clip at the p and 1-p quantiles of all visible bars (naive) or of bars up to each bar (strict)."""
    if not strict:
        lo = np.nanquantile(x, p)
        hi = np.nanquantile(x, 1 - p)
        return np.where(np.isfinite(x), np.clip(x, lo, hi), np.nan)
    out = np.full_like(x, np.nan)
    step = max(1, len(x) // 60)
    lo = hi = None
    for t in range(len(x)):
        if t % step == 0 or lo is None:
            seg = x[: t + 1]
            if np.isfinite(seg).any():
                lo, hi = np.nanquantile(seg, p), np.nanquantile(seg, 1 - p)
        if lo is not None:
            out[t] = np.where(np.isfinite(x[t]), np.clip(x[t], lo, hi), np.nan)
    return out


def _eval(node, env, strict):
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Field):
        return env[node.name]
    if isinstance(node, Neg):
        return -_eval(node.arg, env, strict)
    if isinstance(node, BinOp):
        a, b = _eval(node.left, env, strict), _eval(node.right, env, strict)
        with np.errstate(divide="ignore", invalid="ignore"):
            if node.op == "+":
                return a + b
            if node.op == "-":
                return a - b
            if node.op == "*":
                return a * b
            r = np.asarray(a) / np.asarray(b)
            return np.where(np.isfinite(r), r, np.nan)
    if isinstance(node, Call):
        name = node.name
        x = _eval(node.args[0], env, strict)
        if not isinstance(x, np.ndarray):
            x = np.full(env["_shape"], float(x))
        k = [_num_of(a) for a in node.args[1:]]
        with np.errstate(divide="ignore", invalid="ignore"):
            if name == "rank":
                return _rank(x)
            if name == "zscore":
                return _zscore(x, int(k[0]))
            if name == "ts_mean":
                return ts_mean(x, int(k[0]))
            if name == "ts_std":
                return ts_std(x, int(k[0]))
            if name == "ts_sum":
                return _roll_sum(x, int(k[0]))
            if name == "delta":
                return x - _delay(x, int(k[0]))
            if name == "delay":
                return _delay(x, int(k[0]))
            if name == "winsor":
                return _winsor(x, k[0])
            if name == "sign":
                return np.sign(x)
            if name == "abs":
                return np.abs(x)
            if name == "log":
                return np.where(x > 0, np.log(np.where(x > 0, x, 1.0)), np.nan)
            if name == "zscore_full":
                return _zscore_full(x, strict)
            if name == "winsor_full":
                return _winsor_full(x, k[0], strict)
    raise ValueError("internal error: unknown node")


def evaluate(expr, world, *, mode: str = "naive", upto: int | None = None) -> np.ndarray:
    """Evaluate `expr` into a [T, N] signal using only bars 0..upto-1 (rows from `upto` on are NaN).
    mode='strict' reads each field's point-in-time version (world.asof) and gives full-sample operators
    expanding windows. mode='naive' reads the live field and lets full-sample operators see all bars below `upto`."""
    if isinstance(expr, str):
        expr = parse(expr)
    if mode not in ("naive", "strict"):
        raise ValueError("mode must be 'naive' or 'strict'")
    T = world.T
    upto = T if upto is None else int(min(max(upto, 0), T))
    src = world.asof if mode == "strict" else world.fields
    env = {"_shape": (upto, world.N)}
    for name in expr.fields():
        if name not in src:
            raise ValueError(f"field '{name}' does not exist in this world")
        env[name] = np.asarray(src[name][:upto], dtype=np.float64)
    out = np.full((T, world.N), np.nan)
    if upto == 0:
        return out
    res = _eval(expr, env, mode == "strict")
    if not isinstance(res, np.ndarray):
        res = np.full((upto, world.N), float(res))
    res = np.where(np.isfinite(res), res, np.nan)
    out[:upto] = res
    return out
