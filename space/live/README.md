---
title: AlphaCourt live
sdk: gradio
sdk_version: 6.31.0
python_version: "3.12"
app_file: app.py
license: mit
short_description: Put a trading strategy on trial before it trades
models:
  - Qwen/Qwen3-8B
---

# AlphaCourt live

Pick a case from the small docket, or paste a strategy spec as JSON, and put it on trial. A prosecutor, a defence and a judge, all played by Qwen3 8B, run forensic tests on simulated market data, file charges, rebut them and rule: deploy, paper trade, or reject. Every sustained charge must cite an exhibit that exists in the record.

The trial runs on ZeroGPU, so a first call can wait in a queue. The same function is an MCP tool, `put_on_trial(spec_json, claim_sharpe)`.

Everything is simulated. No order is placed.

Authors: Arush Gumber, Sidhant Gumber, Pranav Viksar Garg. MIT licence.
