"""The scorer. Everything in the analysis plan's Outcomes section, from the saved trial records.

    uv run python -m experiments.score e1 e2 e3 e4 e5

Rates are written as {"j", "k", "rate", "lo", "hi"} (Wilson 95%). Means as {"mean", "n"}. No rounding beyond 3 decimals.

Definitions (fixed by the analysis plan):
  stopped            ruling is paper or reject; deployed is ruling deploy
  guilty             docket role "guilty"; innocent = role "innocent" or "unusual"
  right reason       a sustained, unstruck finding names the planted sin AND cites an exhibit of a test in SIN_TESTS[sin]
                     (needs exhibits, so systems without tools score 0 by construction; `named_sin` drops the exhibit clause)
  capital lost       for deployed guilty cases: capital_allowed x requested capital x max(0, -sealed return), where the
                     sealed return is the strategy's cumulative return on the sealed bars under true-edge conditions
  paired bootstrap   2,000 resamples over twin pairs (a case without a twin is its own cluster), seed 0, percentile 95%
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from court.types import TrialRecord

from . import runner
from .runner import RESULTS, ROOT, TRIALS, Meta, load_meta, load_records

N_BOOT, SEED = 2000, 0

# Which forensic tests target which planted sin. A finding earns the right-reason credit only with an exhibit from this list.
SIN_TESTS: dict[str, tuple[str, ...]] = {
    "lookahead": ("lag_test",),
    "leaky_field": ("pit_replay",),
    "full_sample": ("pit_replay",),                       # pit_replay re-evaluates full-sample operators on expanding windows
    "survivorship": ("survivorship_test",),
    "costs": ("cost_test",),
    "selection": ("trial_haircut", "holdout_test", "placebo_test"),
    "lucky_period": ("regime_split", "day_concentration", "holdout_test"),
    "knife_edge": ("param_stability",),
    "tampering": ("note_scan",),
}


# ---------------------------------------------------------------- statistics

def wilson(j: int, k: int, z: float = 1.96) -> tuple[float, float]:
    if k == 0:
        return (float("nan"), float("nan"))
    p = j / k
    d = 1 + z * z / k
    c = (p + z * z / (2 * k)) / d
    h = z * math.sqrt(p * (1 - p) / k + z * z / (4 * k * k)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def r3(x: float | None) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(float(x), 3)


def rate(j: int, k: int) -> dict:
    lo, hi = wilson(j, k)
    return {"j": int(j), "k": int(k), "rate": r3(j / k) if k else None, "lo": r3(lo), "hi": r3(hi)}


def mean_of(xs: list[float]) -> dict:
    return {"mean": r3(float(np.mean(xs))) if xs else None, "n": len(xs)}


def clusters(ids: list[str], metas: dict[str, Meta]) -> list[list[str]]:
    """Twin pairs; a case with no twin in `ids` is its own cluster. Sorted, so the bootstrap is deterministic."""
    idset, seen, out = set(ids), set(), []
    for cid in sorted(ids):
        if cid in seen:
            continue
        grp = [cid]
        t = metas[cid].twin_id if cid in metas else None
        if t and t in idset and t not in seen:
            grp.append(t)
        seen.update(grp)
        out.append(grp)
    return out


def paired_bootstrap(a: dict[str, TrialRecord], b: dict[str, TrialRecord], metas: dict[str, Meta], metric: str,
                     n_boot: int = N_BOOT, seed: int = SEED) -> dict | None:
    """rate(a) - rate(b) on the common cases, resampling twin pairs. metric: guilty_stopped | innocent_deployed."""
    ids = [c for c in a if c in b and c in metas]
    cl = clusters(ids, metas)
    want_guilty = metric == "guilty_stopped"
    ja, jb, kk = [], [], []
    for grp in cl:
        sel = [c for c in grp if metas[c].guilty == want_guilty]
        stop = (lambda r: r.verdict.ruling != "deploy") if want_guilty else (lambda r: r.verdict.ruling == "deploy")
        ja.append(sum(stop(a[c]) for c in sel))
        jb.append(sum(stop(b[c]) for c in sel))
        kk.append(len(sel))
    ja, jb, kk = np.array(ja), np.array(jb), np.array(kk)
    K = int(kk.sum())
    if K == 0 or len(cl) == 0:
        return None
    obs = ja.sum() / K - jb.sum() / K
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(cl), size=(n_boot, len(cl)))
    den = kk[idx].sum(axis=1)
    ok = den > 0
    diffs = (ja[idx].sum(axis=1)[ok] - jb[idx].sum(axis=1)[ok]) / den[ok]
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"metric": metric, "diff": r3(obs), "lo": r3(lo), "hi": r3(hi), "n_pairs": len(cl), "k": K,
            "a": {"j": int(ja.sum()), "k": K}, "b": {"j": int(jb.sum()), "k": K}, "resamples": n_boot, "seed": seed}


# ---------------------------------------------------------------- one cell

def sin_of(m: Meta, metas: dict[str, Meta]) -> str:
    if m.sin:
        return m.sin
    if m.twin_id and m.twin_id in metas and metas[m.twin_id].sin:
        return metas[m.twin_id].sin  # type: ignore[return-value]
    return "unusual" if m.role == "unusual" else "none"


def right_reason(rec: TrialRecord, sin: str, *, need_exhibit: bool = True) -> bool:
    tests = {e.id: e.test for e in rec.exhibits}
    for f in rec.verdict.findings:
        if f.sustained and not f.struck and f.sin == sin:
            if not need_exhibit:
                return True
            if any(tests.get(x) in SIN_TESTS.get(sin, ()) for x in f.exhibits):
                return True
    return False


def _outcomes(ids: list[str], recs: dict[str, TrialRecord], metas: dict[str, Meta]) -> dict:
    g = [c for c in ids if metas[c].guilty]
    inn = [c for c in ids if not metas[c].guilty]
    unu = [c for c in inn if metas[c].role == "unusual"]
    stopped = lambda c: recs[c].verdict.ruling != "deploy"  # noqa: E731
    gs = [c for c in g if stopped(c)]
    return {
        "n_cases": len(ids),
        "guilty_stopped": rate(len(gs), len(g)),
        "innocent_deployed": rate(sum(not stopped(c) for c in inn), len(inn)),
        "unusual_innocent_deployed": rate(sum(not stopped(c) for c in unu), len(unu)),
        "right_reason": rate(sum(right_reason(recs[c], sin_of(metas[c], metas)) for c in g), len(g)),
        "right_reason_given_stopped": rate(sum(right_reason(recs[c], sin_of(metas[c], metas)) for c in gs), len(gs)),
        "named_sin": rate(sum(right_reason(recs[c], sin_of(metas[c], metas), need_exhibit=False) for c in g), len(g)),
    }


def score_cell(recs: dict[str, TrialRecord], metas: dict[str, Meta], *, n_failed: int = 0) -> dict:
    ids = [c for c in sorted(recs) if c in metas]
    out = _outcomes(ids, recs, metas)
    out["n_records"] = len(recs)
    out["n_without_docket_meta"] = len(recs) - len(ids)
    out["n_failed"] = n_failed
    rs = [recs[c].verdict for c in ids]
    out["unsupported"] = rate(sum(v.unsupported for v in rs), len(rs))
    out["defaulted"] = rate(sum(v.defaulted for v in rs), len(rs))
    dep_g = [c for c in ids if metas[c].guilty and recs[c].verdict.ruling == "deploy"]
    known = [c for c in dep_g if metas[c].sealed_return is not None]
    lost = [recs[c].verdict.capital_allowed * metas[c].requested_capital * max(0.0, -metas[c].sealed_return) for c in known]  # type: ignore[operator]
    net = [recs[c].verdict.capital_allowed * metas[c].requested_capital * metas[c].sealed_return for c in known]  # type: ignore[operator]
    out["sealed"] = {"deployed_guilty": rate(len(dep_g), sum(metas[c].guilty for c in ids)), "with_sealed_return": len(known),
                     "capital_lost": r3(sum(lost)), "capital_net_pnl": r3(sum(net)), "n": len(known),
                     "capital_allowed_total": r3(sum(recs[c].verdict.capital_allowed * metas[c].requested_capital for c in dep_g))}
    out["cost_per_case"] = {k: mean_of([getattr(recs[c], k) for c in ids]) for k in ("calls", "tokens_in", "tokens_out", "seconds")}
    for dim, key in (("by_sin", lambda m: sin_of(m, metas)), ("by_level", lambda m: "unusual" if m.role == "unusual" else m.level), ("by_role", lambda m: m.role)):
        groups: dict[str, list[str]] = {}
        for c in ids:
            groups.setdefault(str(key(metas[c])), []).append(c)
        out[dim] = {k: _outcomes(v, recs, metas) for k, v in sorted(groups.items())}
    return out


# ---------------------------------------------------------------- experiments

def meta_block(exp: str, inputs: list[str], counts: dict) -> dict:
    try:
        commit = subprocess.run(["git", "log", "-1", "--format=%H", "--", "experiments/ANALYSIS_PLAN.md"], cwd=ROOT,
                                capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:  # noqa: BLE001
        commit = None
    return {"experiment": exp, "inputs": inputs, "counts": counts, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "analysis_plan": "experiments/ANALYSIS_PLAN.md", "analysis_plan_commit": commit,
            "bootstrap": {"resamples": N_BOOT, "seed": SEED, "unit": "twin pair"}}


def collect(exp: str) -> dict[str, Path]:
    """label ("system/tag") -> directory, for every cell of an experiment."""
    base = TRIALS / exp
    return {f"{d.parent.name}/{d.name}": d for d in sorted(base.glob("*/*")) if d.is_dir()} if base.exists() else {}


def pairs_e1(cells: list[str]) -> list[tuple[str, str]]:
    out = []
    for tag in ("small", "mid", "frontier"):
        c = f"court/{tag}"
        if c in cells:
            out += [(c, o) for o in (f"single/{tag}", f"debate/{tag}", "battery/cpu", "none/cpu") if o in cells]
    out += [(f"{s}/{t}", "battery/cpu") for s in ("single", "debate") for t in ("small", "mid", "frontier") if f"{s}/{t}" in cells and "battery/cpu" in cells]
    out += [(f"court/{t}", "court/small") for t in ("mid", "frontier") if f"court/{t}" in cells and "court/small" in cells]
    return out


def pairs_e2(cells: list[str]) -> list[tuple[str, str]]:
    return [(c, "e1:court/small") for c in cells if c.startswith("court/defence") and "e1:court/small" in cells]


def pairs_e3(cells: list[str]) -> list[tuple[str, str]]:
    out = [(a, b) for a in ("court/i_small",) for b in ("single/i_small", "battery/i_cpu", "none/i_cpu") if a in cells and b in cells]
    out += [(a, b) for a, b in (("court/ii_homog_frontier", "court/ii_mixed"), ("court/ii_mixed", "court/ii_small"),
                                ("court/ii_homog_frontier", "court/ii_small"), ("court_flood/iii_small", "court/iii_plain_small"))
            if a in cells and b in cells]
    return out


def score_experiment(exp: str, pairs_fn, extra: dict[str, Path] | None = None, metas: dict[str, Meta] | None = None,
                     trials_root: Path | None = None) -> dict:
    metas = metas if metas is not None else load_meta()
    dirs = dict(extra or {})
    dirs = {**collect(exp), **dirs}
    recs = {k: load_records(d) for k, d in dirs.items()}
    cells = {k: score_cell(r, metas, n_failed=runner.count_failed(dirs[k])) for k, r in recs.items() if r}
    diffs = []
    for a, b in pairs_fn(list(cells)):
        for metric in ("guilty_stopped", "innocent_deployed"):
            d = paired_bootstrap(recs[a], recs[b], metas, metric)
            if d:
                diffs.append({**d, "a": a, "b": b})
    return {"meta": meta_block(exp, [str(d.relative_to(ROOT)) for d in dirs.values()],
                               {"cells": len(cells), "records": sum(len(r) for r in recs.values()),
                                "docket_cases_with_meta": len(metas)}),
            "cells": cells, "paired_differences": diffs}


def write(exp: str, obj: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / f"{exp}.json"
    p.write_text(json.dumps(obj, indent=1))
    return p


SPLITS: tuple[str, ...] = ("test",)  # the paper's numbers come from the test split only; --split dev for tuning views


def _frontier_subset(metas: dict) -> dict:
    """Frontier court and debate are reported on the fixed subset (analysis plan, note of 09:37 UTC)."""
    f = ROOT / "results" / "frontier_subset.txt"
    return metas if not f.exists() else {k: v for k, v in metas.items() if k in set(f.read_text().strip().split(","))}


def score_e1() -> dict:
    metas = runner.load_meta(SPLITS)
    out = score_experiment("e1", pairs_e1, metas=metas)
    if "test" in SPLITS:
        sub = score_experiment("e1", pairs_e1, metas=_frontier_subset(metas))
        for k in ("debate/frontier", "court/frontier"):
            if k in sub["cells"]:
                out["cells"][k] = {**sub["cells"][k], "subset": "results/frontier_subset.txt"}
    return out


def score_e2() -> dict:
    extra = {}
    c = TRIALS / "e1" / "court" / "small"
    if c.exists():
        extra["e1:court/small"] = c
    return score_experiment("e2", pairs_e2, extra, metas=runner.load_meta(SPLITS))


def score_e3() -> dict:
    return score_experiment("e3", pairs_e3, metas=runner.load_meta(SPLITS))


def main(argv: list[str] | None = None) -> None:
    global SPLITS
    names = list(argv if argv is not None else sys.argv[1:])
    if "--split" in names:
        i = names.index("--split")
        SPLITS = (names[i + 1],)
        del names[i:i + 2]
    names = names or ["e1", "e2", "e3", "e4", "e5"]
    for n in names:
        if n in ("e1", "e2", "e3"):
            obj = {"e1": score_e1, "e2": score_e2, "e3": score_e3}[n]()
        elif n == "e4":
            from . import e4
            obj = e4.score()
        elif n == "e5":
            from . import e5
            obj = e5.score()
        else:
            raise SystemExit(f"unknown experiment {n}")
        print("wrote", write(n, obj))


if __name__ == "__main__":
    main()
