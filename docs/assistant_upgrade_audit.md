# AI Assistant Upgrade Audit

This audit document evaluates the current architecture of the local-first AI assistant (Nyx Ichos), details existing implementations, identifies completed upgrades across specialist areas, and documents system capabilities.

---

## 1. Current Architecture

The assistant (Nyx Ichos) is built as a modular Python application integrating both local inference (via Ollama) and external cloud providers (Anthropic Claude, OpenAI, and Perplexity), alongside a unified adapter layer for connectors and dynamic tool registration.

```
                        ┌─────────────────────────┐
                        │   Frontend (nyx-pulse)  │
                        │  Vue/Vite/TS (Web/App)  │
                        └────────────┬─────────────┘
                                     │ HTTP/WebSocket
                        ┌────────────▼─────────────┐
                        │      Backend API          │
                        │     (FastAPI, CLI)        │
                        └────────────┬─────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         │                           │                           │
┌────────▼─────────┐        ┌────────▼──────────┐       ┌────────▼─────────┐
│ Orchestrator /   │        │   RAG / Memory    │       │ Device Profile / │
│ Router           │        │   (Privacy Filter)│       │ Model Tier System│
│ (local/escalate) │        │                   │       │ (Strain-aware)   │
└────────┬─────────┘        └───────────────────┘       └──────────────────┘
         │
         ├───────────────────────────────────────────────┐
         │                                               │
┌────────▼────────────────┐                    ┌─────────▼────────┐
│ Connectors & Tools      │                    │ Model Providers  │
│ • Local Files           │                    │ • Ollama (local) │
│ • Web Search            │                    │ • Claude (API)   │
│ • App Launcher          │                    │ • OpenAI (API)   │
│ • MCP Bridge            │                    │ • Perplexity     │
│ • Dynamic Modularity    │                    └──────────────────┘
│ • Graph & Media Engine  │
│ • Storage & Custom DB   │
└─────────────────────────┘
```

---

## 2. What Is Built and Upgraded

Nyx Ichos features a complete local-first foundation with comprehensive testing:

- **Config System (`config.py`)**: Safe dataclass-backed settings loader pulling from `.env` without exposing keys in code.
- **Privacy Filter & Secret Scrubbing (`memory.py`)**: Automatic scrubbing of API keys (e.g. `sk-`, `ghp_`), passwords, and auth tokens before saving to memory.
- **Device Profiling & Model Tiers (`device_profile.py`)**: Scans CPU, RAM, and GPU VRAM to select appropriate model tiers (`large`, `medium`, `small`, `tiny`).
- **Hardware Safety Monitor (`hardware_safety.py`)**: Thermal safety and strain guardrails to prevent host throttling/overheating.
- **Unified Connectors Adapter Layer (`connectors/`)**:
  - `base.py`: Abstract `BaseConnector` and `ConnectorManifest`.
  - `policies.py`: `ConfirmationGate` ensuring write/destructive actions require explicit user approval.
  - `registry.py`: `ConnectorRegistry` managing discovery, health checks, and dispatch.
  - `local_files.py`: Sandboxed local filesystem searching and reading.
  - `web_search.py`: Query decomposition and search with offline fallback.
  - `app_launcher.py`: System app opening with confirmation gate.
  - `mcp.py`: Model Context Protocol tool bridge.
  - `dynamic_tools.py`: Dynamic Modularity allowing file scanning via AST to register new abilities on the fly.
- **Serious Mode & Specialized Personalities (`personalities.py`)**:
  - `serious`: High analytical rigor, zero conversational filler, structured output.
  - `coding_mentor`, `research_assistant`, `systems_architect`, `debugger`, `homework_helper`.
