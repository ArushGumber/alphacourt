"""Shared types. The rest of the package codes against these.

Conventions
- Bars are trading days, indexed 0..T-1. Assets are indexed 0..N-1.
- ret[t, i] is the return of asset i from the close of bar t-1 to the close of bar t.
- A signal value S[t, i] may use only data available at the close of bar t (if the fields are point in time).
- Weights w[t, i] are computed from S[t]. Daily P&L is pnl[t] = sum_i w[t - lag, i] * ret[t, i] - costs[t].
  lag = 1 is honest (decide at the close, earn the next bar). lag = 0 is same-bar look-ahead.
- Sharpe ratios are annualised with sqrt(252), net of the spec's own costs unless stated.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ----------------------------------------------------------------------------------------------
# Strategy

Universe = Literal["all", "survivors", "default"]  # "default" = whatever the data room's universe file lists
PortfolioType = Literal["long_short_quantile", "long_only_top"]


class Portfolio(BaseModel):
    type: PortfolioType = "long_short_quantile"
    quantile: float = Field(0.2, gt=0, le=0.5)  # top and bottom share of assets held
    gross: float = Field(1.0, gt=0, le=2.0)  # sum of absolute weights


class Sample(BaseModel):
    start: int = 0  # first bar used, inside the research period
    end: int | None = None  # last bar (exclusive); None = end of the research period


class StrategySpec(BaseModel):
    """A strategy is data, never code. The engine evaluates `signal` with a whitelisted interpreter (court/expr.py)."""

    name: str = Field(..., max_length=80)
    universe: Universe = "default"
    signal: str = Field(..., max_length=400)  # e.g. "rank(ts_mean(ret, 20) - ts_mean(ret, 120))"
    lag: int = Field(1, ge=0, le=20)
    rebalance: int = Field(1, ge=1, le=63)  # recompute weights every k bars, hold in between
    portfolio: Portfolio = Portfolio()
    costs_bps: float = Field(0.0, ge=0, le=200)  # cost per unit of one-way turnover, in basis points
    sample: Sample = Sample()
    params: dict[str, float | int | str] = {}  # free-form, recorded for the trial-count and stability tests
    notes: str = Field("", max_length=2000)  # the submitter's text; may contain anything, including tampering


class Metrics(BaseModel):
    sharpe: float
    ann_return: float  # annualised mean daily P&L x 252 (fraction of gross capital)
    ann_vol: float
    max_drawdown: float  # positive fraction
    turnover: float  # mean daily one-way turnover
    hit_rate: float  # share of days with positive P&L
    n_days: int


class BacktestResult(BaseModel):
    spec_hash: str
    mode: Literal["naive", "strict"]
    period: Literal["research", "sealed", "full"]
    metrics: Metrics
    equity: list[float]  # cumulative P&L, downsampled to at most 400 points for the site
    equity_index: list[int]  # bar index of each equity point
    yearly_sharpe: dict[str, float] = {}  # "year 1" -> Sharpe, by blocks of 252 bars
    regime_sharpe: dict[str, float] = {}  # "calm" / "stressed" -> Sharpe
    notes: list[str] = []  # engine warnings, e.g. "signal uses a full-sample operator"


# ----------------------------------------------------------------------------------------------
# Research log (written by the gateway; the court's evidence on how many variants were tried)


class Trial(BaseModel):
    t: float  # unix time
    spec_hash: str
    spec: StrategySpec
    metrics: Metrics  # naive research-period metrics the agent saw


class ResearchLog(BaseModel):
    session_id: str
    agent: str = "unknown"  # model or client name, as reported
    trials: list[Trial] = []
    pages_read: list[str] = []  # alpha-web URLs read through the gateway
    submitted_spec_hash: str | None = None


# ----------------------------------------------------------------------------------------------
# Case, exhibits, trial


class Claim(BaseModel):
    sharpe: float
    ann_return: float | None = None
    max_drawdown: float | None = None
    text: str = ""  # the submitter's pitch


class CaseFile(BaseModel):
    """What the court sees. Built by the clerk (code) from the submission and the research log."""

    case_id: str
    world_id: str  # which data room the strategy was researched in
    spec: StrategySpec
    claim: Claim
    requested_capital: float = 1_000_000.0
    log_summary: dict[str, Any] = {}  # n_trials, n_distinct_specs, best_of, grid (param -> values tried), is_best
    pages_read: list[str] = []


ExhibitHint = Literal["damaging", "neutral", "supportive"]


class Exhibit(BaseModel):
    id: str  # "EX-1", "EX-2", ... unique within a case
    test: str  # forensic tool name
    params: dict[str, Any] = {}
    numbers: dict[str, float | int | str | None] = {}  # the measured values, e.g. {"sharpe_before": 2.9, "sharpe_after": 0.1}
    summary: str  # one plain sentence written by code from the numbers
    hint: ExhibitHint
    chart: dict[str, Any] = {}  # small plot data for the site: {"type": "equity", "series": [{"label":..., "y": [...]}]}
    called_by: Literal["prosecution", "defence", "battery", "clerk"] = "prosecution"


SINS = [
    "lookahead",  # same-bar trading (lag 0)
    "leaky_field",  # a field that is not point in time (backfilled, restated, revised)
    "full_sample",  # normalisation with full-sample statistics
    "survivorship",  # survivors-only universe
    "costs",  # costs ignored or understated
    "selection",  # best of many trials without correction
    "lucky_period",  # performance from one period or regime
    "knife_edge",  # fragile tuned parameters
    "tampering",  # text addressed to the reviewers
]
Sin = Literal[
    "lookahead", "leaky_field", "full_sample", "survivorship", "costs", "selection", "lucky_period", "knife_edge", "tampering", "other"
]


class Charge(BaseModel):
    sin: Sin
    exhibits: list[str] = []  # exhibit ids
    argument: str = Field("", max_length=1200)


class Rebuttal(BaseModel):
    sin: Sin
    concede: bool = False
    exhibits: list[str] = []
    argument: str = Field("", max_length=1200)


Ruling = Literal["deploy", "paper", "reject"]


class Finding(BaseModel):
    sin: Sin
    sustained: bool
    exhibits: list[str] = []
    struck: bool = False  # set by the exhibit rule: sustained but cites no valid exhibit


class Verdict(BaseModel):
    ruling: Ruling
    findings: list[Finding] = []
    capital_allowed: float = 0.0  # fraction of the requested capital, 0 to 1
    opinion: str = Field("", max_length=1200)
    unsupported: bool = False  # set by the exhibit rule when a stop ruling had no surviving finding and was converted
    defaulted: bool = False  # the judge gave no valid ruling; the cautious default (paper) was used


class Event(BaseModel):
    """One step of a trial, streamed to the site and stored in the transcript."""

    t: float
    role: Literal["clerk", "prosecution", "defence", "judge", "rule", "gateway", "system"]
    kind: Literal["case", "tool_call", "exhibit", "charge", "rebuttal", "verdict", "note", "error"]
    data: dict[str, Any] = {}


class TrialRecord(BaseModel):
    case: CaseFile
    system: str  # "court", "single", "debate", "battery", "none"
    staffing: dict[str, str] = {}  # role -> model id
    exhibits: list[Exhibit] = []
    charges: list[Charge] = []
    rebuttals: list[Rebuttal] = []
    verdict: Verdict
    events: list[Event] = []
    calls: int = 0  # model calls made
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
