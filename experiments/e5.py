"""E5: cost and speed. Calls, tokens and seconds per trial from the records, and the gateway's backtest throughput.

    uv run python -m experiments.e5 --bench     # measure throughput (CPU only), then score
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

import numpy as np

from . import runner
from .runner import RESULTS, TRIALS, load_records

BENCH = RESULTS / "e5_gateway_bench.json"


def _specs(n: int):
    return [{"name": f"bench-{i}", "signal": f"rank(ts_mean(ret, {10 + i % 40}) - ts_mean(ret, {60 + i % 90}))", "params": {"i": i}}
            for i in range(n)]


def bench(n: int = 60, threads: tuple[int, ...] = (1, 4)) -> dict:
    """Backtests per second through the gateway service (in process, the same call the MCP tool makes)."""
    from experiments.e4 import make_service
    import tempfile
    out = {"n_backtests": n, "world": "t2-clean", "runs": []}
    with tempfile.TemporaryDirectory() as td:
        svc = make_service(Path(td), {"default": "local:qwen3-8b"})
        svc.session("bench-warm", "t2-clean")
        svc.run_backtest("bench-warm", _specs(1)[0])                     # builds and caches the world
        for nt in threads:
            specs = _specs(n)
            chunks = [specs[i::nt] for i in range(nt)]
            lat: list[float] = []

            def work(k, ch):
                sid = f"bench-{nt}-{k}"
                svc.session(sid, "t2-clean")
                for s in ch:
                    t = time.time()
                    svc.run_backtest(sid, s)
                    lat.append(time.time() - t)
            ts = [threading.Thread(target=work, args=(k, ch)) for k, ch in enumerate(chunks)]
            t0 = time.time()
            [t.start() for t in ts]
            [t.join() for t in ts]
            el = time.time() - t0
            out["runs"].append({"threads": nt, "seconds": round(el, 3), "backtests_per_second": round(n / el, 3),
                                "latency_ms_median": round(1000 * float(np.median(lat)), 1),
                                "latency_ms_p90": round(1000 * float(np.percentile(lat, 90)), 1)})
        svc.shutdown()
    BENCH.write_text(json.dumps(out, indent=1))
    return out


def score() -> dict:
    from .score import meta_block, mean_of
    cells = {}
    for p in sorted(TRIALS.glob("*/*/*")):
        if not p.is_dir():
            continue
        recs = list(load_records(p).values())
        if not recs:
            continue
        cells[f"{p.parent.parent.name}/{p.parent.name}/{p.name}"] = {
            "n": len(recs), **{k: mean_of([getattr(r, k) for r in recs]) for k in ("calls", "tokens_in", "tokens_out", "seconds")},
            "seconds_p90": {"value": round(float(np.percentile([r.seconds for r in recs], 90)), 3), "n": len(recs)},
            "total": {"calls": sum(r.calls for r in recs), "tokens_in": sum(r.tokens_in for r in recs),
                      "tokens_out": sum(r.tokens_out for r in recs), "seconds": round(sum(r.seconds for r in recs), 1)}}
    out = {"meta": meta_block("e5", ["results/trials/*/*/*"], {"cells": len(cells)}), "cells": cells,
           "gateway_throughput": json.loads(BENCH.read_text()) if BENCH.exists() else None}
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("-n", type=int, default=60)
    a = ap.parse_args(argv)
    if a.bench:
        print(json.dumps(bench(a.n), indent=1))
    from .score import write
    print("wrote", write("e5", score()))


if __name__ == "__main__":
    main()
