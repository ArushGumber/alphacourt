"""One function, chat(), for every model backend, with a disk cache keyed by the request.

Model ids: local:<name> (llm/local_server.py), google:<model>, groq:<model>, claude:<alias>, codex:<model>,
fake:<name> (scripted replies for tests, see register_fake). Keys are read from the key file or the
environment and are never logged or written.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "results" / "cache" / "llm"
BUDGET_FILE = ROOT / "llm" / "budget.json"
KEY_FILE = Path(os.environ.get("ALPHACOURT_KEYS", str(ROOT / "keys.txt")))
LOCAL_URL = os.environ.get("ALPHACOURT_LOCAL_URL", "http://127.0.0.1:8791")
GOOGLE_RPM = float(os.environ.get("ALPHACOURT_GOOGLE_RPM", "5"))  # per key; set from results/model_probe.json
FORBIDDEN = ("astra",)  # never call gpt-6-astra
LOCAL_BIN = Path.home() / ".local" / "bin"


@dataclass
class ChatResult:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    cached: bool = False


class LLMError(RuntimeError):
    pass


class BudgetExceeded(LLMError):
    pass


# ---------------------------------------------------------------- fakes

_FAKES: dict[str, Callable[[list[dict]], str]] = {}


def register_fake(name: str, fn: Callable[[list[dict]], str]) -> None:
    """fake:<name> calls fn(messages) -> text. Not cached, no network."""
    _FAKES[name] = fn


# ---------------------------------------------------------------- in-process model (space:<name>)

_SPACE: Callable[[str, list[dict], int], tuple[str, int, int]] | None = None


def register_space(fn: Callable[[str, list[dict], int], tuple[str, int, int]] | None) -> None:
    """space:<name> calls fn(name, messages, max_tokens) -> (text, tokens_in, tokens_out) inside this process
    (the Hugging Face Space loads the model itself). Not cached."""
    global _SPACE
    _SPACE = fn


# ---------------------------------------------------------------- cache

def cache_key(model: str, messages: list[dict], max_tokens: int, temperature: float, json_mode: bool = False) -> str:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["json_mode"] = True
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / key[:2] / f"{key}.json"


def _cache_get(key: str) -> dict | None:
    p = _cache_path(key)
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _cache_put(key: str, rec: dict) -> None:
    p = _cache_path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False))
    os.replace(tmp, p)


# ---------------------------------------------------------------- budget (claude, codex)

def _take_budget(provider: str) -> None:
    """Count one call against the hard cap, before the call is made. Every attempt counts."""
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BUDGET_FILE, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            b = json.loads(f.read() or "{}")
        except json.JSONDecodeError:
            b = {}
        b.setdefault("claude", {"cap": 150, "used": 0})
        b.setdefault("codex", {"cap": 100, "used": 0})
        e = b[provider]
        if e["used"] >= e["cap"]:
            raise BudgetExceeded(f"{provider}: cap of {e['cap']} calls reached")
        e["used"] += 1
        f.seek(0)
        f.truncate()
        f.write(json.dumps(b))
        fcntl.flock(f, fcntl.LOCK_UN)


def budget_status() -> dict:
    try:
        return json.loads(BUDGET_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------- keys

def _load_keys() -> tuple[list[str], list[str]]:
    google, groq = [], []
    try:
        for line in KEY_FILE.read_text().splitlines():
            k = line.strip()
            if k.startswith("AIza"):
                google.append(k)
            elif k.startswith("gsk_"):
                groq.append(k)
    except OSError:
        pass
    for k in os.environ.get("GOOGLE_API_KEYS", "").split(","):
        if k.strip().startswith("AIza") and k.strip() not in google:
            google.append(k.strip())
    if os.environ.get("GROQ_API_KEY") and os.environ["GROQ_API_KEY"] not in groq:
        groq.append(os.environ["GROQ_API_KEY"])
    return google, groq


class _KeyPool:
    """Round-robin over keys. Each key has a token bucket (requests per minute) and a cooldown after a 429."""

    def __init__(self, keys: list[str], rpm: float):
        self.keys = keys
        self.interval = 60.0 / rpm
        self.next_ok = [0.0] * len(keys)  # earliest time each key may be used again
        self.rr = 0
        self.lock = threading.Lock()

    def acquire(self) -> int:
        while True:
            with self.lock:
                now = time.time()
                n = len(self.keys)
                best, best_t = None, None
                for off in range(n):
                    i = (self.rr + off) % n
                    if best_t is None or self.next_ok[i] < best_t:
                        best, best_t = i, self.next_ok[i]
                    if self.next_ok[i] <= now:
                        break
                if best_t <= now:
                    self.next_ok[best] = now + self.interval
                    self.rr = (best + 1) % n
                    return best
                wait = best_t - now
            time.sleep(min(wait, 1.0))

    def cooldown(self, i: int, seconds: float) -> None:
        with self.lock:
            self.next_ok[i] = max(self.next_ok[i], time.time() + seconds)


_pools: dict[str, _KeyPool] = {}
_pool_lock = threading.Lock()


def _pool(kind: str) -> _KeyPool:
    with _pool_lock:
        if kind not in _pools:
            google, groq = _load_keys()
            keys = google if kind == "google" else groq
            if not keys:
                raise LLMError(f"no {kind} keys available")
            rpm = GOOGLE_RPM if kind == "google" else float(os.environ.get("ALPHACOURT_GROQ_RPM", "20"))
            _pools[kind] = _KeyPool(keys, rpm)
        return _pools[kind]


# ---------------------------------------------------------------- backends

def _retry_after(r: httpx.Response) -> float | None:
    v = r.headers.get("retry-after")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _http_retry(kind: str, send: Callable[[str], httpx.Response], attempts: int | None = None) -> httpx.Response:
    pool = _pool(kind)
    attempts = attempts or max(8, 2 * len(pool.keys))  # a busy key is cooled down and the next key is tried
    last = ""
    for a in range(attempts):
        i = pool.acquire()
        key = pool.keys[i]
        try:
            r = send(key)
        except httpx.HTTPError as e:
            last = f"{type(e).__name__}"
            time.sleep(min(2 ** a, 20) + random.random())
            continue
        if r.status_code == 200:
            return r
        if r.status_code == 400 and "tool_use_failed" in r.text:
            return r  # a model that emitted a native tool call; the caller recovers it
        last = f"HTTP {r.status_code}: {r.text[:200].replace(key, '<key>')}"
        if r.status_code == 403 and "leaked" in r.text.lower():
            pool.cooldown(i, 1e9)  # the provider has disabled this key
        elif r.status_code in (429, 403) or "quota" in r.text.lower():
            pool.cooldown(i, _retry_after(r) or min(30 * (a + 1), 120))
            time.sleep(1 + random.random())
        elif r.status_code == 400 and "api key not valid" in r.text.lower():
            pool.cooldown(i, 1e9)  # invalid key: never use it again
        elif r.status_code == 404 and len(pool.keys) > 1:
            pool.cooldown(i, 3600)  # model not offered to this key
        elif r.status_code >= 500:
            time.sleep(min(2 ** a, 20) + random.random())
        else:
            raise LLMError(last)
    raise LLMError(f"{kind}: failed after {attempts} attempts ({last})")


def _google(model: str, messages, max_tokens, temperature, json_mode) -> tuple[str, int, int]:
    sys_text = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] != "system"]
    gen = {"maxOutputTokens": max_tokens, "temperature": temperature}
    if json_mode:
        gen["responseMimeType"] = "application/json"
    if model.startswith("gemini-2.5") and "pro" not in model:
        gen["thinkingConfig"] = {"thinkingBudget": 0}
    elif model.startswith("gemini-3") and "pro" not in model:
        gen["thinkingConfig"] = {"thinkingLevel": "minimal"}
    body = {"contents": contents, "generationConfig": gen}
    if sys_text:
        body["systemInstruction"] = {"parts": [{"text": sys_text}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    r = _http_retry("google", lambda k: httpx.post(url, headers={"x-goog-api-key": k}, json=body, timeout=60))
    j = r.json()
    cands = j.get("candidates") or []
    parts = (cands[0].get("content", {}).get("parts") or []) if cands else []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    u = j.get("usageMetadata") or {}
    return text, int(u.get("promptTokenCount", 0)), int(u.get("candidatesTokenCount", 0)) + int(u.get("thoughtsTokenCount", 0))


def _groq(model: str, messages, max_tokens, temperature, json_mode) -> tuple[str, int, int]:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if "gpt-oss" in model:
        # reasoning models spend completion tokens on hidden reasoning first; keep it short and leave room for the answer
        body["reasoning_effort"] = "low"
        body["max_tokens"] = max_tokens + 1024
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = _http_retry("groq", lambda k: httpx.post("https://api.groq.com/openai/v1/chat/completions",
                                                 headers={"Authorization": f"Bearer {k}"}, json=body, timeout=120))
    j = r.json()
    if r.status_code == 400:
        # gpt-oss sometimes answers with a native tool call although none is offered; turn it into our JSON action
        gen = (j.get("error") or {}).get("failed_generation") or ""
        try:
            call = json.loads(gen)
            name = str(call.get("name", "")).split(".")[-1]
            args = call.get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            return json.dumps({"tool": name, "args": args}), 0, 0
        except Exception:
            return gen, 0, 0
    u = j.get("usage") or {}
    return j["choices"][0]["message"]["content"] or "", int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))


def _local(model: str, messages, max_tokens, temperature, json_mode) -> tuple[str, int, int]:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    last = ""
    for a in range(3):
        try:
            r = httpx.post(f"{LOCAL_URL}/v1/chat/completions", json=body, timeout=1800)
        except httpx.HTTPError as e:
            last = f"{type(e).__name__}: local server not reachable (scripts/local_models.sh start)"
            time.sleep(2 + a * 3)
            continue
        if r.status_code == 200:
            j = r.json()
            u = j.get("usage") or {}
            return j["choices"][0]["message"]["content"], int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
        last = f"HTTP {r.status_code}: {r.text[:200]}"
        if r.status_code < 500:
            break
        time.sleep(3)
    raise LLMError(f"local: {last}")


def _clean_env() -> dict:
    env = {k: os.environ[k] for k in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "SHELL") if k in os.environ}
    env.setdefault("LANG", "C.UTF-8")
    env["PATH"] = ":".join([str(LOCAL_BIN), "/usr/local/bin", "/usr/bin", "/bin"])
    env["TERM"], env["NO_COLOR"], env["DISABLE_AUTOUPDATER"] = "dumb", "1", "1"
    return env


def _fresh_dir() -> str:
    d = tempfile.mkdtemp(dir="/tmp")  # outside the project, so the tool shows the model nothing about it
    return d


def _split_system(messages) -> tuple[str, str]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [m for m in messages if m["role"] != "system"]
    if len(rest) == 1:
        return system, rest[0]["content"]
    return system, "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in rest)


def _claude(alias: str, messages, max_tokens, temperature, json_mode) -> tuple[str, int, int]:
    system, user = _split_system(messages)
    cmd = [str(LOCAL_BIN / "claude"), "-p", "--model", alias, "--system-prompt", system or "You are a helpful assistant.",
           "--output-format", "json", "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence", "--effort", "low"]
    last = ""
    for a in range(2):
        _take_budget("claude")
        d = _fresh_dir()
        try:
            p = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=d, env=_clean_env(), timeout=600)
        except subprocess.TimeoutExpired:
            last = "timeout"
            continue
        finally:
            shutil.rmtree(d, ignore_errors=True)
        obj = None
        for line in reversed((p.stdout or "").strip().splitlines()):
            if line.strip().startswith("{"):
                try:
                    c = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if c.get("type") == "result":
                    obj = c
                    break
        if obj is None or obj.get("is_error") or p.returncode != 0:
            last = f"claude cli failed: {(obj or {}).get('result') or (p.stderr or '')[-200:]}"[:300]
            if re.search(r"usage limit|limit reached|not logged in|credit balance", last, re.I):
                break
            continue
        u = obj.get("usage") or {}
        tin = int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)
        return str(obj.get("result") or ""), tin, int(u.get("output_tokens") or 0)
    raise LLMError(last)


def _codex(model: str, messages, max_tokens, temperature, json_mode) -> tuple[str, int, int]:
    if any(f in model.lower() for f in FORBIDDEN):
        raise ValueError(f"model {model!r} is excluded")
    system, user = _split_system(messages)
    last = ""
    for a in range(2):
        _take_budget("codex")
        d, aux = _fresh_dir(), tempfile.mkdtemp(dir="/tmp")
        try:
            sf, of = os.path.join(aux, "system.md"), os.path.join(aux, "answer.txt")
            Path(sf).write_text(system or "You are a helpful assistant.")
            cmd = [str(LOCAL_BIN / "codex"), "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
                   "--ignore-rules", "-s", "read-only", "-C", d, "-m", model, "--json", "--color", "never", "-o", of,
                   "-c", 'model_reasoning_effort="low"', "-c", f"model_instructions_file={json.dumps(sf)}",
                   "-c", "include_environment_context=false", "-c", "include_permissions_instructions=false",
                   "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"']
            for feat in ("apps", "plugins", "shell_tool", "view_image", "image_generation", "browser_use",
                         "computer_use", "hooks", "multi_agent"):
                cmd += ["--disable", feat]
            cmd.append("-")
            try:
                p = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=d, env=_clean_env(), timeout=600)
            except subprocess.TimeoutExpired:
                last = "timeout"
                continue
            text = Path(of).read_text() if os.path.exists(of) else ""
        finally:
            shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(aux, ignore_errors=True)
        if p.returncode != 0 or not text.strip():
            last = f"codex cli failed: {(p.stderr or '')[-200:]}"[:300]
            if re.search(r"usage limit|not logged in|quota", last, re.I):
                break
            continue
        tin = tout = 0
        for line in (p.stdout or "").splitlines():
            if '"usage"' in line:
                try:
                    u = (json.loads(line).get("usage") or {})
                    tin, tout = int(u.get("input_tokens") or tin), int(u.get("output_tokens") or tout)
                except (json.JSONDecodeError, ValueError, AttributeError):
                    pass
        return text, tin, tout
    raise LLMError(last)


# ---------------------------------------------------------------- the entry point

def chat(model: str, messages: list[dict], *, max_tokens: int = 800, temperature: float = 0.0,
         json_mode: bool = False) -> ChatResult:
    provider, _, name = model.partition(":")
    if provider == "fake":
        t0 = time.time()
        fn = _FAKES.get(name)
        if fn is None:
            raise LLMError(f"no fake registered as {name!r}")
        text = fn(messages)
        return ChatResult(text, model, sum(len(m["content"]) for m in messages) // 4, len(text) // 4, time.time() - t0)
    if provider == "space":
        if _SPACE is None:
            raise LLMError("no in-process model registered (register_space)")
        t0 = time.time()
        text, tin, tout = _SPACE(name, messages, max_tokens)
        if not text.strip():
            raise LLMError(f"{model}: empty reply")
        return ChatResult(text, model, tin, tout, time.time() - t0)
    if provider not in ("local", "google", "groq", "claude", "codex"):
        raise ValueError(f"unknown model id {model!r}")
    if provider == "codex" and any(f in name.lower() for f in FORBIDDEN):
        raise ValueError(f"model {model!r} is excluded")
    key = cache_key(model, messages, max_tokens, temperature, json_mode)
    hit = _cache_get(key)
    if hit is not None:
        return ChatResult(hit["text"], model, hit.get("tokens_in", 0), hit.get("tokens_out", 0), 0.0, True)
    t0 = time.time()
    fn = {"local": _local, "google": _google, "groq": _groq, "claude": _claude, "codex": _codex}[provider]
    text, tin, tout = fn(name, messages, max_tokens, temperature, json_mode)
    dt = time.time() - t0
    if not text.strip():
        raise LLMError(f"{model}: empty reply")
    _cache_put(key, {"text": text, "tokens_in": tin, "tokens_out": tout, "seconds": round(dt, 3), "model": model})
    return ChatResult(text, model, tin, tout, dt, False)
