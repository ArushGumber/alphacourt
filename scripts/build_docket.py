"""Build the docket: python scripts/build_docket.py [dev|test|all] [--procs N]. Idempotent; evaluations are cached."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docket import build_docket  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("split", nargs="?", default="all")
ap.add_argument("--procs", type=int, default=16)
a = ap.parse_args()
for sp in (["dev", "test"] if a.split == "all" else [a.split]):
    cs = build_docket(sp, procs=a.procs)
    print(sp, len(cs), "cases")
