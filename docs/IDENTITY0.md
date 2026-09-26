# Identity 0 — "Big Kahuna" — living design, contracts and progress

Read this before touching `identity0/`. Why the design looks like this: `docs/adr/ADR-001-identity-0.md`.
The owner's words: `AI_HANDOFF/01_GOALS.md` § Request S. Keep the **Progress log** at the bottom current; newest first.

- **Public name:** Big Kahuna. **Second (secret) name:** Identity 0. **Code name:** `identity0`.
- **Router provider id:** `identity0`, label "Big Kahuna". **UI tab id:** `kahuna`.
- **Data directory:** `kahuna/`, resolved with `paths.data_path("kahuna/...")`. In dev that is `<project>/kahuna/`.
  NEVER `data_path("identity0/...")`: in dev, DATA_DIR is the project folder, so that path would write into the
  code package. `kahuna/` is gitignored because it holds chat-derived data and weights.

## 1. What it is, in one picture

```
                           ┌──────────────── Identity 0 (Big Kahuna) ────────────────┐
 chat turn ─► router ─►    │ classify (nyx_core + heaviness) → plan (competence table) │
 (turn_runner)  first in   │   lead member ──stream──► answer                         │
                chain      │   shadow member (budgeted, background) ─► experience log  │
                           │   judge (order-swapped, local-first) ─► competence update │
                           │   "can't figure it out" → panel/critique → learn          │
                           │ members: ollama:qwen3.5:9b · nvidia:* · gemini:* · groq:* │
                           │          custom:* · self:<version> (own model, later)     │
                           └───────────────┬─────────────────────────────┬─────────────┘
          if Identity 0 raises → router's   │ learn: super_brain (now)    │ jobs (subprocess, torch)
          old chain continues (backup)      ▼ dataset (policy-gated)      ▼ corpus → dataset → train → eval
                                                                          → serve own model :11500
```

Stages ("2 models at once, then 1"), decided **per domain**:

| Stage | Own model? | Who leads | Shadow |
|---|---|---|---|
| `collaborate` | none yet | best member for the domain (competence) | another member, budgeted |
| `twin` | yes, not graduated in this domain | teacher (Ollama) or best member | own model runs alongside; judged |
| `solo` | graduated in this domain | own model (`self:<version>`) | teacher at a low sampling rate for monitoring |

Graduation rule: the own model's Wilson lower bound (95%) on its win rate against the teacher must be ≥ 0.50, with
n ≥ 30 judged comparisons in that domain. Demotion happens when the upper bound over the last 30 is < 0.45. Ties count
half.

Domains are nyx_core's: `chat web files code knowledge agents self-study email design system models voice`.

## 2. Team and file ownership (Request S build)

| Agent | Owns (creates/edits freely) | May insert small edits into |
|---|---|---|
| Manager (lead session) | `docs/IDENTITY0.md` (sections 1–4 and 7), `docs/adr/*`, `AI_HANDOFF/*`, final wiring and live checks | anything, after the owners deliver |
| Coder | `identity0/__init__.py state.py members.py competence.py collab.py provider.py experience.py judge.py supercore.py tabs.py tools.py`, `identity0/templates/**`, `routes_identity0.py`, `frontend/nyx-pulse/src/panels/kahuna/**`, `tests/test_identity0_core.py test_identity0_routes.py test_identity0_templates.py test_identity0_tabs.py` | `router.py`, `providers/ollama_provider.py`, `turn_runner.py`, `learning_hooks.py`, `model_hub.py`, `model_choice.py`, `predictor.py`, `server.py` (router tuple: add `"routes_identity0"` AFTER `"routes_freewill"`), `tool_setup.py` (append `("identity0.tools", "register_identity0_tools")`), `tests/test_server_auth.py` (append only), `frontend/nyx-pulse/src/tabs.ts` + `App.tsx` (one entry each, AFTER `freewill`), `.gitignore` (add `kahuna/`) |
| Trainer (AI/ML) | `identity0/policy.py jobs.py evaluate.py`, `identity0/corpus/**`, `identity0/model/**`, `requirements-identity0.txt`, `tests/test_identity0_policy.py test_identity0_corpus.py test_identity0_model.py test_identity0_layered.py test_identity0_train.py test_identity0_eval.py test_identity0_jobs.py` | `resource_governor.py` (read-only use preferred), `docs/IDENTITY0.md` §5 |
| Reviewer | nothing, read-only; reports findings to the Manager | — |

