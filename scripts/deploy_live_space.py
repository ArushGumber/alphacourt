"""The live Space Arushthegarlic/alphacourt-live: a ZeroGPU Gradio app that puts a strategy on trial with a court
staffed by Qwen3 8B, plus an MCP tool put_on_trial(spec_json, claim_sharpe). Weights are pulled from the Hub by the
Space; nothing is downloaded here.

    uv run python scripts/deploy_live_space.py build     # assemble build/live_space/
    uv run python scripts/deploy_live_space.py upload    # upload it (private), wait until it runs
    uv run python scripts/deploy_live_space.py check     # one trial through the API, MCP tool list
    uv run python scripts/deploy_live_space.py all

Re-bundle the docket first with scripts/bundle_space_docket.py. The Space is created private; this script never
changes visibility.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_common import (ROOT, SPACE_LIVE, hf_api, log, must_be_clean, now, secret, space_url,  # noqa: E402
                           wait_space)

BUILD = ROOT / "build" / "live_space"
APP = ROOT / "space" / "live"
CODE = ["court/*.py", "llm/__init__.py", "llm/client.py", "docket/__init__.py", "LICENSE"]
HARDWARE = "zero-a10g"


def build() -> None:
    bundle = ROOT / "scripts" / "bundle_space_docket.py"
    import subprocess
    subprocess.run([sys.executable, str(bundle)], check=True)
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    for pat in CODE:
        found = sorted(ROOT.glob(pat))
        if not found:
            raise SystemExit(f"nothing matches {pat}")
        for f in found:
            q = BUILD / f.relative_to(ROOT)
            q.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, q)
    for f in sorted(APP.iterdir()):
        if f.is_file() and f.suffix in (".py", ".md", ".txt", ".json"):
            shutil.copy2(f, BUILD / f.name)
    must_be_clean(BUILD)
    n = sum(1 for p in BUILD.rglob("*") if p.is_file())
    log(f"live build: {n} files in build/live_space")


def upload(minutes: float) -> dict:
    api = hf_api()
    must_be_clean(BUILD)
    api.create_repo(SPACE_LIVE, repo_type="space", space_sdk="gradio", space_hardware=HARDWARE, private=True,
                    exist_ok=True)
    c = api.upload_folder(repo_id=SPACE_LIVE, repo_type="space", folder_path=str(BUILD), commit_message="Update app",
                          delete_patterns=["*"])
    sha = getattr(c, "oid", None)
    res = {"when": now(), "repo": SPACE_LIVE, "url": space_url(SPACE_LIVE), "commit": sha,
           "private": bool(api.space_info(SPACE_LIVE).private)}
    res.update(wait_space(api, sha, minutes, SPACE_LIVE))
    return res


def check() -> dict:
    import httpx
    base = space_url(SPACE_LIVE)
    h = {"Authorization": f"Bearer {secret('HF_TOKEN')}"}
    spec = json.dumps({"name": "three-day signal", "signal": "rank(ts_mean(ret, 3))", "lag": 0, "costs_bps": 0})
    out: dict = {"when": now(), "url": base}
    t = time.time()
    with httpx.Client(timeout=900, headers=h, follow_redirects=True) as c:
        r = c.post(f"{base}/gradio_api/call/put_on_trial", json={"data": [spec, None]})
        if r.status_code != 200:
            out["api"] = {"status": r.status_code, "error": r.text[:300]}
        else:
            eid, event, data = r.json()["event_id"], None, None
            with c.stream("GET", f"{base}/gradio_api/call/put_on_trial/{eid}") as s:
                for line in s.iter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:") and event in ("complete", "error"):
                        data = line[5:].strip()
                        break
            try:
                v = json.loads(data)[0] if event == "complete" else data
            except Exception:
                v = data
            out["api"] = {"event": event, "seconds": round(time.time() - t, 1),
                          "ruling": v.get("ruling") if isinstance(v, dict) else None,
                          "exhibits": len(v.get("exhibits", [])) if isinstance(v, dict) else None,
                          "detail": None if isinstance(v, dict) else str(v)[:400]}
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        try:
            r = c.post(f"{base}/gradio_api/mcp/", json=msg, headers={**h, "Accept": "application/json, text/event-stream"})
            out["mcp"] = {"status": r.status_code, "body": r.text[:300]}
        except Exception as e:
            out["mcp"] = {"error": type(e).__name__}
    log(f"live check: {json.dumps(out)[:600]}")
    (ROOT / "results" / "deploy_live_space.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["build", "upload", "check", "all"])
    ap.add_argument("--wait-minutes", type=float, default=40.0)
    a = ap.parse_args()
    if a.step in ("build", "all"):
        build()
    if a.step in ("upload", "all"):
        r = upload(a.wait_minutes)
        log(f"live upload: {r}")
        if r.get("stage") != "RUNNING":
            return 1
    if a.step in ("check", "all"):
        r = check()
        return 0 if (r.get("api") or {}).get("ruling") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
