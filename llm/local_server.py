"""Local model server: OpenAI-style /v1/chat/completions on 127.0.0.1:8791, GPU 1 only.

Run with the interpreter in ALPHACOURT_TORCH_PYTHON (the main environment does not install torch). One model is loaded at a time;
a request for another model swaps it. Concurrent requests for the loaded model are batched (left padding,
greedy decoding). Qwen3 thinking is off. Weights come from the local Hugging Face cache; nothing is downloaded.
"""
import os

os.environ["CUDA_VISIBLE_DEVICES"] = "1"  # before torch is imported: GPU 0 must never be visible
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch

assert torch.cuda.device_count() == 1, "exactly one GPU (physical GPU 1) must be visible"

HOST, PORT = "127.0.0.1", 8791
MODELS = {  # id -> (hf repo, thinking_off, max batch)
    "qwen3-8b": ("Qwen/Qwen3-8B", True, 16),
    "gemma3-12b": ("google/gemma-3-12b-it", False, 12),
    "qwen3-4b": ("Qwen/Qwen3-4B", True, 24),
    "phi4-mini": ("microsoft/Phi-4-mini-instruct", False, 24),
}
BATCH_WAIT = 0.15  # seconds to wait for more requests to join a batch


class Job:
    def __init__(self, model, messages, max_tokens):
        self.model, self.messages, self.max_tokens = model, messages, max_tokens
        self.done = threading.Event()
        self.text, self.tokens_in, self.tokens_out, self.error = "", 0, 0, None


class Engine:
    def __init__(self):
        self.q: "queue.Queue[Job]" = queue.Queue()
        self.model_id = None
        self.model = self.tok = None
        self.stats = {"calls": 0, "batches": 0, "swaps": 0}
        threading.Thread(target=self.loop, daemon=True).start()

    def load(self, mid):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        if self.model is not None:
            del self.model
            self.model = None
            torch.cuda.empty_cache()
        repo = MODELS[mid][0]
        self.tok = AutoTokenizer.from_pretrained(repo)
        self.tok.padding_side = "left"
        if self.tok.pad_token_id is None:
            self.tok.pad_token = self.tok.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(repo, dtype=torch.bfloat16, device_map="cuda").eval()
        self.model_id = mid
        self.stats["swaps"] += 1

    def loop(self):
        pending: list[Job] = []
        while True:
            if not pending:
                pending.append(self.q.get())
            time.sleep(BATCH_WAIT)
            while True:
                try:
                    pending.append(self.q.get_nowait())
                except queue.Empty:
                    break
            target = pending[0].model
            same = [j for j in pending if j.model == target]
            pending = [j for j in pending if j.model != target]
            try:
                if self.model_id != target:
                    self.load(target)
                cap = MODELS[target][2]
                same.sort(key=lambda j: len(json.dumps(j.messages)))
                for i in range(0, len(same), cap):
                    self.run(same[i:i + cap])
            except Exception as e:  # report to callers, keep serving
                for j in same:
                    if not j.done.is_set():
                        j.error = f"{type(e).__name__}: {e}"
                        j.done.set()
                torch.cuda.empty_cache()

    @torch.no_grad()
    def run(self, jobs):
        _, thinking_off, _ = MODELS[self.model_id]
        kw = {"enable_thinking": False} if thinking_off else {}
        texts = [self.tok.apply_chat_template(j.messages, tokenize=False, add_generation_prompt=True, **kw) for j in jobs]
        enc = self.tok(texts, return_tensors="pt", padding=True, add_special_tokens=False).to("cuda")
        new = max(j.max_tokens for j in jobs)
        out = self.model.generate(**enc, max_new_tokens=new, do_sample=False, temperature=None, top_p=None, top_k=None,
                                  pad_token_id=self.tok.pad_token_id)
        plen = enc["input_ids"].shape[1]
        for j, row, am in zip(jobs, out, enc["attention_mask"]):
            gen = row[plen:]
            n = int((gen != self.tok.pad_token_id).sum())
            j.tokens_in, j.tokens_out = int(am.sum()), n
            j.text = self.tok.decode(gen[:j.max_tokens], skip_special_tokens=True).strip()
            j.done.set()
        self.stats["calls"] += len(jobs)
        self.stats["batches"] += 1


ENGINE = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/health", "/v1/models"):
            self._send(200, {"ok": True, "loaded": ENGINE.model_id, "available": list(MODELS), "stats": ENGINE.stats,
                             "gpu_visible": torch.cuda.device_count()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": "not found"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            mid = str(req.get("model", "")).replace("local:", "")
            if mid not in MODELS:
                return self._send(400, {"error": f"unknown model {mid}; known: {list(MODELS)}"})
            job = Job(mid, req["messages"], int(req.get("max_tokens", 300)))
        except Exception as e:
            return self._send(400, {"error": str(e)})
        ENGINE.q.put(job)
        job.done.wait()
        if job.error:
            return self._send(500, {"error": job.error})
        self._send(200, {"model": f"local:{mid}", "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": job.text}}],
                         "usage": {"prompt_tokens": job.tokens_in, "completion_tokens": job.tokens_out}})


def main():
    global ENGINE
    ENGINE = Engine()
    print(f"local_server on {HOST}:{PORT}, gpu_visible={torch.cuda.device_count()}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
