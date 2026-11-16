"""Throughput of the local server: calls per minute at about 2k tokens in and up to 300 out."""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
import httpx
model, n, conc = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
filler = " ".join(f"Row {i}: strategy variant {i} tested with window {10 + i % 90}, Sharpe {1 + (i % 17) / 10:.2f}." for i in range(80))
def one(i):
    msgs = [{"role": "system", "content": "You are a careful reviewer."},
            {"role": "user", "content": f"Case {i}.\n{filler}\n\nWrite a detailed numbered review of at least 25 points on what could be wrong with this research log."}]
    t = time.time()
    r = httpx.post("http://127.0.0.1:8791/v1/chat/completions", json={"model": model, "messages": msgs, "max_tokens": 300}, timeout=3000).json()
    return time.time() - t, r["usage"]
t0 = time.time()
with ThreadPoolExecutor(conc) as ex: res = list(ex.map(one, range(n)))
wall = time.time() - t0
out = {"model": model, "n": n, "concurrency": conc, "wall_s": round(wall, 1), "calls_per_min": round(n / wall * 60, 1),
       "mean_tokens_in": sum(r[1]["prompt_tokens"] for r in res) / n, "mean_tokens_out": sum(r[1]["completion_tokens"] for r in res) / n,
       "mean_latency_s": round(sum(r[0] for r in res) / n, 1)}
print(json.dumps(out))
