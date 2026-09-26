# Update ideas — future updates, recorded 2026-09-26

**The owner's list of what to build next.** They asked for "a future updates file for you to read" and kept adding to
it ("Add all of these to the updateIdeas file", "Add to updates file like the last ones"). Their words are kept exactly
as sent below; the table after them breaks each idea out, with the code it would build on.

**Status: ideas, not started.** Like Project Null, nothing here is built until the owner picks an item and says go.
When one is picked: record it in `01_GOALS.md` and `START_HERE.md`, then mark it here with the session and date.

## The owner's words (verbatim, in the order sent)

```text
After add a future updateees file for you to read, in here add fix the research tab, add create tab for images wherre the suer can draw and the ASI helps and can scan to make the image bnetter with a bar for what teh suer wants the AI to draw. Lasst thing toa dd to tyhis file ios to fix the collab space and repo link, so it will actually work. Then another things is ssuepr free create since the AI still hgas tab creation limits and creativity limits
```

```text
Also in the file add  swarm idea. In this it can make lots of agents, with a slider if the user has a limit. They can have lots of access which can run 24/7, do so many things like opening internet and watching stocks for an integration idea. Add a cloud environment which is a button next to users which basically allows you to host with a secret access code and a name so a person can input it and connect. Usable for phones and stuff later on. for swarm it can also be used and connected to basically anything else. Add connectors idea where it allows for all the basic ones claude and gpt have but the suer can input a site or connector, it either finds it or creates the connection and takes mcp or api or whatever or even website url. Also the 3d modelling should be a bit better. (for example if I wanted to make a case and environment to host this AI and use as cloud (also add a cloud mode so it ahs different UI and new capabilities swath network and how many people can be on it)) An example use for swarm is to upload things to projects, fix small code errors, and more. This can be a mode similar to normal, cowork, and plan, also add swarm and auto to this mix.  Also game dev and web dev need  to be better. If i want to try the  site or the game i want to open it either on a download where I can actually do things without posting or on a website page or on the AI environment itself. Add all for these to the updateIdeaas file.
```

```text
Add to this file to remove Agent city since it was basiclaly what office woudl look like, then  for office space make sure that it can run mutliple offices at once if needed on high enmd machines. Then some tabs on memory field annd even the button for big kahuna is obstructive and to fix. Add to updates file like the last ones
```

## The ideas

