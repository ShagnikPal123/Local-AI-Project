"""Block-wise weight compression for layer files (AirLLM's idea: smaller files load faster from disk).

* **int8** — each block of 64 values stores int8 codes and one scale (absmax / 127): ~2× smaller than
  bf16, error at most half a step per value.
* **nf4** — each block of 64 values stores 4-bit indices into the 16 "normal float" levels from the
  QLoRA paper (levels spaced for normally distributed weights) and one absmax scale: ~4× smaller.

Weights are decompressed on the compute device right before the layer runs; activations stay bf16.
"""

from __future__ import annotations

from typing import Dict

import torch

BLOCK = 64
NF4 = torch.tensor([-1.0, -0.6961928009986877, -0.5250730514526367, -0.39491748809814453, -0.28444138169288635,
                    -0.18477343022823334, -0.09105003625154495, 0.0, 0.07958029955625534, 0.16093020141124725,
                    0.24611230194568634, 0.33791524171829224, 0.44070982933044434, 0.5626170039176941,
                    0.7229568362236023, 1.0])


def _blocks(t: torch.Tensor) -> tuple:
    flat = t.detach().float().reshape(-1)
    pad = (-flat.numel()) % BLOCK
    if pad:
        flat = torch.cat([flat, flat.new_zeros(pad)])
    return flat.view(-1, BLOCK), pad


def compress(t: torch.Tensor, kind: str) -> Dict[str, torch.Tensor]:
    blocks, pad = _blocks(t)
    absmax = blocks.abs().amax(dim=1).clamp_min(1e-12)
    meta = torch.tensor(list(t.shape) + [pad], dtype=torch.int64)
    if kind == "int8":
        codes = torch.round(blocks / (absmax[:, None] / 127)).clamp(-127, 127).to(torch.int8)
        return {"q": codes, "scale": absmax.to(torch.float16), "meta": meta}
    if kind == "nf4":
        normed = blocks / absmax[:, None]
        index = (normed[..., None] - NF4).abs().argmin(dim=-1).to(torch.uint8)
        packed = (index[:, 0::2] << 4) | index[:, 1::2]
        return {"q": packed, "scale": absmax.to(torch.float16), "meta": meta}
    raise ValueError(f"unknown compression {kind}")


def decompress(parts: Dict[str, torch.Tensor], kind: str, device, dtype) -> torch.Tensor:
    meta = parts["meta"].tolist()
    shape, pad = meta[:-1], meta[-1]
    scale = parts["scale"].to(device=device, dtype=torch.float32)
    if kind == "int8":
        values = parts["q"].to(device).float() * (scale[:, None] / 127)
    else:
        packed = parts["q"].to(device)
        index = torch.stack([packed >> 4, packed & 0x0F], dim=-1).view(packed.shape[0], -1).long()
        values = NF4.to(device)[index] * scale[:, None]
    flat = values.reshape(-1)
    if pad:
        flat = flat[:-pad]
    return flat.view(shape).to(dtype)
