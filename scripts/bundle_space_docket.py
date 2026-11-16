"""Write space/live/docket.json, the small docket the live Space offers.

    uv run python scripts/bundle_space_docket.py

Uses docket/cases/*.json when present (each file: a case with "spec", "claim" and optionally "world",
"title", "case_id"); otherwise the saved smoke trials in results/smoke/. At most 12 cases.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "space" / "live" / "docket.json"


SHOWCASE = ["AC-D014-G", "AC-D014-I", "AC-D012-G", "AC-D012-I", "AC-HERO-G", "AC-HERO-I", "AC-D009-G", "AC-D009-I",
            "AC-D021-G", "AC-D021-I", "AC-D-U01", "AC-D005-G"]  # dev-split demonstration cases


def from_docket() -> list[dict]:
    out = []
    files = [ROOT / "docket" / "cases" / "dev" / f"{i}.json" for i in SHOWCASE]
    for f in [f for f in files if f.exists()]:
        try:
            c = json.loads(f.read_text())
        except ValueError:
            continue
        c = c.get("case", c)
        if "spec" in c and "claim" in c:
            w = {"seed": c.get("seed", 1), "variant": c.get("variant")}
            out.append({"id": c.get("case_id", f.stem), "title": c.get("title", c.get("case_id", f.stem)),
                        "world": w if isinstance(w, dict) else {"seed": 1, "variant": None},
                        "spec": c["spec"], "claim": c["claim"]})
    return out


def from_smoke() -> list[dict]:
    seen, out = set(), []
    for f in sorted((ROOT / "results" / "smoke").glob("*_*.json")):
        if f.name == "summary.json":
            continue
        c = json.loads(f.read_text())["case"]
        if c["case_id"] in seen:
            continue
        seen.add(c["case_id"])
        out.append({"id": c["case_id"], "title": f"{c['spec']['name']} (claimed Sharpe {c['claim']['sharpe']:.2f})",
                    "world": {"seed": 1, "variant": None}, "spec": c["spec"], "claim": c["claim"]})
    return out


def main() -> None:
    cases = (from_docket() or from_smoke())[:12]
    OUT.write_text(json.dumps({"source": "docket" if from_docket() else "smoke", "cases": cases}, indent=1) + "\n")
    print(f"{len(cases)} cases -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
