"""Studio API: a visitor starts an AI research session and watches it, then the trial of what it submitted.

POST /api/studio/start {brief, model, world, user_key?} -> {"session_id"}
GET  /api/studio/{id}/events   server-sent events: "agent" events (the research steps), then "trial" events
                               (the court's), then "end".

Limits (in memory): one running session per address, two at once overall, five per address per day, and a hard
cap of 300 model calls an hour across all sessions. A visitor's own Google key is used for that session only,
is never stored or logged, and is refused unless the request is local or arrived over HTTPS.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from agent import briefs
from agent.research import google_chat_with_key, run_session
from .guard import client_ip, is_public

MAX_BRIEF = 1000
KEY_RE = re.compile(r"[A-Za-z0-9_-]{20,100}")
GOOGLE_NAME_RE = re.compile(r"google:[A-Za-z0-9._-]{1,60}")
DAY = 86400.0
HOUR = 3600.0


class StudioError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


class Studio:
    def __init__(self, service, *, max_running_per_ip: int = 1, max_running: int = 2, per_ip_per_day: int = 5,
                 calls_per_hour: int = 300, max_calls: int = 25, run_fn: Callable | None = None,
                 clock: Callable[[], float] = time.time, **run_kw):
        self.svc = service
        self.max_running_per_ip, self.max_running = max_running_per_ip, max_running
        self.per_ip_per_day, self.calls_per_hour, self.max_calls = per_ip_per_day, calls_per_hour, max_calls
        self.run_fn, self.clock, self.run_kw = run_fn or run_session, clock, run_kw
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._starts: dict[str, list[float]] = {}
        self._calls: deque[float] = deque()

    # ------------------------------------------------------------------ limits

    def _take_call(self) -> None:
        with self._lock:
            now = self.clock()
            while self._calls and self._calls[0] < now - HOUR:
                self._calls.popleft()
            if len(self._calls) >= self.calls_per_hour:
                raise RuntimeError("The Studio's hourly model-call budget is used up. Try again later.")
            self._calls.append(now)

    def _calls_left(self) -> int:
        now = self.clock()
        return self.calls_per_hour - sum(1 for t in self._calls if t >= now - HOUR)

    def _chat_fn(self, user_key: str | None):
        if user_key:
            inner = google_chat_with_key(user_key)
        else:
            from llm import client
            inner = lambda *a, **k: client.chat(*a, **k)

        def chat(model, messages, **kw):
            self._take_call()
            return inner(model, messages, **kw)
        return chat

    # ------------------------------------------------------------------ start

    def start(self, body: dict, ip: str, *, secure: bool, local: bool) -> str:
        brief = body.get("brief")
        if not isinstance(brief, str) or not brief.strip():
            raise StudioError("brief is required.")
        if len(brief) > MAX_BRIEF:
            raise StudioError(f"brief must be at most {MAX_BRIEF} characters.")
        brief = briefs.resolve(brief)
        model, world = body.get("model"), body.get("world") or self.svc.config.get("default_world", "demo")
        user_key = body.get("user_key")
        if user_key is not None:
            if not isinstance(user_key, str) or not KEY_RE.fullmatch(user_key):
                raise StudioError("user_key does not look like a Google API key.")
            if not (secure or local):
                raise StudioError("A personal key is accepted only over HTTPS.", 400)
            if not isinstance(model, str) or not GOOGLE_NAME_RE.fullmatch(model):
                raise StudioError("With your own key, choose a Google model, for example google:gemini-2.5-flash.")
        else:
            allowed = self.svc.config.get("allowed_models", [])
            if model not in allowed:
                raise StudioError(f"Model '{model}' is not available. Choose from: {', '.join(allowed)}.")
        try:
            self.svc.world_name_check(world)
        except Exception as e:
            raise StudioError(str(e)) from None
        now = self.clock()
        with self._lock:
            running = [s for s in self._sessions.values() if s["status"] == "running"]
            if sum(1 for s in running if s["ip"] == ip) >= self.max_running_per_ip:
                raise StudioError("You already have a session running. Wait for it to finish.", 429)
            if len(running) >= self.max_running:
                raise StudioError("The Studio is busy: two sessions are running. Try again in a few minutes.", 429)
            starts = [t for t in self._starts.get(ip, []) if t > now - DAY]
            if len(starts) >= self.per_ip_per_day:
                raise StudioError(f"Daily limit reached: {self.per_ip_per_day} sessions per address.", 429)
            if self._calls_left() <= 0:
                raise StudioError("The Studio's hourly model-call budget is used up. Try again later.", 429)
            sid = "st-" + uuid.uuid4().hex[:12]
            starts.append(now)
            self._starts[ip] = starts
            self._sessions[sid] = {"id": sid, "ip": ip, "status": "running", "events": [], "case_id": None,
                                   "model": model, "world": world, "result": None}
        threading.Thread(target=self._run, args=(sid, brief, model, world, user_key), daemon=True,
                         name=f"studio-{sid}").start()
        return sid

    def _run(self, sid: str, brief: str, model: str, world: str, user_key: str | None) -> None:
        s = self._sessions[sid]

        def on_event(ev: dict) -> None:
            ev = dict(ev)
            with self._lock:
                s["events"].append(ev)
                if ev.get("kind") == "tool_result" and ev.get("tool") == "submit_strategy":
                    cid = (ev.get("data") or {}).get("case_id")
                    if cid:
                        s["case_id"] = cid
        try:
            self.run_fn(brief, model, world=world, gateway=self.svc, max_calls=self.max_calls, on_event=on_event,
                        session_id=sid, chat_fn=self._chat_fn(user_key), **self.run_kw)
        except Exception as e:
            on_event({"t": self.clock(), "kind": "error", "error": f"{type(e).__name__}"})
        finally:
            user_key = None
            with self._lock:
                s["status"] = "done"

    # ------------------------------------------------------------------ read

    def get(self, sid: str) -> dict | None:
        return self._sessions.get(sid)

    def agent_events_since(self, sid: str, i: int) -> tuple[list[dict], bool]:
        with self._lock:
            s = self._sessions[sid]
            return list(s["events"][i:]), s["status"] == "done"


def make_router(service, studio: Studio | None = None) -> APIRouter:
    st = studio or Studio(service)
    r = APIRouter(prefix="/api/studio")
    r.studio = st  # type: ignore[attr-defined]

    @r.get("/models")
    async def models():
        return {"models": service.config.get("allowed_models", []), "briefs": briefs.BRIEFS,
                "worlds": [w["name"] for w in service.worlds()]}

    @r.post("/start")
    async def start(request: Request):
        ip = client_ip(request)
        try:
            body = json.loads(await request.body() or b"{}")
            if not isinstance(body, dict):
                raise StudioError("The body must be a JSON object.")
            secure = request.headers.get("x-forwarded-proto", "").lower() == "https" or request.url.scheme == "https"
            sid = await asyncio.to_thread(st.start, body, ip, secure=secure, local=not is_public(ip))
        except ValueError:
            return JSONResponse({"detail": "The body is not valid JSON."}, status_code=400)
        except StudioError as e:
            return JSONResponse({"detail": str(e)}, status_code=e.code)
        return {"session_id": sid}

    @r.get("/{session_id}/events")
    async def events(session_id: str, request: Request):
        if st.get(session_id) is None:
            return JSONResponse({"detail": "No such session."}, status_code=404)

        async def gen():
            i, j, case_id = 0, 0, None
            while True:
                evs, done = st.agent_events_since(session_id, i)
                for ev in evs:
                    yield {"event": "agent", "id": f"a{i}", "data": json.dumps(ev, default=str)}
                    i += 1
                case_id = case_id or st.get(session_id)["case_id"]
                tdone = True
                if case_id:
                    tevs, tdone = service.events_since(case_id, j)
                    for ev in tevs:
                        yield {"event": "trial", "id": f"t{j}", "data": json.dumps(ev, default=str)}
                        j += 1
                    tdone = tdone and not tevs
                if done and not evs and tdone:
                    yield {"event": "end", "data": json.dumps({"session_id": session_id, "case_id": case_id})}
                    return
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.2)
        return EventSourceResponse(gen(), ping=15)

    return r
