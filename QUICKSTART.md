# Quick Start Guide — Get Nyx Running

## Step 1: Double-click `Start Nyx.bat`

That is the whole install. The first time, it installs Python for you if you do
not have it, installs Nyx's packages, puts a **Nyx Ichos** icon on your desktop,
registers the `nyx://` start link, turns on start-with-Windows, and opens Nyx.
Every time after that, click the desktop icon — or do nothing, because Nyx
starts with Windows and waits in the tray near the clock.

Nothing to type or paste. (Developers: the same file works in a git checkout.)

## Step 2: Choose Your Provider (2 minutes)

You need **at least one** API key or a local Ollama setup.

### Option A: Claude (Recommended)
1. Get an API key: https://console.anthropic.com/
2. Add to `.env.local`:
   ```
   ANTHROPIC_API_KEY=sk-ant-v1-YOUR-KEY-HERE
   ```

### Option B: OpenAI (GPT-4o)
1. Get an API key: https://platform.openai.com/
2. Add to `.env.local`:
   ```
   OPENAI_API_KEY=sk-proj-YOUR-KEY-HERE
   ```

### Option C: Ollama (Local, Free)
1. Install: https://ollama.ai
2. Run in another terminal: `ollama serve`
3. Download a model: `ollama pull llama3.1`
4. `.env.local` is already configured for Ollama by default

### Option D: Perplexity (Online Search)
1. Get API key: https://www.perplexity.ai/
2. Add to `.env.local`:
   ```
   PERPLEXITY_API_KEY=pplx-YOUR-KEY-HERE
   ```

**Pro Tip:** Set up Claude first (Option A). It's the most capable and has a free trial.

## Step 3: Create Your Config File (1 minute)
```bash
cp .env.example .env.local
# Edit .env.local with your chosen provider's API key
# (Keep the file, don't commit it to git - it's in .gitignore)
```

## Step 4: Run It (1 minute)
```bash
python cli.py
```

You'll see:
```
============================================================
Nyx Pulse — AI Assistant
============================================================

System Status:
  Device Tier: large
  Online: True
  Primary Provider: ...

Commands:
  /help      - Show available commands
  /status    - Show system and routing status
  /metrics   - Show latency and reliability metrics
  /clear     - Clear conversation history
  /history   - Show conversation history
  /quit      - Exit the assistant

You: 
```

**Type something and press Enter!**

---

## Example Conversation

```
You: What's 2+2?

Nyx Pulse (claude):
  2 + 2 = 4

You: /status

Router Status:
  Device Tier: large
  Online: True
  Ollama Available: False
  Claude Available: True
  Preferred Provider: claude

Device Profile:
  os: Windows
  cpu: Intel Core i7
  cpu_cores: 8
  ram_gb: 16.0
  gpu: NVIDIA GeForce RTX 4070
  vram_gb: 12.0

Conversation:
  Messages: 2

You: Write a Python function to calculate factorial

Nyx Pulse (claude):
  Here's a simple factorial function:
  
  def factorial(n):
      if n <= 1:
          return 1
      return n * factorial(n - 1)
  
  Or an iterative version:
  
  def factorial(n):
      result = 1
      for i in range(2, n + 1):
          result *= i
      return result

You: /quit

Goodbye!
```

---

## Troubleshooting

### "No providers available"
- Check `.env.local` has an API key set
- If using Ollama, make sure it's running: `ollama serve`

### "Claude unavailable"
- Verify your `ANTHROPIC_API_KEY` in `.env.local` is correct
- Make sure it's not expired: https://console.anthropic.com/

### "Ollama offline"
- Start it: `ollama serve` in another terminal
- Check it's reachable: curl `http://localhost:11434/api/tags`

### My key doesn't work
- Check for extra spaces or quotes in `.env.local`
- Make sure the key is active on the provider's website
- Try a fresh key from the provider's console

---

## What Just Happened?

You just set up **Tier 1 & Multi-Agent Core** of the Nyx Pulse assistant:
- ✅ Text conversation loop
- ✅ Intelligent provider routing
- ✅ Device detection
- ✅ Conversation memory (current session)
- ✅ Fallback if provider fails

**Tier 2** (coming next): Function calling — the model can invoke tools.  
**Tier 3**: Speech input/output (push-to-talk).  

---

## Running Tests

Want to verify everything works under the hood?

```bash
python -m pytest tests/test_router.py tests/test_chat_service.py tests/test_providers.py -v
```

You should see **27 tests passing** ✅.

---

## Next Steps

1. **Explore the CLI**
   - Run `python cli.py`
   - Try `/help`, `/status`, `/history`
   - Have a conversation

2. **Read the Architecture** (optional)
   - [AGENT.md](AGENT.md) — Design decisions & tiers
   - [README.md](README.md) — Full documentation

3. **Ready for Tier 2?**
   - Next: Function calling (models invoke tools)
   - After: Speech I/O, fine-tuning, memory, proactive agent

---

## Support

- Stuck? Check the [README.md](README.md) troubleshooting section
- Want to understand how it works? Read [AGENT.md](AGENT.md)
- Found an issue? Review the test suite in `tests/`

**Happy coding! 🚀**