| # | Idea | What it means in practice | Builds on | Watch out for |
|---|---|---|---|---|
| U1 | **Fix the Research tab** | Finish Request L's UI: a research box (standard / deep), the live job, the cited report, sources with citation styles, paper search, exports | Backend done: `research_engine.py`, `routes_research.py`, tools `research` / `search_papers` / `cite`. UI half-landed: `panels/research/ResearchPanel.tsx` with placeholder `JobView.tsx` / `PapersView.tsx`, no `research.css`, not registered in `tabs.ts` / `App.tsx` (PROJECT_NULL.md, "Next" item 9) | A dynamic tab called "research" that the owner made in chat already sits in the tab bar — decide whether the real tab replaces it |
| U2 | **Create tab for images** | The owner draws; the AI helps draw; "scan" reads the drawing and makes it better; a prompt bar says what the AI should draw | `components/diagram/DiagramOverlay.tsx` (pens, eraser, undo, Save PNG), `image_gen.py`, the `image_check` vision role (`model_roles.py`), `design_studio.py` | Needs a model that edits an image from a sketch (img2img / inpainting). Local first (owner prefers local and small); say plainly when a picture leaves the PC |
| U3 | **Make the Collab space and repo link actually work** | Testers see and send changes; the site's Collab page loads; the GitHub link opens | `site/collab/`, `site/api/collab/*`, `beta_collab.py`, `docs/COLLAB_SETUP.md`. The repo went **public on 2026-09-26**, so the GitHub link now works | The functions need a GitHub token and tester keys in Vercel first; then delete the `beta/`, `collab/`, `api/`, `package.json` lines from `site/.vercelignore` and redeploy |
| U4 | **Super free create** | Remove the limits on what tabs Nyx can make and how creative they can be | `dynamic_tabs.py`, `tab_editor.py`, `spec_ai.py`, `design_sense.py`, `landscape_tools.py`, `panels/DynamicTab.tsx`, `identity0/tabs.py` | Invariant 2 (AGENTS.md): tabs are validated specs, never generated code that runs. "Free" means a much richer spec vocabulary (layouts, blocks, styling, interactions, higher caps), not executing model-written code |
| U5 | **Swarm** | Many agents at once, with a slider for the user's limit; broad access; runs 24/7; opens the internet, watches stocks; connects to anything else. Examples: upload things to projects, fix small code errors | `agent_dispatch.py` (parallel copies, today ≤12), `office/` (hierarchy, many agents), `resource_governor.py` + `device_profile.py` (what the PC can take), `trading/autopilot.py` (24/7 run modes), connectors | Every agent still goes through `permissions.py` and the tool guards; irreversible actions (posting, sending, paying, deleting) keep their approvals. The slider's ceiling comes from the hardware, not a guess |
| U6 | **Swarm and Auto chat modes** | Next to Normal · Co-work · Plan. Auto picks the mode for each message; Swarm hands the message to a swarm | `chat_modes.py`, `components/chat/ModeSlider.tsx`, `turn_runner.py` | The slider's description area must keep a fixed height (see the 2026-09-26 jitter fix in `ModeSlider.tsx`) |
| U7 | **Cloud environment button** (next to Accounts) | Host this Nyx under a name and a secret access code; someone enters both to connect — phones later | `access_keys.py` (NYX1- keys), `routes_access.py`, `server_auth.py` invites, `deploy_mode.py` (hosted builds) | Anything reachable from the internet must not have machine control or self-editing (`deploy_mode.HOSTED_BLOCKED_PREFIXES`). Needs a way in from outside (tunnel), rate limits, and revocable codes |
| U8 | **Cloud mode** | A different UI and capabilities while hosting; shows the network and how many people are on it (and a maximum) | `deploy_mode.py`, `turn_registry.py`, `metrics.py`, `auth.py` sessions | Same rule as U7 |
| U9 | **Connectors: everything, and any site** | All the common connectors Claude and ChatGPT have; plus the user types a site or connector and Nyx finds an existing MCP server / API, or builds the connection (MCP, API or plain website URL) | `connector_builder.py`, `connector_use.py`, `connectors/registry.py`, the connectors grid (Project Null N70–N79) | Credentials go through `secret_store.py`, never into a prompt or a log (invariant 5) |
| U10 | **Better 3D modelling** | E.g. design a case and environment to host this AI as a cloud box | `build_ai.py`, `design_studio.py`, the Build studio (`BuildStudio` / `Viewport`) | — |
| U11 | **Better game dev** | Try a game three ways: a download that really runs, a web page, or inside Nyx | `game_studio.py`, `routes_game.py`, `panels/game/GameStudioPanel.tsx` | A download or page must be something the owner chooses to share; nothing is posted by itself |
| U12 | **Better web dev** | Try a site three ways: run it locally, download it, or open it as a web page; also inside Nyx | `code_workspace.py` (the "website" starter), `panels/code/CodePanel.tsx`; a local preview server for a folder; publishing (e.g. Vercel) only on the owner's click | `machine_tools.run_command` stops a command when its timeout passes (30 s by default, 15 min at most), so a dev server needs its own runner that keeps it alive in the background and stops it on request |
| U13 | **Remove Agent City** | Office Space already shows the team as a place, so the Memory field's "Agent city" view goes | `components/brain/AgentCity.tsx`, the Memory field / Agent city / Core switch in `panels/NyxPanel.tsx` | Move anything only Agent City shows (clicking a building opens that agent) into Office Space first |
| U14 | **Several offices at once** | On high-end machines, run more than one office at the same time | `office/` (engine, focus mode, library), `resource_governor.py` | Focus mode assumes one office pauses everything else; decide how two offices share the machine |
| U15 | **Memory field clutter** | Some tabs/cards on the memory field, and the Big Kahuna button, get in the way | `panels/NyxPanel.tsx` + `nyx.css` (the HUD cards, legend, title, tags), `components/kahuna/Companion.tsx` (the floating Big Kahuna button) | Check at the owner's window sizes, with the chat sheet open and closed |

## Already done from the same conversation (2026-09-26)

- The Normal · Co-work · Plan switch no longer jumps up and down under the mouse (`ModeSlider.tsx`).
- **Accounts** next to Log Out: separate local spaces with their own files, an optional password, a name and a purpose
  Nyx is told about (`local_accounts.py`, `routes_accounts.py`, `components/accounts/`). See `START_HERE.md`.
