# Features taken from the Jarvis projects

On 2026-10-09 the owner asked to "use these githubs, strip off features and add to ours, similar pages and such":
OpenJarvis (open-jarvis/OpenJarvis), ethanplusai/jarvis, and the `jarvis-assistant` topic on GitHub. Each feature
below was rebuilt in Nyx's own code on Nyx's own parts. No code was copied.

| Source | Licence | Taken as |
|---|---|---|
| [OpenJarvis](https://github.com/open-jarvis/OpenJarvis) | Apache-2.0 | ideas, credited here |
| [ethanplusai/jarvis](https://github.com/ethanplusai/jarvis) | personal, non-commercial use only | ideas only. Its code cannot be used in a public repo |
| `jarvis-assistant` topic (N.E.K.O, M.I.L.E.S, J.A.R.V.I.S 2.0, …) | various | not used yet; ideas listed below |

## Built

| Feature | From | In Nyx |
|---|---|---|
| **Jarvis tab**: a particle orb that listens, thinks and speaks, plus an Ask box that answers out loud | ethanplusai's voice orb page | `panels/jarvis/JarvisPanel.tsx` (three.js, Nyx's voice bus and TTS) |
| **Needs you**: everything waiting on the owner | ethanplusai's "Needs attention" / "Needs you" panels | `routes_jarvis.needs_you`: Nyx approval cards, trade approvals, Claude Code sessions |
| **Claude Code sessions** on this PC by state | ethanplusai's Sessions tab | `claude_sessions.py` reads transcript heads and tails, read-only |
| **Morning Digest**: a daily spoken briefing | OpenJarvis `morning_digest` | `morning_digest.py`: calendar, mail, Open-Meteo weather, news, prices, offices; optional WhatsApp copy |
| **Skills from GitHub** (SKILL.md) | OpenJarvis skills / agentskills.io | `skill_import.py` + Add capability → Skills from GitHub. Only text is imported |
| **Taint gate**: risky actions ask after outside content | ethanplusai's untrusted-content gate | `taint_gate.py`, checked in `tools.call_tool`; Settings → Safety |

Already in Nyx before this, so not rebuilt: deep research (Research tab), code assistant (Code tab, Office), scheduled
monitors (AI-task blocks, the predictor), `doctor` (`/doctor`, `/api/doctor`), persistent memory, Markdown memory
files (Second Brain), run history (turn registry, Office jobs).

## Not taken (yet), and why

- **Driving Claude Code to build a project** (ethanplusai: brainstorm → spec → `claude -p` build). This overlaps
  UPDATE_IDEAS U61 (DeepSeek harness) and needs the owner's say on letting Nyx start coding sessions with full
  permissions.
- **Answering a Claude Code permission prompt by pressing keys** (ethanplusai). This acts on another program's
  approval. That is an owner decision.
- **Energy and cost benchmarks** (OpenJarvis `bench`). A good fit for Big Kahuna's scoreboard. Later.
- **Ideas from the topic list**: N.E.K.O's proactive outreach (Nyx's curiosity and predictor are close), M.I.L.E.S's
  Spotify and volume control, J.A.R.V.I.S 2.0's Android control over ADB, face sign-in.
