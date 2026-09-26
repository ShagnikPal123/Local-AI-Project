"""Identity 0's own tokenizer: byte-level BPE trained on its own corpus, plus its chat format.

Byte-level means any text (code, emoji, other languages) can be encoded — there are no unknown
tokens — while merges learned from the corpus keep common words short. The chat format uses special
tokens of its own, so no other model's template is copied.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

SPECIALS = ["<|pad|>", "<|bos|>", "<|eos|>", "<|system|>", "<|user|>", "<|assistant|>", "<|end|>"]


class KahunaTokenizer:
    def __init__(self, tokenizer) -> None:
        self._tok = tokenizer
        self.ids: Dict[str, int] = {name: tokenizer.token_to_id(name) for name in SPECIALS}

    # --- building ---------------------------------------------------------------------------

    @classmethod
    def train(cls, texts: Iterable[str], vocab_size: int, directory: Path) -> "KahunaTokenizer":
        from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

        tok = Tokenizer(models.BPE())
        tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
        tok.decoder = decoders.ByteLevel()
        trainer = trainers.BpeTrainer(vocab_size=vocab_size, min_frequency=2, special_tokens=SPECIALS,
                                      initial_alphabet=pre_tokenizers.ByteLevel.alphabet(), show_progress=False)
        tok.train_from_iterator(texts, trainer=trainer)
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        tok.save(str(directory / "tokenizer.json"))
        return cls(tok)

    @classmethod
    def load(cls, directory: Path) -> "KahunaTokenizer":
        from tokenizers import Tokenizer

        return cls(Tokenizer.from_file(str(Path(directory) / "tokenizer.json")))

    @property
    def vocab_size(self) -> int:
        return self._tok.get_vocab_size()

    # --- text -------------------------------------------------------------------------------

    def encode(self, text: str) -> List[int]:
        return self._tok.encode(text or "").ids

    def encode_batch(self, texts: Sequence[str]) -> List[List[int]]:
        return [e.ids for e in self._tok.encode_batch(list(texts))]

    def decode(self, ids: Sequence[int]) -> str:
        return self._tok.decode(list(ids), skip_special_tokens=True)

    # --- chat -------------------------------------------------------------------------------

    def chat(self, messages: Sequence[Dict[str, str]], *, add_generation_prompt: bool = True) -> Tuple[List[int], List[int]]:
        """Token ids for a conversation, and a mask that is 1 on assistant tokens (what SFT learns)."""
        ids: List[int] = [self.ids["<|bos|>"]]
        mask: List[int] = [0]
        role_token = {"system": "<|system|>", "user": "<|user|>", "assistant": "<|assistant|>"}
        for message in messages:
            role = message.get("role", "user")
            head = [self.ids[role_token.get(role, "<|user|>")]]
            body = self.encode(str(message.get("content", ""))) + [self.ids["<|end|>"]]
            ids += head + body
            learn = 1 if role == "assistant" else 0
            mask += [0] + [learn] * len(body)
        if add_generation_prompt:
            ids.append(self.ids["<|assistant|>"])
            mask.append(0)
        return ids, mask

    def stop_ids(self) -> List[int]:
        return [self.ids["<|end|>"], self.ids["<|eos|>"]]


def describe(directory: Path) -> Dict[str, object]:
    data = json.loads((Path(directory) / "tokenizer.json").read_text(encoding="utf-8"))
    return {"vocab": len(data.get("model", {}).get("vocab", {})), "specials": SPECIALS}
