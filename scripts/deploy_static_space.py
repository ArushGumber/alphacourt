"""Mirror web/dist into the Static Space Arushthegarlic/alphacourt.

    uv run python scripts/deploy_static_space.py [--api URL] [--public] [--no-build]

Same build as the Vercel site, with a /live.json that names the live gateway (default: logs/tunnel.url, else empty).
A new Space is private unless --public is given; an existing Space keeps its visibility.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_common import (ROOT, SPACE_STATIC, build_web, hf_api, log, must_be_clean, now,  # noqa: E402
                           space_url, wait_space)
from deploy_vercel import live_address  # noqa: E402

BUILD = ROOT / "build" / "static_space"
README = """---
title: AlphaCourt
sdk: static
app_file: index.html
license: mit
short_description: AI-written trading strategies on trial before they trade
---
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api")
    ap.add_argument("--public", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    if not a.no_build:
        build_web()
    src = ROOT / "web" / "dist"
    if not (src / "index.html").is_file():
        raise SystemExit("web/dist is empty")
    if BUILD.exists():
        shutil.rmtree(BUILD)
    shutil.copytree(src, BUILD)
    (BUILD / "live.json").write_text(json.dumps({"api": live_address(a.api)}) + "\n")
    (BUILD / "README.md").write_text(README)
    must_be_clean(BUILD)
    api = hf_api()
    api.create_repo(SPACE_STATIC, repo_type="space", space_sdk="static", private=not a.public, exist_ok=True)
    c = api.upload_folder(repo_id=SPACE_STATIC, repo_type="space", folder_path=str(BUILD), commit_message="Update site",
                          delete_patterns=["*"])
    sha = getattr(c, "oid", None)
    res = {"when": now(), "repo": SPACE_STATIC, "url": space_url(SPACE_STATIC), "commit": sha,
           "private": bool(api.space_info(SPACE_STATIC).private)}
    res.update(wait_space(api, sha, 10, SPACE_STATIC))
    log(f"static space: {res}")
    (ROOT / "results" / "deploy_static_space.json").write_text(json.dumps(res, indent=1) + "\n")
    return 0 if res.get("stage") == "RUNNING" else 1


if __name__ == "__main__":
    sys.exit(main())
