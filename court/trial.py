"""The trial: clerk, prosecutor, defence, judge, and the exhibit rule enforced in code.

Agents act through a plain JSON action loop. Systems: court, debate, single, battery, none.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from court import roles
from court.types import (CaseFile, Charge, Event, Exhibit, Finding, Rebuttal, ResearchLog, TrialRecord,
                         Verdict, SINS)
from llm.client import ChatResult, chat

SYSTEMS = ("none", "battery", "single", "debate", "court",
           # ablations added after the cold reviews (16 Nov, post hoc): the rule off, and a reviewer given the exhibits
           "court_norule", "single_exhibits", "single_exhibits_rule")
DEFAULT_BUDGET = {"prosecutor_tools": 6, "defence_tools": 4, "max_tokens": 900, "judge_tokens": 900}
VALID_SINS = set(SINS) | {"other"}
RULINGS = ("deploy", "paper", "reject")


class _Ctx:
    """Mutable state of one trial."""

    def __init__(self, case, world, log, staffing, on_event, budget):
        self.case, self.world, self.log, self.staffing = case, world, log, staffing
        self.on_event = on_event
        self.budget = {**DEFAULT_BUDGET, **(budget or {})}
        self.events: list[Event] = []
        self.exhibits: list[Exhibit] = []
        self.calls = self.tokens_in = self.tokens_out = 0

    def emit(self, role: str, kind: str, **data: Any) -> None:
        ev = Event(t=time.time(), role=role, kind=kind, data=data)  # type: ignore[arg-type]
        self.events.append(ev)
        if self.on_event:
            self.on_event(ev)

    def model_for(self, role: str) -> str:
        s = self.staffing
        for k in {"prosecution": ("prosecution", "prosecutor"), "prosecutor": ("prosecutor", "prosecution")}.get(role, (role,)):
            if k in s:
                return s[k]
        for k in ("default", "judge", "reviewer"):
            if k in s:
                return s[k]
        raise KeyError(f"staffing has no model for role {role!r}")

    def ask(self, role: str, messages: list[dict], max_tokens: int) -> str | None:
        model = self.model_for(role)
        try:
            r: ChatResult = chat(model, messages, max_tokens=max_tokens, temperature=0.0)
        except Exception as e:  # noqa: BLE001 - a failed call is a step with no action
            self.calls += 1
            self.emit("system", "error", agent=role, model=model, error=f"{type(e).__name__}: {str(e)[:300]}")
            return None
        self.calls += 1
        self.tokens_in += r.tokens_in
        self.tokens_out += r.tokens_out
        return r.text

    def next_exhibit_id(self) -> str:
        return f"EX-{len(self.exhibits) + 1}"


def _act(ctx: _Ctx, role: str, messages: list[dict], max_tokens: int) -> dict | None:
    """One model step. Malformed output gets one repair attempt, then counts as no action."""
    text = ctx.ask(role, messages, max_tokens)
    if text is None:
        return None
    action = roles.parse_action(text)
    if action is not None:
        messages.append({"role": "assistant", "content": text})
        return action
    messages.append({"role": "assistant", "content": text})
    messages.append({"role": "user", "content": "That was not a valid action. " + roles.ACTION_FORMAT})
    text2 = ctx.ask(role, messages, max_tokens)
    action = roles.parse_action(text2) if text2 else None
    if text2:
        messages.append({"role": "assistant", "content": text2})
    if action is None:
        ctx.emit("system", "error", agent=role, error="malformed output after one repair attempt")
    return action


def _loop(ctx: _Ctx, role: str, system: str, user: str, max_tools: int) -> dict | None:
    """Run tool calls until a final answer. Returns the `final` dict or None."""
    from court import forensics

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    used = 0
    for _ in range(max_tools + 3):
        action = _act(ctx, role, messages, ctx.budget["max_tokens"])
        if action is None:
            return None
        if "final" in action:
            return action["final"]
        if action.get("tool") == "final" and isinstance(action.get("args"), dict):
            return action["args"]  # a model that names its final answer as a tool call
        if used >= max_tools:
            messages.append({"role": "user", "content": "No tool calls are left. Give your final answer now."})
            continue
        used += 1
        name, args = action["tool"], action["args"]
        ctx.emit(role, "tool_call", tool=name, args=args, n=used)
        ex = forensics.run_tool(name, args, ctx.case, ctx.world, ctx.log, exhibit_id=ctx.next_exhibit_id(), called_by=role)
        ctx.exhibits.append(ex)
        ctx.emit(role, "exhibit", **ex.model_dump())
        left = max_tools - used
        messages.append({"role": "user", "content": f"Result:\n{roles.render_exhibit(ex)}\n\n"
                         f"{roles.render_damaging(ctx.exhibits)}\n{left} tool call(s) left."})
    return None


def _clean_ids(v: Any) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else []


def _sin(v: Any) -> str:
    return v if isinstance(v, str) and v in VALID_SINS else "other"


def _charges(final: dict | None) -> list[Charge]:
    out = []
    for c in (final or {}).get("charges", []) if isinstance((final or {}).get("charges"), list) else []:
        if isinstance(c, dict):
            out.append(Charge(sin=_sin(c.get("sin") or c.get("charge")), exhibits=_clean_ids(c.get("exhibits")),
                              argument=str(c.get("argument", ""))[:1200]))  # type: ignore[arg-type]
    return out


def _rebuttals(final: dict | None) -> list[Rebuttal]:
    out = []
    for r in (final or {}).get("rebuttals", []) if isinstance((final or {}).get("rebuttals"), list) else []:
        if isinstance(r, dict):
            out.append(Rebuttal(sin=_sin(r.get("sin") or r.get("charge")), concede=bool(r.get("concede", False)),
                                exhibits=_clean_ids(r.get("exhibits")), argument=str(r.get("argument", ""))[:1200]))  # type: ignore[arg-type]
    return out


def apply_exhibit_rule(verdict: Verdict, valid_ids: set[str]) -> Verdict:
    """Strike sustained findings that cite no damaging exhibit in the record. A paper or reject ruling left with no
    surviving sustained finding becomes deploy, flagged unsupported."""
    findings = []
    for f in verdict.findings:
        cited = [x for x in f.exhibits if x in valid_ids]
        struck = f.sustained and not cited
        findings.append(Finding(sin=f.sin, sustained=f.sustained, exhibits=cited, struck=struck))
    v = verdict.model_copy(update={"findings": findings})
    surviving = [f for f in findings if f.sustained and not f.struck]
    if v.ruling in ("paper", "reject") and not surviving:
        v = v.model_copy(update={"ruling": "deploy", "unsupported": True, "capital_allowed": 1.0})
    return v


def _verdict(final: dict | None, *, rule_ids: set[str] | None) -> Verdict:
    """Build a Verdict from the judge's final. No valid ruling -> paper (the cautious default)."""
    if not final or final.get("ruling") not in RULINGS:
        return Verdict(ruling="paper", capital_allowed=0.0, opinion="No valid ruling was returned; held for paper trading.")
    findings = []
    for f in final.get("findings", []) if isinstance(final.get("findings"), list) else []:
        if isinstance(f, dict):
            findings.append(Finding(sin=_sin(f.get("sin") or f.get("charge")), sustained=bool(f.get("sustained", False)),
                                    exhibits=_clean_ids(f.get("exhibits"))))  # type: ignore[arg-type]
    ruling = final["ruling"]
    try:
        cap = min(1.0, max(0.0, float(final.get("capital_allowed", 1.0 if ruling == "deploy" else 0.0))))
    except (TypeError, ValueError):
        cap = 1.0 if ruling == "deploy" else 0.0
    if ruling != "deploy":
        cap = 0.0
    v = Verdict(ruling=ruling, findings=findings, capital_allowed=cap, opinion=str(final.get("opinion", ""))[:1200])
    return apply_exhibit_rule(v, rule_ids) if rule_ids is not None else v


