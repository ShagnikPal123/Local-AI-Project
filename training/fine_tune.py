"""Fine-tuning pipeline scaffold for Nyx Ichos.

Prepares training data from the local memory store (important memories,
curated online results, and speech patterns) into a format suitable for
fine-tuning a local model (e.g. Ollama LoRA / Unsloth / HuggingFace).

This is a scaffold: it generates the dataset and validates it. The actual
training run is delegated to the tool of your choice via the generated
config, so no heavy ML dependencies are required to use this module.

Usage:
    python training/fine_tune.py --output training/dataset.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
# Allow running directly from the training/ directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memory import MemoryStore
from speech_patterns import SpeechPatternStore


def build_training_records(
    memory: MemoryStore,
    speech: SpeechPatternStore,
    system_prompt: str = "You are Nyx Ichos, a local-first AI coding assistant.",
) -> List[Dict[str, Any]]:
    """Convert stored knowledge into (instruction, response) training records.

    Each record is a dict with keys: instruction, response, and optional
    metadata (source, topic). Records are deduplicated by instruction.
    """
    records: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def add(instruction: str, response: str, source: str, topic: str = "") -> None:
        key = instruction.strip().lower()
        if not instruction.strip() or not response.strip() or key in seen:
            return
        seen.add(key)
        records.append({
            "instruction": instruction.strip(),
            "response": response.strip(),
            "metadata": {"source": source, "topic": topic},
        })

    # Important memories become Q&A pairs.
    for item in memory.get_important():
        topic = item.get("topic", "")
        content = item.get("content", "")
        add(
            f"What should I remember about {topic}?",
            content,
            source="important_memory",
            topic=topic,
        )

    # Curated online results become fact-retrieval pairs.
    for item in memory.data.get("online_results", []):
        add(
            item.get("prompt", ""),
            item.get("result", ""),
            source="online_result",
            topic=item.get("provider", ""),
        )

    # Preferences become instruction-following pairs.
    for key, value in memory.data.get("preferences", {}).items():
        add(
            f"Remember my preference: {key}",
            value,
            source="preference",
            topic=key,
        )

    # Speech patterns become style-mirroring pairs.
    patterns = speech.get_patterns()
    if patterns:
        style = speech.build_context_prompt()
        add(
            "How should you talk to me?",
            style,
            source="speech_patterns",
            topic="speech_style",
        )

    return records


def write_dataset(records: List[Dict[str, Any]], output: Path) -> Path:
    """Write records as JSONL and return the output path."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return output


def write_ollama_modelfile(records: List[Dict[str, Any]], output: Path) -> Path:
    """Write a Modelfile template for Ollama fine-tuning (LoRA-ready)."""
    content = (
        "# Ollama Modelfile for Nyx Ichos fine-tune\n"
        "# 1. Train a LoRA adapter with your preferred tool (e.g. Unsloth).\n"
        "# 2. Place the adapter in ./adapters and uncomment the line below.\n"
        "# 3. Run: ollama create nyx-finetuned -f this file\n"
        "FROM llama3.1\n"
        "# ADAPTER ./adapters/nyx-lora.safetensors\n"
        f"# Dataset size: {len(records)} records\n"
        "PARAMETER temperature 0.7\n"
        "PARAMETER top_p 0.9\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    return output


def main(argv: List[str] | None = None) -> None:
    """CLI entry point for the fine-tuning scaffold."""
    parser = argparse.ArgumentParser(description="Prepare Nyx Ichos fine-tuning data")
    parser.add_argument("--output", default="training/dataset.jsonl", help="Output JSONL path")
    parser.add_argument("--memory", default=None, help="Path to memory.json (default: memory.json)")
    parser.add_argument("--speech", default=None, help="Path to speech_patterns.json (default: speech_patterns.json)")
    args = parser.parse_args(argv)

    memory = MemoryStore(path=args.memory)
    speech = SpeechPatternStore(path=args.speech)
    records = build_training_records(memory, speech)

    dataset_path = write_dataset(records, Path(args.output))
    modelfile_path = write_ollama_modelfile(records, Path(args.output).with_name("Modelfile"))

    print(f"Wrote {len(records)} training records to {dataset_path}")
    print(f"Wrote Ollama Modelfile template to {modelfile_path}")
    if not records:
        print("Note: no records found. Add important memories or online results first.")


if __name__ == "__main__":
    main()