Both builders append their own notes to **§6 Build notes** of this file, under their own heading.

## 3. Rules every agent follows (from AGENTS.md + this request)

1. Run from the project folder with `.venv/Scripts/python.exe`. Tests: `.venv/Scripts/python.exe -m pytest tests/test_identity0_*.py -q -p no:warnings`.
   After frontend edits: `cd frontend/nyx-pulse && npm run build` (tsc is the only frontend gate).
2. **The app process never imports torch** (not even at module import of anything the server loads). torch/safetensors/
   tokenizers are imported only inside `identity0/model/**`, `identity0/jobs.py` workers and tests. Those modules must
   import cleanly without torch (lazy imports), and tests needing torch use `pytest.importorskip("torch")`.
3. Every persistent path goes through `paths.data_path("kahuna/...")`. Tests use `tmp_path` or monkeypatch — never the
   real `kahuna/`, `brain/`, `chats.json`.
4. Deny by default: every `/api/identity0/*` route is owner-only (`server_auth`), and has a refusal test.
5. No secrets in code, logs, experiences, datasets or UI. Scrub with `providers.custom.scrub_secrets` /
   `identity0.policy.scrub_pii`.
6. Never execute model-written code. Templates are static files written only into a folder the owner chose. Coding
   evals are judged or statically checked (ast.parse, expected symbols), never run.
7. Identity 0 never approves its own change. Self-changes go through `change_review` / Improve review (owner approves).
8. Free-only: never call a paid provider the owner hasn't allowed (`router.unavailable_reason(name)` / `SETTINGS.free_only`
   / `model_choice.allowed_paid`). Shadow and judge calls are budgeted (settings below) and local-first.
9. A failure anywhere inside Identity 0 must never fail the turn: raise `ProviderError` so the router's old chain
   continues. The hot path (plan) is offline and stays under ~5 ms. No network or disk I/O in `is_available()` beyond
   cached checks.
10. Don't `git commit`/`push`. Don't restart the owner's engine (port 8000). For live checks, start a second instance on
    another port (e.g. 8011) and stop it afterwards.
11. Keep it small (owner): no new heavy dependency without the Manager's OK. Allowed: torch, safetensors, tokenizers,
    gguf, numpy. transformers is allowed **only** as an optional test-time parity check (skip if absent; don't install it
    without asking the Manager).

## 4. Contracts (signatures both builders code against)

### 4.1 Settings — `identity0/state.py` (Coder)

```python
def data_dir() -> Path                                  # paths.data_path("kahuna/.keep").parent
def get_settings() -> Dict[str, Any]
def update_settings(**changes) -> Dict[str, Any]        # validates types/ranges, atomic write kahuna/settings.json
DEFAULTS = {
  "enabled": True,            # Big Kahuna leads every turn (router chain head)
  "shadow_rate": 0.25,        # share of turns that also run a second member
  "shadow_local_only": False, # False: a free online member may shadow/judge too, inside api_shadow_per_hour
                              # (every online shadow, helper and judge reading comes out of that hourly budget)
  "api_shadow_per_hour": 6,   # hard cap on API calls spent on shadows+judging per hour
  "judge_per_hour": 20,
  "panel_on_hard": True,      # hard/weak-domain requests use a panel/critique protocol
  "auto_promote": False,      # promoting a new own-model version needs the owner's click
  "layered_mode": "off",      # "off" | "auto" (auto = only at MAX power and when the model is too big) — Request P
  "train_on_chats": True,     # Safe mix (owner answer 2026-09-18)
  "corpus_cap_mb": 2048, "dataset_cap_mb": 256, "experience_cap_mb": 50,
  "auto_tabs": False,         # tab planner proposes; creating needs a click unless this is on
  "ollama_autostart": True,   # bring the local service back up when it is down (at most once every 5 min)
  "id0_all": False,           # "ID0 + All": the companion window with its own chat (Request S21)
}
```

