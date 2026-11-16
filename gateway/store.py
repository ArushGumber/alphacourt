"""File store for the gateway: cases, research logs, trial records, events and audit records as JSON.

Everything lives under one root (default `results/gateway/`), so a restart resumes where it stopped.
There is no database.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "results" / "gateway"
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_name(name: str) -> str:
    return _SAFE.sub("_", name)[:120]


class Store:
    def __init__(self, base: Path | str | None = None):
        self.base = Path(base) if base else DEFAULT_DIR
        for d in ("cases", "logs", "records", "events", "audit"):
            (self.base / d).mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}

    def _path(self, kind: str, key: str, ext: str = "json") -> Path:
        return self.base / kind / f"{safe_name(key)}.{ext}"

    def write(self, kind: str, key: str, obj: Any) -> Path:
        p = self._path(kind, key)
        tmp = p.with_suffix(".tmp")
        with self._lock:
            tmp.write_text(json.dumps(obj, indent=2, default=str))
            os.replace(tmp, p)
        return p

    def read(self, kind: str, key: str) -> Any | None:
        p = self._path(kind, key)
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return None

    def keys(self, kind: str) -> list[str]:
        return sorted(p.stem for p in (self.base / kind).glob("*.json"))

    def append_event(self, case_id: str, event: dict) -> None:
        with self._lock, self._path("events", case_id, "jsonl").open("a") as f:
            f.write(json.dumps(event, default=str) + "\n")

    def read_events(self, case_id: str) -> list[dict]:
        p = self._path("events", case_id, "jsonl")
        out = []
        try:
            for line in p.read_text().splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        except OSError:
            pass
        return out

    def next_id(self, prefix: str) -> str:
        """AC-0001, AC-0002, ... continuing after the highest id on disk."""
        with self._lock:
            if prefix not in self._counters:
                hi = 0
                for p in (self.base / "cases").glob(f"{prefix}-*.json"):
                    m = re.fullmatch(rf"{prefix}-(\d+)", p.stem)
                    if m:
                        hi = max(hi, int(m.group(1)))
                self._counters[prefix] = hi
            self._counters[prefix] += 1
            return f"{prefix}-{self._counters[prefix]:04d}"
