"""E2: a small court with a strong defence. Court roles on the small model, the defence on a stronger one.
The all-small court on the same cases is E1's court/small (same cache, so a rerun costs nothing).
"""
from __future__ import annotations

import argparse

from . import runner
from .runner import (FRONTIER, LARGE_OPEN, SMALL, STAFFINGS, add_cli, load_split, run_cases, staffing_of, trial_dir,
                     write_meta)

EXP = "e2"
STAFF = {"defence_frontier": staffing_of(SMALL, FRONTIER, SMALL), "defence_groq": staffing_of(SMALL, LARGE_OPEN, SMALL)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    add_cli(ap)
    ap.add_argument("--groq-slice", type=int, default=0, help="also run the Groq defence on this many cases (0 = skip)")
    ap.add_argument("--defence", default="frontier", choices=["frontier", "groq"], help="the strong defence's model")
    a = ap.parse_args(argv)
    cases = runner.filter_ids(load_split(a.split, only=a.only, limit=a.limit), a.ids_file)
    write_meta(a.split, runner.list_split(a.split), sealed=not a.no_sealed)
    tag = f"defence_{a.defence}"
    run_cases(cases, "court", STAFF[tag], trial_dir(EXP, "court", tag), concurrency=a.concurrency, exp=EXP)
    run_cases(cases, "court", STAFFINGS["small"], trial_dir("e1", "court", "small"), concurrency=a.concurrency, exp=EXP)
    if a.groq_slice:
        sl = load_split(a.split, only=a.only, limit=a.groq_slice)
        run_cases(sl, "court", STAFF["defence_groq"], trial_dir(EXP, "court", "defence_groq"), exp=EXP)


if __name__ == "__main__":
    main()
