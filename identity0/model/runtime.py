"""Identity 0's own transformer — our code, our weights (runs in job and serve processes only; imports torch).

A decoder-only language model in the modern small-model recipe: RMSNorm, rotary position embeddings,
grouped-query attention with per-head q/k norm, SwiGLU feed-forward, tied input/output embeddings.
Attention goes through ``scaled_dot_product_attention``, which picks the flash / memory-efficient
kernels on CUDA ("Flash attention", Request P3). Generation keeps a preallocated KV cache per layer, so
each new token costs one position of compute instead of re-reading the whole prompt.

Weights are saved as ``model.safetensors`` next to ``config.json`` and ``tokenizer.json`` — a flat,
inspectable format that ``layered.py`` can also split into one file per layer.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence

import torch
import torch.nn as nn
import torch.nn.functional as F

from identity0.model.config import ModelConfig


class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-5) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        dtype = x.dtype
        x = x.float()
        x = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return x.to(dtype) * self.weight


def rope_tables(head_dim: int, length: int, theta: float, device: torch.device) -> tuple:
    inv = 1.0 / (theta ** (torch.arange(0, head_dim, 2, device=device, dtype=torch.float32) / head_dim))
    angles = torch.outer(torch.arange(length, device=device, dtype=torch.float32), inv)
    return angles.cos(), angles.sin()


def apply_rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    """Rotate the two halves of each head (the "rotate_half" convention). x: [B, H, T, hd]; cos/sin: [T, hd/2]."""
    half = x.shape[-1] // 2
    x1, x2 = x[..., :half].float(), x[..., half:].float()
    cos, sin = cos[None, None], sin[None, None]
    return torch.cat((x1 * cos - x2 * sin, x2 * cos + x1 * sin), dim=-1).to(x.dtype)


class KVCache:
    """Preallocated keys/values for one layer: [B, KV, max_len, hd]."""

    def __init__(self, batch: int, kv_heads: int, max_len: int, head_dim: int, device, dtype) -> None:
        self.k = torch.zeros(batch, kv_heads, max_len, head_dim, device=device, dtype=dtype)
        self.v = torch.zeros_like(self.k)
        self.length = 0

    def append(self, k: torch.Tensor, v: torch.Tensor) -> tuple:
        end = self.length + k.shape[2]
        if end > self.k.shape[2]:
            raise ValueError("the conversation is longer than the model's context")
        self.k[:, :, self.length:end] = k
        self.v[:, :, self.length:end] = v
        self.length = end
        return self.k[:, :, :end], self.v[:, :, :end]


class Attention(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.n_heads, self.n_kv, self.hd = cfg.n_heads, cfg.n_kv_heads, cfg.head_dim
        self.q = nn.Linear(cfg.dim, self.n_heads * self.hd, bias=False)
        self.k = nn.Linear(cfg.dim, self.n_kv * self.hd, bias=False)
        self.v = nn.Linear(cfg.dim, self.n_kv * self.hd, bias=False)
        self.o = nn.Linear(self.n_heads * self.hd, cfg.dim, bias=False)
        self.qk_norm = cfg.qk_norm
        if cfg.qk_norm:
            self.q_norm = RMSNorm(self.hd, cfg.norm_eps)
            self.k_norm = RMSNorm(self.hd, cfg.norm_eps)

    def forward(self, x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor, cache: Optional[KVCache] = None) -> torch.Tensor:
        b, t, _ = x.shape
        q = self.q(x).view(b, t, self.n_heads, self.hd).transpose(1, 2)
        k = self.k(x).view(b, t, self.n_kv, self.hd).transpose(1, 2)
        v = self.v(x).view(b, t, self.n_kv, self.hd).transpose(1, 2)
        if self.qk_norm:
            q, k = self.q_norm(q), self.k_norm(k)
        q, k = apply_rope(q, cos, sin), apply_rope(k, cos, sin)
        past = cache.length if cache is not None else 0
        if cache is not None:
            k, v = cache.append(k, v)
        if self.n_kv != self.n_heads:
            repeat = self.n_heads // self.n_kv
            k, v = k.repeat_interleave(repeat, dim=1), v.repeat_interleave(repeat, dim=1)
        if past and t > 1:
            # New tokens after a cached prefix: each may see the whole prefix and the new tokens before it.
            total = past + t
            mask = torch.ones(t, total, dtype=torch.bool, device=x.device).tril(diagonal=past)
            y = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        else:
            y = F.scaled_dot_product_attention(q, k, v, is_causal=(past == 0 and t > 1))
        return self.o(y.transpose(1, 2).reshape(b, t, self.n_heads * self.hd))


class FeedForward(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.gate = nn.Linear(cfg.dim, cfg.ffn_dim, bias=False)
        self.up = nn.Linear(cfg.dim, cfg.ffn_dim, bias=False)
        self.down = nn.Linear(cfg.ffn_dim, cfg.dim, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down(F.silu(self.gate(x)) * self.up(x))


class Block(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.attn_norm = RMSNorm(cfg.dim, cfg.norm_eps)
        self.attn = Attention(cfg)
        self.ffn_norm = RMSNorm(cfg.dim, cfg.norm_eps)
        self.ffn = FeedForward(cfg)

    def forward(self, x, cos, sin, cache=None):
        x = x + self.attn(self.attn_norm(x), cos, sin, cache)
        return x + self.ffn(self.ffn_norm(x))


class KahunaLM(nn.Module):
    """Identity 0's language model."""

    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.cfg = cfg.validate()
        self.embed = nn.Embedding(cfg.vocab_size, cfg.dim)
        self.layers = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layers))
        self.norm = RMSNorm(cfg.dim, cfg.norm_eps)
        self.lm_head = nn.Linear(cfg.dim, cfg.vocab_size, bias=False)
        if cfg.tie_embeddings:
            self.lm_head.weight = self.embed.weight
        self._rope: Dict[str, tuple] = {}
        self.apply(self._init)
        for name, param in self.named_parameters():
            if name.endswith(("o.weight", "down.weight")):
                # GPT-2's residual scaling: deep stacks start stable.
                nn.init.normal_(param, mean=0.0, std=0.02 / math.sqrt(2 * cfg.n_layers))

    @staticmethod
    def _init(module: nn.Module) -> None:
        if isinstance(module, (nn.Linear, nn.Embedding)):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def rope(self, start: int, length: int, device: torch.device) -> tuple:
        key = str(device)
        table = self._rope.get(key)
        if table is None or table[0].shape[0] < start + length:
            size = max(self.cfg.max_seq_len, start + length)
            table = rope_tables(self.cfg.head_dim, size, self.cfg.rope_theta, device)
            self._rope[key] = table
        cos, sin = table
        return cos[start:start + length], sin[start:start + length]

    def forward(self, ids: torch.Tensor, caches: Optional[List[KVCache]] = None, start: int = 0) -> torch.Tensor:
        x = self.embed(ids)
        cos, sin = self.rope(start, ids.shape[1], ids.device)
        for index, layer in enumerate(self.layers):
            x = layer(x, cos, sin, caches[index] if caches is not None else None)
        return self.lm_head(self.norm(x))

    def new_caches(self, batch: int, max_len: int, device, dtype) -> List[KVCache]:
        return [KVCache(batch, self.cfg.n_kv_heads, max_len, self.cfg.head_dim, device, dtype)
                for _ in range(self.cfg.n_layers)]

    def parameter_count(self) -> int:
        return sum(p.numel() for p in self.parameters())

    # --- saving -----------------------------------------------------------------------------

    def save(self, directory: Path) -> None:
        from safetensors.torch import save_file

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.cfg.save(directory)
        state = {k: v.detach().to("cpu").contiguous() for k, v in self.state_dict().items()
                 if not (self.cfg.tie_embeddings and k == "lm_head.weight")}
        save_file(state, str(directory / "model.safetensors"))

    @classmethod
    def load(cls, directory: Path, device: str = "cpu", dtype: Optional[torch.dtype] = None) -> "KahunaLM":
        from safetensors.torch import load_file

        directory = Path(directory)
        model = cls(ModelConfig.load(directory))
        state = load_file(str(directory / "model.safetensors"))
        missing, unexpected = model.load_state_dict(state, strict=False)
        allowed = {"lm_head.weight"} if model.cfg.tie_embeddings else set()
        if set(missing) - allowed or unexpected:
            raise ValueError(f"weights do not match the config: missing {missing}, unexpected {unexpected}")
        model.to(device=device, dtype=dtype) if dtype else model.to(device)
        return model.eval()


