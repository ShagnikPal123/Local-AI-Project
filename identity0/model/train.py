"""Train Identity 0's own model from scratch: read the corpus, then learn to converse (job process only).

Two stages inside one time budget:

1. **Pretraining** (most of the budget): next-token prediction over the Safe-mix corpus, packed into
   fixed windows. This is where the model learns language and facts.
2. **Instruction tuning**: the chat examples (its identity + the teacher's answers + trainable
   experiences), with the loss on the assistant's tokens only, mixed with a little pretraining text so
   it does not forget how to read.

The schedule is time-based (cosine over the minutes allowed), so "train for 30 minutes" means exactly
that on any GPU. Held-out perplexity is measured on documents the model never trained on, so the number
is honest. Final weights are saved in bfloat16 (half the size) — the owner asked to keep things small.

Both stages are measured on held-out material the model never trains on — documents for reading,
whole conversations for instruction tuning — and the version kept is the best one seen, not the last.
A small chat set is memorised within minutes otherwise (training loss near zero, answers invented).

Instruction tuning is therefore counted in *epochs*, not minutes: the chat set is seen at most
``sft_epochs`` times (default 3), and whatever time is left goes back into reading. With a few hundred
conversations that is a couple of minutes — asking for more would only teach it to recite them.

A run can be interrupted (the PC sleeps, the app closes) and resumed: every checkpoint also writes the
optimiser, the schedule position and the best held-out point (``train_state.json``, ``optimizer.pt``,
``best.safetensors``). ``resume=True`` picks all of it up, so the time budget counts the minutes already
trained. Those extra files are deleted when the run finishes.
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import torch
import torch.nn.functional as F

from identity0.model.config import PRESETS, ModelConfig
from identity0.model.runtime import KahunaLM, generate
from identity0.model.tokenizer import KahunaTokenizer

Progress = Callable[[str, float, Dict[str, Any]], None]


def _quiet(_message: str, _fraction: float, _metrics: Dict[str, Any]) -> None:
    return None


def build_tokens(tokenizer: KahunaTokenizer, texts: List[str], out: Path, holdout_every: int = 100) -> Dict[str, Any]:
    """Tokenize documents into two flat uint16 files (train / held-out), documents separated by <|eos|>."""
    eos = tokenizer.ids["<|eos|>"]
    train: List[np.ndarray] = []
    held: List[np.ndarray] = []
    for start in range(0, len(texts), 256):
        batch = texts[start:start + 256]
        for offset, ids in enumerate(tokenizer.encode_batch(batch)):
            array = np.asarray(ids + [eos], dtype=np.uint16)
            (held if (start + offset) % holdout_every == holdout_every - 1 else train).append(array)
    train_arr = np.concatenate(train) if train else np.zeros(0, np.uint16)
    held_arr = np.concatenate(held) if held else train_arr[-50_000:]
    train_arr.tofile(out / "tokens_train.bin")
    held_arr.tofile(out / "tokens_held.bin")
    return {"train_tokens": int(train_arr.size), "held_tokens": int(held_arr.size)}


def _windows(data: np.ndarray, batch: int, length: int, device: str, rng: np.random.Generator):
    starts = rng.integers(0, max(1, data.size - length - 1), size=batch)
    x = np.stack([data[s:s + length] for s in starts]).astype(np.int64)
    y = np.stack([data[s + 1:s + length + 1] for s in starts]).astype(np.int64)
    return torch.from_numpy(x).to(device, non_blocking=True), torch.from_numpy(y).to(device, non_blocking=True)


def _sft_batch(rows: List[Dict[str, Any]], tokenizer: KahunaTokenizer, batch: int, length: int, device: str,
               rng: random.Random):
    pad = tokenizer.ids["<|pad|>"]
    picked = [rng.choice(rows) for _ in range(batch)]
    xs, ys = [], []
    for row in picked:
        ids, mask = tokenizer.chat(row["messages"], add_generation_prompt=False)
        ids, mask = ids[:length + 1], mask[:length + 1]
        labels = [t if m else -100 for t, m in zip(ids, mask)]
        xs.append(ids[:-1])
        ys.append(labels[1:])
    width = max(len(x) for x in xs)
    x = torch.full((batch, width), pad, dtype=torch.long)
    y = torch.full((batch, width), -100, dtype=torch.long)
    for i, (a, b) in enumerate(zip(xs, ys)):
        x[i, :len(a)] = torch.tensor(a)
        y[i, :len(b)] = torch.tensor(b)
    return x.to(device), y.to(device)


def _loss(model: KahunaLM, x: torch.Tensor, y: torch.Tensor, device: str) -> torch.Tensor:
    with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
        logits = model(x)
    return F.cross_entropy(logits.float().view(-1, logits.shape[-1]), y.view(-1), ignore_index=-100)


@torch.no_grad()
def sft_loss(model: KahunaLM, rows: List[Dict[str, Any]], tokenizer: KahunaTokenizer, length: int, device: str,
             batches: int = 6, batch: int = 8) -> float:
    """Average loss on conversations the model never trains on — whether it is learning to answer or memorising."""
    if not rows:
        return float("nan")
    model.eval()
    rng = random.Random(4321)
    losses = []
    for _ in range(batches):
        x, y = _sft_batch(rows, tokenizer, min(batch, len(rows)), length, device, rng)
        losses.append(float(_loss(model, x, y, device)))
    model.train()
    return sum(losses) / len(losses)


@torch.no_grad()
def held_out_perplexity(model: KahunaLM, data: np.ndarray, length: int, device: str, batches: int = 20) -> float:
    model.eval()
    rng = np.random.default_rng(1234)
    losses = []
    for _ in range(batches):
        x, y = _windows(data, 8, length, device, rng)
        losses.append(float(_loss(model, x, y, device)))
    model.train()
    return float(math.exp(sum(losses) / len(losses)))


def run(params: Dict[str, Any], progress: Progress = _quiet, stop: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    out = Path(params["out"])
    out.mkdir(parents=True, exist_ok=True)
    minutes = float(params.get("minutes", 30))
    length = int(params.get("seq_len", 512))
    batch = int(params.get("batch", 32))
    peak_lr = float(params.get("lr", 1e-3))
    pretrain_share = float(params.get("pretrain_share", 0.75))
    device = "cuda" if torch.cuda.is_available() and not params.get("cpu") else "cpu"
    seed = int(params.get("seed", 7))
    torch.manual_seed(seed)
    rng_np, rng = np.random.default_rng(seed), random.Random(seed)
    prep_started = time.time()
    started = time.time()  # reset once the corpus is ready: the time budget is for training, not for tokenising

    texts: List[str] = params.get("texts") or []
    if not texts and params.get("corpus"):
        from identity0.corpus.store import CorpusStore

        texts = list(CorpusStore(Path(params["corpus"]), cap_mb=1e9).texts())
    if not texts:
        raise ValueError("there is no corpus to learn from yet")
    base = PRESETS[params.get("preset", "nano")]

    resume = bool(params.get("resume")) and (out / "tokenizer.json").exists() and (out / "model.safetensors").exists()
    saved: Dict[str, Any] = {}
    if resume and (out / "train_state.json").exists():
        saved = json.loads((out / "train_state.json").read_text(encoding="utf-8"))
    progress("Learning its own words (tokenizer)…", 0.01, {})
    if resume:
        tokenizer = KahunaTokenizer.load(out)
    else:
        sample = texts if sum(len(t) for t in texts) < 80_000_000 else rng.sample(texts, k=max(1, len(texts) // 3))
        tokenizer = KahunaTokenizer.train(sample, base.vocab_size, out)
    if resume and (out / "tokens_train.bin").exists() and (out / "tokens_held.bin").exists():
        stats = {"train_tokens": int((out / "tokens_train.bin").stat().st_size // 2),
                 "held_tokens": int((out / "tokens_held.bin").stat().st_size // 2)}  # same split as before
    else:
        stats = build_tokens(tokenizer, texts, out)
    train_data = np.fromfile(out / "tokens_train.bin", dtype=np.uint16)
    held_data = np.fromfile(out / "tokens_held.bin", dtype=np.uint16)
    progress(f"Corpus ready: {stats['train_tokens']:,} training tokens", 0.03, stats)

    cfg = ModelConfig.from_json({**base.to_json(), "vocab_size": tokenizer.vocab_size, "max_seq_len": max(length * 2, base.max_seq_len)})
    model = KahunaLM(cfg).to(device)
    if resume:
        model = KahunaLM.load(out, device=device, dtype=torch.float32).train()
    model.train()
    decay = [p for n, p in model.named_parameters() if p.dim() >= 2]
    rest = [p for n, p in model.named_parameters() if p.dim() < 2]
    optimizer = torch.optim.AdamW([{"params": decay, "weight_decay": 0.1}, {"params": rest, "weight_decay": 0.0}],
                                  lr=peak_lr, betas=(0.9, 0.95), fused=device == "cuda")
    if resume and (out / "optimizer.pt").exists():
        try:
            optimizer.load_state_dict(torch.load(out / "optimizer.pt", map_location=device, weights_only=True))
        except Exception:  # noqa: BLE001 - a fresh optimiser (with a short warm-up) is fine
            saved["step"] = 0

    sft_rows: List[Dict[str, Any]] = []
    for path in params.get("sft", []) or []:
        from identity0.corpus.dataset import load_sft

        sft_rows += load_sft(Path(path))
    sft_rows += params.get("sft_rows", []) or []
    # One conversation in twenty is never trained on, so "it answers well" can be measured, not hoped.
    rng.shuffle(sft_rows)
    sft_held = sft_rows[::20] if len(sft_rows) >= 40 else []
    if sft_held:
        keep = set(id(row) for row in sft_held)
        sft_rows = [row for row in sft_rows if id(row) not in keep]

    budget = minutes * 60
    prep_seconds = round(time.time() - prep_started, 1)
    started = time.time()  # from here on the clock is training time
    # How many chat batches the set is worth: seeing it three times teaches the shape of an answer,
    # thirty times teaches the answers themselves.
    sft_batch_size = max(4, batch // 2)
    sft_cap = int(float(params.get("sft_epochs", 3)) * max(1, len(sft_rows)) / sft_batch_size) if sft_rows else 0
    sft_seen = 0
    step, tokens_seen, last_eval, last_report = 0, 0, 0.0, 0.0
    # A small corpus is seen many times in a long run; the version kept is the one that did best on documents
    # it never trained on, not simply the last one (early stopping by held-out perplexity).
    best: Dict[str, Any] = {"ppl": float("inf"), "state": None, "step": 0}
    best_chat: Dict[str, Any] = {"loss": float("inf"), "state": None, "step": 0}
    switched, kept_best = False, False
    history: List[Dict[str, float]] = []
    warmup = int(params.get("warmup", 200))
    if saved:
        # Carry on where it stopped: same schedule position, new random batches.
        started -= float(saved.get("elapsed", 0.0))
        step, tokens_seen = int(saved.get("step", 0)), int(saved.get("tokens_seen", 0))
        history = list(saved.get("history", []))
        switched, kept_best = bool(saved.get("switched")), bool(saved.get("kept_best"))
        rng_np, rng = np.random.default_rng(seed + step), random.Random(seed + step)
        if saved.get("best_ppl") is not None and (out / "best.safetensors").exists():
            from safetensors.torch import load_file

            best = {"ppl": float(saved["best_ppl"]), "step": int(saved.get("best_step", 0)),
                    "state": load_file(str(out / "best.safetensors"))}
    if resume and not step:
        warmup = min(warmup, 50)  # resumed weights without their optimiser: a short warm-up is enough

    def snapshot() -> Dict[str, Any]:
        return {k: v.detach().to("cpu", copy=True) for k, v in model.state_dict().items()}

    def checkpoint(now: float) -> None:
        model.save(out)  # a checkpoint the owner can already try
        torch.save(optimizer.state_dict(), out / "optimizer.pt")
        state = {"elapsed": now - started, "step": step, "tokens_seen": tokens_seen, "history": history,
                 "switched": switched, "kept_best": kept_best, "best_step": best["step"],
                 "best_ppl": best["ppl"] if best["state"] is not None else None}
        (out / "train_state.json").write_text(json.dumps(state), encoding="utf-8")

    while True:
        elapsed = time.time() - started
        fraction = min(1.0, elapsed / budget)
        if fraction >= 1.0 or stop():
            break
        phase = "pretrain" if (fraction < pretrain_share or not sft_rows or sft_seen >= sft_cap) else "sft"
        if phase == "sft" and not switched:
            switched = True
            progress(f"Learning to answer ({len(sft_rows)} conversations, {sft_cap} batches)…",
                     0.05 + 0.9 * fraction, {"phase": "sft"})
            now_ppl = held_out_perplexity(model, held_data, length, device)
            if best["state"] is not None and best["ppl"] < now_ppl:
                # Reading overfitted before the conversation stage: learn to converse from its best point.
                model.load_state_dict(best["state"])
                kept_best = True
        lr = peak_lr * min(1.0, (step + 1) / warmup) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * fraction)))
        if phase == "sft":
            lr *= float(params.get("sft_lr_scale", 0.3))  # gentler, so it learns the style without swallowing the set
        for group in optimizer.param_groups:
            group["lr"] = lr
        if phase == "sft" and rng.random() > 0.15:
            x, y = _sft_batch(sft_rows, tokenizer, sft_batch_size, length, device, rng)
            sft_seen += 1
        else:
            x, y = _windows(train_data, batch, length, device, rng_np)
        loss = _loss(model, x, y, device)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        step += 1
        tokens_seen += int(x.numel())
        now = time.time()
        if now - last_report > 5:
            last_report = now
            rate = tokens_seen / max(1e-6, now - started)
            progress(f"{phase}: step {step}, loss {loss.item():.3f}, {rate:,.0f} tokens/s", 0.05 + 0.9 * fraction,
                     {"step": step, "loss": round(loss.item(), 4), "phase": phase, "tokens": tokens_seen})
        if now - last_eval > max(60, budget / 12):
            last_eval = now
            ppl = held_out_perplexity(model, held_data, length, device)
            history.append({"step": step, "minutes": round((now - started) / 60, 2), "loss": round(loss.item(), 4),
                            "held_out_perplexity": round(ppl, 2), "phase": phase})
            if phase == "pretrain" and ppl < best["ppl"]:
                best.update(ppl=ppl, step=step, state=snapshot())
                from safetensors.torch import save_file

                save_file({k: v.contiguous() for k, v in best["state"].items()}, str(out / "best.safetensors"))
            if phase == "sft" and sft_held:
                chat = sft_loss(model, sft_held, tokenizer, length, device)
                history[-1]["held_out_chat_loss"] = round(chat, 4)
                if chat < best_chat["loss"]:
                    best_chat.update(loss=chat, step=step, state=snapshot())
            checkpoint(now)

    if best_chat["state"] is not None and sft_held:
        # Instruction tuning memorises a small chat set fast: keep the point where unseen conversations
        # were answered best, not the point where the training ones were reproduced best.
        final_chat = sft_loss(model, sft_held, tokenizer, length, device)
        if best_chat["loss"] < final_chat - 0.01:
            model.load_state_dict(best_chat["state"])
            kept_best = True
    ppl = held_out_perplexity(model, held_data, length, device, batches=40)
    if best["state"] is not None and not sft_rows and best["ppl"] < ppl:
        # Pure pretraining that overfitted: go back to its best point.
        model.load_state_dict(best["state"])
        ppl = held_out_perplexity(model, held_data, length, device, batches=40)
        kept_best = True
    samples = []
    model.eval()
    for question in ("Who are you?", "What is photosynthesis?", "Tell me about the Moon."):
        ids, _ = tokenizer.chat([{"role": "user", "content": question}])
        reply = tokenizer.decode(list(generate(model, ids, max_new_tokens=80, temperature=0.7, stop=tokenizer.stop_ids(), seed=1)))
        samples.append({"question": question, "answer": reply})
    model.to(torch.bfloat16).save(out)
    for leftover in ("tokens_train.bin", "tokens_held.bin", "optimizer.pt", "best.safetensors", "train_state.json"):
        (out / leftover).unlink(missing_ok=True)  # small on disk: tokens are rebuilt from the corpus when needed
    metrics = {"params": model.parameter_count(), "steps": step, "tokens_seen": tokens_seen,
               "minutes": round((time.time() - started) / 60, 2), "held_out_perplexity": round(ppl, 2),
               "train_tokens": stats["train_tokens"], "sft_examples": len(sft_rows), "device": device,
               "history": history, "samples": samples, "preset": params.get("preset", "nano"),
               "best_pretrain_perplexity": round(best["ppl"], 2) if best["state"] is not None else None,
               "best_pretrain_step": best["step"], "kept_best": kept_best, "resumed": bool(saved) or resume,
               "held_out_chat_loss": round(sft_loss(model, sft_held, tokenizer, length, device), 4) if sft_held else None,
               "best_chat_loss": round(best_chat["loss"], 4) if best_chat["state"] is not None else None,
               "sft_held_out": len(sft_held), "sft_batches": sft_seen, "sft_batch_cap": sft_cap,
               "prep_minutes": round(prep_seconds / 60, 2),
               "sft_epochs": round(sft_seen * sft_batch_size / max(1, len(sft_rows)), 2),
               "gpu": torch.cuda.get_device_name(0) if device == "cuda" else "cpu"}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, ensure_ascii=False), encoding="utf-8")
    progress(f"Done: held-out perplexity {ppl:.1f}", 1.0, {"held_out_perplexity": ppl})
    return metrics