def run_trial(case: CaseFile, world, log: ResearchLog | None, *, system: str, staffing: dict[str, str],
              on_event: Callable[[Event], None] | None = None, budget: dict | None = None) -> TrialRecord:
    if system not in SYSTEMS:
        raise ValueError(f"unknown system {system!r}; known: {SYSTEMS}")
    t0 = time.time()
    ctx = _Ctx(case, world, log, staffing or {}, on_event, budget)
    ctx.emit("clerk", "case", case_id=case.case_id, system=system, prompt_version=roles.PROMPT_VERSION, staffing=staffing)
    charges: list[Charge] = []
    rebuttals: list[Rebuttal] = []

    if system == "none":
        verdict = Verdict(ruling="deploy", capital_allowed=1.0, opinion="No review: deployed without a trial.")
    elif system == "battery":
        from court import forensics

        ctx.exhibits = forensics.battery(case, world, log)
        for ex in ctx.exhibits:
            ctx.emit("clerk", "exhibit", **ex.model_dump())
        verdict = forensics.battery_ruling(ctx.exhibits)
    elif system == "single":
        user = roles.render_case(case) + "\n\nGive your ruling."
        final = _loop(ctx, "judge", roles.SINGLE_SYSTEM, user, 0)
        verdict = _verdict(final, rule_ids=None)
    elif system in ("single_exhibits", "single_exhibits_rule"):
        from court import forensics

        ctx.exhibits = forensics.battery(case, world, log)  # every test at its defaults, as the battery runs them
        user = roles.render_case(case) + "\n\nExhibits:\n" + roles.render_exhibits(ctx.exhibits) + "\n\nGive your ruling."
        final = _loop(ctx, "judge", roles.JUDGE_SYSTEM, user, 0)
        rule = {e.id for e in ctx.exhibits if e.hint == "damaging"} if system == "single_exhibits_rule" else None
        verdict = _verdict(final, rule_ids=rule)
    elif system == "court_norule":
        verdict, charges, rebuttals = _court_or_debate(ctx, tools=True, enforce=False)
    else:
        verdict, charges, rebuttals = _court_or_debate(ctx, tools=(system == "court"))
    ctx.emit("judge" if system not in ("none", "battery") else "clerk", "verdict", **verdict.model_dump())
    return TrialRecord(case=case, system=system, staffing=staffing or {}, exhibits=ctx.exhibits, charges=charges,
                       rebuttals=rebuttals, verdict=verdict, events=ctx.events, calls=ctx.calls,
                       tokens_in=ctx.tokens_in, tokens_out=ctx.tokens_out, seconds=round(time.time() - t0, 3))


