"""AlphaCourt live: put a strategy on trial with a court staffed by Qwen3 8B, on ZeroGPU. Also an MCP tool."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import gradio as gr
import spaces
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from court.engine import run_backtest
from court.market import make_world
from court.trial import run_trial
from court.types import CaseFile, Claim, ResearchLog, StrategySpec, Trial
from llm import client

HERE = Path(__file__).resolve().parent
REPO = os.environ.get("ALPHACOURT_SPACE_MODEL", "Qwen/Qwen3-8B")
MODEL_ID = "space:" + REPO.split("/")[-1].lower()
DOCKET = json.loads((HERE / "docket.json").read_text())["cases"]
BY_ID = {c["id"]: c for c in DOCKET}
MAX_NEW = 700
GPU_SECONDS = int(os.environ.get("ALPHACOURT_GPU_SECONDS", "120"))

tok = AutoTokenizer.from_pretrained(REPO)
model = AutoModelForCausalLM.from_pretrained(REPO, dtype=torch.bfloat16).to("cuda").eval()


def _generate(name: str, messages: list[dict], max_tokens: int) -> tuple[str, int, int]:
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    ids = tok(text, return_tensors="pt").to("cuda")
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=min(max_tokens, MAX_NEW), do_sample=False)
    new = out[0, ids["input_ids"].shape[1]:]
    return tok.decode(new, skip_special_tokens=True), int(ids["input_ids"].shape[1]), int(new.shape[0])


client.register_space(_generate)


def build_case(case_id: str, spec: StrategySpec, claim_sharpe: float | None, world_cfg: dict, text: str):
    world = make_world(int(world_cfg.get("seed", 1)), variant=world_cfg.get("variant"))
    bt = run_backtest(spec, world, mode="naive")
    h = bt.spec_hash
    log = ResearchLog(session_id=case_id, agent="visitor", trials=[Trial(t=time.time(), spec_hash=h, spec=spec,
                      metrics=bt.metrics)], submitted_spec_hash=h)
    sharpe = bt.metrics.sharpe if claim_sharpe is None else float(claim_sharpe)
    case = CaseFile(case_id=case_id, world_id=world.world_id, spec=spec,
                    claim=Claim(sharpe=sharpe, ann_return=bt.metrics.ann_return, max_drawdown=bt.metrics.max_drawdown,
                                text=text),
                    log_summary={"n_trials": 1, "n_distinct_specs": 1, "best_of": 1, "is_best": True})
    return case, world, log


@spaces.GPU(duration=GPU_SECONDS)
def _trial(case, world, log):
    return run_trial(case, world, log, system="court", staffing={"default": MODEL_ID})


def markdown(rec) -> str:
    c, v = rec.case, rec.verdict
    L = [f"## Case {c.case_id}: {c.spec.name}", "",
         f"Signal `{c.spec.signal}`, lag {c.spec.lag}, costs {c.spec.costs_bps:g} bps. "
         f"Claimed Sharpe **{c.claim.sharpe:.2f}**. Court staffed by `{MODEL_ID.removeprefix('space:')}`.", "",
         "### Exhibits"]
    for e in rec.exhibits:
        L.append(f"- **{e.id}** ({e.test}, called by {e.called_by}, {e.hint}): {e.summary}")
    if not rec.exhibits:
        L.append("- none")
    L += ["", "### Charges"]
    for ch in rec.charges:
        L.append(f"- **{ch.sin}** citing {', '.join(ch.exhibits) or 'no exhibit'}: {ch.argument}")
    if not rec.charges:
        L.append("- none")
    L += ["", "### Rebuttals"]
    for r in rec.rebuttals:
        L.append(f"- **{r.sin}** ({'conceded' if r.concede else 'contested'}), "
                 f"citing {', '.join(r.exhibits) or 'no exhibit'}: {r.argument}")
    if not rec.rebuttals:
        L.append("- none")
    L += ["", f"### Ruling: {v.ruling.upper()} (capital allowed {v.capital_allowed:.0%})"]
    for f in v.findings:
        L.append(f"- {f.sin}: {'struck' if f.struck else 'sustained' if f.sustained else 'dismissed'} "
                 f"({', '.join(f.exhibits) or 'no exhibit'})")
    if v.unsupported:
        L.append("- The ruling had no supported finding and was converted to deploy.")
    if v.defaulted:
        L.append("- The judge gave no valid ruling; the cautious default was used.")
    L += ["", v.opinion, "", f"{rec.calls} model calls, {rec.tokens_in} tokens in, {rec.tokens_out} out, "
          f"{rec.seconds:.0f} s."]
    return "\n".join(L)


def _run(spec: StrategySpec, claim_sharpe, world_cfg, case_id, text):
    case, world, log = build_case(case_id, spec, claim_sharpe, world_cfg, text)
    rec = _trial(case, world, log)
    return rec


def put_on_trial(spec_json: str, claim_sharpe: float | None = None) -> dict:
    """Put a trading strategy on trial before it trades, and return the verdict and the exhibits.

    A prosecutor, a defence and a judge (all Qwen3 8B) run forensic tests on simulated data, file charges and rule.

    Args:
        spec_json: The strategy as a JSON object with name, signal (for example "rank(ts_mean(ret, 20))"), lag,
            rebalance, costs_bps and universe. A strategy is data, never code.
        claim_sharpe: The Sharpe ratio the submitter claims. Leave empty to claim what the backtest shows.

    Returns:
        The ruling (deploy, paper or reject), the capital allowed, the findings, the opinion and every exhibit.
    """
    try:
        spec = StrategySpec.model_validate_json(spec_json)
        from court.expr import parse
        parse(spec.signal)
    except Exception as e:
        raise gr.Error(f"The spec is not valid: {str(e)[:300]}")
    rec = _run(spec, claim_sharpe, {"seed": 1, "variant": None}, "mcp-" + str(int(time.time())), "Submitted over MCP.")
    v = rec.verdict
    return {"ruling": v.ruling, "capital_allowed": v.capital_allowed, "opinion": v.opinion,
            "findings": [f.model_dump() for f in v.findings], "exhibits": [e.model_dump(exclude={"chart"}) for e in rec.exhibits],
            "unsupported": v.unsupported, "defaulted": v.defaulted, "calls": rec.calls, "seconds": rec.seconds}


def trial_ui(case_id: str, spec_json: str, claim_sharpe):
    try:
        if spec_json and spec_json.strip():
            spec = StrategySpec.model_validate_json(spec_json)
            from court.expr import parse
            parse(spec.signal)
            cfg, cid, text = {"seed": 1, "variant": None}, "visitor-" + str(int(time.time())), "Pasted by a visitor."
            claim = None if claim_sharpe in (None, "") else float(claim_sharpe)
        else:
            c = BY_ID.get(case_id)
            if c is None:
                raise gr.Error("Pick a case or paste a spec.")
            spec = StrategySpec.model_validate(c["spec"])
            cfg, cid, text = c["world"], c["id"], c["claim"].get("text", "")
            claim = c["claim"]["sharpe"] if claim_sharpe in (None, "") else float(claim_sharpe)
    except gr.Error:
        raise
    except Exception as e:
        raise gr.Error(f"The spec is not valid: {str(e)[:300]}")
    rec = _run(spec, claim, cfg, cid, text)
    return markdown(rec), json.loads(rec.model_dump_json(exclude={"events"}))


def load_case(case_id: str):
    c = BY_ID.get(case_id)
    return (json.dumps(c["spec"], indent=1), c["claim"]["sharpe"]) if c else ("", None)


with gr.Blocks(title="AlphaCourt live") as demo:
    gr.Markdown("# AlphaCourt live\nPut a trading strategy on trial. A prosecutor, a defence and a judge (Qwen3 8B) "
                "run forensic tests on simulated data and rule: deploy, paper, or reject. Everything is simulated.")
    with gr.Row():
        with gr.Column(scale=3):
            case = gr.Dropdown(choices=[(c["title"], c["id"]) for c in DOCKET], value=DOCKET[0]["id"] if DOCKET else None,
                               label="Docket case")
            spec_box = gr.Code(label="Strategy spec (JSON). Leave empty to use the docket case.", language="json",
                               value="", lines=14)
            claim = gr.Number(label="Claimed Sharpe (empty: the case's claim, or what the backtest shows)")
            go = gr.Button("Put on trial", variant="primary")
        with gr.Column(scale=4):
            transcript = gr.Markdown()
            raw = gr.JSON(label="Trial record (JSON)")
    case.change(load_case, case, [spec_box, claim], api_name=False)
    demo.load(load_case, case, [spec_box, claim], api_name=False)
    go.click(trial_ui, [case, spec_box, claim], [transcript, raw], api_name="trial")
    gr.api(put_on_trial, api_name="put_on_trial")

demo.queue(max_size=8, default_concurrency_limit=1)

if __name__ == "__main__":
    demo.launch(mcp_server=True)
