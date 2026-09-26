# Nyx Ichos — own-model routine

Standing goal, set 2026-09-06. This file exists so the work survives a lost
session: it holds the goal, the phase plan, and the exact cloud-routine config.

## Status

**Blocked on one authorization.** The routine was rejected at creation with
`403 — You don't have access to a repository this routine uses`. The repo URL is
correct (`origin` here is `https://github.com/ShagnikPal123/Local-AI-Project.git`);
Claude Code's **cloud** side has not been granted access to it.

Fix: connect GitHub / grant this repository to Claude Code cloud sessions at
<https://claude.ai/code/routines>. Then the create call below succeeds unchanged.

## The goal

Nyx Ichos routes to hosted providers (Gemini, OpenAI, others) through `router.py`.
Give it **its own model** — not a stock model wearing a system prompt, but an
open-weights base fine-tuned on data specific to what Nyx Ichos is for, packaged
as a custom Ollama model, wired into the existing router, with retrieval and a
real evaluation harness.

Framing that matters: **Ollama is a runtime, not a model.** "Built on top of
Ollama" means a custom model *served by* Ollama — `FROM <open-weights base>` in a
Modelfile plus a fine-tuned adapter. Nothing retrains Ollama itself.

## Phases

- **0 — Choose the base.** Qwen3 / Llama 3.x / Mistral Small / Gemma 3 / DeepSeek,
  judged on license (must permit derivative work *and* redistribution — quote the
  terms), tool-calling quality, context length, and whether a quantized build runs
  on a consumer GPU under Ollama. Record the decision, the runner-up, and what
  would change it.
- **1 — Identity and packaging.** `model/Modelfile` → `ollama create nyx-ichos:v0`.
  System prompt lifted from the personality already in the Python source, not
  invented fresh. README with exact commands and VRAM per quantization.
- **2 — Dataset pipeline.** `model/data/` builds JSONL chat data from the owner's
  own Nyx logs (collector only — never fabricated), the project's own docs and
  source, and named permissively-licensed public sets. Dedup, quality filter, PII
  scrub.
- **3 — Fine-tuning.** `model/train/` LoRA/QLoRA, GGUF conversion, `nyx-ichos:v1`
  with the adapter. Runs on one consumer GPU, with a documented rented-GPU path.
- **4 — Evaluation.** `model/eval/` — a benchmark for what Nyx actually does: tool
  calling, generating the app's declarative tab/widget specs, memory recall,
  refusal calibration, latency. Scoreboard vs base and vs the hosted providers.
- **5 — Online data and autonomy.** Live retrieval into context; a documented
  self-improvement loop harvesting real failures into the next training set.
  Designed, not armed — anything autonomous stays behind explicit approval.
- **6 — Router integration.** `nyx-ichos:*` as a first-class local provider with
  the same fallback behaviour as the hosted ones.

## Accepted constraint — training data provenance

**Do not build a pipeline that trains on scraped Claude, OpenAI, Perplexity or
Kimi responses.** Those providers' terms restrict using their outputs to train
competing models. They stay in the router at runtime, and may be used for
evaluation and comparison. Later runs must not undo this.

## The routine

Every 3 hours (`0 */3 * * *` UTC), model `claude-opus-5`, environment
`env_01JkDRwdaKcLpoT1vJRUxwFw`, source `https://github.com/ShagnikPal123/Local-AI-Project`,
tools `Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch`.

Each run: read `NYX_MODEL_PLAN.md`; if absent, create it with Phase 0 decided and
stop; otherwise advance the **first unchecked item** and tick it off. Work on
branch `nyx-model`, keep **one** PR open and update it rather than opening a new
one per run. Never commit `.env.local`, `.secrets.json`, `auth.json`, `chats.json`,
`memory.json`, or anything under `Real Nyx/`. Never fabricate benchmark numbers.

Manage or re-create it at <https://claude.ai/code/routines>.
