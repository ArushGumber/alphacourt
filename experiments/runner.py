"""Experiment runner: runs `court.trial.run_trial` over docket cases, resumable, one JSON file per trial.

    results/trials/{exp}/{system}/{staffing_tag}/{case_id}.json      a TrialRecord
    results/trials/{exp}/{system}/{staffing_tag}/{case_id}.failed.json   a failure (retried on the next run)
    logs/exp_{exp}.log                                                progress with an estimated time to finish

The docket is reached through `docket.build_docket / get_case / world_for / log_for`. Cases may be
pydantic models or dicts; `norm()` reads either.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from court.types import CaseFile, Claim, ResearchLog, StrategySpec, TrialRecord

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
TRIALS = RESULTS / "trials"
LOGS = ROOT / "logs"
META_DIR = RESULTS / "docket_meta"

# Staffings fixed in the analysis plan's freeze note (from an initial probe of the available models).
SMALL, MID, FRONTIER = "local:qwen3-8b", "local:gemma3-12b", "google:gemini-3.1-flash-lite"
FRONTIER_SLICE = "google:gemini-3.5-flash"  # daily quota is small; used on a slice after the reset
LARGE_OPEN = "groq:openai/gpt-oss-120b"
STAFFINGS = {t: {"default": m, "prosecution": m, "defence": m, "judge": m}
             for t, m in (("small", SMALL), ("mid", MID), ("frontier", FRONTIER))}
CPU_SYSTEMS = ("battery", "none")


def staffing_of(prosecution: str, defence: str, judge: str) -> dict[str, str]:
    return {"default": judge, "prosecution": prosecution, "defence": defence, "judge": judge}


# ---------------------------------------------------------------- docket adapter

def _get(o: Any, key: str, default: Any = None) -> Any:
    if o is None:
        return default
    if isinstance(o, dict):
        return o.get(key, default)
    return getattr(o, key, default)


def _plain(o: Any) -> Any:
    return o.model_dump(mode="json") if hasattr(o, "model_dump") else o


def _docket():
    import docket
    return docket


@dataclass
class Meta:
    """What the scorer needs to know about a docket case."""
    case_id: str
    role: str                     # guilty | innocent | unusual
    sin: str | None
    level: str
    family: str
    twin_id: str | None
    split: str = ""
    claim_sharpe: float | None = None
    true_sharpe: float | None = None
    requested_capital: float = 1_000_000.0
    attack: str | None = None
    sealed_return: float | None = None     # cumulative sealed-period return (fraction of gross) under true-edge conditions
    name: str = ""

    @property
    def guilty(self) -> bool:
        return self.role.startswith("guilty")

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _sin_str(s: Any) -> str | None:
    if isinstance(s, (list, tuple)):
        s = s[0] if s else None
    return str(s) if s else None


def norm(raw: Any) -> Meta:
    truth = _get(raw, "truth") or {}
    claim = _get(raw, "claim") or {}
    spec = _get(raw, "spec") or {}
    ts = _get(truth, "sharpe", _get(truth, "true_sharpe", _get(truth, "true_edge")))
    if isinstance(ts, dict):
        ts = ts.get("sharpe")
    return Meta(case_id=str(_get(raw, "case_id")), role=str(_get(raw, "role", "innocent")), sin=_sin_str(_get(raw, "sin")),
                level=str(_get(raw, "level", "")), family=str(_get(raw, "family", "")),
                twin_id=_get(raw, "twin_id"), split=str(_get(raw, "split", "")),
                claim_sharpe=_get(claim, "sharpe"), true_sharpe=ts,
                requested_capital=float(_get(raw, "requested_capital", 1_000_000.0) or 1_000_000.0),
                attack=_get(raw, "attack"), name=str(_get(spec, "name", "")))


def list_split(split: str) -> list[Any]:
    """The built docket of a split, read from docket/cases/{split}/*.json (build it first with docket.build_docket)."""
    from docket.build import CASES
    d = Path(CASES) / split
    out = [_docket().load_case(p.stem) for p in sorted(d.glob("*.json"))] if d.exists() else []
    if not out:
        raise SystemExit(f"no docket cases in {d}; build the docket first (docket.build_docket('{split}'))")
    return out


def load_split(split: str, *, only: str | None = None, limit: int | None = None, attacks: str = "exclude") -> list[Any]:
    """Raw docket cases of a split. `only` is "sin=lookahead,level=L3"; `limit` keeps whole twin pairs, in id order.
    attacks: "exclude" (E1 to E2), "only" (E3 i), "include"."""
    cases = list_split(split)
    if attacks == "exclude":
        cases = [c for c in cases if not _get(c, "attack")]
    elif attacks == "only":
        cases = [c for c in cases if _get(c, "attack")]
    if only:
        for kv in only.split(","):
            k, _, v = kv.partition("=")
            cases = [c for c in cases if str(_get(c, k.strip())) == v.strip()]
    cases.sort(key=lambda c: str(_get(c, "case_id")))
    if limit is not None:
        keep: list[Any] = []
        seen: set[str] = set()
        by_id = {str(_get(c, "case_id")): c for c in cases}
        for c in cases:
            cid = str(_get(c, "case_id"))
            if cid in seen:
                continue
            group = [cid] + ([str(_get(c, "twin_id"))] if _get(c, "twin_id") and str(_get(c, "twin_id")) in by_id else [])
            if len(keep) + len(group) > limit and keep:
                break
            for g in group:
                seen.add(g)
                keep.append(by_id[g])
        cases = keep
    return cases


_world_lock = threading.Lock()
_world_memo: dict[str, Any] = {}


def default_world(raw: Any):
    d = _docket()
    with _world_lock:
        key = str(_get(raw, "world_id") or _get(raw, "case_id"))
        if key not in _world_memo:
            if len(_world_memo) >= 6:                       # worlds are large; keep a few
                _world_memo.pop(next(iter(_world_memo)))
            _world_memo[key] = d.world_for(raw)
        return _world_memo[key]


def default_log(raw: Any) -> ResearchLog | None:
    return _docket().log_for(raw)


def case_file(raw: Any, world: Any, log: ResearchLog | None) -> CaseFile:
    """The case the court sees. Uses a case file from the docket if it carries one, else builds it like the clerk."""
    cf_ = _get(raw, "case_file")
    if cf_ is None and isinstance(getattr(raw, "case", None), dict):    # docket.DocketCase.case
        cf_ = raw.case
    if cf_ is not None:
        return cf_ if isinstance(cf_, CaseFile) else CaseFile.model_validate(_plain(cf_))
    from gateway.service import log_summary
    from court.engine import spec_hash
    spec = _get(raw, "spec")
    spec = spec if isinstance(spec, StrategySpec) else StrategySpec.model_validate(_plain(spec))
    claim = _get(raw, "claim")
    claim = claim if isinstance(claim, Claim) else Claim.model_validate(_plain(claim))
    summ = _get(raw, "log_summary") or (log_summary(log, spec_hash(spec)) if log is not None else {})
    return CaseFile(case_id=str(_get(raw, "case_id")), world_id=str(getattr(world, "world_id", _get(raw, "world_id", ""))),
                    spec=spec, claim=claim, requested_capital=float(_get(raw, "requested_capital", 1_000_000.0) or 1_000_000.0),
                    log_summary=dict(summ), pages_read=list(log.pages_read) if log is not None else [])


def sealed_return(raw: Any, world: Any) -> float:
    """Cumulative return on the sealed bars when the strategy is deployed honestly: strict data, lag >= 1, full
    universe, the world's real costs. A fraction of gross capital."""
    from court.engine import run_backtest
    spec = _get(raw, "spec")
    spec = spec if isinstance(spec, StrategySpec) else StrategySpec.model_validate(_plain(spec))
    s2 = spec.model_copy(update={"lag": max(spec.lag, 1)})
    r = run_backtest(s2, world, mode="strict", period="sealed", cost_bps=world.cost_bps_true, universe="all")
    return round(float(r.metrics.ann_return) * r.metrics.n_days / 252.0, 6)


def write_meta(split: str, cases: list[Any], *, sealed: bool = True, world_fn: Callable = default_world) -> Path:
    """Save the scorer's view of the docket to results/docket_meta/{split}.json (resumable: keeps earlier sealed values)."""
    META_DIR.mkdir(parents=True, exist_ok=True)
    p = META_DIR / f"{split}.json"
    old = {m["case_id"]: m for m in json.loads(p.read_text())} if p.exists() else {}
    out: dict[str, dict] = dict(old)
    for c in cases:
        m = norm(c)
        m.split = split
        prev = old.get(m.case_id, {})
        m.sealed_return = prev.get("sealed_return")
        if sealed and m.guilty and m.sealed_return is None:
            m.sealed_return = sealed_return(c, world_fn(c))
        out[m.case_id] = m.to_dict()
    p.write_text(json.dumps(list(out.values()), indent=1))
    return p


def load_meta(splits: tuple[str, ...] = ("dev", "test")) -> dict[str, Meta]:
    out: dict[str, Meta] = {}
    for s in splits:
        p = META_DIR / f"{s}.json"
        if p.exists():
            for d in json.loads(p.read_text()):
                out[d["case_id"]] = Meta(**d)
    return out


# ---------------------------------------------------------------- logging

_log_lock = threading.Lock()


def log(exp: str, msg: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    with _log_lock, (LOGS / f"exp_{exp}.log").open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def fmt_eta(s: float) -> str:
    s = int(s)
    return f"{s // 3600}h{(s % 3600) // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


def concurrency_for(staffing: dict[str, str]) -> int:
    models = set(staffing.values())
    if any(m.startswith("groq:") for m in models):
        return 2
    if any(m.startswith("google:") for m in models):
        return 12
    return 16


# ---------------------------------------------------------------- the runner

def _save(path: Path, text: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _one(raw: Any, system: str, staffing: dict, trial_fn: Callable | None, world_fn: Callable | None,
         log_fn: Callable | None) -> str:
    """Run one case, return the record as JSON text. Module-level so a process pool can call it."""
    if trial_fn is None:
        from court.trial import run_trial as trial_fn  # noqa: PLW0127
    world = (world_fn or default_world)(raw)
    lg = (log_fn or default_log)(raw)
    case = case_file(raw, world, lg)
    rec = trial_fn(case, world, lg, system=system, staffing=staffing)
    return rec.model_dump_json()


def run_cases(cases: list[Any], system: str, staffing: dict[str, str], out_dir: Path | str, *, concurrency: int | None = None,
              exp: str = "adhoc", trial_fn: Callable | None = None, world_fn: Callable | None = None,
              log_fn: Callable | None = None, label: str | None = None) -> dict:
    """Run `system` over `cases`. Existing records are skipped. Failures are written beside the records and retried
    next time. `concurrency` defaults to what the staffing allows (local 16, Google 12, Groq 2); CPU systems use a
    process pool. Returns counts."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    label = label or f"{system}/{out.name}"
    todo = []
    skipped = 0
    for c in cases:
        cid = str(_get(c, "case_id"))
        if (out / f"{cid}.json").exists():
            skipped += 1
        else:
            todo.append((cid, c))
    total = len(todo)
    log(exp, f"[{label}] {len(cases)} cases, {skipped} done already, {total} to run")
    if not total:
        return {"label": label, "total": len(cases), "skipped": skipped, "ran": 0, "failed": 0, "seconds": 0.0}
    cpu = system in CPU_SYSTEMS and trial_fn is None and world_fn is None and log_fn is None and system != "none"
    n = concurrency or (min(8, os.cpu_count() or 2) if cpu else concurrency_for(staffing))
    t0 = time.time()
    done = failed = 0
    Pool = cf.ProcessPoolExecutor if cpu else cf.ThreadPoolExecutor
    with Pool(max_workers=n) as pool:
        futs = {pool.submit(_one, c, system, staffing, trial_fn, world_fn, log_fn): cid for cid, c in todo}
        for fut in cf.as_completed(futs):
            cid = futs[fut]
            try:
                _save(out / f"{cid}.json", fut.result())
                (out / f"{cid}.failed.json").unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001 - recorded, run goes on
                failed += 1
                _save(out / f"{cid}.failed.json", json.dumps({"case_id": cid, "error": f"{type(e).__name__}: {str(e)[:500]}",
                                                              "trace": traceback.format_exc()[-1500:], "t": time.time()}))
            done += 1
            el = time.time() - t0
            if done % max(1, min(10, total // 20 or 1)) == 0 or done == total:
                eta = el / done * (total - done)
                log(exp, f"[{label}] {done}/{total} ({failed} failed) {el / done:.1f}s/case, eta {fmt_eta(eta)}")
    secs = round(time.time() - t0, 1)
    log(exp, f"[{label}] finished: {done - failed} ran, {failed} failed, {fmt_eta(secs)}")
    return {"label": label, "total": len(cases), "skipped": skipped, "ran": done - failed, "failed": failed, "seconds": secs}


def trial_dir(exp: str, system: str, tag: str) -> Path:
    return TRIALS / exp / system / tag


def load_records(d: Path | str) -> dict[str, TrialRecord]:
    out = {}
    for p in sorted(Path(d).glob("*.json")):
        if p.name.endswith(".failed.json"):
            continue
        out[p.stem] = TrialRecord.model_validate_json(p.read_text())
    return out


def count_failed(d: Path | str) -> int:
    return len(list(Path(d).glob("*.failed.json")))


# ---------------------------------------------------------------- shared CLI

def add_cli(ap) -> None:
    ap.add_argument("--split", default="test", choices=["dev", "test"])
    ap.add_argument("--only", help='filter, e.g. "sin=lookahead,level=L3"')
    ap.add_argument("--limit", type=int, help="keep about this many cases (whole twin pairs)")
    ap.add_argument("--systems", help="comma list, subset of the experiment's systems")
    ap.add_argument("--staffings", help="comma list, subset of the experiment's staffings")
    ap.add_argument("--concurrency", type=int)
    ap.add_argument("--no-sealed", action="store_true", help="skip the sealed-period returns when writing docket meta")
    ap.add_argument("--ids-file", help="keep only the case ids listed in this file (comma or newline separated)")


def pick(arg: str | None, allowed: list[str]) -> list[str]:
    if not arg:
        return allowed
    want = [a.strip() for a in arg.split(",")]
    bad = [w for w in want if w not in allowed]
    if bad:
        raise SystemExit(f"unknown {bad}; choose from {allowed}")
    return want


def filter_ids(cases: list[Any], ids_file: str | None) -> list[Any]:
    if not ids_file:
        return cases
    keep = {x.strip() for x in Path(ids_file).read_text().replace(",", "\n").split() if x.strip()}
    return [c for c in cases if str(_get(c, "case_id")) in keep]
