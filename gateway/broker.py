"""A simulated broker. The gateway never sends an order anywhere: nothing here touches a network, a
real account or a real market. An account is a record in memory (and in the audit file) that says how
much capital a ruling released. Only a ruling releases anything: `deploy` books capital, `paper` books
it as paper capital, `reject` books nothing.
"""
from __future__ import annotations

import threading
import time


class Broker:
    def __init__(self):
        self._accounts: dict[str, dict] = {}
        self._lock = threading.Lock()

    def account(self, session_id: str) -> dict:
        with self._lock:
            return dict(self._accounts.setdefault(session_id, {"session_id": session_id, "live_capital": 0.0,
                                                               "paper_capital": 0.0, "positions": []}))

    def enforce(self, session_id: str, case_id: str, ruling: str, requested_capital: float,
                capital_allowed: float = 0.0, spec_hash: str = "") -> dict:
        """Book the ruling on the session's simulated account and return the action taken."""
        # capital_allowed: a fraction of the request (0 to 1) as the judge gives it, or an amount above 1;
        # 0 or missing means the full request
        ca = float(capital_allowed or 0.0)
        amount = ca if ca > 1 else (requested_capital * ca if ca > 0 else requested_capital)
        amount = max(0.0, float(amount))
        if ruling == "deploy":
            action = {"action": "deploy", "booked": "live (simulated)", "capital": amount}
        elif ruling == "paper":
            action = {"action": "paper", "booked": "paper", "capital": amount}
        else:
            action = {"action": "reject", "booked": "nothing", "capital": 0.0}
        action.update(case_id=case_id, t=time.time(), simulated=True)
        with self._lock:
            acc = self._accounts.setdefault(session_id, {"session_id": session_id, "live_capital": 0.0,
                                                         "paper_capital": 0.0, "positions": []})
            if action["action"] == "deploy":
                acc["live_capital"] += amount
            elif action["action"] == "paper":
                acc["paper_capital"] += amount
            if action["action"] != "reject":
                acc["positions"].append({"case_id": case_id, "spec_hash": spec_hash, "kind": action["action"],
                                         "capital": amount})
        return action
