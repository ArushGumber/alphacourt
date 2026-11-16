# Architecture

AlphaCourt sits between a research agent and a (simulated) broker. The agent reads data and pages, backtests, and submits a strategy with a claim about its Sharpe ratio. The strategy does not trade until a court has ruled on it. This document describes the modules, their interfaces and the data flow. Shared types are in `court/types.py`.

## Data flow

```
research agent (any MCP client)
    |  list_fields, field_info, read_page, run_backtest      -> logged as the research log
    |  submit_strategy(spec, claim, capital)                  -> case_id, status "held"
    v
gateway/ (FastAPI, /mcp and /api)
    |  builds a CaseFile, starts a trial in a background worker
    v
court/trial.py  <-- court/roles.py (prompts)    <-- llm/client.py (models)
    |  prosecution and defence call forensic tools; every tool call is an Exhibit
    |  the judge rules on the findings; the exhibit rule is applied
    v
court/forensics.py  -->  court/engine.py, court/expr.py, court/market.py (simulated world)
    v
Verdict: deploy | paper | reject, with capital_allowed in [0, 1]
    v
gateway/broker.py (simulated): deploy or paper only after a verdict; audit record written
```

## Modules

### `court/market.py`, `court/expr.py`, `court/engine.py`

The simulated market and the backtester. All numbers are deterministic given a seed.

- `make_world(seed, *, variant=None, T=3000, N=300) -> World`. Returns come from a factor model with planted effects (momentum, short-term reversal that dies after costs, point-in-time post-earnings drift, low volatility, a sentiment effect, regime dependence) and a delisting process tied to bad returns. A `World` holds `fields`, `field_info` (documented availability), `asof` (the point-in-time version of every field), `alive`, `universe_files`, `regime`, `cost_bps_true` and the generating `params`. Some fields are leaky by construction: restated earnings placed at period end, revised sentiment that includes the next bar's return, index membership as of today. `variant` builds twin worlds that differ in one thing, for example `{"backfilled": ["eps_reported"]}` or `{"default_universe": "survivors"}`. Research tools never see bars at or after `research_end`.
- `expr.parse(signal) -> Expr` and `expr.evaluate(expr, world, *, mode, upto)`. A small expression language: `rank, zscore, ts_mean, ts_std, ts_sum, delta, delay, winsor, sign, abs, log`, arithmetic, numbers and field names. `zscore_full` and `winsor_full` use statistics over the whole sample (a look-ahead footgun). `mode="strict"` replaces every field by its `asof` version and evaluates full-sample operators on expanding windows.
- `engine.run_backtest(spec, world, *, mode, period, cost_bps, lag_extra, universe, sample) -> BacktestResult`. Weights computed at bar t earn the return of bar t+lag. Defaults come from the spec; the overrides exist for the forensic tests.
- `engine.true_edge(spec, world, seeds=...)` is the ground truth used to score the court: strict mode, lag of at least one bar, the full universe, realistic costs, the sealed period, averaged over fresh noise seeds. No model is involved.
- `engine.spec_hash(spec)` is the first 12 hex characters of the sha256 of the canonical JSON.

### `court/forensics.py`

`TOOLS` maps a tool name to its description and arguments. `run_tool(name, args, case, world, log, *, exhibit_id, called_by) -> Exhibit` runs one test; an unknown tool or bad arguments give a neutral exhibit with an error summary, never an exception. The tools are `lag_test`, `pit_replay`, `cost_test`, `survivorship_test`, `holdout_test`, `regime_split`, `trial_haircut` (expected maximum Sharpe of N trials under no edge), `placebo_test`, `param_stability`, `day_concentration` and `note_scan` (text in notes or in pages read that is addressed to reviewers). Each exhibit has a one-sentence `summary`, a `hint` from fixed thresholds, and a small `chart`. `battery(case, world, log)` runs every tool at its defaults and `battery_ruling(exhibits)` rules with fixed thresholds and no model; it is the non-model baseline.

### `court/trial.py` and `court/roles.py`

`run_trial(case, world, log, *, system, staffing, on_event=None, budget=None) -> TrialRecord`.

