"""Serve Identity 0's own model on 127.0.0.1 (a process of its own, so the app never loads torch).

``python -m identity0.model.serve --dir kahuna/models/nano-v1`` → an OpenAI-shaped endpoint:
``GET /health``, ``GET /v1/models``, ``POST /v1/chat/completions`` (``stream`` true or false).
Only loopback callers are answered. One generation runs at a time (a lock), which is plenty for one
owner and keeps VRAM use flat. It exits by itself after ``--idle`` minutes without a request, or at once
on ``POST /shutdown`` — which is how a newly promoted version takes the GPU over from an older one.

The model's window is small (a few hundred to a few thousand tokens), so a request is fitted to it:
Nyx's long system prompts and tool results are replaced by the short note the model was trained with,
and the newest turns are kept that fit next to room for the answer.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List

import torch

from identity0.model.runtime import KahunaLM, generate
from identity0.model.tokenizer import KahunaTokenizer


class Engine:
    def __init__(self, directory: Path, version: str) -> None:
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        self.model = KahunaLM.load(directory, device=self.device, dtype=dtype)
        self.tokenizer = KahunaTokenizer.load(directory)
        self.version = version
        self.lock = threading.Lock()
        self.last_used = time.time()

    def fit(self, messages: List[Dict[str, Any]], max_tokens: int) -> List[int]:
        """Token ids for the conversation that fit the window with ``max_tokens`` of room left."""
        try:
            from identity0.corpus.dataset import SYSTEM
        except Exception:  # noqa: BLE001
            SYSTEM = "You are Identity 0, also called Big Kahuna: the owner's own AI model inside the Nyx app."
        turns: List[Dict[str, str]] = []
        for message in messages or []:
            role = message.get("role")
            if role not in ("user", "assistant") or message.get("_tool_results"):
                continue
            content = message.get("content", "")
            if isinstance(content, list):  # OpenAI-style parts: keep the words
                content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
            if str(content).strip():
                turns.append({"role": role, "content": str(content)})
        if not turns:
            turns = [{"role": "user", "content": "Hello."}]
        budget = self.model.cfg.max_seq_len - max_tokens - 4
        system = [{"role": "system", "content": SYSTEM}]
        kept: List[Dict[str, str]] = []
        for turn in reversed(turns):
            trial = system + [turn] + kept
            if len(self.tokenizer.chat(trial)[0]) > budget and kept:
                break
            kept.insert(0, turn)
        ids, _ = self.tokenizer.chat(system + kept)
        if len(ids) > budget:  # one very long message: keep the system note and the end of what was said
            head, _ = self.tokenizer.chat(system, add_generation_prompt=False)
            ids = head + ids[len(head):][-(budget - len(head)):]
        return ids

    def stream(self, messages, max_tokens: int, temperature: float):
        max_tokens = max(1, min(max_tokens, self.model.cfg.max_seq_len // 2))
        ids = self.fit(messages, max_tokens)
        with self.lock:
            self.last_used = time.time()
            pending = []
            for token in generate(self.model, ids, max_new_tokens=max_tokens, temperature=temperature,
                                  stop=self.tokenizer.stop_ids()):
                pending.append(token)
                text = self.tokenizer.decode(pending)
                if text and not text.endswith("�"):  # wait until a multi-byte character is complete
                    pending = []
                    yield text
            if pending:
                yield self.tokenizer.decode(pending)
            self.last_used = time.time()


def _exit_soon() -> None:
    """Let the reply reach the caller, then go (the weights are the only thing we hold)."""
    import os

    time.sleep(0.2)
    os._exit(0)


def make_handler(engine: Engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:  # quiet
            return

        def _loopback(self) -> bool:
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self.send_error(403, "loopback only")
                return False
            return True

        def _json(self, status: int, body: Dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if not self._loopback():
                return
            if self.path == "/health":
                self._json(200, {"ok": True, "version": engine.version, "device": engine.device,
                                 "params": engine.model.parameter_count()})
            elif self.path == "/v1/models":
                self._json(200, {"data": [{"id": engine.version, "object": "model"}]})
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if not self._loopback():
                return
            if self.path == "/shutdown":
                self._json(200, {"ok": True, "version": engine.version})
                threading.Thread(target=_exit_soon, name="kahuna-serve-exit", daemon=True).start()
                return
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)) or b"{}")
            except ValueError:
                self._json(400, {"error": "bad json"})
                return
            messages = body.get("messages") or []
            max_tokens = max(1, min(1024, int(body.get("max_tokens", 256))))
            temperature = float(body.get("temperature", 0.7))
            if not body.get("stream"):
                text = "".join(engine.stream(messages, max_tokens, temperature))
                self._json(200, {"id": "kahuna", "object": "chat.completion", "model": engine.version,
                                 "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                              "finish_reason": "stop"}]})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                for piece in engine.stream(messages, max_tokens, temperature):
                    chunk = {"choices": [{"index": 0, "delta": {"content": piece}}], "model": engine.version}
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--port", type=int, default=11500)
    parser.add_argument("--version", default="own")
    parser.add_argument("--idle", type=float, default=60.0, help="minutes without a request before exiting")
    args = parser.parse_args()
    engine = Engine(Path(args.dir), args.version)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(engine))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    while time.time() - engine.last_used < args.idle * 60:
        time.sleep(15)
    server.shutdown()


if __name__ == "__main__":
    main()
