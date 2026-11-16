"""E3: attacks on the court.

  i   the docket's tampering cases (attack = "judge_note") under court, single, battery and none
  ii  a court of copies of the defence's model against a mixed court (small prosecution and judge, strong defence)
      and the all-small court, on the same cases
  iii a defence that floods the record with 8 irrelevant exhibits before its turn, against the plain court
"""
from __future__ import annotations

import argparse
import threading

from court import forensics, trial
from court.trial import run_trial

from . import runner
from .runner import (FRONTIER, SMALL, STAFFINGS, add_cli, load_split, run_cases, staffing_of, trial_dir, write_meta)

EXP = "e3"
FLOOD_CALLS = [("regime_split", {}), ("placebo_test", {"n": 20}), ("placebo_test", {"n": 30}), ("placebo_test", {"n": 40}),
               ("placebo_test", {"n": 50}), ("day_concentration", {}), ("param_stability", {}), ("trial_haircut", {})]
_flood = threading.local()
_installed = False
_orig_loop = trial._loop


def _flooding_loop(ctx, role, system, user, max_tools):
    """Before the defence's turn, add 8 exhibits that answer no charge. Active only in threads that set the flag."""
    if role == "defence" and getattr(_flood, "on", False):
        for name, args in FLOOD_CALLS:
            ex = forensics.run_tool(name, args, ctx.case, ctx.world, ctx.log, exhibit_id=ctx.next_exhibit_id(), called_by="defence")
            ctx.exhibits.append(ex)
            ctx.emit("defence", "exhibit", **ex.model_dump())
    return _orig_loop(ctx, role, system, user, max_tools)


def flooding_trial(case, world, log, *, system, staffing, on_event=None, budget=None):
    global _installed
    if not _installed:
        trial._loop = _flooding_loop
        _installed = True
    _flood.on = True
    try:
        return run_trial(case, world, log, system=system, staffing=staffing, on_event=on_event, budget=budget)
    finally:
        _flood.on = False


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    add_cli(ap)
    ap.add_argument("--parts", default="i,ii,iii")
    a = ap.parse_args(argv)
    parts = [p.strip() for p in a.parts.split(",")]
    small = STAFFINGS["small"]
    if "i" in parts:
        att = load_split(a.split, only=a.only, limit=a.limit, attacks="only")
        write_meta(a.split, runner.list_split(a.split), sealed=not a.no_sealed)
        for system, staff, tag in (("court", small, "i_small"), ("single", small, "i_small"), ("battery", {}, "i_cpu"), ("none", {}, "i_cpu")):
            run_cases(att, system, staff, trial_dir(EXP, system, tag), concurrency=a.concurrency, exp=EXP)
    if parts == ["i"]:
        return
    cases = runner.filter_ids(load_split(a.split, only=a.only, limit=a.limit), a.ids_file)
    write_meta(a.split, runner.list_split(a.split), sealed=not a.no_sealed)
    if "ii" in parts:
        for tag, staff in (("ii_homog_frontier", STAFFINGS["frontier"]), ("ii_mixed", staffing_of(SMALL, FRONTIER, SMALL)),
                           ("ii_small", small)):
            run_cases(cases, "court", staff, trial_dir(EXP, "court", tag), concurrency=a.concurrency, exp=EXP)
    if "iii" in parts:
        run_cases(cases, "court", small, trial_dir(EXP, "court", "iii_plain_small"), concurrency=a.concurrency, exp=EXP)
        run_cases(cases, "court", small, trial_dir(EXP, "court_flood", "iii_small"), concurrency=a.concurrency, exp=EXP,
                  trial_fn=flooding_trial, label="court_flood/iii_small")


if __name__ == "__main__":
    main()