- `system="court"`: a prosecutor (up to 6 tool calls), a defence (up to 4) and a judge. `"debate"` uses the same roles with no tools. `"single"` is one reviewer reading the case file. `"battery"` is the fixed battery. `"none"` always deploys.
- `staffing` maps `prosecution`, `defence` and `judge` to model ids, with `default` as a fallback.
- Agents act through a JSON action loop: `{"tool": name, "args": {...}}` or `{"final": {...}}`, with one repair attempt on malformed output.
- The exhibit rule applies to `system="court"`: a sustained finding that cites no exhibit in the record is struck. A `paper` or `reject` ruling with no surviving sustained finding becomes `deploy`, flagged `unsupported`. A judge with no valid ruling yields `paper` with `defaulted=True`.
- `roles.py` holds the role prompts (versioned by `PROMPT_VERSION`) and the rendering of a case and of exhibits as text.

### `llm/`

`client.chat(model, messages, *, max_tokens, temperature, json_mode) -> ChatResult` is the single entry point. Model ids have a prefix: `local:<name>` (the server in `llm/local_server.py`, OpenAI-style `/v1/chat/completions` on 127.0.0.1:8791, one model loaded at a time), `google:<model>` (AI Studio REST with key rotation, per-key rate limiting and backoff), `groq:<model>` (OpenAI-compatible), and `claude:<name>` and `codex:<name>` through their command-line tools under hard call caps in `llm/budget.json`. Responses are cached on disk under `results/cache/llm/`, keyed by the sha256 of model, messages, `max_tokens` and temperature, so a re-run costs nothing. API keys are read from the file named by `ALPHACOURT_KEYS` (one key per line) and never printed or logged.

### `gateway/`

- `service.py`: `GatewayService` with `list_fields`, `field_info`, `read_page`, `run_backtest` (naive mode, research period, logged as a `Trial`), `submit_strategy -> {case_id, status: "held", watch_url}` and `get_verdict`. Submitting builds the `CaseFile`, starts the trial in a background worker and enforces the verdict through `broker.py`.
- `mcp.py`: the six tools above as MCP over streamable HTTP (JSON-RPC at `/mcp`).
- `app.py`: the FastAPI app. `/mcp`, an HTTP mirror under `/api/` for the site, server-sent events at `/api/cases/{id}/events`, `/api/health`. It serves the built site from `web/dist` when present.
- `guard.py`: rate limits and caps. `store.py`: cases, logs, trial records and audit records as JSON files under `results/gateway/`, so a restart resumes where it stopped. `audit.py`: one audit record per case (submission, log summary, exhibits, charges, rebuttals, verdict, model ids, timings, hashes). `studio.py`: the endpoints behind the Studio page. `broker.py`: the simulated broker. No real order is placed.
- `config.json`: the default staffing and the named demo worlds.

### `alphaweb/` and `agent/`

`alphaweb/pages.py` is a small invented corner of the internet (all addresses are on `.example` domains) that an agent reads through `read_page`; two pages carry text addressed to reviewers. `agent/research.py` is a plain JSON action loop that plays a research agent against the gateway, in process or over HTTP, and saves each session. `agent/briefs.py` holds the neutral and the pressure briefs.

### `docket/`

`build.py` builds the docket from the simulator alone, with no model call: twin pairs (a guilty case and an innocent one), difficulty levels, unusual innocents, attack copies, ground truth from `true_edge` and synthesised research logs. `cases/` holds the built dev and test splits and `index.json` their index.

### `experiments/`

`e1.py` to `e5.py` are the runners, `runner.py` the shared trial runner, `score.py` the scorer that writes `results/e*.json`. `ANALYSIS_PLAN.md` is the pre-registered analysis plan, written before the test split was run. Trials are saved under `results/trials/` and finished trials are skipped on re-run.

### `web/`, `space/`, `paper/`

`web/` is the site (Vite, React, TypeScript, Tailwind), reading `web/public/data/*.json` written by `scripts/export_site.py`. `space/live/` is the Gradio app that runs a trial on a hosted Space. `paper/` holds the LaTeX sources; `scripts/make_paper.py` fills the result slots in the `*.tex.in` templates from `results/*.json` so every number in the paper comes from a saved file.

## Conventions

- Python 3.12 with `uv`. Tests (`uv run pytest`) run on CPU, with no network.
- Every function that produces a reported number is deterministic given its inputs and seed.
- Local model inference runs in a separate process (`llm/local_server.py`) because the main environment does not install torch; point `ALPHACOURT_TORCH_PYTHON` at an interpreter that has it.