- **Graph Creation & Analysis (`graph_engine.py`)**: Mermaid flowchart/sequence/state diagram generation and ASCII/NL graph extraction.
- **Media Analyzer (`media_analyzer.py`)**: Picture dimension/format/EXIF inspection, base64 encoding for vision LLMs, and video sampling strategy generator.
- **Educational Homework Helper (`homework_helper.py`)**: Subject classification, Socratic step-by-step problem breakdown, and hints.
- **Local Storage, Cookies & Custom DB (`storage.py`)**: Key-value store with TTL, session cookie manager, and embedded document database.
- **Self-Running Loop (`self_running.py`)**: Scheduled recurring/one-shot background tasks and supervisor.
- **Interactive CLI & Slash Commands (`cli.py`)**:
  - Full suite of slash commands: `/upgrade-assistant`, `/assistant-doctor`, `/assistant-benchmark`, `/assistant-connectors`, `/serious-mode`, `/graph-create`, `/homework-help`, `/rag`, `/memory`, etc.
- **FastAPI Server (`server.py`)**: Complete REST API exposing chat, folders, memory, speech, connectors, graphs, homework, and diagnostics.
- **Evaluation Test Suite (`tests/`)**: 190 tests covering all features with 100% offline pass rate.

---

## 3. Performance & Scaling Profile

- **Best-case hardware (High VRAM / GPU)**: Large coding models (`qwen2.5-coder:14b`), 8 concurrent agent workers, 32k context character budget.
- **Mid-tier hardware (Laptops / 8-16GB RAM)**: Balanced tier (`llama3.1:8b` or `llama3.2:3b`), 2-4 workers.
- **Constrained hardware (Phones / Lightweight PCs)**: Tiny tier (`llama3.2:1b`), eco power mode, 1 worker, strict context pruning under 4k chars.

---

## 2b. App & Web Readiness Upgrades

New capabilities added for App/Web deployment, always-on autonomy, and expert accuracy:

- **Math Engine (`math_engine.py`)**: Dependency-free safe evaluator + equation solver.
  - Unicode symbols: `√ × ÷ −` superscripts (`x²`), percent, postfix `!`, implicit multiplication (`2x`, `3(4+5)`, `2pi`).
  - 40+ functions (sqrt, trig, logs, factorial, gcd/lcm, hyperbolic) and constants (pi, e, tau, phi).
  - Solves linear/quadratic equations exactly with step-by-step notes; higher-degree and
    transcendental equations numerically (bisection + Newton). `solve_math` tool + `/math` + `/api/math`.
- **Permanent General Knowledge (`general_knowledge.md` + `knowledge.py`)**: Always-on curated
  reference brain (history, math, science, geography, technology, units) independent of personal
  memory. Searchable with stopword filtering and abbreviation aliases (`ww2`, `km`, `usa`).
  `search_knowledge` tool + `/knowledge` + `/api/knowledge`.
- **Background Thought Loop (`thought_loop.py`)**: The assistant can "stay in thought" — acknowledge
  immediately, then research/study in a daemon thread with live milestones and a pollable result.
  `BackgroundThinker`, `/think`, and `/api/think` + background mode on `/api/chat`.
- **Concurrent Multi-Chat Server**: Each `chat_id` gets its own `ChatService`, so the App can run
  2+ prompts across chats simultaneously without interference (`/api/chats`, `chat_id` on responses).
- **Auto Collaboration (default ON)**: For research/verification tasks, the assistant automatically
  asks one configured online AI (Gemini/OpenAI/Claude/Kimi/Perplexity) for a second opinion and
  synthesizes it into the final answer. Toggle via `/collab auto` or `set_auto_collaboration`.
- **Auto Large-Prompt Compression**: Messages over the threshold are written to a single file
  (`attachments/prompt_*.md`) and the model reads the file instead of flooding the context window.
- **Online Self-Improvement Scanner (`self_improvement.py`)**: `scan_online_improvements()` searches
  the web for new features and known issues and files approval-gated proposals (`/improve scan`).
  Proposals stay in "beta" until the owner explicitly promotes them — large changes always need permission.