**Who may call these routes.** All of `/api/identity0/*` is the *owner's* alone — not an admin's.
`require_local_owner` also lets an admin through (they may restart the engine), so `routes_identity0._owner_dep`
checks the role as well: Big Kahuna reads every answer and can open things on this PC by voice.
`tests/test_server_auth.py` proves anonymous, beta and admin callers all get 401/403 on every route.

**The stable way in for the rest of Nyx** is `identity0/api.py` — `best_models(task_or_domain)`, `domain_of(text)`,
`competence()`, `voice_intent(text, final=, tabs=)`, `suggest(text, current_tab=)`. They never raise and never
write, so a broken Big Kahuna cannot break the feature asking it for advice. Other features bind to these, not to
`competence`/`predict`/`companion` directly (Office Space, agent grading and the voice bar all use them).

### 4.2 Members — `identity0/members.py` + `identity0/collab.py` (Coder)

Member id format: `"<provider>:<model>"`, e.g. `ollama:qwen3.5:9b`, `nvidia:nvidia/nemotron-3-super-120b-a12b`,
`gemini:gemini-flash-lite-latest`, and `self:<version>` for the own model.

```python
members.available(job: str = "text") -> List[Dict]   # {"id","provider","model","local":bool,"free":bool,"vision":bool,"label"}
collab.complete(member: str, messages: List[Dict], *, max_tokens: int = 800, temperature: float = 0.3,
                timeout: float = 60, system: str = "") -> Dict   # {"text","ms","ok","error","member"} — never raises
collab.stream(member: str, messages, *, thinking=False, cancelled=None) -> Iterator[Dict]  # router-style events
collab.panel(messages, members: List[str], *, budget_s: float = 40) -> Dict  # {"answers":[...],"best":..., "synthesis":...}
```

### 4.3 Experiences — `identity0/experience.py` (Coder) → read by the Trainer's dataset builder

`kahuna/experiences.jsonl`, one JSON object per line, capped at `experience_cap_mb` (oldest dropped):

```json
{"id":"exp_<12hex>","ts":1789770000.0,"turn_id":"...","domain":"code","difficulty":0.42,
 "prompt":"last user text ≤4000 chars","context_digest":"sha1 of the full message list",
 "protocol":"solo|race|panel|critique",
 "lead":{"member":"ollama:qwen3.5:9b","text":"≤8000 chars","ms":812,"ok":true},
 "shadow":{"member":"nvidia:…","text":"…","ms":2100,"ok":true} ,
 "verdict":{"winner":"lead|shadow|tie","confidence":0.8,"by":"member id","reason":"≤300 chars"},
 "rating":null,
 "trainable":{"lead":true,"shadow":false},
 "learned":false}
```

`shadow` and `verdict` may be `null`. `trainable` comes from `identity0.policy.may_train_on(provider, model)`.

### 4.4 Judge — `identity0/judge.py` (Coder); also used by the Trainer's evals

```python
judge.compare(question: str, a: str, b: str, *, context: str = "", exclude: Sequence[str] = (), budget_s: float = 30)
    -> Dict  # {"winner":"a"|"b"|"tie","confidence":0..1,"reason":str,"by":member_id}; asks twice with a/b swapped,
             # disagreement → "tie"; the judge is never one of `exclude` (the two contestants); never raises
judge.grade(question: str, answer: str, *, reference: str = "", rubric: str = "", budget_s: float = 30)
    -> Dict  # {"score":0..10,"reason":str,"by":member_id}
```

### 4.5 Provenance policy — `identity0/policy.py` (Trainer); used by the Coder when logging experiences

```python
may_train_on(provider: str, model: str = "") -> Tuple[bool, str]   # deny by default; reason in words
source_license(source: str) -> Dict   # {"source","license","train":bool,"attribution":str}
scrub_pii(text: str) -> str           # emails, phones, keys/tokens, card-like numbers, street addresses (best effort)
```

