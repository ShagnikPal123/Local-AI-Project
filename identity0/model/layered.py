"""Layer-by-layer inference for models bigger than the GPU — the parts of AirLLM, in our own code (Request P, S5).

AirLLM's trick, re-implemented for Identity 0's own architecture:

1. **Flat per-layer files** (``shard``): the checkpoint is split into ``embed``, ``layer_000`` …
   ``layer_NNN`` and ``head`` safetensors files plus a ``manifest.json`` (sizes, sha256, compression).
   Interrupted sharding resumes: finished files are listed in the manifest and skipped.
2. **One layer on the GPU at a time** (``LayeredModel``): a single reusable block lives on the device;
   for each layer its weights are copied in, the whole batch of hidden states runs through it, and the
   next layer's weights replace them. VRAM use is one layer + activations, whatever the model size.
3. **Prefetch**: while layer *i* computes, a background thread reads layer *i+1* from disk into pinned
   CPU memory, hiding most of the disk time.
4. **Block-wise compression** (``quant``): int8 or NF4 layer files load 2–4× faster.
5. **Flash attention**: the block's attention is ``scaled_dot_product_attention``.

Decoding keeps a KV cache per layer on the device, but every new token still streams every layer's
weights again, so speed is bound by disk/PCIe bandwidth — this is for models that could not run at all
otherwise. That is why it is OFF by default and only allowed at the MAX power mode (``allowed``).
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

import torch

from identity0.model.config import ModelConfig
from identity0.model.quant import compress, decompress
from identity0.model.runtime import Block, KahunaLM, KVCache, RMSNorm, rope_tables, sample


def needs_layered(model_bytes: int, free_vram: int, free_ram: int, headroom: float = 0.85) -> bool:
    """True when the weights will not fit in the GPU (with headroom) — the case layered mode exists for."""
    return model_bytes > free_vram * headroom


def allowed() -> Dict[str, Any]:
    """Layered mode runs only when the owner turned it on AND the power mode is MAX (Request P4)."""
    try:
        from identity0.state import get_settings

        setting = get_settings().get("layered_mode", "off")
    except Exception:  # noqa: BLE001
        setting = "off"
    try:
        from resource_governor import GOVERNOR, PowerMode  # type: ignore[attr-defined]

        mode = GOVERNOR.mode
        is_max = mode is PowerMode.MAX
    except Exception:  # noqa: BLE001 - no governor means not MAX
        is_max = False
    ok = setting == "auto" and is_max
    reason = "" if ok else ("switched off in Big Kahuna's settings" if setting != "auto" else "only at the Max power mode")
    return {"allowed": ok, "reason": reason}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pack(tensors: Dict[str, torch.Tensor], compression: Optional[str]) -> Dict[str, torch.Tensor]:
    if not compression:
        return {k: v.contiguous() for k, v in tensors.items()}
    packed: Dict[str, torch.Tensor] = {}
    for name, tensor in tensors.items():
        if tensor.dim() >= 2:
            for part, value in compress(tensor, compression).items():
                packed[f"{name}::{part}"] = value.contiguous()
        else:
            packed[name] = tensor.contiguous()
    return packed


def _unpack(tensors: Dict[str, torch.Tensor], compression: Optional[str], device, dtype) -> Dict[str, torch.Tensor]:
    out: Dict[str, torch.Tensor] = {}
    grouped: Dict[str, Dict[str, torch.Tensor]] = {}
    for key, value in tensors.items():
        if "::" in key:
            name, part = key.split("::", 1)
            grouped.setdefault(name, {})[part] = value
        else:
            out[key] = value.to(device=device, dtype=dtype, non_blocking=True)
    for name, parts in grouped.items():
        out[name] = decompress(parts, compression or "int8", device, dtype)
    return out


def shard(model_dir: Path, out_dir: Path, *, compression: Optional[str] = None,
          progress: Optional[Callable[[str, float], None]] = None) -> Dict[str, Any]:
    """Split ``model.safetensors`` into flat per-layer files (resumable)."""
    from safetensors.torch import load_file, save_file

    model_dir, out_dir = Path(model_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = ModelConfig.load(model_dir)
    cfg.save(out_dir)
    for extra in ("tokenizer.json",):
        if (model_dir / extra).exists():
            (out_dir / extra).write_bytes((model_dir / extra).read_bytes())
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"files": {}}
    manifest.update(compression=compression, n_layers=cfg.n_layers, format="kahuna-layered-1")
    state = load_file(str(model_dir / "model.safetensors"))
    groups: List[tuple] = [("embed", {"embed.weight": state["embed.weight"]})]
    for i in range(cfg.n_layers):
        prefix = f"layers.{i}."
        groups.append((f"layer_{i:03d}", {k[len(prefix):]: v for k, v in state.items() if k.startswith(prefix)}))
    head = {"norm.weight": state["norm.weight"]}
    if not cfg.tie_embeddings:
        head["lm_head.weight"] = state["lm_head.weight"]
    groups.append(("head", head))
    for index, (name, tensors) in enumerate(groups):
        path = out_dir / f"{name}.safetensors"
        if name in manifest["files"] and path.exists():
            continue  # resuming: this one is already done
        save_file(_pack(tensors, compression if name.startswith("layer_") else None), str(path))
        manifest["files"][name] = {"bytes": path.stat().st_size, "sha256": _sha(path)}
        manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        if progress:
            progress(f"wrote {name}", (index + 1) / len(groups))
    return {"dir": str(out_dir), "files": len(manifest["files"]),
            "bytes": sum(f["bytes"] for f in manifest["files"].values()), "compression": compression}


class LayeredModel:
    """Run a sharded model with only one transformer block resident on the device."""

    def __init__(self, directory: Path, device: str = "cuda", dtype: torch.dtype = torch.bfloat16,
                 prefetch: bool = True) -> None:
        from safetensors.torch import load_file

        self.dir = Path(directory)
        self.cfg = ModelConfig.load(self.dir)
        self.manifest = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
        self.compression = self.manifest.get("compression")
        self.device, self.dtype, self.prefetch = device, dtype, prefetch
        embed = load_file(str(self.dir / "embed.safetensors"))["embed.weight"]
        self.embed = embed.to(device=device, dtype=dtype)
        head = load_file(str(self.dir / "head.safetensors"))
        self.norm = RMSNorm(self.cfg.dim, self.cfg.norm_eps).to(device=device, dtype=dtype)
        self.norm.weight.data.copy_(head["norm.weight"].to(device=device, dtype=dtype))
        self.lm_head = head["lm_head.weight"].to(device=device, dtype=dtype) if "lm_head.weight" in head else self.embed
        self.block = Block(self.cfg).to(device=device, dtype=dtype).eval()
        self.loads = 0

    def _read(self, index: int) -> Dict[str, torch.Tensor]:
        from safetensors.torch import load_file

        tensors = load_file(str(self.dir / f"layer_{index:03d}.safetensors"))
        if self.device == "cuda":
            tensors = {k: v.pin_memory() for k, v in tensors.items()}
        return tensors

    def _layers(self) -> Iterator[Dict[str, torch.Tensor]]:
        """Each layer's CPU tensors in order, the next one read on a thread while the current one computes."""
        if not self.prefetch:
            for i in range(self.cfg.n_layers):
                yield self._read(i)
            return
        box: Dict[int, Any] = {}

        def fetch(i: int) -> None:
            box[i] = self._read(i)

        worker = threading.Thread(target=fetch, args=(0,), daemon=True)
        worker.start()
        for i in range(self.cfg.n_layers):
            worker.join()
            current = box.pop(i)
            if i + 1 < self.cfg.n_layers:
                worker = threading.Thread(target=fetch, args=(i + 1,), daemon=True)
                worker.start()
            yield current

    @torch.inference_mode()
    def forward(self, ids: torch.Tensor, caches: Optional[List[KVCache]] = None, start: int = 0) -> torch.Tensor:
        x = torch.nn.functional.embedding(ids.to(self.device), self.embed)
        cos, sin = rope_tables(self.cfg.head_dim, start + ids.shape[1], self.cfg.rope_theta, x.device)
        cos, sin = cos[start:], sin[start:]
        for index, tensors in enumerate(self._layers()):
            weights = _unpack(tensors, self.compression, self.device, self.dtype)
            self.block.load_state_dict(weights, strict=True)
            self.loads += 1
            x = self.block(x, cos, sin, caches[index] if caches is not None else None)
        return torch.nn.functional.linear(self.norm(x), self.lm_head)

    def generate(self, prompt: Sequence[int], *, max_new_tokens: int = 64, temperature: float = 0.0,
                 stop: Sequence[int] = ()) -> Iterator[int]:
        caches = [KVCache(1, self.cfg.n_kv_heads, len(prompt) + max_new_tokens, self.cfg.head_dim, self.device, self.dtype)
                  for _ in range(self.cfg.n_layers)]
        logits = self.forward(torch.tensor([list(prompt)]), caches, 0)[0, -1]
        length = len(prompt)
        for _ in range(max_new_tokens):
            token = sample(logits, temperature=temperature)
            if token in stop:
                return
            yield token
            logits = self.forward(torch.tensor([[token]]), caches, length)[0, -1]
            length += 1
