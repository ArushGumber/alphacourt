"""Figure 1, bottom strip: three exhibits from one real trial and its ruling.

    python scripts/fig_trial_strip.py            # reads web/public/data/cases/AC-HERO-G.json
    python scripts/fig_trial_strip.py --fixture  # fixture data shaped like web/src/types.ts CaseBundle

Writes paper/fig_trial_strip.pdf (paper/fig_trial_strip_fixture.pdf with --fixture, which main.tex never prints), 7.0 in wide (a figure* in acmart sigconf), every glyph at least 6.5 pt.
Picks the first three distinct exhibits cited by a sustained, unstruck finding (falling back to damaging exhibits), draws each
by its chart type (equity, bars, line, histogram) and ends with the ruling and the sealed-period truth.
Style: the kit's figstyle_example_acm.py (serif body face, ink text, one colour per meaning, vector PDF, fonts embedded).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HERO = ROOT / "web/public/data/cases/AC-D014-G.json"
FIXTURE = ROOT / "scripts/fixtures/AC-HERO-G.fixture.json"
OUT = ROOT / "paper/fig_trial_strip.pdf"
FULL = 7.0
INK, SUB = "#20201D", "#5C574F"
CLAY, SLATE, GRAY, OCHRE, SAGE = "#BF5B3D", "#456076", "#A9A198", "#C98A2B", "#77854F"
MIN_PT = 6.5
TEST_NAME = {"lag_test": "Lag test", "pit_replay": "Point-in-time replay", "cost_test": "Cost test", "survivorship_test": "Survivorship test",
             "holdout_test": "Sealed holdout", "regime_split": "Regime split", "trial_haircut": "Trial-count haircut",
             "placebo_test": "Placebo test", "param_stability": "Parameter stability", "day_concentration": "Day concentration",
             "note_scan": "Note scan"}


def style() -> None:
    serif = "DejaVu Serif"
    from matplotlib import font_manager
    have = {f.name for f in font_manager.fontManager.ttflist}
    for c in ("Linux Libertine O", "Libertinus Serif", "TeX Gyre Termes", "Nimbus Roman"):
        if c in have:
            serif = c
            break
    plt.rcParams.update({"font.family": "serif", "font.serif": [serif], "font.size": 7, "axes.labelsize": 7, "xtick.labelsize": 6.5,
                         "ytick.labelsize": 6.5, "legend.fontsize": 6.5, "legend.frameon": False, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
                         "xtick.major.size": 2, "ytick.major.size": 2, "lines.linewidth": 1.1, "text.color": INK, "axes.labelcolor": INK,
                         "xtick.color": INK, "ytick.color": INK, "axes.edgecolor": INK, "pdf.fonttype": 42, "ps.fonttype": 42})


PLAIN = {"holdout_test": "Replay on unseen data", "lag_test": "Trade one bar later",
         "cost_test": "Charge realistic trading costs", "pit_replay": "Use only data known at the time",
         "survivorship_test": "Include companies that later failed", "placebo_test": "Compare with shuffled signals",
         "trial_haircut": "Discount for the number of tries"}


def short(x, n: int) -> str:
    return str(x) if len(str(x)) <= n else str(x)[: n - 1] + "."


def draw_exhibit(ax, ex: dict) -> None:
    ch, t = ex.get("chart") or {}, (ex.get("chart") or {}).get("type")
    series = ch.get("series") or []
    cols = [GRAY, CLAY, SLATE]
    if t in ("equity", "line"):
        for i, s in enumerate(series):
            y = np.asarray(s["y"], float)
            x = np.asarray(s.get("x") or np.arange(len(y)), float)
            ax.plot(x, y, color=cols[(i if t == "equity" else 1) % 3] if i else GRAY if t == "equity" else CLAY, label=short(s["label"], 18))
        ax.legend(loc="upper left" if t == "equity" else "best", handlelength=1.1, borderaxespad=0.1)
        ax.set_xlabel(ch.get("x_label") or ("trading day" if t == "equity" else ""))
        ax.set_ylabel("cumulative return" if t == "equity" else "")
    elif t == "bars":
        import textwrap
        labels = ["\n".join(textwrap.wrap(str(v), 9)) for v in ch.get("labels", [])]
        n = max(1, len(series))
        w = 0.8 / n
        for i, s in enumerate(series):
            ax.bar(np.arange(len(labels)) + (i - (n - 1) / 2) * w, s["y"], w, color=[GRAY, CLAY, SLATE][i % 3] if n > 1 else CLAY, label=short(s["label"], 18))
        ax.set_xticks(range(len(labels)), labels)
        ax.axhline(0, color=INK, lw=0.5)
        if n == 1:
            for xi, yv in enumerate(series[0]["y"]):
                ax.text(xi, yv, f"{yv:.2f}", ha="center", va="bottom" if yv >= 0 else "top", fontsize=6.5, color=INK)
            lo, hi = min(series[0]["y"] + [0]), max(series[0]["y"] + [0])
            ax.set_ylim(lo - 0.25 * (hi - lo), hi + 0.25 * (hi - lo))
        ax.set_ylabel("Sharpe ratio")
        if n > 1:
            ax.legend(loc="best", handlelength=1.1)
    elif t in ("histogram", "dist"):
        edges = np.asarray(ch.get("bin_edges") or np.linspace(ch.get("lo", 0), ch.get("hi", 1), len(ch["counts"]) + 1))
        ax.bar(edges[:-1], ch["counts"], np.diff(edges), align="edge", color=GRAY)
        m = ch.get("marker")
        if isinstance(m, dict):
            m = m.get("value")
        if m is not None:
            ax.axvline(m, color=CLAY, lw=1.4)
            ax.text(m, max(ch["counts"]) * 0.97, " " + str(ch.get("marker_label") or "real"), color=CLAY, va="top", ha="left")
        ax.set_xlabel("Sharpe, shuffled signals")
        ax.set_ylabel("count")
    else:
        ax.text(0.5, 0.5, "no chart", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()


def pick(bundle: dict) -> list[dict]:
    rec = bundle["record"]
    ex = {e["id"]: e for e in rec["exhibits"]}
    out: list[dict] = []
    for f in rec["verdict"]["findings"]:
        if f.get("sustained") and not f.get("struck"):
            for i in f["exhibits"]:
                if i in ex and ex[i] not in out and ex[i].get("chart"):
                    out.append(ex[i])
    for e in rec["exhibits"]:
        if len(out) >= 3:
            break
        if e not in out and e["hint"] == "damaging" and e.get("chart"):
            out.append(e)
    return sorted(out[:3], key=lambda e: e["id"])


def make_fixture() -> dict:
    rng = np.random.default_rng(0)
    n = 120
    base = np.cumsum(rng.normal(0.0016, 0.004, n))
    lag = np.cumsum(rng.normal(-0.0002, 0.004, n))
    counts, edges = np.histogram(rng.normal(0.0, 0.45, 2000), bins=24)
    ex = [
        {"id": "EX-1", "test": "lag_test", "params": {"k": 1}, "numbers": {"sharpe_before": 2.9, "sharpe_after": -0.4}, "summary": "", "hint": "damaging",
         "chart": {"type": "equity", "series": [{"label": "as submitted", "y": base.tolist()}, {"label": "lag + 1", "y": lag.tolist()}]}, "called_by": "prosecution"},
        {"id": "EX-2", "test": "trial_haircut", "params": {}, "numbers": {}, "summary": "", "hint": "damaging",
         "chart": {"type": "bars", "labels": ["claimed", "expected max, no edge", "haircut"], "series": [{"label": "Sharpe", "y": [2.9, 2.5, 0.4]}]}, "called_by": "prosecution"},
        {"id": "EX-3", "test": "placebo_test", "params": {"n": 200}, "numbers": {}, "summary": "", "hint": "damaging",
         "chart": {"type": "histogram", "bin_edges": edges.tolist(), "counts": counts.tolist(), "marker": 0.2, "marker_label": "real"}, "called_by": "prosecution"},
    ]
    verdict = {"ruling": "reject", "capital_allowed": 0.0, "unsupported": False, "opinion": "Fixture data.",
               "findings": [{"sin": "lookahead", "sustained": True, "exhibits": ["EX-1"], "struck": False},
                            {"sin": "selection", "sustained": True, "exhibits": ["EX-2", "EX-3"], "struck": False}]}
    case = {"case_id": "AC-HERO-G", "claim": {"sharpe": 2.9}, "log_summary": {"n_trials": 37, "best_of": 37}}
    return {"record": {"case": case, "exhibits": ex, "verdict": verdict, "charges": [], "rebuttals": []},
            "truth": {"sharpe": -0.4, "guilty": True, "sins": ["lookahead", "selection"], "equity": np.cumsum(rng.normal(-0.0004, 0.004, 100)).tolist()},
            "_fixture": True}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", action="store_true")
    ap.add_argument("--src")
    ap.add_argument("--out")
    a = ap.parse_args()
    a.out = a.out or str(OUT.with_name("fig_trial_strip_fixture.pdf") if a.fixture else OUT)  # a fixture never takes the real figure's name
    if a.fixture:
        bundle = make_fixture()
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(json.dumps(bundle))
    else:
        p = Path(a.src or HERO)
        if not p.exists():
            sys.exit(f"{p} does not exist yet; run with --fixture to draw the layout")
        bundle = json.loads(p.read_text())
    style()
    exs = pick(bundle)
    rec, truth = bundle["record"], bundle.get("truth") or {}
    v = rec["verdict"]
    ne = max(1, len(exs))
    fig = plt.figure(figsize=(FULL, 1.9))
    gs = fig.add_gridspec(1, ne + 1, width_ratios=[1] * ne + [0.9], wspace=0.5, left=0.065, right=0.995, top=0.76, bottom=0.26)
    for i in range(ne):
        ax = fig.add_subplot(gs[0, i])
        if i < len(exs):
            draw_exhibit(ax, exs[i])
            x0 = ax.get_position().x0
            fig.text(x0, 0.99, f"{exs[i]['id'].replace('EX-', 'Exhibit ')}: {TEST_NAME.get(exs[i]['test'], exs[i]['test'])}", fontsize=7, va="top", ha="left")
            nb = exs[i].get("numbers") or {}
            extra = ""
            if "sharpe_before" in nb and "sharpe_after" in nb:
                extra = f": Sharpe {nb['sharpe_before']:.2f} to {nb['sharpe_after']:.2f}"
            fig.text(x0, 0.99 - 0.095, PLAIN.get(exs[i]["test"], "") + extra, fontsize=6.5, va="top", ha="left", color=SUB)
        else:
            ax.set_axis_off()
    ax = fig.add_subplot(gs[0, ne])
    ax.set_axis_off()
    x0 = ax.get_position().x0
    names = {"reject": "REJECT", "paper": "PAPER ONLY", "deploy": "DEPLOY"}
    fig.text(x0, 0.99, "Ruling", fontsize=7, va="top")
    fig.text(x0, 0.99 - 0.095, "Findings cite exhibits", fontsize=6.5, va="top", color=SUB)
    ax.text(0, 1.04, names[v["ruling"]], color=CLAY if v["ruling"] != "deploy" else SAGE, fontsize=11, va="top", transform=ax.transAxes)
    claimed = rec["case"]["claim"]["sharpe"]
    lines = [f"Claimed Sharpe {claimed:.2f}"]
    if truth:
        lines.append(f"True Sharpe on sealed\ndata {truth['sharpe']:.2f}")
    ax.text(0, 0.80, "\n".join(lines), fontsize=7, va="top", transform=ax.transAxes, linespacing=1.4)
    if truth.get("equity"):
        ins = ax.inset_axes([0.0, 0.0, 1.0, 0.22])
        ins.plot(truth["equity"], color=SLATE)
        ins.set_xticks([])
        ins.set_yticks([])
        ins.set_xlabel("sealed period, true P&L", labelpad=1)
        for s_ in ("left", "bottom"):
            ins.spines[s_].set_visible(True)
    Path(a.out).parent.mkdir(exist_ok=True)
    fig.savefig(a.out, format="pdf")
    sizes = sorted({round(t.get_fontsize(), 1) for t in fig.findobj(matplotlib.text.Text) if t.get_text().strip() and t.get_visible()})
    print(f"wrote {a.out}; font sizes used: {sizes}; smallest {sizes[0]} pt (need >= {MIN_PT})")
    if sizes[0] < MIN_PT:
        sys.exit(1)


if __name__ == "__main__":
    main()