Safe mix (owner, 2026-09-18). **Allowed:** Wikipedia (CC BY-SA 4.0, attribution in the dataset card), Project
Gutenberg (US public domain, strip the PG header/footer), Wikidata (CC0), arXiv *abstracts/metadata* (CC0), the owner's
chats (while `train_on_chats`), and answers from open-license models: Qwen family, DeepSeek, Mistral (Apache), gpt-oss,
NVIDIA Nemotron (NVIDIA Open Model License), and the own model. **Denied:** OpenAI, Anthropic/Claude, Google Gemini,
Moonshot Kimi, Perplexity, Llama-family outputs (naming clause), Gemma outputs, web/Google pages (lookup only), and
anything unknown.

### 4.6 Own model — `identity0/model/*` (Trainer); used by the Coder's members/collab

```python
identity0.model.client.current() -> Optional[Dict]  # {"version","kind":"nano"|"lora","base","params","ready":bool,"endpoint"}
identity0.model.client.is_ready() -> bool           # cached ≤5 s; never imports torch in the caller's process
identity0.model.client.stream_chat(messages, *, max_tokens=1024, temperature=0.7, cancelled=None) -> Iterator[str]
identity0.model.client.complete(messages, **kw) -> str
identity0.model.client.ensure_started() -> Dict     # starts the serve subprocess for the promoted version if allowed
identity0.model.registry.list_versions() / promote(version) / rollback()
```

The serve process speaks OpenAI-compatible `/v1/chat/completions` (stream) on `127.0.0.1:11500`, loopback only.

### 4.7 Jobs — `identity0/jobs.py` (Trainer); called by the Coder's routes

```python
jobs.requirements() -> Dict   # {"torch":bool,"cuda":bool,"gpu":str,"vram_gb":float,"missing":[...]}
jobs.start(kind: str, params: Optional[Dict] = None) -> Dict
    # kinds: "corpus", "dataset", "train_nano", "train_lora", "eval", "shard", "export", "serve"
    # returns {"id","kind","state":"queued|running|done|failed|cancelled","progress":0..1,"message","started","log_tail"}
jobs.get(job_id) -> Optional[Dict]; jobs.list_jobs(limit=30) -> List[Dict]; jobs.cancel(job_id) -> Dict
```

Jobs run as `[sys.executable, "-m", "identity0.jobs", "run", "<id>"]` and write progress to `kahuna/jobs/<id>.json`.
Heavy kinds check `resource_governor` first (HIGH or MAX). Layered inference needs MAX and `layered_mode != "off"`.

### 4.8 Evaluation — `identity0/evaluate.py` (Trainer)

```python
evaluate.suites() -> Dict[str, Dict]
evaluate.run(member: str, suite: str = "core", limit: int = 0) -> Dict  # appended to kahuna/scoreboard.jsonl
evaluate.scoreboard() -> List[Dict]
```

## 5. Model track — Identity 0's own neural network (from scratch; owner 2026-09-21)

