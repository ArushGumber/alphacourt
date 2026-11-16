"""Push the docket and selected results to the dataset repo Arushthegarlic/alphacourt-docket.

    uv run python scripts/deploy_dataset.py [--public] [--dry-run]

Uploads docket/cases/ and the files listed in RESULTS (those that exist) with a dataset card. Run it after the
experiments. A new dataset is private unless --public is given.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_common import DATASET, ROOT, hf_api, log, must_be_clean  # noqa: E402

BUILD = ROOT / "build" / "dataset"
RESULTS = ["results/e1.json", "results/e2.json", "results/e3.json", "results/e4.json", "results/e5.json",
           "results/docket_summary.json", "results/numbers.json"]
CARD = """---
license: mit
pretty_name: AlphaCourt docket
tags:
  - finance
  - agents
  - evaluation
---

# AlphaCourt docket

Strategy cases with known flaws and clean twins, each with its truth on sealed simulated data, and the results of the
experiments that use them. All markets are simulated.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--public", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    cases = ROOT / "docket" / "cases"
    if cases.is_dir():
        shutil.copytree(cases, BUILD / "cases")
    for r in RESULTS:
        f = ROOT / r
        if f.is_file():
            (BUILD / "results").mkdir(exist_ok=True)
            shutil.copy2(f, BUILD / "results" / f.name)
    (BUILD / "README.md").write_text(CARD)
    n = sum(1 for p in BUILD.rglob("*") if p.is_file())
    must_be_clean(BUILD)
    log(f"dataset: {n} files staged in build/dataset")
    if a.dry_run:
        return 0
    api = hf_api()
    api.create_repo(DATASET, repo_type="dataset", private=not a.public, exist_ok=True)
    api.upload_folder(repo_id=DATASET, repo_type="dataset", folder_path=str(BUILD), commit_message="Update docket")
    log(f"dataset: uploaded to {DATASET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
