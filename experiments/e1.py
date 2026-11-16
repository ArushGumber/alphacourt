"""E1: what the exhibit rule buys. Five systems, three staffings, one docket.

    uv run python -m experiments.e1 --split dev --limit 4 --systems battery,none
"""
from __future__ import annotations

import argparse

from . import runner
from .runner import STAFFINGS, add_cli, load_split, pick, run_cases, trial_dir, write_meta

EXP = "e1"
SYSTEMS = ["none", "battery", "single", "debate", "court", "court_norule", "single_exhibits", "single_exhibits_rule"]
LLM_SYSTEMS = ["single", "debate", "court"]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    add_cli(ap)
    a = ap.parse_args(argv)
    systems, staffings = pick(a.systems, SYSTEMS), pick(a.staffings, list(STAFFINGS))
    cases = runner.filter_ids(load_split(a.split, only=a.only, limit=a.limit), a.ids_file)
    write_meta(a.split, runner.list_split(a.split), sealed=not a.no_sealed)
    runner.log(EXP, f"E1 on {a.split}: {len(cases)} cases, systems {systems}, staffings {staffings}")
    for system in systems:
        if system in ("none", "battery"):
            run_cases(cases, system, {}, trial_dir(EXP, system, "cpu"), concurrency=a.concurrency, exp=EXP)
        else:
            for tag in staffings:
                run_cases(cases, system, STAFFINGS[tag], trial_dir(EXP, system, tag), concurrency=a.concurrency, exp=EXP)


if __name__ == "__main__":
    main()
