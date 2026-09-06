# Local-AI-Project

An Local Ai that can search online and access other AI models for versatility and privacy.

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
- `ANTHROPIC_API_KEY` â€” Claude (recommended primary)
- `OPENAI_API_KEY` â€” GPT-4o (OpenAI)
- `PERPLEXITY_API_KEY` â€” Perplexity Sonar (online search)
- `OLLAMA_HOST` â€” Local Ollama (default: `http://localhost:11434`)
- `OLLAMA_MODEL` â€” Model to use (default: `llama3.1`)

### 3. Run the CLI
```bash
python cli.py
```

You'll see system status and be prompted to chat. Type `/help` for commands.

## Architecture

### The Five-Layer Model

```
Tier 1: Text Brain (DONE)
  â”œâ”€ Conversation loop in pure text
  â”œâ”€ Provider routing
  â””â”€ Message history

Tier 2: Function Calling
  â”œâ”€ Models can invoke tools
  â””â”€ Typed tool registry

Tier 3: Speech I/O
  â”œâ”€ Push-to-talk microphone input
  â”œâ”€ Whisper STT
  â””â”€ TTS output

Tier 4: Fine-Tuning
  â”œâ”€ LoRA on local Ollama
  â””â”€ Personalized model

Tier 5: Proactive Agent
  â”œâ”€ Background heartbeat
  â””â”€ Reminders & notifications

Tier 6: Memory & Learning
  â”œâ”€ Vector embeddings
  â”œâ”€ Conversation search
  â””â”€ Long-term context

Tier 7: Multi-Platform
  â”œâ”€ Web frontend
  â”œâ”€ Mobile app
  â””â”€ Shared backend API
```

**Status: Tier 1 complete, all tests passing. Tier 2â€“3 ready for implementation.**

## How Routing Works

The `Router` class in `router.py` chooses a provider based on:

1. **Device Capability** â€” detected at startup
   ```
   16GB+ RAM + 12GB+ VRAM â†’ Large tier   â†’ prefer local Ollama
   8GB RAM + 6GB VRAM     â†’ Medium tier  â†’ prefer local Ollama
   4GB RAM + 1GB VRAM     â†’ Small tier   â†’ prefer local Ollama
   < 4GB RAM              â†’ Tiny tier    â†’ prefer online (Claude/GPT)
   ```

2. **Connectivity** â€” checked every request
   ```
   Online + capable device  â†’ Ollama (privacy, speed)
   Online + tiny device     â†’ Claude/Perplexity (practical)
   Offline                  â†’ Ollama (only option)
   ```

3. **Automatic Fallback** â€” if primary fails
   ```
   Ollama fails + online â†’ try Perplexity
   Perplexity fails      â†’ try Ollama
   Both fail             â†’ raise error
   ```

## Project Structure

```
â”œâ”€â”€ cli.py                           # Interactive CLI (text interface)
â”œâ”€â”€ chat_service.py                  # Conversation orchestration
â”œâ”€â”€ router.py                        # Provider routing logic
â”œâ”€â”€ config.py                        # Settings from .env
â”œâ”€â”€ connectivity.py                  # Network availability check
â”œâ”€â”€ device_profile.py                # Hardware detection
â”œâ”€â”€ tools.py                         # Tool registry (ready for Tier 2)
â”‚
â”œâ”€â”€ providers/
â”‚   â”œâ”€â”€ base.py                      # Provider interface
â”‚   â”œâ”€â”€ ollama_provider.py           # Local Ollama
â”‚   â”œâ”€â”€ openai_provider.py           # OpenAI GPT-4
â”‚   â”œâ”€â”€ anthropic_provider.py        # Claude
â”‚   â””â”€â”€ perplexity_provider.py       # Perplexity Sonar
â”‚
â”œâ”€â”€ tests/
â”‚   â”œâ”€â”€ test_router.py               # Router logic (7 tests)
â”‚   â”œâ”€â”€ test_chat_service.py         # Chat loop (13 tests)
â”‚   â”œâ”€â”€ test_providers.py            # API providers (8 tests)
â”‚   â””â”€â”€ test_*.py                    # Other components
â”‚
â”œâ”€â”€ AGENT.md                         # Agent specification & design
â”œâ”€â”€ requirements.txt                 # Python dependencies
â”œâ”€â”€ .env.example                     # Template for secrets
â”œâ”€â”€ .env.local                       # Your actual secrets (git-ignored)
â””â”€â”€ README.md                        # This file
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
- **Type normally** â€” send a message to the AI
- **/help** â€” show available commands
- **/status** â€” show device profile, connectivity, and routing status
- **/history** â€” show conversation history so far
- **/clear** â€” clear conversation (start fresh)
- **/quit** â€” exit

### Example Session
```
$ python cli.py

================================================================
Nyx Pulse â€” High-Quality Local-First AI Assistant
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

1. **Text-First Brain** â€” Speech is a layer on top, not the foundation
2. **One Unified Router** â€” All requests flow through the same decision logic
3. **Fail Gracefully** â€” Errors are caught and formatted, never raw exceptions
4. **No Hardcoded Secrets** â€” All API keys come from `.env`
5. **Modular Providers** â€” Swappable, independently testable
6. **Device-Aware from Day 1** â€” Hardware detection informs every decision
7. **Mockable for Tests** â€” No real API calls in test suite

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