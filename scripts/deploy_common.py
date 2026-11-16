"""Shared helpers for the deploy scripts: secrets from .env, an upload-folder scan for tokens, a log, the Space wait loop."""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "deploy.log"
HF_USER = "Arushthegarlic"
SPACE_STATIC = f"{HF_USER}/alphacourt"
SPACE_LIVE = f"{HF_USER}/alphacourt-live"
DATASET = f"{HF_USER}/alphacourt-docket"
VERCEL_PROJECT = "alphacourt"
NODE_BIN = os.environ.get("NODE_BIN", "")  # optional: a folder holding node and npm
SECRET_RE = [("Hub token", re.compile(r"hf_[A-Za-z0-9]{20,}")), ("Vercel token", re.compile(r"vc[a-z]_[A-Za-z0-9]{20,}")),
             ("API key", re.compile(r"AIza[0-9A-Za-z_-]{30,}|gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{30,}"))]


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{now()} {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def secret(name: str) -> str:
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and k.strip().removeprefix("export ").strip() == name and v.strip().strip("'\""):
                return v.strip().strip("'\"")
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit(f"No {name} in .env or the environment.")
    return v


def scan(folder: Path) -> list[str]:
    """Problems in a folder about to be uploaded: the tokens themselves, token-shaped strings, env or tool files."""
    toks = [t.encode() for t in (secret("HF_TOKEN"), secret("VERCEL_TOKEN"))]
    out = []
    for p in sorted(folder.rglob("*")):
        r = p.relative_to(folder).as_posix()
        if p.name.startswith(".env"):
            out.append(f"{r}: file must not be uploaded")
        if not p.is_file():
            continue
        b = p.read_bytes()
        if any(t in b for t in toks):
            out.append(f"{r}: contains a token")
        if b"\0" in b[:4096]:
            continue
        t = b.decode("utf-8", errors="replace")
        for name, rx in SECRET_RE:
            if rx.search(t):
                out.append(f"{r}: looks like a {name}")
    return out


def must_be_clean(folder: Path) -> None:
    bad = scan(folder)
    if bad:
        for x in bad[:20]:
            log(f"scan: {x}")
        raise SystemExit(f"{folder}: failed the scan ({len(bad)} problems); nothing uploaded")


def space_url(repo_id: str) -> str:
    owner, name = repo_id.split("/")
    return f"https://{owner.lower()}-{name.lower().replace('_', '-').replace('.', '-')}.hf.space"


def wait_space(api, sha: str | None, minutes: float, repo_id: str) -> dict:
    t0, last, stage = time.time(), None, None
    while time.time() - t0 < minutes * 60:
        rt = api.get_space_runtime(repo_id)
        stage = str(getattr(rt.stage, "value", rt.stage))
        running = (rt.raw or {}).get("sha")
        if stage != last:
            log(f"wait {repo_id}: {stage} (hardware {getattr(rt, 'hardware', None)}, commit {running})")
            last = stage
        fresh = sha is None or running is None or running == sha
        if stage == "RUNNING" and fresh and time.time() - t0 > 20:
            return {"stage": stage, "wait_seconds": round(time.time() - t0, 1)}
        if stage in ("BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE") and fresh:
            tail = list(api.fetch_space_logs(repo_id, build=stage == "BUILD_ERROR"))[-40:]
            for line in tail:
                log(f"space log: {line.rstrip()}")
            return {"stage": stage}
        time.sleep(15)
    return {"stage": stage, "error": f"not running after {minutes} minutes"}


def hf_api():
    os.environ["HF_HUB_OFFLINE"] = "0"       # uploads need the Hub; nothing here downloads a model
    from huggingface_hub import HfApi
    return HfApi(token=secret("HF_TOKEN"))


def node_env() -> dict:
    env = dict(os.environ)
    if NODE_BIN:
        env["PATH"] = f"{NODE_BIN}:{env.get('PATH', '')}"
    env["CUDA_VISIBLE_DEVICES"] = ""
    return env


def build_web(dist: Path | None = None) -> Path:
    import subprocess
    p = subprocess.run(["npm", "run", "build"], cwd=ROOT / "web", env=node_env(), capture_output=True, text=True)
    if p.returncode:
        for line in (p.stdout + p.stderr).strip().splitlines()[-20:]:
            log(f"web build: {line}")
        raise SystemExit("the site did not build")
    d = ROOT / "web" / "dist"
    if not (d / "index.html").is_file():
        raise SystemExit("web/dist/index.html missing after build")
    return d


if __name__ == "__main__":
    sys.exit("helpers only")