def _court_or_debate(ctx: _Ctx, tools: bool, enforce: bool = True):
    from court import forensics

    case = ctx.case
    tool_text = roles.render_tools(forensics.TOOLS) if tools else "(none)"
    case_text = roles.render_case(case)

    def system_for(template: str, n: int) -> str:
        return template.replace("{max_tools}", str(n)).replace("{tools}", tool_text)

    # prosecution
    n_p = ctx.budget["prosecutor_tools"] if tools else 0
    user = case_text + "\n\n" + ("Investigate with the tools, then file your charges." if tools else roles.NO_TOOLS_NOTE + " File your charges.")
    final = _loop(ctx, "prosecution", system_for(roles.PROSECUTOR_SYSTEM, n_p), user, n_p)
    charges = _charges(final)
    for c in charges:
        ctx.emit("prosecution", "charge", **c.model_dump())

    # defence (skipped when there is nothing to answer)
    rebuttals: list[Rebuttal] = []
    if charges:
        n_d = ctx.budget["defence_tools"] if tools else 0
        user = (case_text + "\n\nExhibits so far:\n" + roles.render_exhibits(ctx.exhibits) + "\n\nCharges:\n" + roles.render_charges(charges)
                + "\n\n" + ("Answer the charges." if tools else roles.NO_TOOLS_NOTE + " Answer the charges."))
        final = _loop(ctx, "defence", system_for(roles.DEFENCE_SYSTEM, n_d), user, n_d)
        rebuttals = _rebuttals(final)
        for r in rebuttals:
            ctx.emit("defence", "rebuttal", **r.model_dump())

    # judge
    user = (case_text + "\n\nExhibits:\n" + roles.render_exhibits(ctx.exhibits) + "\n\nCharges:\n" + roles.render_charges(charges)
            + "\n\nRebuttals:\n" + roles.render_rebuttals(rebuttals) + "\n\nGive your ruling.")
    final = _loop(ctx, "judge", roles.JUDGE_SYSTEM, user, 0)
    # The exhibit rule (dev-split calibration, 16 Nov): a finding counts only if it cites an exhibit whose
    # fixed, published threshold marks it damaging.
    verdict = _verdict(final, rule_ids={e.id for e in ctx.exhibits if e.hint == "damaging"} if (tools and enforce) else None)
    if tools and verdict.unsupported:
        ctx.emit("rule", "note", message="Ruling converted to deploy: no sustained finding cites an exhibit in the record.")
    elif tools and any(f.struck for f in verdict.findings):
        ctx.emit("rule", "note", message="Findings without an exhibit in the record were struck.")
    return verdict, charges, rebuttals
