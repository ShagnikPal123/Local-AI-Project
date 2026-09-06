# Nyx Pulse AI Assistant — Project Specification

**Last Updated:** 2026-08-17
**Status:** Multi-Agent & Strain-Aware Core Complete

## Agent Identity

**Name:** Nyx Pulse
**Purpose:** A coding-focused, local-first multi-agent AI assistant for personal use, with intelligent provider routing, dynamic hardware strain regulation, multi-route double-checking, and growing memory.
**Target User:** Individual developer (laptop-first, capable of scaling to always-on)

## Core Capabilities (First Three)

1. **Real-time Coding Assistant** — In-terminal chat, code review, debugging help
2. **Conversation Memory** — Recalls earlier messages in the same session, maintains context
3. **Intelligent Provider Escalation** — Uses local Ollama when available, routes to Claude/OpenAI/Perplexity when needed

## Stack

- **Language:** Python 3.14+
- **Runtime:** Windows (laptop primary), will support Linux/Mac later
- **Main Model Provider:** Anthropic Claude (via API), with Ollama (local) as fallback
- **Secondary Providers:** OpenAI, Perplexity (online), all swappable
- **Config:** `.env` / `.env.local` for secrets (git-ignored)

## Interaction Model

- **Tier 1 (Now):** Text-only CLI, push-to-talk foundation ready
- **Tier 3:** Push-to-talk speech input via microphone
- **Future:** Wake-word detection, always-on background agent

## Safety Boundaries

The assistant will **always ask before**:
- Sending messages or emails
- Making API calls that cost money
- Deleting or modifying files
- Changing system settings

## Proactivity

Starting quiet (Tier 5+): The assistant can raise reminders and surface insights, but only after earning permission through careful, non-intrusive behavior.

---

## Current Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    CLI (cli.py)                          │
│            Interactive text conversation loop             │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                  ChatService (chat_service.py)           │
│    Orchestrates conversations, manages history           │
└────────────────────┬────────────────────────────────────┘
                     │
          ┌──────────┼──────────┐
          │          │          │
    ┌─────▼─┐  ┌────▼────┐  ┌─▼────────┐
    │ Router │  │ Tools   │  │ Memory   │
    │        │  │ Registry│  │ (future) │
    └─────┬──┘  └────┬────┘  └─────────┘
          │          │
    ┌─────▼──────────▼─────────────────┐
    │       Provider Abstraction        │
    └─────┬──┬──────┬──────┬───────────┘
          │  │      │      │
    ┌─────▼┐│      │      │
    │local ││    ┌─▼─┐  ┌▼──┐  ┌────┐
    │Ollama││    │GPT│  │Per│  │Cla │
    │      ││    │   │  │sex│  │ude │
    └──────┘│    └───┘  └───┘  └────┘
           ││
          (offline-first, but all online providers available)
```

## Files & Responsibilities

### Core System
- **`router.py`** — Intelligent provider selection based on device + connectivity
- **`chat_service.py`** — Conversation loop, message history, system prompts
- **`cli.py`** — Interactive terminal interface (Tier 1)

### Providers
- **`providers/base.py`** — `Provider` interface (all providers implement this)
- **`providers/ollama_provider.py`** — Local Ollama chat
- **`providers/openai_provider.py`** — OpenAI API (GPT-4o)
- **`providers/anthropic_provider.py`** — Anthropic Claude API
- **`providers/perplexity_provider.py`** — Perplexity online search

### Infrastructure
- **`config.py`** — Unified settings from `.env` / `.env.local`
- **`connectivity.py`** — Network availability check
- **`device_profile.py`** — Hardware detection, model-tier selection
- **`tools.py`** — Tool registry, built-in tools (time, web search, etc.)
- **`folder_reader.py`** — Generic folder reader: register any local folder by name, then list/read/search its files regardless of format (text read directly; media/binary reported with metadata until multimodal support lands)

### Tests
- **`tests/test_router.py`** (7 tests) — Provider routing logic
- **`tests/test_chat_service.py`** (13 tests) — Chat loop, tools, registry
- **`tests/test_providers.py`** (8 tests) — OpenAI, Anthropic availability & chat

## Running Tier 1: Text Conversation Loop

```bash
# Install dependencies (already done)
pip install -r requirements.txt

# Set up your API keys
cp .env.example .env.local
# Edit .env.local with your OPENAI_API_KEY, etc.

# Run the interactive CLI
python cli.py
```

**Commands in CLI:**
- `/help` — Show available commands
- `/status` — Show device, routing, and provider status
- `/history` — Show conversation so far
- `/clear` — Clear conversation history
- `/quit` — Exit

## Routing Logic (How Nyx Pulse Decides)

1. **Device Capability Check:** Scans CPU, RAM, GPU on startup
   - Tiny (< 4GB RAM or < 1GB VRAM) → prefers online providers
   - Small/Medium/Large → prefers local Ollama for privacy & speed

2. **Network Check:** Every request asks "are we online?"
   - Online + capable device → use local Ollama (private)
   - Online + tiny device → use Claude / Perplexity (practical)
   - Offline → must use Ollama (no choice)

3. **Fallback on Failure:**
   - Ollama fails → try Perplexity (online)
   - Perplexity fails → try Ollama (last resort)
   - Both fail → raise error with both failure messages

## Test Coverage

**27 tests, all passing:**
- Router: Provider selection logic, device tiers, fallback scenarios
- Chat Service: Conversation history, system prompts, message flow
- Providers: API key validation, response parsing, error handling
- Tools: Registry, execution, built-in tools

Run all tests:
```bash
python -m pytest tests/test_router.py tests/test_chat_service.py tests/test_providers.py -v
```

## Next Steps (Tier 2+)

- **Tier 2:** Add function-calling support (tool invocation by models)
- **Tier 3:** Push-to-talk speech input (mic → OpenAI Whisper → chat → text-to-speech)
- **Tier 4:** Fine-tuning pipeline (LoRA on Ollama for personalization)
- **Tier 5:** Background heartbeat (proactive checks and reminders)
- **Tier 6:** Conversation memory store (RAG, vector search for context)
- **Tier 7:** Web & mobile app frontends (share backend logic)

## Assumptions & Design Decisions

1. **Text first, voice later:** The brain works in plaintext. Speech is an adapter.
2. **One routing layer:** All requests flow through `router.py`. Provider swaps are invisible to the caller.
3. **No hardcoded secrets:** All API keys come from `.env`, never embedded.
4. **Fail gracefully:** Providers raise `ProviderError`, not raw exceptions.
5. **Mockable for tests:** No provider makes a real network call in tests.
6. **Device-aware from the start:** Hardware detection runs at startup, informs every routing decision.

## Known Limitations (v1.0)

- No tool invocation yet (models can't call functions)
- No vector memory / long-term learning
- No speech input/output
- No multi-user support
- Conversation history lost on restart (Tier 6 will fix)

---

**This is a working foundation.** Each tier builds on the one before. Tests pass, routing works, CLI is usable. The brain is ready for speech and memory layers on top.
