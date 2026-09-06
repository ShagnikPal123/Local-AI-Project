# Nyx Pulse — API Keys

**For:** Shagnik
**Rule:** keys go in `.env.local` (git-ignored). Never in code, never committed.

Nothing here is required to run Nyx Pulse. Every key is optional and every online path has a
local fallback. This file exists so you know what each key unlocks and what you lose without it.

---

## Currently configured

| Key | Status |
|---|---|
| `OPENAI_API_KEY` | ✅ set |
| `GEMINI_API_KEY` | ✅ set |
| `OLLAMA_HOST` / `OLLAMA_MODEL` | ✅ set — local, no key needed |
| `PREFERRED_ONLINE_PROVIDER` | ✅ set |

You have enough configured to run today, including one free online provider (Gemini) and
local inference (Ollama).

---

## Free — worth adding

These have free tiers. Adding them improves the multi-provider collaboration mode (roadmap M1–M3)
at no cost.

| Key | Unlocks | Without it |
|---|---|---|
| `GROQ_API_KEY` | Very fast Llama inference; good for the quick-response path | Falls back to Gemini or local |
| `DEEPSEEK_API_KEY` | Strong, cheap coding model; good second opinion in collab mode | One fewer collaborator |

Note `.env.example` already documents `FREE_ONLY=true`, which prevents auto-selecting paid
models entirely. That setting plus Ollama is the zero-cost configuration — relevant to your
goal of publishing this for free use.

---

## Paid — only if you want them

| Key | Unlocks | Without it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude as a provider | Other providers cover it |
| `PERPLEXITY_API_KEY` | Search-native answering | Falls back to the web search connector |
| `KIMI_API_KEY` | Long-context provider | Prompt compression (E5) covers most of this |

---

## Search — relevant to the stale-answer bug (D1)

| Key | Unlocks | Without it |
|---|---|---|
| `BING_API_KEY` | Referenced in the search connector | Falls back to scraping-based search, which is less reliable |
| `GOOGLE_API_KEY` | Google connector (roadmap L3) | Google control unavailable |

**Worth knowing:** the stale-president bug (D1) is most likely a routing/recency problem
rather than a missing-key problem — the model answered from parametric memory instead of
searching at all. I'll confirm that before asking you to buy anything. Do not add a paid
search key on my account until I've diagnosed it.

---

## Not yet wired — will need keys when their roadmap items are built

| Service | Roadmap item | Notes |
|---|---|---|
| Amazon Product Advertising API | L6 | Requires an Associates account |
| Vercel token | N2, N3 | Free tier is fine |
| YouTube Data API | L1 | Free quota, generous |
| Stock/market data | O2, L10 | Several free tiers exist — I'll pick one and tell you |
| OmniRoute | L11 | Need to know which service you mean |
| 3D printer / parts search | J3, J4 | Depends on which stores |

---

## How to add one

Open `.env.local` and add the line. No restart of anything but the app is needed.

```bash
notepad "C:\Users\shagn\Desktop\Ai Dev Folder\Ai Dev Folder\.env.local"
```

Tell me when you've added one and I'll wire up and test the provider.
