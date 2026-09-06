# Local-First AI Assistant

**Created by Shagnik**

A modular, coding-focused AI assistant that runs on your own hardware with intelligent fallback to online providers. Built in Python with Claude, GPT-4, Perplexity, and local Ollama models.

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Set Up API Keys
```bash
cp .env.example .env.local
# Edit .env.local with your API keys
```

**Required keys** (at least one):
- `ANTHROPIC_API_KEY` — Claude (recommended primary)
- `OPENAI_API_KEY` — GPT-4o (OpenAI)
- `PERPLEXITY_API_KEY` — Perplexity Sonar (online search)
- `OLLAMA_HOST` — Local Ollama (default: `http://localhost:11434`)
- `OLLAMA_MODEL` — Model to use (default: `llama3.1`)

### 3. Run the CLI
```bash
python cli.py
```

You'll see system status and be prompted to chat. Type `/help` for commands.

## Architecture

### The Five-Layer Model

```
Tier 1: Text Brain (DONE)
  ├─ Conversation loop in pure text
  ├─ Provider routing
  └─ Message history

Tier 2: Function Calling
  ├─ Models can invoke tools
  └─ Typed tool registry

Tier 3: Speech I/O
  ├─ Push-to-talk microphone input
  ├─ Whisper STT
  └─ TTS output

Tier 4: Fine-Tuning
  ├─ LoRA on local Ollama
  └─ Personalized model

Tier 5: Proactive Agent
  ├─ Background heartbeat
  └─ Reminders & notifications

Tier 6: Memory & Learning
  ├─ Vector embeddings
  ├─ Conversation search
  └─ Long-term context

Tier 7: Multi-Platform
  ├─ Web frontend
  ├─ Mobile app
  └─ Shared backend API
```

**Status: Tier 1 complete, all tests passing. Tier 2–3 ready for implementation.**

## How Routing Works

The `Router` class in `router.py` chooses a provider based on:

1. **Device Capability** — detected at startup
   ```
   16GB+ RAM + 12GB+ VRAM → Large tier   → prefer local Ollama
   8GB RAM + 6GB VRAM     → Medium tier  → prefer local Ollama
   4GB RAM + 1GB VRAM     → Small tier   → prefer local Ollama
   < 4GB RAM              → Tiny tier    → prefer online (Claude/GPT)
   ```

2. **Connectivity** — checked every request
   ```
   Online + capable device  → Ollama (privacy, speed)
   Online + tiny device     → Claude/Perplexity (practical)
   Offline                  → Ollama (only option)
   ```

3. **Automatic Fallback** — if primary fails
   ```
   Ollama fails + online → try Perplexity
   Perplexity fails      → try Ollama
   Both fail             → raise error
   ```

## Project Structure

```
├── cli.py                           # Interactive CLI (text interface)
├── chat_service.py                  # Conversation orchestration
├── router.py                        # Provider routing logic
├── config.py                        # Settings from .env
├── connectivity.py                  # Network availability check
├── device_profile.py                # Hardware detection
├── tools.py                         # Tool registry (ready for Tier 2)
│
├── providers/
│   ├── base.py                      # Provider interface
│   ├── ollama_provider.py           # Local Ollama
│   ├── openai_provider.py           # OpenAI GPT-4
│   ├── anthropic_provider.py        # Claude
│   └── perplexity_provider.py       # Perplexity Sonar
│
├── tests/
│   ├── test_router.py               # Router logic (7 tests)
│   ├── test_chat_service.py         # Chat loop (13 tests)
│   ├── test_providers.py            # API providers (8 tests)
│   └── test_*.py                    # Other components
│
├── AGENT.md                         # Agent specification & design
├── requirements.txt                 # Python dependencies
├── .env.example                     # Template for secrets
├── .env.local                       # Your actual secrets (git-ignored)
└── README.md                        # This file
```

## Running Tests

