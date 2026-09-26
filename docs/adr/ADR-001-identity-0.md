# ADR-001: Identity 0 ("Big Kahuna") — one main brain that collaborates first, trains its own model, then runs on its own

**Status:** Accepted (owner request S, 2026-09-18); amended 2026-09-21 (see *Amendment* below). Tracked in `docs/IDENTITY0.md`.
**Date:** 2026-09-18
**Deciders:** Shagnik (owner) — final say. Proposed by the Claude Code Manager session; built with Coder, Trainer
(AI/ML) and Reviewer subagents.

## Context

The owner wants Identity 0, whose public name is **Big Kahuna**, to become Nyx's **main brain**. It should be "the
overall supercore and the AI model powering it all", replacing today's brains. Every other model becomes a
collaborator first and a backup second. It should train its own local model: work alongside Ollama at first
("2 models running at once"), then detach and run alone ("then 1"). It should learn from everything, make the tabs the
owner needs, ship templates for every kind of project, run every change through itself, and eventually be able to
pass other local and online models.

What exists today (2026-09-18):

| Piece | What it is | Limitation Identity 0 addresses |
|---|---|---|
| `router.py` | Picks *a* working provider, free-first, with fallback | Knows nothing about which model is good at what; no collaboration |
| `consult.py` | Second opinions on "heavy" questions (25 s budget) | Only a context note for one answering model; learns nothing |
| `model_roles.py` / `model_hub.py` | Exact provider+model calls per job, with fallbacks | Static assignments |
| `nyx_core.py` | A growing numpy MLP (route/domain/tool heads), a word model, a "crutch ledger", a distillation set | Not a language model; cannot answer anything itself |
| `super_brain.py` | SQLite+FTS5 knowledge graph (29k+ nodes) with `recall` | Retrieval only |
| `absorb_engine.py` | Reads papers/GitHub/Wikipedia/web into the super brain | Feeds memory, not a model |

Machine and accounts: RTX 5080 Laptop GPU, 16 GB VRAM (sm_120), 31 GB RAM, ~650 GB free disk, Python 3.14.
torch 2.11.0+cu128 is now installed and works on this GPU. Ollama 0.34.2 serves `qwen3.5:9b` (Apache-2.0; text,
vision, tools, thinking; about 89 tok/s warm). Of the online keys, NVIDIA works, Gemini hits its free quota, OpenAI has no
credit and Kimi gets a 401. Groq and DeepSeek keys are stored but untested.

Hard constraints:

- **The five invariants in `AGENTS.md`:** deny-by-default routes; specs are data, never code; the overlay never
  mutates base modules; nothing publishes without human review; no credential in source.
  "Changes are run through it" therefore means Identity 0 *reviews and proposes*. It never approves its own change.
- **Training-data provenance** (`NYX_MODEL_ROUTINE.md`, re-confirmed by the owner as the "Safe mix"): never train on
  OpenAI, Anthropic, Gemini, Kimi or Perplexity outputs. Llama-family outputs are excluded too, because the Llama
  license would force the model's name to start with "Llama". Web and Google results are for lookup only.
- **Owner preferences:** keep downloads and disk size small ("shrink the size, keep capabilities"). No full-precision
  base weights until the owner says go. The chat must "run flawlessly": a new brain must never make a turn fail.
- **Honesty about compute.** Frontier models are trained on thousands of GPUs. A 16 GB laptop GPU can LoRA-fine-tune
  roughly a 4B model in bf16, or an 8B model with 4-bit QLoRA, and can train a small model from scratch. "Pass other
  models" is a direction measured on a scoreboard, not a claim.

## Decision

Build Identity 0 as a **supercore package `identity0/`** with four layers. It enters the running app as a router provider
named `identity0` (label "Big Kahuna") at the head of the chain.

1. **Orchestrator (the brain that runs today).** `Identity0Provider.stream_events` classifies the request, then picks a
   lead member and a protocol (solo, race, panel or critique) from a **learned competence table** (domain × member). It
   streams the lead's answer and fails over internally. Sometimes it also runs a **shadow** member in the background for
   comparison. Every other model (Ollama, NVIDIA, Gemini, Groq, custom) is a member. Behind Identity 0, the existing
   router chain stays intact as the backup: if Identity 0 raises, the turn continues exactly as it does today.
