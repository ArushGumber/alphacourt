"""Deploy web/dist to the Vercel project `alphacourt` through the REST API.

    uv run python scripts/deploy_vercel.py                      # build the site, deploy to production
    uv run python scripts/deploy_vercel.py --api https://x.trycloudflare.com   # live gateway address for /live.json
    uv run python scripts/deploy_vercel.py --live-only          # redeploy the last build with a new live.json
    uv run python scripts/deploy_vercel.py --no-build           # use the existing web/dist

/live.json is {"api": "<gateway base URL or empty>"}; the address comes from --api, else logs/tunnel.url, else
empty. The token is read from the local env file and goes only into the request header. Only the project `alphacourt` is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_common import ROOT, VERCEL_PROJECT, build_web, log, must_be_clean, now, secret  # noqa: E402

API = "https://api.vercel.com"
STAGE = ROOT / "build" / "vercel"


def live_address(arg: str | None) -> str:
    if arg is not None:
        return arg.strip().rstrip("/")
    f = ROOT / "logs" / "tunnel.url"
    return f.read_text().strip().rstrip("/") if f.is_file() else ""


def stage(api: str) -> Path:
    """Copy web/dist into build/vercel/ and write live.json."""
    src = ROOT / "web" / "dist"
    if not (src / "index.html").is_file():
        raise SystemExit("web/dist is empty: run without --no-build / --live-only first")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    shutil.copytree(src, STAGE)
    live = {"api": api}
    conf = {"cleanUrls": False, "trailingSlash": False, "headers": [
        {"source": "/live.json", "headers": [{"key": "Cache-Control", "value": "no-cache"}]}]}
    if api:
        # a stable MCP address: the static host forwards /mcp to the gateway, whose own address may change
        conf["rewrites"] = [{"source": "/mcp", "destination": api.rstrip("/") + "/mcp"}]
        live["mcp"] = "https://alphacourt.vercel.app/mcp"
    (STAGE / "live.json").write_text(json.dumps(live) + "\n")
    (STAGE / "vercel.json").write_text(json.dumps(conf) + "\n")
    return STAGE


def deploy(folder: Path) -> dict:
    must_be_clean(folder)
    h = {"Authorization": f"Bearer {secret('VERCEL_TOKEN')}"}
    files = []
    with httpx.Client(timeout=120, headers=h) as c:
        for p in sorted(folder.rglob("*")):
            if not p.is_file():
                continue
            b = p.read_bytes()
            sha = hashlib.sha1(b).hexdigest()
            r = c.post(f"{API}/v2/files", content=b, headers={"x-vercel-digest": sha,
                       "Content-Type": "application/octet-stream", "Content-Length": str(len(b))})
            if r.status_code not in (200, 201):
                raise SystemExit(f"upload of {p.name} failed: HTTP {r.status_code} {r.text[:200]}")
            files.append({"file": p.relative_to(folder).as_posix(), "sha": sha, "size": len(b)})
        body = {"name": VERCEL_PROJECT, "files": files, "target": "production",
                "projectSettings": {"framework": None, "buildCommand": None, "outputDirectory": None,
                                    "installCommand": None}}
        r = c.post(f"{API}/v13/deployments?skipAutoDetectionConfirmation=1", json=body)
        if r.status_code not in (200, 201):
            raise SystemExit(f"deployment failed: HTTP {r.status_code} {r.text[:300]}")
        d = r.json()
        did = d["id"]
        for _ in range(60):
            s = c.get(f"{API}/v13/deployments/{did}").json()
            if s.get("readyState") in ("READY", "ERROR", "CANCELED"):
                break
            time.sleep(3)
        aliases = s.get("alias") or []
        return {"when": now(), "id": did, "state": s.get("readyState"), "url": f"https://{s.get('url')}",
                "aliases": [f"https://{a}" for a in aliases], "files": len(files)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", help="base URL of the live gateway (default: logs/tunnel.url, else empty)")
    ap.add_argument("--live-only", action="store_true", help="skip the build; redeploy web/dist with a new live.json")
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    if not (a.live_only or a.no_build):
        build_web()
    addr = live_address(a.api)
    res = deploy(stage(addr))
    res["live_api"] = addr
    log(f"vercel: {res['state']} {res['url']} aliases {res['aliases']} live.json api={addr or '(empty)'}")
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "deploy_vercel.json").write_text(json.dumps(res, indent=1) + "\n")
    print("production URL:", (res["aliases"] or [res["url"]])[0])
    return 0 if res["state"] == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