```bash
# All core tests (27 passing)
python -m pytest tests/test_router.py tests/test_chat_service.py tests/test_providers.py -v

# Single test file
python -m pytest tests/test_router.py -v

# Run with verbose output
python -m pytest tests/ -vv --tb=short
```

## CLI Commands

### Interactive Commands
- **Type normally** — send a message to the AI
- **/help** — show available commands
- **/status** — show device profile, connectivity, and routing status
- **/history** — show conversation history so far
- **/clear** — clear conversation (start fresh)
- **/quit** — exit

### Example Session
```
$ python cli.py

================================================================
Nyx Pulse — High-Quality Local-First AI Assistant
================================================================

System & Hardware Status:
  Device Tier: large (Power: performance)
  Max Workers: 8
  Online: True
  Primary Provider: Ollama (local)

Commands:
  /help      - Show available commands
  /status    - Show system and routing status
  /metrics   - Show latency and reliability metrics
  /clear     - Clear conversation history
  /history   - Show conversation history
  /quit      - Exit the assistant

You: What's the capital of France?

Nyx Pulse (ollama):
  The capital of France is Paris.

You: /history

Conversation History:

You:
  What's the capital of France?

Nyx Pulse:
  The capital of France is Paris.

You: /quit

Goodbye!
```

## Provider Configuration

### Ollama (Local)
1. Install Ollama: https://ollama.ai
2. Download a model: `ollama pull llama3.1`
3. Start the server: `ollama serve`
4. Set in `.env.local`:
   ```
   OLLAMA_HOST=http://localhost:11434
   OLLAMA_MODEL=llama3.1
   ```

### Claude (Anthropic)
1. Get an API key: https://console.anthropic.com/
2. Add to `.env.local`:
   ```
   ANTHROPIC_API_KEY=sk-ant-v1-...
   ```

### OpenAI
1. Get an API key: https://platform.openai.com/
2. Add to `.env.local`:
   ```
   OPENAI_API_KEY=sk-proj-...
   ```

### Perplexity
1. Get an API key: https://www.perplexity.ai/
2. Add to `.env.local`:
   ```
   PERPLEXITY_API_KEY=pplx-...
   ```

## Key Design Principles

1. **Text-First Brain** — Speech is a layer on top, not the foundation
2. **One Unified Router** — All requests flow through the same decision logic
3. **Fail Gracefully** — Errors are caught and formatted, never raw exceptions
4. **No Hardcoded Secrets** — All API keys come from `.env`
5. **Modular Providers** — Swappable, independently testable
6. **Device-Aware from Day 1** — Hardware detection informs every decision
7. **Mockable for Tests** — No real API calls in test suite

## What's Next

- **Tier 2:** Function calling (models invoking tools)
- **Tier 3:** Speech input/output (push-to-talk)
- **Tier 4:** Model fine-tuning (LoRA on Ollama)
- **Tier 5:** Proactive agent (background tasks)
- **Tier 6:** Persistent memory (RAG)
- **Tier 7:** Web & mobile frontends

## Troubleshooting

### "No providers available"
- Check your `.env.local` has at least one API key set
- Verify Ollama is running if you want local mode: `ollama serve`
- Run `/status` to see which providers are detected

### "Ollama is offline"
- Make sure Ollama is running: `ollama serve` in another terminal
- Check `OLLAMA_HOST` in `.env.local` matches your setup

### "API key invalid"
- Verify the key is correct in `.env.local`
- Make sure it's not expired or revoked
- Check there are no extra spaces or quotes

### Tests failing with permission errors
- This is usually a temp directory issue on Windows
- Try running: `python -m pytest tests/ --basetemp=./tmp`

## Contributing

This is a personal project, but the code is written for clarity and learning. Follow the existing style:
- Use type hints
- Write docstrings explaining *why*, not just *what*
- Keep modules small and focused
- Test everything independently
- No secrets in code

## License

This is a personal project. No license specified yet.

---

**Built with care for a local-first, coding-focused workflow.** Questions? See [AGENT.md](AGENT.md) for architecture & design decisions.
