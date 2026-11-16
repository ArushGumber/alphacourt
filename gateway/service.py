"""The gateway service: sessions and research logs, the held submission, the background trial and the
enforcement of the ruling on a simulated broker (gateway/broker.py). Nothing here sends an order anywhere.

Other lanes are loaded lazily and can be replaced by arguments (tests pass fakes):
  world_loader(name) -> World        default: court.market.make_world, cached
  backtest_fn(spec, world) -> BacktestResult   default: court.engine.run_backtest (naive, research period)
  spec_hash_fn(spec) -> str          default: court.engine.spec_hash
  trial_fn(case, world, log, system=, staffing=, on_event=) -> TrialRecord   default: court.trial.run_trial
  pages_fn(url) -> str | None        default: alphaweb.pages if present
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from court.types import (BacktestResult, CaseFile, Claim, Event, ResearchLog, StrategySpec, Trial)

from . import guard
from .audit import sha12, write_audit
from .broker import Broker
from .store import Store

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
FINAL = ("ruled", "failed")


class ServiceError(Exception):
    """A problem to tell the caller in plain words."""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def load_config(path: Path | str | None = None) -> dict:
    return json.loads(Path(path or CONFIG_PATH).read_text())


def _dump(x: Any) -> Any:
    return x.model_dump(mode="json") if hasattr(x, "model_dump") else x


def _default_spec_hash(spec: StrategySpec) -> str:
    return hashlib.sha256(json.dumps(spec.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:12]


def _lazy_true_edge(spec, world):
    from court.engine import true_edge
    return true_edge(spec, world)


def _lazy_world_loader(config: dict) -> Callable[[str], Any]:
    def load(name: str):
        from court.market import make_world
        w = config["worlds"][name]
        return make_world(w["seed"], variant=w.get("variant"))
    return load


def _lazy_backtest(spec, world):
    from court.engine import run_backtest
    return run_backtest(spec, world, mode="naive", period="research")


def _lazy_spec_hash(spec):
    try:
        from court.engine import spec_hash
    except ImportError:
        return _default_spec_hash(spec)
    return spec_hash(spec)


def _lazy_trial(case, world, log, **kw):
    from court.trial import run_trial
    return run_trial(case, world, log, **kw)


def _lazy_pages(url: str) -> str | None:
    try:
        from alphaweb import pages
    except ImportError:
        return None
    for name in ("read_page", "get_page", "read", "get", "fetch"):
        fn = getattr(pages, name, None)
        if callable(fn):
            out = fn(url)
            return None if out is None else (out if isinstance(out, str) else str(getattr(out, "text", out)))
    table = getattr(pages, "PAGES", None)
    if isinstance(table, dict) and url in table:
        v = table[url]
        return v if isinstance(v, str) else str(v.get("text", v)) if isinstance(v, dict) else str(v)
    return None


def log_summary(log: ResearchLog, spec_hash: str, my_metrics: Any = None) -> dict:
    """What the court is told about the research: counts, the grid tried, and where the spec ranks."""
    best: dict[str, float] = {}
    grid: dict[str, set] = {}
    for t in log.trials:
        best[t.spec_hash] = max(best.get(t.spec_hash, float("-inf")), t.metrics.sharpe)
        for k, v in t.spec.params.items():
            grid.setdefault(k, set()).add(v)
    mine = best.get(spec_hash)
    if mine is None and my_metrics is not None:
        mine = my_metrics.sharpe
    rank = None
    if mine is not None:
        others = [s for h, s in best.items() if h != spec_hash]
        rank = 1 + sum(1 for s in others if s > mine)
    return {
        "n_trials": len(log.trials),
        "n_distinct_specs": len(best),
        "best_of": rank,
        "grid": {k: sorted(v, key=lambda x: (isinstance(x, str), x)) for k, v in sorted(grid.items())},
        "is_best": rank == 1 if rank is not None else False,
    }


class GatewayService:
    def __init__(self, store: Store | None = None, config: dict | None = None, *,
                 world_loader=None, backtest_fn=None, spec_hash_fn=None, trial_fn=None, pages_fn=None,
                 broker: Broker | None = None, prompt_version: str | None = None):
        self.config = config or load_config()
        self.store = store or Store()
        self._world_loader = world_loader or _lazy_world_loader(self.config)
        self._backtest = backtest_fn or _lazy_backtest
        self._spec_hash = spec_hash_fn or _lazy_spec_hash
        self._trial = trial_fn or _lazy_trial
        self._pages = pages_fn or _lazy_pages
        self._true_edge = _lazy_true_edge
        self._truth_cache: dict[str, dict] = {}
        self.broker = broker or Broker()
        self._prompt_version = prompt_version
        self._worlds: dict[str, Any] = {}
        self._world_hashes: dict[str, str] = {}
        self._world_lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._events: dict[str, list[dict]] = {}
        self._cases: dict[str, dict] = {}
        self._pending = 0
        n = int(self.config.get("max_concurrent_trials", 2))
        self._max_pending = n + int(self.config.get("queue_max", 12))
        self._pool = ThreadPoolExecutor(max_workers=n, thread_name_prefix="trial")
        self._mark_interrupted()

    # ------------------------------------------------------------------ worlds and sessions

    @property
    def prompt_version(self) -> str:
        if self._prompt_version:
            return self._prompt_version
        try:
            from court.roles import PROMPT_VERSION
            return str(PROMPT_VERSION)
        except Exception:
            return "unavailable"

    def worlds(self) -> list[dict]:
        return [{"name": k, "seed": v["seed"], "description": v.get("description", ""),
                 "default": k == self.config.get("default_world", "demo")} for k, v in self.config["worlds"].items()
                if not v.get("hidden")]

    def world(self, name: str):
        if name not in self.config["worlds"]:
            raise ServiceError(f"No such world '{name}'. Worlds: {', '.join(self.config['worlds'])}.")
        with self._world_lock:
            if name not in self._worlds:
                self._worlds[name] = self._world_loader(name)
            return self._worlds[name]

    def world_hash(self, name: str) -> str:
        w = self.world(name)
        if name not in self._world_hashes:
            h = hashlib.sha256()
            h.update(json.dumps([getattr(w, "world_id", name), getattr(w, "seed", None), getattr(w, "T", None),
                                 getattr(w, "N", None), getattr(w, "params", None)], sort_keys=True,
                                default=str).encode())
            close = getattr(w, "fields", {}).get("close")
            if close is not None and hasattr(close, "tobytes"):
                h.update(close.tobytes())
            self._world_hashes[name] = h.hexdigest()[:12]
        return self._world_hashes[name]

    def session(self, session_id: str, world: str | None = None, agent: str | None = None) -> dict:
        """The session for an id. The world is chosen on the first call that names one and then fixed."""
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                saved = self.store.read("logs", session_id)
                if saved:
                    log = ResearchLog.model_validate(saved["log"])
                    s = {"id": session_id, "world": saved.get("world"), "log": log}
                else:
                    s = {"id": session_id, "world": None, "log": ResearchLog(session_id=session_id)}
                self._sessions[session_id] = s
            if world and s["world"] is None:
                self.world_name_check(world)
                s["world"] = world
            if agent and s["log"].agent == "unknown":
                s["log"].agent = agent[:80]
            return s

    def world_name_check(self, name: str) -> None:
        if name not in self.config["worlds"]:
            raise ServiceError(f"No such world '{name}'. Worlds: {', '.join(self.config['worlds'])}.")

    def _bound(self, session_id: str, world: str | None = None) -> tuple[dict, Any]:
        s = self.session(session_id, world)
        if s["world"] is None:
            s["world"] = self.config.get("default_world", "demo")
        return s, self.world(s["world"])

    def _save_session(self, s: dict) -> None:
        self.store.write("logs", s["id"], {"world": s["world"], "log": s["log"].model_dump(mode="json")})

    # ------------------------------------------------------------------ research tools

    def list_fields(self, session_id: str, world: str | None = None) -> list[dict]:
        s, w = self._bound(session_id, world)
        return [{"name": n, "description": (w.field_info.get(n) or {}).get("description", ""),
                 "documented_availability": (w.field_info.get(n) or {}).get("documented_availability", "")}
                for n in w.fields]

    def field_info(self, session_id: str, name: str, world: str | None = None) -> dict:
        s, w = self._bound(session_id, world)
        if name not in w.field_info:
            raise ServiceError(f"No field called '{name}'. Call list_fields.")
        return {"name": name, **w.field_info[name]}

    def read_page(self, session_id: str, url: str, world: str | None = None) -> dict:
        s, _ = self._bound(session_id, world)
        if not isinstance(url, str) or not url or len(url) > 2048:
            raise ServiceError("url must be a short text.")
        text = self._pages(url)
        with self._lock:
            if url not in s["log"].pages_read:
                s["log"].pages_read.append(url)
            self._save_session(s)
        if text is None:
            return {"url": url, "found": False, "text": "no such page"}
        return {"url": url, "found": True, "text": text}

    def parse_spec(self, spec: Any) -> StrategySpec:
        if not isinstance(spec, dict):
            raise ServiceError("spec must be a JSON object.")
        msg = guard.check_lengths(spec)
        if msg:
            raise ServiceError(msg)
        try:
            return StrategySpec.model_validate(spec)
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(x) for x in first["loc"])
            raise ServiceError(f"Invalid strategy spec at '{where}': {first['msg']}.") from None

    def truth(self, spec: Any, world: str | None = None) -> dict:
        """True edge of a spec on sealed data (strict, lag >= 1, realistic costs). Cached by spec hash and world."""
        sp = self.parse_spec(spec)
        name = world or self.config.get("default_world", "demo")
        w = self.world(name)
        key = f"{name}:{self._spec_hash(sp)}"
        with self._lock:
            hit = self._truth_cache.get(key)
        if hit is None:
            hit = self._true_edge(sp, w)
            with self._lock:
                self._truth_cache[key] = hit
        return {"world": name, "spec_hash": key.split(":")[1], **hit}

    def _run(self, spec: StrategySpec, world) -> BacktestResult:
        try:
            return self._backtest(spec, world)
        except ServiceError:
            raise
        except ValueError as e:
            raise ServiceError(f"The signal could not be evaluated: {e}") from None

    def run_backtest(self, session_id: str, spec: Any, world: str | None = None) -> dict:
        """Naive research-period backtest, logged as a Trial. Returns the result and the trial's place in the log."""
        sp = self.parse_spec(spec)
        s, w = self._bound(session_id, world)
        res = self._run(sp, w)
        h = res.spec_hash or self._spec_hash(sp)
        with self._lock:
            s["log"].trials.append(Trial(t=time.time(), spec_hash=h, spec=sp, metrics=res.metrics))
            n = len(s["log"].trials)
            self._save_session(s)
        return {"result": res, "trial_number": n, "spec_hash": h, "world": s["world"]}

    # ------------------------------------------------------------------ cases

    def _mark_interrupted(self) -> None:
        for cid in self.store.keys("cases"):
            c = self.store.read("cases", cid)
            if c and c.get("status") not in FINAL:
                c["status"] = "failed"
                c["error"] = "The gateway restarted before the trial ended."
                self.store.write("cases", cid, c)

    def _emit(self, case_id: str, ev: Event | dict) -> None:
        d = _dump(ev)
        with self._lock:
            self._events.setdefault(case_id, []).append(d)
        self.store.append_event(case_id, d)

    def events_since(self, case_id: str, i: int) -> tuple[list[dict], bool]:
        """(events from index i, whether the case has finished). Past events replay from disk after a restart."""
        with self._lock:
            evs = self._events.get(case_id)
            meta = self._cases.get(case_id)
        if evs is None:
            evs = self.store.read_events(case_id)
            meta = meta or self.store.read("cases", case_id) or {}
        else:
            evs = list(evs)
        return evs[i:], (meta or {}).get("status") in FINAL

    def get_case(self, case_id: str) -> dict | None:
        with self._lock:
            c = self._cases.get(case_id)
            if c is not None:
                return json.loads(json.dumps(c, default=str))
        return self.store.read("cases", case_id)

    def list_cases(self) -> list[dict]:
        out = []
        for cid in self.store.keys("cases"):
            c = self.get_case(cid)
            if c:
                out.append({"case_id": cid, "status": c["status"], "source": c.get("source"),
                            "system": c.get("system"), "name": c["case"]["spec"]["name"],
                            "ruling": ((c.get("verdict") or {}).get("ruling")), "created": c.get("created")})
        return out

    def _save_case(self, c: dict) -> None:
        with self._lock:
            self._cases[c["case"]["case_id"]] = c
        self.store.write("cases", c["case"]["case_id"], c)

    def submit_strategy(self, session_id: str, spec: Any, claim: Any, requested_capital: float = 1_000_000.0,
                        world: str | None = None, ip: str = "local") -> dict:
        if not isinstance(claim, dict):
            raise ServiceError("claim must be a JSON object with at least 'sharpe'.")
        msg = guard.check_lengths(spec if isinstance(spec, dict) else {}, claim)
        if msg:
            raise ServiceError(msg)
        try:
            cl = Claim.model_validate(claim)
        except ValidationError as e:
            raise ServiceError(f"Invalid claim: {e.errors()[0]['msg']} at '{e.errors()[0]['loc']}'.") from None
        try:
            cap = float(requested_capital)
        except (TypeError, ValueError):
            raise ServiceError("requested_capital must be a number.") from None
        if not 0 < cap <= 1e10:
            raise ServiceError("requested_capital must be between 0 and 10 billion.")
        sp = self.parse_spec(spec)
        s, w = self._bound(session_id, world)
        h = self._spec_hash(sp)
        my = None
        if all(t.spec_hash != h for t in s["log"].trials):
            try:
                my = self._run(sp, w).metrics        # not logged: only to rank the spec among the trials
            except ServiceError:
                my = None
        with self._lock:
            summary = log_summary(s["log"], h, my)
            s["log"].submitted_spec_hash = h
            self._save_session(s)
            case_id = self.store.next_id("AC")
        case = CaseFile(case_id=case_id, world_id=getattr(w, "world_id", s["world"]), spec=sp, claim=cl,
                        requested_capital=cap, log_summary=summary, pages_read=list(s["log"].pages_read))
        meta = self._new_meta(case, source="submission", session_id=session_id, world_name=s["world"],
                              system=self.config.get("system", "court"),
                              staffing=dict(self.config.get("staffing", {})), ip=ip)
        self._start(meta, s["log"])
        return {"case_id": case_id, "status": "held", "watch_url": f"/#/court/{case_id}"}

    def _new_meta(self, case: CaseFile, *, source: str, session_id: str | None, world_name: str, system: str,
                  staffing: dict, ip: str) -> dict:
        return {"case": case.model_dump(mode="json"), "status": "held", "source": source,
                "session_id": session_id, "world": world_name, "system": system, "staffing": staffing,
                "created": time.time(), "started": None, "ended": None, "spec_hash": self._spec_hash(case.spec),
                "world_hash": self.world_hash(world_name), "verdict": None, "broker_action": None, "error": None}

    def _start(self, meta: dict, log: ResearchLog | None) -> None:
        with self._lock:
            if self._pending >= self._max_pending:
                raise ServiceError("The court is busy: too many trials are waiting. Try again shortly.", 503)
            self._pending += 1
        case_id = meta["case"]["case_id"]
        self._save_case(meta)
        self._emit(case_id, Event(t=time.time(), role="gateway", kind="case",
                                  data={"case_id": case_id, "status": "held", "log_summary": meta["case"]["log_summary"],
                                        "spec_hash": meta["spec_hash"]}))
        self._pool.submit(self._work, case_id, log)

    def _work(self, case_id: str, log: ResearchLog | None) -> None:
        meta = self.get_case(case_id)
        t0 = time.time()
        record, error, action = None, None, None
        try:
            meta["status"], meta["started"] = "in trial", t0
            self._save_case(meta)
            self._emit(case_id, Event(t=t0, role="gateway", kind="note", data={"status": "in trial"}))
            case = CaseFile.model_validate(meta["case"])
            world = self.world(meta["world"])
            streamed = []

            def on_event(ev):
                streamed.append(1)
                self._emit(case_id, ev)

            rec = self._trial(case, world, log, system=meta["system"], staffing=meta["staffing"], on_event=on_event)
            record = _dump(rec)
            if not streamed:
                for ev in record.get("events", []):
                    self._emit(case_id, ev)
            verdict = record["verdict"]
            meta["verdict"] = verdict
            if meta["source"] == "submission":
                action = self.broker.enforce(meta["session_id"] or "none", case_id, verdict["ruling"],
                                             case.requested_capital, verdict.get("capital_allowed", 0.0),
                                             meta["spec_hash"])
                self._emit(case_id, Event(t=time.time(), role="gateway", kind="note",
                                          data={"broker_action": action}))
            meta["broker_action"] = action
            meta["status"] = "ruled"
        except Exception as e:  # a failed trial books nothing
            error = f"{type(e).__name__}: {e}"
            meta["status"], meta["error"] = "failed", error
            self._emit(case_id, Event(t=time.time(), role="gateway", kind="error", data={"error": error}))
        finally:
            meta["ended"] = time.time()
            if record is not None:
                self.store.write("records", case_id, record)
            try:
                write_audit(self.store, case=meta["case"], record=record, broker_action=action,
                            status=meta["status"], staffing=meta["staffing"], system=meta["system"],
                            spec_hash=meta["spec_hash"], world_hash=meta["world_hash"],
                            prompt_version=self.prompt_version,
                            timings={"submitted": meta["created"], "trial_started": meta["started"],
                                     "ended": meta["ended"], "trial_seconds": (record or {}).get("seconds"),
                                     "queue_seconds": (meta["started"] or meta["ended"]) - meta["created"]},
                            error=error)
            finally:
                self._save_case(meta)       # the status turns final only after the audit file exists
                with self._lock:
                    self._pending -= 1

    def get_verdict(self, case_id: str) -> dict:
        c = self.get_case(case_id)
        if c is None:
            raise ServiceError(f"No case {case_id}.", 404)
        out: dict[str, Any] = {"case_id": case_id, "status": c["status"]}
        if c["status"] == "ruled":
            rec = self.store.read("records", case_id) or {}
            out["verdict"] = c["verdict"]
            out["exhibits"] = [{"id": e["id"], "test": e["test"], "summary": e["summary"], "hint": e["hint"]}
                               for e in rec.get("exhibits", [])]
            out["broker_action"] = c.get("broker_action")
        elif c["status"] == "failed":
            out["error"] = c.get("error")
        return out

    def case_detail(self, case_id: str) -> dict:
        c = self.get_case(case_id)
        if c is None:
            raise ServiceError(f"No case {case_id}.", 404)
        c = dict(c)
        c["record"] = self.store.read("records", case_id)
        c["audit"] = self.store.read("audit", case_id)
        return c

    # ------------------------------------------------------------------ site trials

    def run_site_trial(self, req: dict, ip: str = "local") -> dict:
        """Replay a stored case, or try a docket case or a posted case file, with a chosen system and staffing."""
        system = req.get("system") or self.config.get("system", "court")
        if system not in self.config.get("systems", []):
            raise ServiceError(f"system must be one of {', '.join(self.config.get('systems', []))}.")
        staffing = dict(self.config.get("staffing", {}))
        given = req.get("staffing") or {}
        if not isinstance(given, dict):
            raise ServiceError("staffing must be an object of role -> model id.")
        allowed = set(self.config.get("allowed_models", []))
        for role, model in given.items():
            if not isinstance(role, str) or len(role) > 30 or model not in allowed:
                raise ServiceError(f"Model '{model}' is not available here. Choose from: {', '.join(sorted(allowed))}.")
            staffing[role] = model
        if req.get("case_id"):
            old = self.get_case(str(req["case_id"]))
            if old is None:
                raise ServiceError(f"No case {req['case_id']}.", 404)
            cdict, world_name = dict(old["case"]), old["world"]
        elif req.get("docket_id"):
            cdict, world_name, log = self._docket_case(str(req["docket_id"]))
        elif isinstance(req.get("case"), dict):
            cdict = dict(req["case"])
            world_name = req.get("world") or self.config.get("default_world", "demo")
            msg = guard.check_lengths(cdict.get("spec") or {}, cdict.get("claim") or {})
            if msg:
                raise ServiceError(msg)
        else:
            raise ServiceError("Give case_id (replay), docket_id, or case (a case file).")
        self.world_name_check(world_name)
        cdict["case_id"] = self.store.next_id("TR")
        log = locals().get("log")
        try:
            case = CaseFile.model_validate(cdict)
        except ValidationError as e:
            raise ServiceError(f"Invalid case file: {e.errors()[0]['msg']} at '{e.errors()[0]['loc']}'.") from None
        meta = self._new_meta(case, source="trial", session_id=None, world_name=world_name, system=system,
                              staffing=staffing, ip=ip)
        self._start(meta, log)
        return {"case_id": case.case_id, "status": "held", "watch_url": f"/#/court/{case.case_id}"}

    def _docket_case(self, docket_id: str) -> tuple[dict, str, Any]:
        try:
            import docket
        except ImportError:
            raise ServiceError("The docket is not available on this server yet.", 501) from None
        fn = getattr(docket, "get_case", None) or getattr(docket, "load_case", None)
        if fn is None:
            raise ServiceError("The docket is not available on this server yet.", 501)
        dc = fn(docket_id)
        if dc is None:
            raise ServiceError(f"No docket case {docket_id}.", 404)
        case = getattr(dc, "case", dc)
        cd = _dump(case)
        # Register the docket case's own world (with its variant) and pass its research log to the court.
        world_fn, log_fn = getattr(docket, "world_for", None), getattr(docket, "log_for", None)
        name = "docket:" + str(cd.get("world_id") or docket_id)
        log = None
        if world_fn is not None:
            with self._world_lock:
                if name not in self._worlds:
                    self._worlds[name] = world_fn(dc)
            self.config["worlds"].setdefault(name, {"seed": cd.get("seed"), "variant": cd.get("variant"),
                                                    "description": "a docket case's data room", "hidden": True})
        if log_fn is not None:
            try:
                log = log_fn(dc)
            except Exception:
                log = None
        keep = {k: cd[k] for k in ("case_id", "world_id", "spec", "claim", "requested_capital", "log_summary", "pages_read") if k in cd}
        return keep, name, log

    # ------------------------------------------------------------------ misc

    def health(self) -> dict:
        with self._lock:
            return {"ok": True, "pending_trials": self._pending, "sessions": len(self._sessions),
                    "worlds_loaded": sorted(self._worlds), "system": self.config.get("system"),
                    "prompt_version": self.prompt_version}

    def wait_idle(self, timeout: float = 30.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                if self._pending == 0:
                    return True
            time.sleep(0.02)
        return False

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