| Piece | File | What it is |
|---|---|---|
| Shapes | `identity0/model/config.py` | `ModelConfig` (plain data, no torch); presets `tiny` (tests, 107k params), `nano` (32.0M), `small` (88.1M) |
| Network | `identity0/model/runtime.py` | Decoder-only transformer: RMSNorm, RoPE (rotate-half), GQA, per-head q/k norm, SwiGLU, tied embeddings, SDPA (flash kernels on CUDA), preallocated KV cache, `generate` with temperature/top-k/top-p/repetition penalty. KV-cache decode == full recompute (max diff 1.8e-7) |
| Tokenizer | `identity0/model/tokenizer.py` | Byte-level BPE trained on our corpus (`tokenizers`), own chat tokens (system/user/assistant/end), loss mask on assistant tokens |
| Training | `identity0/model/train.py` | Time-budgeted: pretraining on packed windows, then instruction tuning (identity + teacher answers + trainable experiences, 15% pretraining mixed in), fused AdamW, cosine LR over the minutes, bf16 autocast, grad clip 1.0, held-out perplexity on documents never trained on, checkpoints, final weights in bf16 |
| AirLLM parts | `identity0/model/layered.py`, `quant.py` | Flat per-layer safetensors + manifest (resumable), one reusable block on the device, background prefetch into pinned memory, int8 / NF4 block-wise compression (64-value blocks), per-layer KV cache; `allowed()` = setting `layered_mode: auto` AND power mode MAX (Request P) |
| Versions | `identity0/model/registry.py` | `kahuna/models/<version>/`; register, promote (owner click unless `auto_promote`; the very first version is promoted by the job), rollback, remove |
| Serving | `identity0/model/serve.py`, `client.py` | Own process on 127.0.0.1:11500 (loopback only), OpenAI-shaped `/v1/chat/completions` with SSE; exits after 60 idle minutes; `client` never imports torch |
| Jobs | `identity0/jobs.py` | Subprocess jobs `corpus` / `distill` / `train_nano` / `shard` / `serve`; progress in `kahuna/jobs/<id>.json`; cancel file; below-normal priority; no console window |
| Data | `identity0/corpus/` | `store.py` (gzip JSONL shards, SimHash near-dup within 5/64 bits, a license per doc, compressed-size cap, dataset card), `sources.py` (Featured Wikipedia articles sampled at random, intros, Gutenberg via gutendex or a built-in classics list, films via Wikidata + Wikipedia, arXiv abstracts, only the owner's own questions from chats), `dataset.py` (identity examples, grounded teacher prompts, distillation from a permitted teacher only) |
| Scoreboard | `identity0/evaluate.py` | 20 fixed questions (facts, math, reasoning, instructions, code parsed with `ast`, Nyx tool-call format, identity, summary) checked mechanically; `kahuna/scoreboard.jsonl` is append-only |

Measured on this PC (RTX 5080 Laptop, 16 GB): nano (32M) trains at ~56–74k tokens/s at batch 32×512 using ~2 GB
VRAM (bf16); it serves at ~20 tokens/s.

**What a run is judged on.** Reading is scored by held-out perplexity on documents never trained on; instruction
tuning is scored by the loss on *conversations* never trained on (one row in twenty is held back). The version kept
is the best point on those measures, not the last step — a small chat set is memorised in minutes otherwise
(nano-v1 reached a training loss of 0.005 while its answers got worse). Training saves weights, optimiser state and
its place in the schedule every few minutes, so a run that is interrupted (the PC sleeps) resumes rather than restarts.
Growth path: more corpus + minutes → `small` (88M) → larger presets. Function-preserving growth (Net2Net) is planned but
not built yet. Optional track (b), LoRA on an open base, needs the owner's OK for the download.

### 5.1 Measured results (kept up to date — nothing here is an estimate)

The fixed suite is `identity0/evaluate.py` (20 questions, mechanically checked); perplexity is on documents the
model never trained on. Every scoreboard run is appended to `kahuna/scoreboard.jsonl`.

| Version | Training text | Tokens seen | Held-out perplexity | Suite | identity | facts | avg answer |
|---|---|---|---|---|---|---|---|
| `nano-v1` (32M) | 8.5M tokens | 164M | 97.5 | 0.15 | 1.00 | 0.17 | 6.9 s |
| `nano-v3` (32M) | 81.5M tokens | 780M | **34.0** (best 27.7) | 0.10 | 1.00 | 0.00 | 8.2 s |
| teacher `ollama:qwen3.5:9b` | — | — | — | **0.90** | 1.00 | 1.00 | 1.7 s |
| `nvidia:nemotron-3-super-120b` | — | — | — | 0.94 | 1.00 | 1.00 | — |

**What that says.** Ten times more text made it a far better *reader* (perplexity 97 → 34, still falling when the
run ended) and no better at the suite, because the suite is mostly world facts and arithmetic. A 32M-parameter model
cannot hold those; what it can learn is language, style, its own identity (1.00, every run) and short shaped answers.
So the own model's job is the one the design already gives it: the fast twin that answers easy and spoken turns,
graduating per domain only where it actually wins, while the teachers answer the rest. The competence table now
learns this outright — a scoreboard run feeds `competence.record_exam`, so Big Kahuna knows the own model is 0.00
at facts and 1.00 at identity without having to lose judged turns to find out.

**What is still worth doing** (in order of measured effect): more teacher conversations (the instruction set was
772 rows — hundreds of steps of memorising, not learning), then more reading time, then the `small` (88M) preset.
More corpus beyond ~200M tokens helps reading, not facts.

## 6. Build notes (2026-09-21/24)

The Coder and Trainer subagents hit the usage limit before writing any code, so the lead session built their parts
directly to save the owner's weekly budget. The Reviewer subagent audited the result.

- **Router integration**: `Identity0Provider` is registered in every `Router` and put first in `_candidate_chain` when
  enabled and available. Inner `{"type": "member"}` events become `provider` events (the chat shows who really leads).
  Inner `{"type": "reset"}` clears the collected text. `exclude=["identity0"]` can never fall back to Identity 0.
  `_online_order` never contains it. The owner's explicit dropdown pick still goes first.
- **Leading goes through the router** (`collab.stream`: a worker thread + a queue), so key failover, metrics, image routing
  and free-only rules all still apply. One-shot calls (shadow, judge, helpers, evals) call the member's provider object
  directly (`collab.complete`), which also keeps tests on fake providers.
- **Voice & trading speed path** (`predict.speed_mode`): the `[Hands-free voice]` note or trading words → the fastest
  member within 0.08 of the best score, no helpers, no reasoning. Otherwise reasoning (`think`) is on only when the
  request is hard (difficulty ≥ 0.5): Qwen3.5 reasons on everything when `think` is unset.
- **Ollama**: `OLLAMA_MODEL` now points to the installed `qwen3.5:9b`. Every call asks for `num_ctx` 32768, one fixed size
  because a different size makes Ollama reload. The default was 4096, which silently cut Nyx's ~12.7k-token tool
  instructions. `stream_events` honours `model`, `think` and pictures; `supports_vision` asks `/api/show`.
- **Members** skip a model built on another installed one (Data Absorption's `nyx-absorbed` is qwen3.5 plus a system
  prompt, so it's the same weights). They also skip billable providers unless the provider is the owner's current pick.
- **Gotcha found live**: a chat turn sent to an unknown `chat_id` lands in the owner's *active* chat. Create a chat
  first (`POST /api/chats`) for any live test, then delete it. (A test message was removed from chat `bed43c72`.)
- **Tests**: `tests/conftest.py` gives Identity 0 a temp store and turns it OFF by default, so older router tests see
  their original chain. Identity 0's own tests switch it on.
- **Corpus robustness**: every source runs on its own; one service down (gutendex timed out on the first run) costs only
  that source. Sources already collected are skipped on a rerun, by url, so nothing is downloaded twice.
- **Corpus at scale** (2026-09-23): articles are fetched by a few workers at once with `maxlag=5` (Wikipedia's own
  "back off" signal), from Featured *and* Good articles. The store had to keep up: near-duplicate search is banded
  (8 bands of 8 bits, so two hashes within 5 bits always share a band), the per-document index is an append-only
  sidecar instead of a file rewritten per document, and the size on disk is measured once a second, not once a document.
- **Jobs survive the session that started them**: spawned with `CREATE_BREAKAWAY_FROM_JOB | CREATE_NEW_PROCESS_GROUP`,
  and a job whose process is gone is shown as `interrupted` (with `POST /api/identity0/jobs/{id}/resume`), never as
  running forever. Two training runs were lost to this before it was fixed.
- **A teacher that stops answering** (Ollama shut down mid-run) ends distillation after 12 failures in a row with a
  note, instead of spending the whole budget on empty answers — which is what happened on 2026-09-23 (416 answers in
  150 minutes). `run_distill` starts Ollama itself when it is down.
- **Tool steps**: when TurnRunner sends tool results back (a user-role message marked `_tool_results`), Big Kahuna
  plans that call as one quick lead — no helpers, no shadow, no reasoning — and the domain is still read from the
  owner's own words, not from the tool output.
- **Nothing after the answer may cost the turn**: every bookkeeping call in `stream_events` (experience, shadow,
  companion) runs through `_quietly`. When the inner router really has tried every provider, the error is marked
  `chain_exhausted` so the outer router stops instead of walking the same chain again.
- **What is stored is scrubbed**: experiences (prompt, answers, helper drafts) go through `policy.scrub_pii` on the
  way to disk, because that file is both a diary and training data.
- **Keys & Models tab**: Big Kahuna is listed as a provider that is *always on and needs no key* ("Main brain · no
  key"), with a Check button that reports which models it is working with. It used to fall through the generic
  API-key branch and show "No key".

## 7. Progress log (newest first)

- 2026-09-24 (Manager, later): `nano-v3` trained (150 min, 780M tokens seen) → perplexity 34.0, and the numbers in
  §5.1 changed what to build next. Added: instruction tuning is now counted in *epochs* (the chat set is seen three
  times, not three hundred); a scoreboard run teaches the competence table (`competence.record_exam`); a promoted
  version takes the GPU over from the one being served (`client.stop()` + `POST /shutdown`, it used to wait an hour);
  the engine picks an interrupted training run back up on startup (`jobs.recover`, setting `auto_resume_training`);
  and `api.warm_up()` / `POST /api/identity0/warm` loads the local models before the owner speaks — a cold Ollama
  model measured **170 s** to first token, which would have made active voice useless. Corpus now 44k documents /
  749M characters. Live check: a real turn planned *twin* stage — `ollama:qwen3.5:9b` led, `self:nano-v3` shadowed,
  correct answer in 7 s — and a tool-result step was planned as one quick lead with no shadow or helpers.
- 2026-09-24 (Manager): **data pipeline rebuilt around the first measurements** (§5.1). Corpus 35M → 341M characters
  (18,198 documents) and still collecting; parallel fetch, Good articles added, store fast at that scale. Training is
  resumable and survives the PC sleeping; interrupted jobs say so and can be resumed. Instruction tuning now keeps the
  best point measured on unseen conversations and learns at a gentler rate. Ollama had quietly stopped, which cost the
  first distillation run most of its budget — distillation now restarts it and gives up early when the teacher is gone.
  Reviewer's 13 findings all fixed, including owner-only routes (an admin session could reach Big Kahuna) and the own
  model's window (long Nyx prompts left it one token to answer with, so every shadow answer was one token).
  `identity0/api.py` added as the stable way in for other features. Suite: 1,857 passed.

- 2026-09-22 (Manager): built the own-model track (runtime, tokenizer, trainer, AirLLM layered mode + int8/NF4, registry,
  serve/client, jobs), the Safe-mix corpus + distillation, templates (69), the tab planner, chat tools, the scoreboard, and
  the Big Kahuna tab sections (training progress, scoreboard, templates, suggested tabs). First real pipeline run started:
  800 Featured articles, 1,500 intros, 20 books, films and arXiv → teacher answers (qwen3.5, 20 min) → nano training
  (35 min). Project Null recorded (`AI_HANDOFF/PROJECT_NULL.md`), not started.
- 2026-09-21 (Manager): Big Kahuna core live-verified: a real chat turn went through Identity 0 (Gemini led for a chat
  question, 1.8 s), and the Big Kahuna tab renders. The owner's default provider is now `identity0`. Built the ID0 + All
  companion, voice early actions (open Gmail or a tab while the owner is still speaking; an email becomes a filled Gmail
  draft that is never sent) and predictions.

- 2026-09-18 (Manager): Request S recorded; ADR-001 accepted. torch 2.11.0+cu128 installed and tested on the GPU (SDPA works).
  Ollama 0.34.2 installed; `qwen3.5:9b` pulled (6.6 GB, Q4_K_M, vision+tools+thinking; warm 89 tok/s, 0.7 s for a short
  answer). `.env.local` `OLLAMA_MODEL` changed from the absent `qwen3.6:35b` to `qwen3.5:9b`. Team spawned: Coder and
  Trainer in parallel, Reviewer after the first deliveries.