def sample(logits: torch.Tensor, *, temperature: float = 0.7, top_p: float = 0.9, top_k: int = 50,
           recent: Optional[torch.Tensor] = None, repetition_penalty: float = 1.1,
           generator: Optional[torch.Generator] = None) -> int:
    """Pick the next token from one position's logits [V]."""
    logits = logits.float().clone()
    if recent is not None and recent.numel() and repetition_penalty != 1.0:
        seen = logits[recent]
        logits[recent] = torch.where(seen > 0, seen / repetition_penalty, seen * repetition_penalty)
    if temperature <= 0:
        return int(torch.argmax(logits))
    logits = logits / temperature
    if top_k and top_k < logits.shape[-1]:
        kth = torch.topk(logits, top_k).values[-1]
        logits[logits < kth] = float("-inf")
    probs = torch.softmax(logits, dim=-1)
    if 0 < top_p < 1:
        ordered, index = torch.sort(probs, descending=True)
        keep = torch.cumsum(ordered, dim=-1) - ordered < top_p
        filtered = torch.zeros_like(probs)
        filtered[index[keep]] = ordered[keep]
        probs = filtered / filtered.sum()
    return int(torch.multinomial(probs, 1, generator=generator))


@torch.inference_mode()
def generate(model: KahunaLM, prompt: Sequence[int], *, max_new_tokens: int = 256, temperature: float = 0.7,
             top_p: float = 0.9, top_k: int = 50, repetition_penalty: float = 1.1,
             stop: Sequence[int] = (), cancelled=None, seed: Optional[int] = None) -> Iterator[int]:
    """Stream token ids after ``prompt`` (prefill once, then one position per step through the KV cache)."""
    device = next(model.parameters()).device
    dtype = next(model.parameters()).dtype
    budget = model.cfg.max_seq_len
    # Room for the answer comes first (up to half the window); a long prompt keeps its newest tokens.
    room = max(1, min(max_new_tokens, budget // 2))
    prompt = list(prompt)[-(budget - room):]
    max_new_tokens = max(0, min(max_new_tokens, budget - len(prompt)))
    caches = model.new_caches(1, len(prompt) + max_new_tokens, device, dtype)
    generator = torch.Generator(device=device).manual_seed(seed) if seed is not None else None
    ids = torch.tensor([prompt], device=device)
    logits = model(ids, caches, start=0)[0, -1]
    history = list(prompt)
    for step in range(max_new_tokens):
        if cancelled is not None and cancelled():
            return
        recent = torch.tensor(history[-64:], device=device)
        token = sample(logits, temperature=temperature, top_p=top_p, top_k=top_k, recent=recent,
                       repetition_penalty=repetition_penalty, generator=generator)
        if token in stop:
            return
        yield token
        history.append(token)
        logits = model(torch.tensor([[token]], device=device), caches, start=len(history) - 1)[0, -1]
