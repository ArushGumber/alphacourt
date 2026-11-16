"""Print the headline table of results/e1.json as Markdown. Usage: python scripts/results_table.py [path]"""
import json
import sys
from pathlib import Path

STAFF = {"small": "Qwen3 8B", "mid": "Gemma 3 12B", "frontier": "Gemini 3.1 Flash-Lite"}
SYSTEMS = [("none", "No gate"), ("battery", "Battery of fixed tests"), ("single", "Single reviewer"),
           ("debate", "Debate, no tools"), ("court", "Court with exhibit rule")]


def cell(c: dict, key: str) -> str:
    m = c[key]
    return f"{m['j']}/{m['k']}"


def main(path: str) -> str:
    cells = json.loads(Path(path).read_text())["cells"]
    rows = ["| System | Staffing | Cases | Guilty stopped | Innocent deployed |", "|---|---|---|---|---|"]
    for sysid, name in SYSTEMS:
        for key, c in cells.items():
            s, who = key.split("/")
            if s != sysid or not c.get("n_cases"):
                continue
            rows.append(f"| {name} | {STAFF.get(who, 'no model')} | {c['n_cases']} | "
                        f"{cell(c, 'guilty_stopped')} | {cell(c, 'innocent_deployed')} |")
    return "\n".join(rows)


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1] / "results" / "e1.json")))