- **Data Understanding (`summarize_data` tool)**: Reads CSV/TSV/JSON files and reports structure,
  column stats (min/max/mean/median), and unique values. `create_graph` tool added for model-side graphing.
- **Fixed errors**: repaired malformed double-quote docstrings in `chat_service.py` and `tools.py`
  that previously broke module imports on some runtimes.
- **Finance Advisor Tab (`connectors/finance_connector.py` + `finance.py` + `finance_knowledge.md`)**:
  - Live market data via keyless feeds (Yahoo chart API primary, Stooq CSV fallback):
    quotes with previous close, daily OHLCV history (1mo–5y), US market open/close status.
    Crypto pairs supported (BTC-USD). `stock_quote`, `stock_history`, `market_status` tools.
  - Permanent financial literacy memory (`finance_knowledge.md`): market basics, valuation
    ratios (P/E, P/B, ROE, debt/equity, dividend yield), technical indicators (RSI, MACD,
    moving averages), when-to-invest / when-to-sell reasoning, risk management, strategies,
    and behavioral finance — with an educational disclaimer built in.
  - `finance` attribute/mode ("Finance Advisor") so the full App can expose it as a separate
    tab: `attribute_id="finance"`, `/finance` CLI, and `/api/finance/quote`, `/history`,
    `/status`, `/knowledge`, `/advice` endpoints. Advice pulls the user's saved portfolio
    context from permanent memory when present.
- **Expanded AI Model Roster (`providers/` + `collaborators.py`)**:
  - New online providers: **Gemini** (`gemini_provider.py`, native REST), **Kimi/Moonshot**
    (`kimi_provider.py`), **DeepSeek** (`deepseek_provider.py`), **Groq** (`groq_provider.py`).
    The OpenAI-compatible trio (Kimi/DeepSeek/Groq) shares a retry/error base
    (`providers/compat.py`). Gemini and Kimi keys were already read in config but had no
    providers — now wired into the router's primary/fallback order and status.
  - **Local models**: Ollama remains the local engine; the provider now lists installed
    models (`list_models()`) and the active model can be switched at runtime.
  - **Collaborators**: auto collaboration now has more diversity — DeepSeek and Groq added,
    and the **local Ollama model is now a collaborator** too (keyless). Auto-collaboration
    prefers a different model than the one that produced the main answer.
  - New CLI: `/models` (list local + online), `/model <name>` (switch). New API:
    `/api/models` and `/api/models/switch` for the App.
  - Config: `DEEPSEEK_API_KEY`, `GROQ_API_KEY`, and per-provider model overrides
    (`GEMINI_MODEL`, `DEEPSEEK_MODEL`, `KIMI_MODEL`, `GROQ_MODEL`).
- **Voice Engine (`voice.py` + `connectors/voice_connector.py`)**:
  - **Talk back (TTS)**: Windows SAPI voices via PowerShell — `speak()` (async or wait),
    `stop_speaking()`, voice selection. Ships with Microsoft David/Zira; any installed
    Windows voice (including installable neural voices) can be selected.
  - **Listening (STT)**: offline dictation via the Windows SAPI recognizer (`listen()`),
    no cloud keys.
  - **Voice ID / voice scan**: captures a short sample with ffmpeg (dshow mic), computes a
    lightweight spectral voiceprint (autocorrelation pitch, spectral centroid, rolloff,
    band energy, zero-crossing, RMS, flatness) with numpy/scipy, and compares new samples
    to the enrolled one (cosine similarity). Soft verification — convenience-grade, not
    biometric-grade. Enrollment and verification are fully offline.
  - **App startup flow**: `/api/voice/status` tells the App whether a voice is enrolled;
    the App can prompt "voice scan" and POST `/api/voice/scan` (enroll/verify).
  - Tools: `speak`, `listen`, `list_voices`, `set_voice`, `voice_scan`. CLI: `/voice`.
    API: `/api/voice/status|voices|speak|listen|set|scan`. Profile persisted in
    `voice_profile.json` (gitignored).
