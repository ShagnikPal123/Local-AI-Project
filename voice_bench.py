"""voice_bench: where the seconds go in a spoken turn, measured on this PC.

The owner (Fixer Upper S33): "When I test different voices it doesn't work super fast … fix these and the speed and
the actual listening." Guessing at speed is how the voice got slow, so this times each stage on its own:

* **voice tests** — how long a voice sample takes to make the first time (no cache) and again (cached), per voice;
* **first sound** — for a neural voice, when the first audio arrives versus when the whole clip is done. A big gap
  means playing audio as it streams in would start the voice sooner;
* **voice to action** — how long Ultra Fast takes to decide on "open chrome" (decision only, nothing opens);
* **the spoken answer** — how long the voice model takes to write a three-sentence answer, only when that model is on
  this PC (a cloud model is skipped unless ``--online`` is given, so the bench never spends money by itself).

Run it from the project folder:  .venv/Scripts/python.exe voice_bench.py   (add --json for machine-readable output)
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any, Callable, Dict, List, Optional

SAMPLE = "Hi, this is how I sound. I can help with that right away."
QUESTION = "What should I make for dinner tonight?"
LOCAL_PROVIDERS = ("ollama", "identity0")


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def time_voice_tests(voices: List[str], synth: Optional[Callable[..., Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """First-time and cached time for each voice's sample line."""
    if synth is None:
        import tts

        synth = tts.synthesize
    rows = []
    for voice in voices:
        fresh_text = f"{SAMPLE} ({int(time.time() * 1000) % 100000})"   # a new line, so nothing comes from the cache
        row: Dict[str, Any] = {"voice": voice}
        try:
            start = time.perf_counter()
            synth(fresh_text, voice_id=voice)
            row["first_ms"] = _ms(start)
            start = time.perf_counter()
            synth(fresh_text, voice_id=voice)
            row["cached_ms"] = _ms(start)
        except Exception as error:  # noqa: BLE001 - one broken voice must not stop the bench
            row["error"] = f"{type(error).__name__}: {str(error)[:120]}"
        rows.append(row)
    return rows


def time_first_sound(voice: str, stream: Optional[Callable[[str, str], Any]] = None) -> Dict[str, Any]:
    """When the first audio chunk of a neural voice arrives, and when the last does."""
    if stream is None:
        import asyncio

        import edge_tts

        def stream(text: str, voice_id: str):  # type: ignore[no-redef]
            async def collect() -> List[float]:
                marks, start = [], time.perf_counter()
                async for chunk in edge_tts.Communicate(text, voice_id).stream():
                    if chunk.get("type") == "audio":
                        marks.append((time.perf_counter() - start) * 1000)
                return marks

            return asyncio.run(collect())
    try:
        marks = list(stream(SAMPLE, voice))
    except Exception as error:  # noqa: BLE001
        return {"voice": voice, "error": f"{type(error).__name__}: {str(error)[:120]}"}
    if not marks:
        return {"voice": voice, "error": "no audio came back"}
    return {"voice": voice, "first_chunk_ms": round(marks[0], 1), "whole_clip_ms": round(marks[-1], 1),
            "chunks": len(marks)}


def time_voice_to_action(handle: Optional[Callable[..., Dict[str, Any]]] = None, runs: int = 5) -> Dict[str, Any]:
    """Ultra Fast's decision for a desktop command, dry run (nothing is opened)."""
    if handle is None:
        import ultrafast

        handle = ultrafast.handle
    times, result = [], {}
    for _ in range(runs):
        start = time.perf_counter()
        result = handle("open chrome", dry_run=True)
        times.append(_ms(start))
    return {"command": "open chrome", "median_ms": statistics.median(times), "handled": bool(result.get("handled")),
            "reply": result.get("reply", "")}


def time_spoken_answer(run: Optional[Callable[..., Any]] = None, provider: str = "", online: bool = False) -> Dict[str, Any]:
    """How long the voice model takes to write a short spoken answer."""
    if run is None:
        import voice_pipeline
        from model_roles import MODEL_ROLES

        roles = voice_pipeline.ensure_roles()
        role = roles.get(voice_pipeline.ROLE_REPLY) or {}
        provider = str(role.get("provider") if isinstance(role, dict) else getattr(role, "provider", "") or "")

        def run(prompt: str):  # type: ignore[no-redef]
            return MODEL_ROLES.run(voice_pipeline.ROLE_REPLY, prompt, system=voice_pipeline._DRAFT_SYSTEM,
                                   max_tokens=voice_pipeline.DRAFT_MAX_TOKENS)
    if provider and provider not in LOCAL_PROVIDERS and not online:
        return {"provider": provider, "skipped": "a cloud model — run with --online to time it"}
    start = time.perf_counter()
    try:
        answer = run(QUESTION)
    except Exception as error:  # noqa: BLE001
        return {"provider": provider, "error": f"{type(error).__name__}: {str(error)[:120]}"}
    text = str(getattr(answer, "text", answer) or "")
    return {"provider": provider or getattr(answer, "provider", ""), "model": getattr(answer, "model", ""),
            "answer_ms": _ms(start), "words": len(text.split())}


def bench(voices: List[str], online: bool = False) -> Dict[str, Any]:
    return {
        "voice_tests": time_voice_tests(voices),
        "first_sound": time_first_sound(voices[0]) if voices and voices[0].endswith("Neural") else {"skipped": "not a neural voice"},
        "voice_to_action": time_voice_to_action(),
        "spoken_answer": time_spoken_answer(online=online),
    }


def _default_voices() -> List[str]:
    import tts

    reply = tts.voice_for("reply")
    others = [v["id"] for v in tts.neural_voices("en-US")[:6] if v["id"] != reply][:2]
    return [reply, *others]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--voices", nargs="*", help="voice ids to time (default: the reply voice and two others)")
    parser.add_argument("--online", action="store_true", help="also time a cloud voice model (may cost money)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of lines")
    args = parser.parse_args(argv)
    report = bench(args.voices or _default_voices(), online=args.online)
    if args.json:
        print(json.dumps(report, indent=1))
        return 0
    for row in report["voice_tests"]:
        print(f"voice test   {row['voice']}: " + (row.get("error") or f"first {row['first_ms']} ms, again {row['cached_ms']} ms"))
    sound = report["first_sound"]
    print("first sound  " + (sound.get("error") or sound.get("skipped") or
                             f"{sound['voice']}: first audio {sound['first_chunk_ms']} ms, whole clip {sound['whole_clip_ms']} ms"))
    action = report["voice_to_action"]
    print(f"to action    '{action['command']}': {action['median_ms']} ms, handled={action['handled']}")
    answer = report["spoken_answer"]
    print("answer       " + (answer.get("error") or answer.get("skipped") or
                             f"{answer['provider']} {answer.get('model', '')}: {answer['answer_ms']} ms, {answer['words']} words"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
