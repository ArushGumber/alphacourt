"""Fill the paper's result slots from results/e1.json .. e5.json.

    python3 scripts/make_paper.py [--build]

Reads every paper/*.tex.in and writes the same name without `.in`. A slot is {{exp.path[:format]}}:

    {{e1.court.small.guilty_stopped}}          cell "court/small" of results/e1.json, field guilty_stopped  -> "41 of 48"
    {{e1.court.small.by_level.L3.guilty_stopped:pct}}                                                       -> "85\%"
    {{e1.diff.court.small.vs.battery.cpu.guilty_stopped}}      paired difference (bootstrap over twin pairs) -> "+21 points"
    {{e1.diff.court.small.vs.battery.cpu.guilty_stopped:ci}}                                                -> "10 to 33 points"
    {{e4.google:gemini-3.5-flash.pressure.inflation}}          cell "google:gemini-3.5-flash|pressure" (a mean)
    {{e5.gateway_throughput.runs.1.backtests_per_second}}      a path from the top of the file

A cell key is matched with "/" and "|" written as ".". Formats: pct, k, j, slash (j/k), ci, rate, mean, n.
A rate {"j","k","rate","lo","hi"} prints "j of k" by default. A mean {"mean","n"} prints the mean.
Every output line that holds a slot gets " % source: results/eN.json -> <path>" (the path inside the file).
An unresolved slot prints \\textbf{[?]} and says so in its source comment, so the PDF builds and the gap is visible.
Lines that start with %% are notes to the authors and are dropped. Python 3 standard library only.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import os
PAPER, RESULTS = ROOT / "paper", Path(os.environ.get("ALPHACOURT_RESULTS", ROOT / "results"))  # override only to test the filler on fixtures
SLOT = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
FORMATS = {"pct", "k", "j", "slash", "ci", "rate", "mean", "n", "miss"}
MISSING = r"\textbf{[?]}"
_cache: dict[str, dict | None] = {}


def load(exp: str) -> dict | None:
    if exp not in _cache:
        p = RESULTS / f"{exp}.json"
        try:
            _cache[exp] = json.loads(p.read_text())
        except (OSError, ValueError):
            _cache[exp] = None
    return _cache[exp]


def canon(key: str) -> str:
    return key.replace("/", ".").replace("|", ".")


def descend(obj, tokens: list[str]):
    for t in tokens:
        if isinstance(obj, list) and t.lstrip("-").isdigit() and -len(obj) <= int(t) < len(obj):
            obj = obj[int(t)]
        elif isinstance(obj, dict) and t in obj:
            obj = obj[t]
        else:
            return None
    return obj


EXPECTED_N = {"court.frontier": 44, "debate.frontier": 44}      # frontier court and debate run on the fixed subset (ANALYSIS_PLAN note)
FULL_N = 104                                                      # test cases scored in E1


def incomplete(exp: str, key: str, cell: dict) -> str | None:
    """A cell that is still running must not print partial counts as if they were final."""
    if exp != "e1" or "n_cases" not in cell:
        return None
    want = EXPECTED_N.get(canon(key).rsplit(".cpu", 1)[0], FULL_N)
    return None if cell["n_cases"] >= want else f"partial: {cell['n_cases']} of {want} cases so far"


def derived(rest: str):
    """e1.derived.court.<staffing>.no_charge | few_tests: of the guilty cases the court deployed, how many had no charge filed
    (or at most one prosecutor test). Computed from the trial records; returns a rate-like {"j","k"}."""
    parts = rest.split(".")
    if len(parts) != 4 or parts[1] != "court" and parts[1] != "debate":
        return None, "bad derived path"
    _, system, staffing, field = parts
    files = sorted((RESULTS / "trials" / "e1" / system / staffing).glob("*-G.json"))
    miss = [json.loads(f.read_text()) for f in files]
    miss = [t for t in miss if t.get("verdict", {}).get("ruling") == "deploy"]
    if not files:
        return None, "no trial records"
    def tests(t):
        return sum(1 for e in t.get("events", []) if e.get("role") == "prosecution" and e.get("kind") == "tool_call")
    if field == "no_charge":
        j = sum(1 for t in miss if not t.get("charges"))
    elif field == "few_tests":
        j = sum(1 for t in miss if tests(t) <= 1)
    else:
        return None, "unknown derived field"
    return {"j": j, "k": len(miss)}, f"derived from results/trials/e1/{system}/{staffing}/*-G.json ({field})"


def derived_e2(rest: str):
    """e2.derived.court_small44.guilty_stopped | innocent_deployed: the all-small court (results/trials/e1/court/small) restricted to the
    44-case subset in results/frontier_subset.txt, so it can sit beside the E2 cell. Guilty ids end in -G; the rest are innocent."""
    parts = rest.split(".")
    if len(parts) != 3 or parts[1] != "court_small44":
        return None, "bad derived path"
    ids = set((RESULTS / "frontier_subset.txt").read_text().strip().split(","))
    base = RESULTS / "trials" / "e1" / "court" / "small"
    recs = {i: json.loads((base / f"{i}.json").read_text()) for i in ids if (base / f"{i}.json").exists()}
    if len(recs) != len(ids):
        return None, "missing trial records"
    stopped = lambda i: recs[i]["verdict"]["ruling"] != "deploy"
    if parts[2] == "guilty_stopped":
        g = [i for i in ids if i.endswith("-G")]
        j = sum(1 for i in g if stopped(i))
    elif parts[2] == "innocent_deployed":
        g = [i for i in ids if not i.endswith("-G")]
        j = sum(1 for i in g if not stopped(i))
    else:
        return None, "unknown derived field"
    return {"j": j, "k": len(g)}, f"derived from results/trials/e1/court/small restricted to results/frontier_subset.txt ({parts[2]})"


def resolve(exp: str, rest: str):
    """Return (value, path-in-file) or (None, why)."""
    if exp == "e2" and rest.startswith("derived."):
        return derived_e2(rest)
    if exp == "e1" and rest.startswith("derived."):
        return derived(rest)
    data = load(exp)
    if data is None:
        return None, "results file missing"
    if rest.startswith("diff."):
        body = rest[5:]
        for d in data.get("paired_differences", []):
            pre = f"{canon(d['a'])}.vs.{canon(d['b'])}."
            if body.startswith(pre) and body[len(pre):] == d["metric"]:
                return d, f"paired_differences[{d['a']} vs {d['b']}, {d['metric']}]"
        return None, "no such paired difference"
    best = None
    for key in data.get("cells", {}):
        c = canon(key)
        if rest.startswith(c + ".") and (best is None or len(c) > len(canon(best))):
            best = key
    if best is not None:
        sub = rest[len(canon(best)) + 1:].split(".")
        why = incomplete(exp, best, data["cells"][best])
        if why:
            return None, why
        v = descend(data["cells"][best], sub)
        return (v, f"cells.{best}.{'.'.join(sub)}") if v is not None else (None, "no such field in cell")
    v = descend(data, rest.split("."))
    return (v, rest) if v is not None else (None, "no such path")


def num(x: float) -> str:
    return f"{x:.0f}" if abs(x) >= 100 else f"{x:.1f}" if abs(x) >= 10 else f"{x:.2f}"


def fmt(v, f: str | None) -> str | None:
    if isinstance(v, dict) and "metric" in v and "diff" in v:                       # paired difference
        if f == "ci":
            return f"{v['lo'] * 100:.0f} to {v['hi'] * 100:.0f} points"
        return f"{v['diff'] * 100:+.0f} points"
    if isinstance(v, dict) and "j" in v and "k" in v:                               # a rate
        j, k = v["j"], v["k"]
        if k == 0:                                                                   # nothing was run: leave the slot visibly open
            return None
        if f == "k":
            return str(k)
        if f == "j":
            return str(j)
        if f == "miss":
            return str(k - j)
        if f == "slash":
            return f"{j}/{k}"
        if f == "rate":
            return None if v.get("rate") is None else f"{v['rate']:.2f}"
        if f == "pct":
            return None if v.get("rate") is None else f"{v['rate'] * 100:.0f}\\%"
        if f == "ci":
            return None if v.get("lo") is None else f"{v['lo'] * 100:.0f} to {v['hi'] * 100:.0f}\\%"
        return f"{j} of {k}"
    if isinstance(v, dict) and "mean" in v:                                         # a mean
        if f == "n":
            return str(v["n"])
        return None if v["mean"] is None else num(v["mean"])
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return num(v)
    return None


def fill_line(line: str, missing: list[str]) -> str:
    sources: list[str] = []

    def sub(m: re.Match) -> str:
        spec = m.group(1)
        f = None
        if ":" in spec and spec.rsplit(":", 1)[1] in FORMATS:
            spec, f = spec.rsplit(":", 1)
        exp, _, rest = spec.partition(".")
        v, path = resolve(exp, rest) if exp in {"e1", "e2", "e3", "e4", "e5"} else (None, "unknown experiment")
        out = fmt(v, f) if v is not None else None
        if out is None:
            missing.append(m.group(1))
            sources.append(f"results/{exp}.json -> {rest} [UNFILLED: {path}]")
            return MISSING
        sources.append(f"results/{exp}.json -> {path}")
        return out

    new = SLOT.sub(sub, line)
    if sources:
        new = new.rstrip("\n") + " % source: " + "; ".join(sources) + "\n"
    return new


def process(src: Path) -> list[str]:
    missing: list[str] = []
    out = [f"% Filled in by scripts/make_paper.py from {src.name}. Do not edit; edit the template.\n"]
    for line in src.read_text().splitlines(keepends=True):
        if line.lstrip().startswith("%%"):
            continue
        out.append(fill_line(line, missing))
    dst = src.with_suffix("")                                                       # name.tex.in -> name.tex
    dst.write_text("".join(out))
    return missing


def main() -> None:
    total = 0
    for src in sorted(PAPER.glob("*.tex.in")):
        miss = process(src)
        total += len(miss)
        print(f"{src.name} -> {src.with_suffix('').name}: {len(miss)} unfilled slot(s)")
    print(f"{total} unfilled slot(s) in all")
    if "--build" in sys.argv:
        sys.exit(subprocess.call(["tectonic", "--outdir", str(PAPER), "main.tex"], cwd=PAPER))


if __name__ == "__main__":
    main()
