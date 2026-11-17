# AlphaCourt

No alpha without a trial: an MCP gateway that puts agent-written trading strategies on trial before they trade.

AI agents can now research a trading strategy end to end: read data, read the web, backtest, and write up a claim. The same agent that wrote the strategy also grades it, and the usual failure is a backtest that looks good because of look-ahead, backfilled data, ignored costs, survivorship or an instruction planted in a page the agent read. A single model asked to review a strategy mostly refuses everything, and a fixed battery of tests cannot explain itself.

AlphaCourt is a gateway between a research agent and a simulated broker. The agent connects over MCP, researches, and submits a strategy with a claim. The strategy is held until a court has ruled. A prosecutor and a defence, played by language models, run forensic tests on the simulated market data and file charges and rebuttals; a judge rules deploy, paper trade or reject. Every test run is an exhibit with an identifier, and the ruling is recorded in an audit file.

The exhibit rule is the one design choice that matters most: a sustained charge must cite an exhibit whose fixed threshold marks it damaging, otherwise it is struck, and a rejection with no surviving charge becomes a deploy that is flagged as unsupported. The rule lets a small model approve honest strategies without losing the guilty ones it catches. Everything is simulated; no real order is ever placed.

- Demo: https://alphacourt.vercel.app
- Live court (runs a trial on request): https://arushthegarlic-alphacourt-live.hf.space
- Paper: [`paper/main.pdf`](paper/main.pdf)
- Video: https://youtu.be/EbEt-P5uCX8

## Headline results

Test split of the docket, built from the simulator: 46 guilty and 58 innocent strategies (12 of the innocent ones are unusual but honest). "Guilty stopped" is the number of guilty strategies that were not deployed; "innocent deployed" is the number of honest ones that were. Generated from `results/e1.json` by `scripts/results_table.py`.

| System | Staffing | Cases | Guilty stopped | Innocent deployed |
|---|---|---|---|---|
| No gate | no model | 104 | 0/46 | 58/58 |
| Battery of fixed tests | no model | 104 | 46/46 | 50/58 |
| Single reviewer | Gemini 3.1 Flash-Lite | 104 | 45/46 | 4/58 |
| Single reviewer | Gemma 3 12B | 104 | 42/46 | 3/58 |
| Single reviewer | Qwen3 8B | 104 | 46/46 | 0/58 |
| Debate, no tools | Gemini 3.1 Flash-Lite | 44 | 17/20 | 5/24 |
| Debate, no tools | Gemma 3 12B | 104 | 46/46 | 0/58 |
| Debate, no tools | Qwen3 8B | 104 | 46/46 | 0/58 |
| Court with exhibit rule | Gemma 3 12B | 104 | 26/46 | 48/58 |
| Court with exhibit rule | Qwen3 8B | 104 | 46/46 | 52/58 |

Debate with Gemini 3.1 Flash-Lite ran on a fixed 48-case subset because of API quota. The court with Gemini 3.1 Flash-Lite did not complete and is not reported. Full numbers, intervals and the paired comparisons are in `results/e1.json` to `results/e5.json`; the pre-registered analysis is `experiments/ANALYSIS_PLAN.md`.

## Quick start

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Node 20 or later for the site.

```bash
make setup          # uv sync, and npm install in web/
make test           # runs the Python tests (CPU only, no network)
make web            # builds the site into web/dist
make gateway        # serves the gateway and the built site on http://127.0.0.1:8787
```

Models. Local open models run in a separate process because the main environment does not install torch:

```bash
export ALPHACOURT_TORCH_PYTHON=/path/to/python-with-torch   # default: python
scripts/local_models.sh start                               # serves llm/local_server.py on 127.0.0.1:8791
```

Hosted models read API keys from `ALPHACOURT_KEYS` (default `keys.txt`, ignored by git). Copy `keys.example.txt` and put one key per line. Without keys, the tests and the cached results still work.

Attach an agent over MCP. A gateway you run yourself speaks MCP over streamable HTTP at `http://127.0.0.1:8787/mcp`; the public demo's gateway is at `https://alphacourt.vercel.app/mcp` while it is online; see [`examples/mcp/`](examples/mcp) for Claude Code, Codex and Gemini CLI. For example:

```bash
claude mcp add --transport http alphacourt http://127.0.0.1:8787/mcp
scripts/attach_claude.sh "Find a strategy with a high Sharpe ratio and submit it."   # set CLAUDE_BIN if claude is not on PATH
```

## Reproducing the experiments

Finished trials are saved under `results/trials/` and skipped on re-run, and model calls are cached, so the commands below resume rather than restart.

```bash
scripts/local_models.sh start                  # local staffings
uv run python -m experiments.e1 --split test   # the court against its baselines
uv run python -m experiments.e2 --split test
uv run python -m experiments.e3 --split test
uv run python -m experiments.e4                # attached research agents, neutral and pressure briefs
uv run python -m experiments.e5 --bench        # gateway benchmark
uv run python -m experiments.score e1 e2 e3 e4 e5   # writes results/e1.json ... e5.json
scripts/run_experiments.sh test                # all of the above, then exports the site data
make paper                                     # fills the result slots and builds paper/main.pdf (needs tectonic)
```

The docket is rebuilt from the simulator with `uv run python scripts/build_docket.py all`; it uses no model.

## Repository layout

| Path | Contents |
|---|---|
| `court/` | simulated market, expression language, backtest engine, forensic tools, trial and role prompts |
| `gateway/` | FastAPI app, MCP server, broker, audit log, rate limits |
| `llm/` | model client (local, Google, Groq, command-line agents) and the local model server |
| `agent/`, `alphaweb/` | the research agent loop and the invented web it reads |
| `docket/` | the case docket (dev and test splits) |
| `experiments/` | runners for E1 to E5, the scorer and the analysis plan |
| `web/` | the site (Vite, React, TypeScript) |
| `space/` | the live court app for a hosted Space |
| `paper/` | LaTeX sources and the compiled paper |
| `results/` | saved trials and the scored result files |
| `scripts/` | build, export, deploy and figure scripts |
| `tests/`, `examples/`, `docs/` | tests, MCP client examples, [architecture notes](docs/ARCHITECTURE.md) |

## Citation

```bibtex
@inproceedings{gumber2027alphacourt,
  title     = {{AlphaCourt}: Putting Agent-Written Trading Strategies on Trial Before They Trade},
  author    = {Gumber, Arush and Gumber, Sidhant and Garg, Pranav Viksar and Batra, Naman},
  booktitle = {Companion Proceedings of The ACM Web Conference 2027 (Demo Track)},
  year      = {2027}
}
```

## Licence

MIT, see [`LICENSE`](LICENSE).
