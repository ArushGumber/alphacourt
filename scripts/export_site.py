"""Write the site's data to web/public/data/ from the results files.

    uv run python scripts/export_site.py [--split test] [--out web/public/data] [--max-mb 15]

  docket.json            index rows (DocketRow)
  cases/{case_id}.json   CaseBundle (what the Courtroom page loads)
  results.json           headline numbers and chart data for E1 to E5 (ResultsFile plus a `detail` block)
  studio_session.json    one recorded E4 session, as StudioSession
  (Forensic-tool charts are converted: histogram -> dist, bars get `values`)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments import runner  # noqa: E402
from experiments.runner import Meta, load_meta, load_records  # noqa: E402
from experiments.score import sin_of  # noqa: E402

RESULTS = ROOT / "results"


def _dump(o) -> str:
    return json.dumps(o, separators=(",", ":"), default=str)


def _read(name: str) -> dict | None:
    p = RESULTS / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def best_court_cell() -> tuple[str, dict]:
    """The E1 court staffing with the highest balanced accuracy (mean of guilty stopped and innocent deployed)."""
    e1 = _read("e1") or {"cells": {}}
    best, bs = None, -1.0
    full = max((c.get("n_cases", 0) for c in e1["cells"].values()), default=0)
    for k, c in e1["cells"].items():
        if not k.startswith("court/") or c.get("n_cases", 0) < full:  # only staffings run on every test case
            continue
        a, b = c["guilty_stopped"]["rate"], c["innocent_deployed"]["rate"]
        s = ((a or 0) + (b or 0)) / 2
        if s > bs:
            best, bs = k, s
    return best or "court/small", e1["cells"].get(best or "", {})


def records_for(cell: str) -> dict:
    sys_, _, tag = cell.partition("/")
    return load_records(runner.trial_dir("e1", sys_, tag))


def level_label(m: Meta) -> str:
    return "unusual" if m.role == "unusual" else m.level


def convert_chart(ch: dict) -> dict:
    """Forensic-tool chart dicts to the shapes the site draws: histogram -> dist (lo, hi, counts, marker), bars get `values`."""
    if not ch:
        return ch
    ch = dict(ch)
    if ch.get("type") == "histogram":
        e = ch.get("bin_edges") or [0, 1]
        ch = {"type": "dist", "counts": ch.get("counts", []), "lo": e[0], "hi": e[-1],
              "marker": {"value": ch.get("marker"), "label": ch.get("marker_label", "real")}}
    elif ch.get("type") == "bars" and "values" not in ch and ch.get("series"):
        ch["values"] = ch["series"][0]["y"]
    return ch


def convert_record(rec: dict) -> dict:
    for e in rec.get("exhibits", []):
        e["chart"] = convert_chart(e.get("chart") or {})
    for ev in rec.get("events", []):
        d = ev.get("data")
        if isinstance(d, dict) and d.get("chart"):
            d["chart"] = convert_chart(d["chart"])
        if ev.get("kind") == "case" and isinstance(rec.get("case"), dict):
            # the site reads the full case file (spec, claim, log summary) from the clerk's case event
            ev["data"] = {**rec["case"], **(d if isinstance(d, dict) else {})}
    return rec


def strip_charts(rec: dict) -> dict:
    for e in rec.get("exhibits", []):
        e["chart"] = {}
    for ev in rec.get("events", []):
        if isinstance(ev.get("data"), dict) and "chart" in ev["data"]:
            ev["data"]["chart"] = {}
    return rec


def bundle(m: Meta, rec: dict, raw, world, log) -> dict:
    from court.engine import run_backtest
    from court.types import StrategySpec
    spec = StrategySpec.model_validate(rec["case"]["spec"])
    tear = run_backtest(spec, world, mode="naive", period="research")
    s2 = spec.model_copy(update={"lag": max(spec.lag, 1)})
    sealed = run_backtest(s2, world, mode="strict", period="sealed", cost_bps=world.cost_bps_true, universe="all")
    truth_raw = runner._get(raw, "truth") or {}
    return {"record": rec, "log": log.model_dump(mode="json") if log is not None else {"session_id": m.case_id, "trials": []},
            "tearsheet": tear.model_dump(mode="json"),
            "truth": {"sharpe": m.true_sharpe, "per_seed": list(runner._get(truth_raw, "per_seed", []) or []),
                      "how": runner._get(truth_raw, "how", ""), "guilty": m.guilty,
                      "sins": [m.sin] if m.guilty and m.sin else [], "equity": sealed.equity},
            "twin_of": m.twin_id if not m.guilty else None}


def export(split: str, out: Path, max_mb: float, feature: list[str] | None = None) -> dict:
    all_metas = load_meta()
    metas = {k: m for k, m in all_metas.items() if m.split in ("", split)}
    feature = [f for f in (feature or []) if f in all_metas]
    for f in feature:  # showcase cases from the dev split, shown on the site as demonstrations
        metas[f] = all_metas[f]
    cell, _ = best_court_cell()
    court = records_for(cell)
    court_staffed = {c: model_name(cell) for c in court}
    if feature:  # demonstrations: prefer the frontier-staffed dev records, which show the most exhibits
        fr = records_for("court/frontier")
        for f in feature:
            if f in fr:
                court[f] = fr[f]
                court_staffed[f] = model_name("court/frontier")
    battery = load_records(runner.trial_dir("e1", "battery", "cpu"))
    rows = []
    for cid, m in sorted(metas.items()):
        rec, sysname = (court.get(cid), "court") if cid in court else ((battery.get(cid), "battery") if cid in battery else (None, "none"))
        ruling = rec.verdict.ruling if rec else "deploy"
        rows.append({"case_id": cid, "name": m.name, "family": m.family.replace("_", " ").capitalize(),
                     "sins": [m.sin] if m.guilty and m.sin else [], "level": level_label(m),
                     "twin_of": m.twin_id if not m.guilty else None, "guilty": m.guilty,
                     "claimed_sharpe": m.claim_sharpe, "true_sharpe": m.true_sharpe, "ruling": ruling, "system": sysname,
                     "staffing": court_staffed.get(cid) if sysname == "court" else None,
                     "correct": (ruling != "deploy") if m.guilty else (ruling == "deploy"), "has_trial": cid in court})
    if out.exists():
        for sub in ("cases", "trials", "research"):
            shutil.rmtree(out / sub, ignore_errors=True)
        (out / "hero.json").unlink(missing_ok=True)
    for sub in ("cases",):
        (out / sub).mkdir(parents=True, exist_ok=True)
    (out / "docket.json").write_text(_dump(rows))
    budget = int(max_mb * 1024 * 1024)
    used = (out / "docket.json").stat().st_size

    # hero pair: the first featured pair if given; otherwise the first twin pair (id order) where the court was right
    # on both, preferring L3, then L2, then L1
    hero = tuple(feature[:2]) if len(feature) >= 2 else None
    for lvl in (("L3", "L2", "L1") if hero is None else ()):
        for cid, m in sorted(metas.items()):
            t = metas.get(m.twin_id or "")
            if m.guilty and t and m.level == lvl and cid in court and t.case_id in court \
                    and court[cid].verdict.ruling != "deploy" and court[t.case_id].verdict.ruling == "deploy":
                hero = (cid, t.case_id)
                break
        if hero:
            break
    featured = set(hero or ()) | set(feature)      # featured cases keep their charts when the size budget is tight
    if feature:
        (out / "hero.json").write_text(_dump({"pairs": [feature[i:i + 2] for i in range(0, len(feature) - 1, 2)],
                                              "note": "Demonstration trials from the dev split; the evaluation uses the test split."}))
    written, stripped, skipped = 0, 0, 0
    hero_b: dict = {}
    data = runner._docket()
    for cid, rec in court.items():
        if cid not in metas:
            continue
        raw = data.get_case(cid)
        b = bundle(metas[cid], convert_record(json.loads(rec.model_dump_json())), raw, runner.default_world(raw), runner.default_log(raw))
        txt = _dump(b)
        if used + len(txt) > budget * 0.8 and cid not in featured:
            b["record"] = strip_charts(b["record"])
            b["tearsheet"]["equity"] = b["tearsheet"]["equity"][::4]
            b["tearsheet"]["equity_index"] = b["tearsheet"]["equity_index"][::4]
            b["truth"]["equity"] = b["truth"]["equity"][::4]
            txt = _dump(b)
            stripped += 1
        (out / "cases" / f"{cid}.json").write_text(txt)
        used += len(txt)
        written += 1
    # results.json
    res = results_file()
    (out / "results.json").write_text(_dump(res))
    used += (out / "results.json").stat().st_size
    n_res = export_studio(out)
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    info = {"cases": written, "charts_stripped": stripped, "trials_skipped_for_size": skipped, "hero": hero,
            "research_sessions": n_res, "total_mb": round(total / 1048576, 2), "staffing": cell}
    print(json.dumps(info))
    if total > budget:
        print("WARNING: over budget", file=sys.stderr)
    return info


def _pct(r: dict) -> dict:
    return {"value": r["rate"], "lo": r["lo"], "hi": r["hi"], "n": f"{r['j']}/{r['k']}"}


MODEL_NAMES = {"local:qwen3-8b": "Qwen3 8B", "local:gemma3-12b": "Gemma 3 12B",
               "google:gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite"}
SYSTEM_LABELS = {"none": "No gate", "single": "Single reviewer", "debate": "Debate without tools",
                 "battery": "Tests with fixed thresholds, no model", "court": "Court",
                 "single_exhibits": "Reviewer given the test results, no rule",
                 "court_norule": "Court, rule not enforced",
                 "single_exhibits_rule": "Reviewer given the test results, rule enforced"}
SYSTEM_ORDER = ("none", "single", "debate", "single_exhibits", "court_norule", "battery", "single_exhibits_rule", "court")


def model_name(cell: str) -> str:
    """'court/small' -> 'Qwen3 8B' (the model that staffs that cell)."""
    tag = cell.partition("/")[2]
    mid = runner.STAFFINGS.get(tag, {}).get("default")
    return MODEL_NAMES.get(mid, mid or tag)


def _bar(r: dict) -> dict:
    return {"value": r["rate"], "lo": r["lo"], "hi": r["hi"], "j": r["j"], "k": r["k"]}


def e1_chart(e1: dict) -> dict:
    """E1 as chart data: one group per system (and staffing), rigged stopped and honest let through, j of k with Wilson bounds."""
    cells = e1["cells"]
    live = {k: c for k, c in cells.items() if c["guilty_stopped"]["k"] and c["innocent_deployed"]["k"]}   # drop empty cells
    full = max((c["n_cases"] for c in live.values()), default=0)
    rank = lambda k: (SYSTEM_ORDER.index(k.partition("/")[0]) if k.partition("/")[0] in SYSTEM_ORDER else 99,
                      list(runner.STAFFINGS).index(k.partition("/")[2]) if k.partition("/")[2] in runner.STAFFINGS else 0)

    def group(k: str, c: dict) -> dict:
        sysname = k.partition("/")[0]
        needs_model = sysname not in ("none", "battery")
        lab = SYSTEM_LABELS.get(sysname, sysname) + (f", {model_name(k)}" if needs_model else "")
        return {"id": k, "label": lab, "n_cases": c["n_cases"], "rigged": _bar(c["guilty_stopped"]), "honest": _bar(c["innocent_deployed"])}

    main = [group(k, c) for k, c in sorted(live.items(), key=lambda kc: rank(kc[0])) if c["n_cases"] >= full]
    sub = [group(k, c) for k, c in sorted(live.items(), key=lambda kc: rank(kc[0])) if c["n_cases"] < full]
    out = {"n_cases": full, "groups": main}
    if sub:
        ns = sorted({g["n_cases"] for g in sub})
        for g in sub:
            g["label"] += f" ({g['n_cases']} cases)"
        title = f"On a {ns[0]}-case subset" if len(ns) == 1 else "On subsets of the cases"
        out["subset"] = {"title": title, "n_cases": ns[-1], "groups": sub}
    return out


def exhibit_note(e1: dict) -> str | None:
    """How many court rulings the exhibit rule converted (a finding with no damaging exhibit is struck and the ruling changes)."""
    parts = []
    for k, c in e1["cells"].items():
        u = c.get("unsupported") or {}
        if k.startswith("court/") and u.get("k"):
            parts.append(f"{u['j']} of {u['k']} court rulings with {model_name(k)}")
    if not parts:
        return None
    return ("The exhibit rule strikes any finding that cites no damaging exhibit. It changed the ruling in " + "; ".join(parts) + ".")


def results_file() -> dict:
    e1, e2, e3, e4, e5 = (_read(n) for n in ("e1", "e2", "e3", "e4", "e5"))
    headline, exps = [], []
    if e1:
        cells = e1["cells"]
        court, cell = best_court_cell()
        for lab, k in (("Court", court), ("Single reviewer", court.replace("court", "single")),
                       ("Fixed thresholds, no model", "battery/cpu")):
            c = cells.get(k)
            if c and c["guilty_stopped"]["k"]:
                headline.append({"id": f"e1-{lab.lower().replace(' ', '-')}", "label": lab,
                                 "sub": model_name(k) if k.partition("/")[0] != "battery" else "automatic, no model",
                                 "rigged": _bar(c["guilty_stopped"]), "honest": _bar(c["innocent_deployed"])})
        chart = e1_chart(e1)
        exps.append({"id": "e1", "title": "What the exhibit rule buys", "chart": chart, "exhibit_note": exhibit_note(e1),
                     "question": "Five systems on the same held-out cases: no gate, a single reviewer, a debate without tools, the same tests with fixed thresholds and no model, and the court. "
                                 "Each is scored twice: how many rigged strategies it stops, and how many honest ones it lets through.",
                     "note": "Wilson 95% intervals; labels are j of k cases."})
    if e2:
        exps.append({"id": "e2", "title": "A small court and a strong defence", "question": "Does the ruling hold when the defence is a stronger model?",
                     "rows": [{"label": f"{k}, {m}", **_pct(c[m])} for k, c in e2["cells"].items() for m in ("guilty_stopped", "innocent_deployed")]})
    if e3:
        exps.append({"id": "e3", "title": "Attacks on the court", "question": "Notes to the judge, copies of one model as judge, a flooding defence.",
                     "rows": [{"label": f"{k}, {m}", **_pct(c[m])} for k, c in e3["cells"].items() for m in ("guilty_stopped", "innocent_deployed")]})
    if e4:
        rows = [{"label": f"{k.replace('|', ', ')}, inflation", "value": c["inflation"]["mean"], "n": f"n={c['inflation']['n']}"}
                for k, c in e4["cells"].items() if c["inflation"]["mean"] is not None]
        exps.append({"id": "e4", "title": "Research agents under pressure", "question": "How far does a pushed agent inflate its claim?",
                     "rows": rows, "note": "Inflation = claimed Sharpe minus true edge, mean over submitted strategies."})
    if e5:
        g = (e5.get("gateway_throughput") or {}).get("runs", [])
        if g:
            headline.append({"id": "e5-throughput", "label": "Gateway backtests per second", "value": f"{g[-1]['backtests_per_second']}",
                             "detail": f"{g[-1]['threads']} threads, median latency {g[-1]['latency_ms_median']} ms"})
        exps.append({"id": "e5", "title": "Cost and speed", "question": "Model calls, tokens and seconds per trial.",
                     "rows": [{"label": f"{k}, calls per case", "value": c["calls"]["mean"], "n": f"n={c['n']}"} for k, c in e5["cells"].items()]})
    detail = {n: o for n, o in zip(("e1", "e2", "e3", "e4", "e5"), (e1, e2, e3, e4, e5)) if o}
    for o in detail.values():
        o.pop("sessions", None)
    return {"headline": headline, "experiments": exps, "detail": detail}


def export_studio(out: Path) -> int:
    """studio_session.json: the first finished E4 session with a submission, as a StudioSession."""
    d = RESULTS / "e4" / "sessions"
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        s = json.loads(p.read_text())
        if s.get("status") != "finished" or not s.get("case_id"):
            continue
        steps, pending = [], None
        for ev in s.get("events", []):
            k, tool = ev["kind"], ev.get("tool")
            if k == "tool_call" and tool == "run_backtest":
                pending = (ev.get("args") or {}).get("spec")
            elif k == "tool_result" and not ev.get("error"):
                if tool == "run_backtest" and (ev.get("data") or {}).get("metrics") and pending:
                    steps.append({"kind": "run_backtest", "spec": pending, "metrics": ev["data"]["metrics"]})
                elif tool in ("list_fields", "field_info"):
                    steps.append({"kind": tool, "text": ev["text"][:400]})
                elif tool == "read_page":
                    steps.append({"kind": "read_page", "url": (ev.get("data") or {}).get("url", ""), "text": ev["text"][:400]})
        steps.append({"kind": "submit", "text": f"Submitted after {s['n_backtests']} backtests. Claimed Sharpe {s.get('claimed_sharpe')}.",
                      "case_id": s["case_id"]})
        (out / "studio_session.json").write_text(_dump({"brief": s["brief"], "model": s["model"], "steps": steps, "case_id": s["case_id"]}))
        return 1
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default=str(ROOT / "web" / "public" / "data"))
    ap.add_argument("--max-mb", type=float, default=15.0)
    ap.add_argument("--feature", default="", help="comma-separated case ids to include as demonstrations (pairs: guilty,innocent)")
    a = ap.parse_args()
    export(a.split, Path(a.out), a.max_mb, [x for x in a.feature.split(",") if x])


if __name__ == "__main__":
    main()
