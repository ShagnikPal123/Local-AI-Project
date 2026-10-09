# Nyx Ichos

A personal AI that runs on your own Windows PC. It remembers what matters, talks with you, researches, and runs a
team of agents — and your chats, memory and files stay on your computer.

**Website:** <https://nyx-ichos.vercel.app> · **Download:** [NyxIchos-Windows.zip](https://nyx-ichos.vercel.app/downloads/NyxIchos-Windows.zip)
· Created by Shagnik

## Install

1. Download `NyxIchos-Windows.zip` from the website.
2. Right-click it and choose **Extract All**.
3. Double-click **Start Nyx** in the folder.

The first run takes a couple of minutes: it installs Python for you if you don't have it (winget, per user, no
admin), installs Nyx's packages (about 80 MB), puts a **Nyx Ichos** icon on your desktop, registers the `nyx://`
link and opens Nyx in your browser. After that Nyx starts with Windows and waits in the tray near the clock.

**No API key is required.** With [Ollama](https://ollama.com) it runs offline. Add a key for Gemini, Groq, NVIDIA,
OpenAI, Anthropic, Qwen and others in the **Keys & Models** tab when you want online models.

## What's new — Update 1 (October 2026)

- **Chats on the left, like Claude.** New chat, search, and every chat grouped by day, with Branch, Semi-branch,
  Duplicate and Rename. One switch at the top brings back the **Second Brain**: the memory field, voice and a chat.
- **Swarm and Auto modes.** Swarm splits a job across many agents at once (as many as your PC can carry; you set the
  limit). Auto picks Normal, Co-work, Plan or Swarm for each message and tells you why.
- **See what every agent was asked and what it answered**, in full, for each hand-off.
- **`/auto` and `@auto`:** Nyx picks the best skills, agents and connectors for a job, or makes the agent it needs.
- **Nyx's own computer.** A sandboxed desktop ([Cua](https://cua.ai), via Docker or Cua Cloud) that Nyx works on instead
  of your screen. It asks before it touches your screen, unless you say otherwise.
- **Connectors.** 88 apps, including Gmail, Google Docs and Sheets, Excel, Word, Outlook, Vercel, AI apps and finance
  apps. You can also add any website, API or MCP server.
- **Research tab** works end to end: cited reports, paper search, citation styles and exports.
- **Office Space:** an Output box with each finished result and its files, **Deliver now**, **Auto decisions**, and
  part-time, promoted and demoted agents.
- **Auto-assign models** in Keys & Models (preview, apply, undo), a voice bar that shows what you're saying, and a
  cleaner memory field.

## What's inside

Every part is a tab in the app, and they share one memory.

| Part | What it does |
|---|---|
| **Second Brain** | A living map of everything Nyx reads, says and learns — search it or fly through it |
| **Big Kahuna** | The main brain: routes each request to the model that does it best, and trains a small model of its own |
| **Agents & Office Space** | Named agents with their own jobs; an office of them for big tasks |
| **Voice** | Hands-free talk that listens while it speaks and never hears itself |
| **Nyx's Computer** | A sandboxed desktop of its own, so it doesn't have to use your screen |
| **Screen Share** | Looks at a window and points to what to click; acts only when you approve |
| **Research & Notes** | Cited research reports; slides turned into notes and quizzes |
| **Code & Build** | Edit a folder together; design 3D-printable parts and circuits |
| **Trading practice** | Paper trading with simulated money, fees and market hours |
| **WhatsApp** | Text Nyx from your phone and get texts back; the line is tied to the PC you paired it on ([how](docs/WHATSAPP.md)) |
| **World** | An office upscaled into a planet of agents with its own government, laws and growth ([design](docs/WORLD.md)) |
| **Mods** | Lasting changes to Nyx's setup — standing instructions, commands, themes, reminders — that you can pause or undo |

## Privacy

Nyx runs on your hardware on purpose. Conversations, memory, notes and files are stored locally. Machine control and
self-editing exist only in the local build — a hosted build leaves them out entirely (`deploy_mode.py`).

## Developers

Python 3.11+ (FastAPI) backend and a React + TypeScript frontend in `frontend/nyx-pulse/`, served by the engine
itself. Run everything from the project folder with the project's own interpreter:

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
cd frontend/nyx-pulse && npm install && npm run build && cd ../..
.venv/Scripts/python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000   # then open http://localhost:8000
.venv/Scripts/python.exe -m pytest -q -p no:warnings                        # the test suite
.venv/Scripts/python.exe build_release.py                                    # dist/NyxIchos-Windows.zip (secret-scanned)
```

Or clone and double-click `Start Nyx.bat` — the same one-time setup runs against your checkout.

Read [`AGENTS.md`](AGENTS.md) before changing code: commands, the traps in this repo, and the five invariants
(deny-by-default routes, specs are data not code, overlays never mutate base modules, nothing publishes without
human review, no credential in source). The website is plain HTML in [`site/`](site/) and deploys to Vercel.

## License

A personal project. No license has been chosen yet, so all rights are reserved by the author.
