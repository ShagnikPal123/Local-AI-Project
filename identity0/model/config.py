"""Shapes of Identity 0's own model, as plain data (no torch), so the app can read them too."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class ModelConfig:
    """A decoder-only transformer: RMSNorm, rotary positions, grouped-query attention, SwiGLU, tied embeddings."""

    vocab_size: int = 16384
    dim: int = 512
    n_layers: int = 8
    n_heads: int = 8
    n_kv_heads: int = 4
    ffn_dim: int = 1408
    max_seq_len: int = 1024
    rope_theta: float = 10000.0
    norm_eps: float = 1e-5
    qk_norm: bool = True          # per-head norm on q and k (as Qwen3 does) keeps attention logits tame when small
    tie_embeddings: bool = True
    name: str = "kahuna-nano"
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def head_dim(self) -> int:
        return self.dim // self.n_heads

    def parameters(self) -> int:
        """Exact parameter count (matches ``runtime.KahunaLM`` without building it)."""
        hd = self.head_dim
        attn = self.dim * self.n_heads * hd * 2 + self.dim * self.n_kv_heads * hd * 2
        if self.qk_norm:
            attn += 2 * hd
        mlp = 3 * self.dim * self.ffn_dim
        block = attn + mlp + 2 * self.dim
        head = 0 if self.tie_embeddings else self.vocab_size * self.dim
        return self.vocab_size * self.dim + self.n_layers * block + self.dim + head

    def validate(self) -> "ModelConfig":
        if self.dim % self.n_heads or self.n_heads % self.n_kv_heads or self.head_dim % 2:
            raise ValueError("dim must split into heads, heads into kv groups, and head_dim must be even")
        return self

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ModelConfig":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known).validate()

    def save(self, directory: Path) -> None:
        Path(directory).mkdir(parents=True, exist_ok=True)
        (Path(directory) / "config.json").write_text(json.dumps(self.to_json(), indent=1), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> "ModelConfig":
        return cls.from_json(json.loads((Path(directory) / "config.json").read_text(encoding="utf-8")))


#: Sizes the jobs offer. "tiny" is for tests; "nano" is the seed; "small" is the next growth step.
PRESETS: Dict[str, ModelConfig] = {
    "tiny": ModelConfig(vocab_size=512, dim=64, n_layers=2, n_heads=4, n_kv_heads=2, ffn_dim=128, max_seq_len=128,
                        name="kahuna-tiny"),
    "nano": ModelConfig(),
    "small": ModelConfig(dim=768, n_layers=12, n_heads=12, n_kv_heads=4, ffn_dim=2048, name="kahuna-small"),
}