2. **Learning loop.** Each answer is logged as an *experience* with its provenance. A budgeted, order-swapped pairwise
   **judge** compares the lead with the shadow and updates competence. When Identity 0 "can't figure it out" (weak
   domain, failure, lost judgement, owner 👎), it brings collaborators in and keeps the winning answer. The answer goes
   to the super brain at once, and to the training set later, but only if the policy allows it.
3. **Its own neural network ("Kahuna model").** Identity 0 has its own PyTorch decoder runtime for the Llama/Qwen family.
   It uses SDPA/flash attention, a KV cache and streaming. It has an **AirLLM-style layered mode**: flat per-layer
   safetensors files, one layer on the GPU at a time, the next one prefetched into pinned memory, optional block-wise
   int8/NF4 compression, and only at MAX power, off by default. This covers Request P. There are two tracks:
   (a) **Nano** — a small model trained from scratch here, now, on the Safe-mix corpus, which grows like Nyx Core does;
   (b) **LoRA on an open base**, once the owner allows the base download. The own model is served by its own local
   process (OpenAI-compatible, `127.0.0.1:11500`), so Identity 0 can detach from Ollama. Exporting to Ollama is optional.
   All heavy ML work runs as **subprocess jobs**. The app process never imports torch.
4. **Staged autonomy — "2 models at once, then 1".** Stage **Collaborate** has no own model; Identity 0 orchestrates the
   members. Stage **Twin**: the own model and the local teacher (Ollama) both run, and a judge compares them. Stage
   **Solo** is reached domain by domain, once the own model's Wilson lower bound on its win rate against the teacher is at
   least 0.5 over at least 30 judged comparisons (demotion is automatic). The teacher and the online members stay as
   escalation and backup.

Around those four layers:

- **Supercore:** a versioned *constitution* (persona, principles, routing weights, thresholds, members) that is data
  and can be changed through the review pipeline. Identity 0 is available as a model for every role (`model_hub` provider
  `identity0`), so the change critic and reviewers can run through it.
- **Tab planner** (proposals from real usage → dynamic-tab specs, which are data; created on approval) and a
  **template library** (code, websites, documents, tabs and prompts, all as static data).
- **Data pipeline:** Wikipedia, Project Gutenberg, films (Wikipedia + Wikidata), arXiv abstracts, the owner's chats
  (PII-scrubbed) and permitted collaborator answers. The corpus is license-tagged, deduplicated and storage-capped.

## Options Considered

### Option A: Identity 0 as an orchestrating provider + own runtime + staged graduation (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | High, but layered: each layer ships and is useful alone |
| Cost | Free; runs on owner's GPU and free keys; no paid calls |
| Scalability | Base model can grow with hardware; layered mode runs models larger than VRAM |
| Team familiarity | Reuses router, model_hub, super_brain, nyx_core, absorb, resource_governor patterns |

**Pros:** It is useful on day one, because collaboration works before any training. It can't break chat: the old chain
sits behind it. Every claim is measured. It respects both the provenance rule and the invariants.
**Cons:** It adds a component to the hot path, so it has to stay cheap (offline ranking in a few ms). The judge spends
model calls, so it is budgeted and uses the local model first.

### Option B: Replace `router.py` with a new brain module

| Dimension | Assessment |
|---|---|
| Complexity | Very high — rewrites key failover, metrics, free-only rules, vision routing, G9/H6/J1 fixes |
| Cost | Free |
| Scalability | Same as A |
| Team familiarity | Throws away months of hard-won fixes |

**Pros:** One module instead of two.
**Cons:** High regression risk, which contradicts "run flawlessly". Rejected.

### Option C: Adopt external stacks as-is (the `airllm` package, Unsloth / LLaMA-Factory, transformers + peft)

| Dimension | Assessment |
|---|---|
| Complexity | Low to write, high to keep alive |
| Cost | Large dependency tree (transformers/accelerate/bitsandbytes), GBs more on disk |
| Scalability | Good on Linux |
| Team familiarity | Low; Windows + Python 3.14 + sm_120 support is uneven; `airllm` is tightly coupled to transformers internals and breaks when they change |

