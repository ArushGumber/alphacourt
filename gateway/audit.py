"""The audit record: one JSON file per case, what a compliance officer would file."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .store import Store


def sha12(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def write_audit(store: Store, *, case: dict, record: dict | None, broker_action: dict | None, status: str,
                staffing: dict, system: str, spec_hash: str, world_hash: str, prompt_version: str,
                timings: dict, error: str | None = None) -> dict:
    rec = record or {}
    audit = {
        "case_id": case["case_id"],
        "status": status,
        "submission": {"spec": case.get("spec"), "claim": case.get("claim"),
                       "requested_capital": case.get("requested_capital"), "world_id": case.get("world_id")},
        "log_summary": case.get("log_summary", {}),
        "pages_read": case.get("pages_read", []),
        "system": system,
        "staffing": staffing,
        "model_ids": sorted(set(staffing.values())),
        "exhibits": rec.get("exhibits", []),
        "charges": rec.get("charges", []),
        "rebuttals": rec.get("rebuttals", []),
        "verdict": rec.get("verdict"),
        "broker_action": broker_action,
        "calls": rec.get("calls"), "tokens_in": rec.get("tokens_in"), "tokens_out": rec.get("tokens_out"),
        "timings": timings,
        "prompt_version": prompt_version,
        "hashes": {"spec": spec_hash, "world": world_hash},
        "error": error,
    }
    store.write("audit", case["case_id"], audit)
    return audit
