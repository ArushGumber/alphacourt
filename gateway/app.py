"""AlphaCourt gateway app: /mcp (JSON-RPC), the /api/ HTTP mirror for the site, and the built site.

Run: uv run uvicorn gateway.app:app --host 127.0.0.1 --port 8787   (or scripts/run_gateway.sh)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from sse_starlette.sse import EventSourceResponse

from . import guard
from .guard import Guard, Limits, client_ip
from .mcp import PROTOCOL_VERSIONS, Ctx, handle, initialize_hint, make_tools
from .service import GatewayService, ServiceError
from .studio import make_router as studio_router

DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
# The site is served from Vercel and from Hugging Face Spaces; extra origins: ALPHACOURT_CORS (comma separated).
CORS_ORIGINS = ["https://alphacourt.vercel.app", "https://arushthegarlic-alphacourt.hf.space",
                "https://arushthegarlic-alphacourt.static.hf.space",
                "http://localhost:5173", "http://127.0.0.1:5173",
                *[o.strip() for o in os.environ.get("ALPHACOURT_CORS", "").split(",") if o.strip()]]
CORS_REGEX = r"https://(alphacourt[a-z0-9-]*\.vercel\.app|arushthegarlic-alphacourt[a-z0-9-]*(\.static)?\.hf\.space)"
SESSION_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _err(e: ServiceError) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=e.code)


def create_app(service: GatewayService | None = None, limits: Limits | None = None,
               dist: Path | str | None = DIST) -> FastAPI:
    svc = service or GatewayService()
    cfg = svc.config
    lim = limits or Limits(backtests_per_minute=cfg.get("backtests_per_minute", 30),
                           trials_per_hour=cfg.get("trials_per_hour", 3), local_exempt=cfg.get("local_exempt", True))
    app = FastAPI(title="AlphaCourt gateway", docs_url=None, redoc_url=None)
    app.state.service, app.state.limits = svc, lim
    app.add_middleware(Guard, general=lim.general)
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_origin_regex=CORS_REGEX,
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"],
                       expose_headers=["mcp-session-id", "retry-after"], max_age=600)
    tools = make_tools()

    def session_of(request: Request, body: dict | None = None) -> str:
        sid = request.headers.get("x-session") or (body or {}).get("session")
        if isinstance(sid, str) and SESSION_RE.fullmatch(sid):
            return sid
        return "web-" + hashlib.sha256(client_ip(request).encode()).hexdigest()[:10]

    async def body_of(request: Request) -> dict:
        try:
            b = json.loads(await request.body() or b"{}")
        except ValueError:
            raise ServiceError("The body is not valid JSON.") from None
        if not isinstance(b, dict):
            raise ServiceError("The body must be a JSON object.")
        return b

    # ------------------------------------------------------------------ MCP

    @app.post("/mcp")
    async def mcp_post(request: Request):
        try:
            body = json.loads(await request.body())
        except Exception:
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                                status_code=400)
        if isinstance(body, list) and (not body or len(body) > 20):
            return JSONResponse({"jsonrpc": "2.0", "id": None,
                                 "error": {"code": -32600, "message": "A batch must hold 1 to 20 messages."}},
                                status_code=400)
        msgs = body if isinstance(body, list) else [body]
        ip = client_ip(request)
        sid = request.headers.get("mcp-session-id")
        has_init, world, agent = initialize_hint(msgs)
        headers = {"mcp-protocol-version": PROTOCOL_VERSIONS[0]}
        try:
            if has_init:
                sid = "mcp-" + uuid.uuid4().hex[:16]
                svc.session(sid, world, agent)
                headers["mcp-session-id"] = sid
            elif not sid or not SESSION_RE.fullmatch(sid):
                sid = "ip-" + hashlib.sha256(ip.encode()).hexdigest()[:10]
        except ServiceError as e:
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32602, "message": str(e)}})
        ctx = Ctx(svc, sid, ip, lim.backtest_wait, lim.trial_wait)

        def run() -> list:
            return [x for x in (handle(m, tools, ctx) for m in msgs) if x is not None]
        out = await asyncio.to_thread(run)
        if not out:
            return Response(status_code=202, headers=headers)
        return JSONResponse(out if isinstance(body, list) else out[0], headers=headers)

    @app.get("/mcp")
    async def mcp_get():
        return Response("MCP endpoint. POST JSON-RPC (streamable HTTP).", status_code=405,
                        headers={"allow": "POST"}, media_type="text/plain")

    @app.delete("/mcp")
    async def mcp_delete():
        return Response(status_code=405, headers={"allow": "POST"})

    # ------------------------------------------------------------------ HTTP mirror

    @app.get("/api/health")
    async def health():
        return svc.health()

    @app.get("/api/worlds")
    async def worlds():
        return {"worlds": svc.worlds()}

    @app.post("/api/backtest")
    async def api_backtest(request: Request):
        try:
            b = await body_of(request)
            sid = session_of(request, b)
            wait = lim.backtest_wait(sid)
            if wait:
                return JSONResponse({"detail": "Too many backtests for this session."}, status_code=429,
                                    headers={"retry-after": str(int(wait) + 1)})
            out = await asyncio.to_thread(svc.run_backtest, sid, b.get("spec"), b.get("world"))
        except ServiceError as e:
            return _err(e)
        return {"session": sid, "trial_number": out["trial_number"], "spec_hash": out["spec_hash"],
                "world": out["world"], "result": out["result"].model_dump(mode="json")}

    @app.post("/api/truth")
    async def api_truth(request: Request):
        try:
            b = await body_of(request)
            wait = lim.backtest_wait("truth:" + client_ip(request))
            if wait:
                return JSONResponse({"detail": "Too many requests."}, status_code=429,
                                    headers={"retry-after": str(int(wait) + 1)})
            return await asyncio.wait_for(asyncio.to_thread(svc.truth, b.get("spec"), b.get("world")), 25)
        except asyncio.TimeoutError:
            return JSONResponse({"detail": "The truth run took too long."}, status_code=504)
        except ServiceError as e:
            return _err(e)

    @app.post("/api/submit")
    async def api_submit(request: Request):
        ip = client_ip(request)
        try:
            b = await body_of(request)
            wait = lim.trial_wait(ip)
            if wait:
                return JSONResponse({"detail": "Trial limit reached for your address."}, status_code=429,
                                    headers={"retry-after": str(int(wait) + 1)})
            sid = session_of(request, b)
            r = await asyncio.to_thread(svc.submit_strategy, sid, b.get("spec"), b.get("claim"),
                                        b.get("requested_capital", 1_000_000.0), b.get("world"), ip)
        except ServiceError as e:
            return _err(e)
        return {**r, "session": sid}

    @app.get("/api/cases")
    async def cases():
        return {"cases": svc.list_cases()}

    @app.get("/api/cases/{case_id}")
    async def case(case_id: str):
        try:
            return svc.case_detail(case_id)
        except ServiceError as e:
            return _err(e)

    @app.get("/api/cases/{case_id}/events")
    async def case_events(case_id: str, request: Request):
        if svc.get_case(case_id) is None:
            return JSONResponse({"detail": f"No case {case_id}."}, status_code=404)
        ip = client_ip(request)
        lease, why = lim.streams.acquire(ip)
        if lease is None:
            return JSONResponse({"detail": why}, status_code=429)

        async def gen():
            i = 0
            try:
                while True:
                    evs, done = svc.events_since(case_id, i)
                    for ev in evs:
                        yield {"event": ev.get("kind", "message"), "id": str(i), "data": json.dumps(ev)}
                        i += 1
                    if done and not evs:
                        yield {"event": "end", "data": json.dumps({"case_id": case_id, "events": i})}
                        return
                    if await request.is_disconnected():
                        return
                    await asyncio.sleep(0.15)
            finally:
                lim.streams.release(lease)
        return EventSourceResponse(gen(), ping=15)

    @app.post("/api/trial")
    async def api_trial(request: Request):
        ip = client_ip(request)
        try:
            b = await body_of(request)
            wait = lim.trial_wait(ip)
            if wait:
                return JSONResponse({"detail": "Trial limit reached for your address."}, status_code=429,
                                    headers={"retry-after": str(int(wait) + 1)})
            return await asyncio.to_thread(svc.run_site_trial, b, ip)
        except ServiceError as e:
            return _err(e)

    app.include_router(studio_router(svc))

    # ------------------------------------------------------------------ the site

    root = Path(dist).resolve() if dist else None

    @app.get("/{path:path}")
    async def site(path: str):
        if path.startswith("api/") or path == "mcp" or root is None or not (root / "index.html").exists():
            return JSONResponse({"detail": "Not found"}, status_code=404)
        f = (root / path).resolve()
        if path and f.is_file() and root in f.parents:
            return FileResponse(f)
        return FileResponse(root / "index.html")

    return app


def __getattr__(name: str):
    if name == "app":       # built on first use, so importing the module has no side effects
        a = create_app()
        globals()["app"] = a
        return a
    raise AttributeError(name)