**Pros:** Less code of our own.
**Cons:** Fragile on this machine; conflicts with "keep it small". We take AirLLM's *ideas* (layer sharding, prefetch,
block-wise compression) and implement them in ~1k lines of our own torch code. transformers may be used in tests only,
as an optional parity check.

### Option D: Train a large model from scratch

| Dimension | Assessment |
|---|---|
| Complexity | Low code, impossible compute |
| Cost | Thousands of GPU-days for anything competitive |
| Scalability | n/a |
| Team familiarity | n/a |

**Pros:** Fully "our own".
**Cons:** Infeasible on one laptop GPU. Kept only as the small Nano seed, which proves the pipeline end to end.

## Trade-off Analysis

The decisive trade-off is **ambition against "run flawlessly"**. Option A puts the new brain in front of the old chain
instead of in place of it. A bug in Identity 0 then costs at most one internal retry, never a failed turn. It still
satisfies "Identity 0 is our main brain": it leads every turn by default and decides who answers.

The second trade-off is **own runtime against dependencies**. Writing our own Llama/Qwen decoder costs us parity work: we
test it against transformers on tiny random configs, whenever transformers is present. In return we get a runtime we
control end to end. That control is what makes the AirLLM-style layered mode, LoRA training and "detach from Ollama"
possible with only torch, safetensors and tokenizers.

The third trade-off is **learning speed against provenance**. Distilling from Gemini or OpenAI would be faster, but their
terms forbid it, and it would block sharing the model with beta testers ("the start for everyone's code"). The Safe
mix is slower but clean. Those providers still help at runtime and as evaluation references.

## Consequences

- **Easier:** answering well with the free keys available (Identity 0 learns who is good at what); adding a model (it
  becomes a member automatically); measuring whether the own model is catching up (scoreboard); running models larger
  than VRAM (layered mode).
- **Harder:** the turn path has a new component, which needs cheap ranking, internal failover and tests on every
  failure path. Judge calls consume quota, so they are budgeted, local-first and off when on battery or at low power.
- **Disk:** torch adds ~4.2 GB to `.venv`. Corpus, datasets and checkpoints are capped (defaults: corpus 2 GB,
  datasets 256 MB, adapters instead of merged copies). A final "shrink" step (S14) compresses and prunes while
  keeping capabilities.
- **Revisit when:** the owner allows the base-weights download (start LoRA track B); a bigger GPU appears (larger base,
  QLoRA 14B+); Ollama gains safetensors import for the chosen base (simpler export); win rates show a domain never
  graduating (change the base or the data mix).

## Action Items

1. [ ] Record request S verbatim; this ADR; living doc `docs/IDENTITY0.md` with contracts (Manager).
2. [ ] Orchestrator: provider, members, competence, collab protocols, experiences, judge, routes, tools, UI (Coder).
3. [ ] Model: runtime, layered/AirLLM mode, quantization, LoRA, Nano trainer, jobs, serving, eval, data pipeline and
       provenance policy (Trainer).
4. [ ] Review every delivery against the invariants, failure paths and tests (Reviewer).
5. [ ] Wire-up and live verification in the running app: a real chat turn led by Big Kahuna, a real Nano training
       run on the GPU, layered inference on a sharded model (Manager).
6. [ ] Shrink step (S14): compress corpora/datasets, keep adapters only, prune caches; measure before/after.
7. [ ] Then Request T (GitHub), U (beta link), V (accounts with Google + Apple sign-in).


## Amendment — 2026-09-21: the own model is ours from the first weight

The owner asked: "be certain ID0 is its own local model right. Not qwen or anything our own one?" So track (a), the
**from-scratch model**, is now the primary track rather than a "seed". It has our own decoder code
(`identity0/model/runtime.py`), a byte-level BPE tokenizer trained on our own corpus, and weights initialised at random
and trained on this PC. Qwen (via Ollama) is only a **teacher** and collaborator: Identity 0 learns from the teacher's
answers (sequence-level distillation, which Apache-2.0 allows) and never from its weights. Track (b), LoRA on someone
else's base, is optional. The owner has not allowed that download, and it would make the model partly someone else's.

Consequences: the own model starts far weaker than the teacher and grows by more data, more training time and larger
presets (`nano` 32M → `small` 88M → larger). The staged graduation rule guarantees that it only leads an area once it
wins judged comparisons there, so a weak early model never costs the owner a bad answer by default.
