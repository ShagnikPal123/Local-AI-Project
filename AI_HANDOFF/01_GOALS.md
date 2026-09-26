# 01 — Goals

The owner's words are kept exactly as written (typos included) so nothing is lost in
paraphrase. Below each block, the goals it produces, each with a status:
**DONE** (built and verified), **PARTIAL** (backend or frontend only, or unverified),
**TODO**.

---

## Request A — 2026-09-05 (original)

```text
9814bdd2... is the API for obsidian and make sure to link o it for better file usage and make sure it is used in your creation for different resources as this project continues. spin up 4 sub agents, 1 manager, 1 site/web dev, 1 coder, and one checker to make sure ideas they put in are solid and work. continue to improve the site, though it seems to still have issues with opening the site to get into the ai and test it. Also make it easier to install the app locally and download it rather than on the web. That was issues 1. issue two is the AI itself, I am worried that it might be in a bugged state since it responds with the same thing about its name and what it is rather than answering the question, check and see if you can fix this. Take your time and efficiently and correctly fix the issues. Also make sure the AI stays versatile and if a user wants to improve on it they can, though it wont affect every version. Also I need a system to set up admin perms and keys and the windows. Mark those are second highest priority behind the first issues I said. Also remember to have these listed in a document so if you lose tokens you are able to find this command again and continue.
```
(The Obsidian token is redacted here on purpose; it lives in `.env.local` as `OBSIDIAN_API_KEY`
and should be rotated because it was once hardcoded in git history.)

| Goal | Status |
|---|---|
| AI answers the actual question (identity-loop bug) | DONE — CWD-relative dotenv + swallowed router error + substring matcher |
| Get into the site and chat | DONE |
| Easy local install | DONE — see Request E |
| Admin permissions, keys, windows | PARTIAL — RBAC engine + claim route + permissions policy exist; admin console UI thin; access keys TODO (Request G) |
| Obsidian connector (Ichnos + Real Nyx vaults, REST + filesystem fallback) | PARTIAL — connector exists, token moved to .env.local |
| Per-user customization that doesn't leak to every install (overlay/profiles) | PARTIAL — overlay exists; profiles not wired |

## Request B — 2026-09-12 (the overhaul)

```text
I want to continue the AI improvement plan. For one, downloading should be much easier. The website is running nicely but running the AI should be easier, whether a command in the cmd or whatever else, make this a basic one or two click so the user doesnt have to copy and paste anything or ask an AI to do it for them. In addition, Make the tab editting much better so the aI works better, tells the suer what its doing, user can see as the AI works and much more., Also after giving a prompt the AI should be showing taht its working, and what its working on, and thought process. Nothing should be restricted unless User asks for it. Also make it much more versitile. The AI seems to have issues with emails and such. It should be able to interact wioth the machine on every level. Also allow computer control. Give it a mouse the User can see. Make sure the AI talking is better. Multiple voices. Also make better animations but also keep some space so in teh future I can give the webUi and the App Ui to a better model specifically for web/app design for the best transitions. If you can make it better with 3d and such but at the moment do what you can. Next the AI tabs should be better simialr to google tabs. Also the web cannot read and displkay the correct PC specs and details, and data, fix. Finally, make it smarter. Also Allow tthe AAI much moree control on the suer for designing the AI landscae. Allow picture uploads and file uploads. It could downlaod the image off the user computer or just look at it and understand it.
```

| Goal | Status |
|---|---|
| B1 One/two-click start, no copy-paste | DONE (Request E) |
| B2 Tab editing streams its steps, shows what it's doing, undo | PARTIAL — `ui_edit_tab` tool exists; streamed edit UI TODO |
| B3 After a prompt: visible working state, current step, thought process | PARTIAL — `/api/chat/stream` + `turn_runner.py` emit everything; chat UI still uses blocking `/api/chat` |
| B4 Nothing restricted unless the user asks | DONE (backend) — `permissions.py`, every category defaults to allow; Permissions UI TODO |
| B5 Email works (send/read/reply) | DONE 2026-09-14 — `email_client.py`, `routes_email.py`, Keys tab → Email (add an app password to read/send directly; otherwise a pre-filled draft opens and Nyx says it is not sent) |
| B6 Machine access on every level (shell, python, files, processes, apps, clipboard, power) | DONE 2026-09-14 — `machine_tools.py` (25 tools) |
| B7 Computer control with a cursor the user can see | DONE 2026-09-14 — `computer_control.py` (SendInput mouse/keyboard with gliding cursor, screen_view with coordinate grid, find_on_screen via `ui_pointing` model, windows list/focus/min/max/close/move), `cursor_overlay.py` (click-through labelled AI cursor + ripple, own process), `routes_computer.py`, in-app `ComputerBanner` with Stop; user override = Esc×3, top-left screen corner (multi-monitor aware), Stop. Overlay verified live on the 2-monitor desktop; real mouse NOT exercised live yet — first real run should be supervised |
| B8 Better talking, multiple voices | DONE 2026-09-14 — `tts.py` + `routes_voice.py`: Microsoft neural voices (edge-tts) with Windows SAPI offline fallback, a voice per role (Nyx, narrator, all 18 agents), audio cache; tools `speak` (→ `voice.say`, one open window plays it via `src/voice/voicePlayer.ts`, else PC speakers), `list_voices`, `set_voice_for`; chat "Listen" button; Settings → Voices with preview. Still possible: voice input (STT) upgrade, streaming playback of long answers |
| B9 Better animations + 3D, and a clean design layer a design model can later restyle | TODO |
| B10 Chrome-style tabs | TODO |
| B11 Correct PC specs and live data | DONE 2026-09-14 — Dashboard "This PC" / "Right now" / "Busiest programs" (`SystemCards.tsx` ← `/api/system/specs`, `/api/system/live`); per-core + per-process CPU fixed (were always 0), rates fixed (were halved), NVIDIA live telemetry fixed (called a missing method), process list via one NtQuerySystemInformation (4.5 s → 0.7 s), `device_profile` CPU name from the registry, Dashboard reads the nested `/api/status` `service` fields (showed 0 tools / no keys / 0°C) |
| B12 Smarter (planning, model choice, tool budget) | PARTIAL — agent delegation, skills search, streaming thoughts exist |
| B13 AI can redesign the workspace (theme, tabs, layout) | DONE (backend) — `landscape_tools.py`, `ui_state.py`; UI must apply theme events |
| B14 Picture and file uploads; look at local images | PARTIAL — `uploads.py` + `/api/uploads` + vision; composer attach UI TODO; `view_image` tool TODO |

## Request C — 2026-09-12 follow-ups

```text
Create 4 subagents. 1 manger, everything goes through this. 1 coer and dev, 1 idea maker, and 1 designer Make subagents betetr on this AI and amke sure they listena nd understand. Actively show the agents created. Skills created. Temp skills specifically for the taskl the AI can show the user it maddde for best efficency. ALso alllow searches where it can see what skills to use, also copy for otehr AI liek Opus, GPT Sol and Asstra, Fable 5.1 and more. The agents dont show, skills, connectors as well. Improve as well. This should be a massive oevrhall for all suers and include a way for me to get beta testers and devs on here. WIth skills I have mentioned befopre. whetehr through a specific key or a new site taht links to the og.
```
```text
Refert.I was refering to you, claude code to making those 4 agents. The agents for the AI should be very default with manager, coder, web design, App design, Finance, educator, tech, hardware, news, and such
```

| Goal | Status |
|---|---|
| C1 In-app default agents (Manager, Coder, Web Design, App Design, Finance, Educator, Tech, Hardware, News, …) that listen and understand | DONE (backend) — `agent_roster.json` (18 agents), `agent_runtime.py` delegation |
| C2 Show agents, skills, connectors live | PARTIAL — data exists; panels do not update live (see Request F) |
| C3 Temporary task skills the AI creates and shows | DONE (backend) — `create_temp_skill`, `skill.created` event; UI TODO |
| C4 Skill search the AI uses to pick skills | DONE (backend) — `search_skills` tool + `/api/skills/search` |
| C5 Export skills to other AIs (Claude Opus/Fable/Sonnet SKILL.md, GPT, Gemini Gems, AGENTS.md, generic) | DONE (backend) — `skill_export.py`; UI TODO |
| C6 Beta testers and developers: access keys and/or a beta site linked to the main site | TODO (Request G) |
| C7 The Claude-side team (these are *Claude Code subagents*, not app features) | process, not a feature |

## Request D — 2026-09-13

```text
FIX the glaring issue which is the engine. Make it a single click to turn on for any user.
```
**DONE** — Windows Smart App Control was blocking the unsigned `Nyx.exe`. Now: `Start Nyx.bat`
(first-run setup incl. Python via winget) → desktop shortcut + `nyx://` link + start-with-Windows,
engine runs on signed `pythonw.exe` with a tray icon; the web UI shows a full-screen "Turn on Nyx"
button when the engine is off and a service worker keeps the page loadable offline.

## Request E — 2026-09-13 (evening)

```text
Continue with the mass overall. Make a server for admin access with all the access details I told you about. In addition allow and make sure that the site is much faster. Dont worry about UI. I will fix it withd esign. Also make sure the Ai is learning and uses ML as well. It should learna nd use cache and cookies. Also if User goes out of tehri website it shuld have data stored for when they come back. Also the Ai agents, SU8BAGENTS DONT update. FIx this maily since it doesn't make sense that I can see. Also amek a visual iidea and remidner that the AI Agents are created in the chat. CXhats can run outside of their windowe and tab. Imporove on all levels and finally when you are almost out of usage make a fodler which has all your goals as well as all features in this app so I can feed to otehr AI for help. Finally, you ands only you make sub agents to help you as in in claude. MAke 4-5 sub agents, 1-2 coders and reviwewers, 1 manager, 1 idea maker, 1 design agent, 1 critic who checks and heavily criticizes teh work until tehy approve and find no flaws at all. In additoon use this gihub for the best design and overall. This should be na masterful app. Fully refdesign the AI bubble part and make sure moer parts are added. Finally you and you alone make a subagent to help you with overall implementation and connect back end to front end and make sure to use the link here for the best desdign langayuage and iddeas.
```
(The "github"/"link here" for design did not come through in the message. The Apple Human
Interface Guidelines skill was invoked with it, so that is the design language used until the
owner supplies the link.)

| Goal | Status |
|---|---|
| E1 **Agents/subagents update live** and it is obvious that agents are created in chat | IN PROGRESS |
| E2 Chats keep running outside their window/tab; reopening shows the live turn | IN PROGRESS |
| E3 Admin access server: beta/dev access keys, testers, invites, users, redemptions, feature flags | IN PROGRESS |
| E4 Site much faster (compression, caching, code splitting, lighter polling) | IN PROGRESS |
| E5 AI learns (ML): feedback-trained routing/skill choice, response cache, preference learning | IN PROGRESS |
| E6 Cookies + stored client state: leaving and returning restores tabs, drafts, active chat, scroll | IN PROGRESS |
| E7 Redesigned AI message bubble with more parts (thinking, steps, agents, skills, images, attachments, actions, feedback) | IN PROGRESS |
| E8 This handoff folder | DONE (kept current) |

## Request F — 2026-09-14 (night, /goal, "Mainly focus on this")

```text
Also for self improve allow it to self improve in different different times. basically make a chat in said chat I can say improve and auto approvce all improvements for a time of 22 hours. Or Study for 1 hour and improve for 1 hour and loop this untuil I stop. Things like that where I can tell the AI. In addition I can ask the AAI to add things to the improve tab liek if I want to have different sliders for when to improve asnbd what to doi and such. Very diferse.

Next add a new tab for 3d design for circuits, machines, electronics, and such. The ai can help in almost any way and analyzes as the user works. A useful application is like tell the ai in this tab to take a couple hours to generate an apparatis and the parts needed to make a containment device for the ai itself

Make a new text application feature that can be toggled in settings. Basically instead of the ai just taking what the user says. There is a complex super ai algorithm that takes in user text, conplexifies and make it much better to read for the ai is most efficient in use in tokens and power while also doing the best output without having confusion. This ai in between should be super intelligent and should work both on and offline. This way a simple command like make this all becomes a couple more lines of text or even a couple paragraphs. Make sure this also have a use sensor so when a simple task that should stay simple is put it it doesn't change and can even make it work while a huge task is only slightly optimized that way the users specific commands are taken in and don't get changed. Also allow the ai that is being prompted to read the of text and overlay with the new optimized to ensure nothing is lost for the prompt. So this should basically be a 3 agent operation, the original that has all the agents and chats and whatnot (nothing new here) and 2 more which read and optimize and check and stuff.

Also add prediction algorithms to almost every part of this ai whichever it be user preferences or whatever. Including selecting models and more. Even making tabs on its own when user is not active with. Switch for this so the user can decide. The ai can make tabs it thinks the user needs, auto updates, has a 1 hour detox period where it self improves and can even get to levels of high end machines.

Allow extension into vs code and such. Basically allow it to connect to a file and edit in there actively similar to Claude code or Codex. Lastly add super learn where the AI improves overall with each prompt, each search and stores it. Asd it does it, it learns and gets smarted. A mix of machine learning and Artificial intelligence. BAsically amking it its own model. Som basiclaly there is a main model, the one that learns and uses otehr mdoels. Starting small and getting bigger, using Gemini or whatever Ai api key as a crutch and improving and the user has a tab to track prograss whiel seeing what it learned on a huge neural model. Also make sure the AI can actually use APi keys. Also make a way to add a API key from a new provider not shown which the AI and user can define for name and use (image, normal text, all uses, and such. All uses like it can be used in images and image detection and text detection and just talking and more)

Fully upload to GitHub and allow it to be deployed form there as well into vercel ad you have rn. Then allow and make sure this to be downloaded from GitHub. Also when launching I wnat my site to launch rather than on windows. Like when you download it it is fine but when it's only website launch when on website.

Use this image that I hyave attached as reference for how the brain should look. A good black background and now design everything around this. Also combine the brain and the chat tabs since I feel like they should be on the same tab so chat, voice, and the second brain should be shown. Also add a super brain. Hundreds of thousands of nodes, basically storing it as the ai looks through it. Black should be the most emphasized color then add apple design components with clicky design, 3d, authentic.
```
```text
Also add the NVIDIA model for nemotron-3-ultra-550b-a55b/ so people can add the free API key
```
(The attached reference image: a "Second Brain" memory field on pure black — 8–10 glowing,
differently coloured particle clusters with thin radial lines to labelled source tags (Gmail,
ChatGPT, Claude, Codex, GitHub, Files, Telegram…), a monospace HUD: left "memory imports / agent
network / input channels" lists, top-right "memory network online · live system · FPS · impulses",
bottom-left huge "Second Brain" title with "3,940 memories in the field +439/24h", bottom-right
"memory counts" card, bottom-centre "drag rotate · scroll zoom · drag pan · full" hints.)

| Goal | Status |
|---|---|
| F1 Improve autopilot: chat-driven schedules ("auto-approve for 22 h", "study 1 h / improve 1 h, loop until stop"), AI-added Improve-tab controls (sliders, when/what) | TODO |
| F2 3D design tab (circuits, machines, electronics), live AI analysis, long-running "design an apparatus + parts" jobs | TODO |
| F3 Prompt optimizer (Settings toggle): optimizer + checker agents, simplicity sensor, works offline, main model sees original + optimized | TODO |
| F4 Predictions everywhere (preferences, model choice, next tab), idle auto-tabs switch, auto updates, 1-hour detox self-improve | TODO |
| F5 VS Code extension: connect a folder/file, Nyx edits live like Claude Code/Codex | TODO |
| F6 Super learn: learns from every prompt/search, own growing model that uses other models as a crutch, progress tab with neural view | TODO |
| F7 API keys really used; add any new provider with name + uses (text, vision, image gen, OCR, all) by user or AI | TODO |
| F8 Nemotron 3 Ultra on NVIDIA | DONE 2026-09-14 — `nvidia/nemotron-3-ultra-550b-a55b` featured in the catalog, aliases, key notes; verified answering (13 s) |
| F9 GitHub: everything pushed, deployable to Vercel from GitHub, downloadable; the website launches the web app itself (not the Windows engine) | TODO |
| F10 Black-first redesign after the reference; Brain + Chat + Voice on one tab; super brain with hundreds of thousands of nodes; Apple components, clicky, 3D | TODO |

## Request G — 2026-09-15 (/apple-design, sent while the session limit was hit)

```text
Add trading and finances. So basically it connects to whatever trading stocks app the user wants, auto integration regardless and connects to account then they can trade form there and the ai devotes the resources the user wants to predict and trade stocks. Using searches or know when stocks are moving.

Also in beta test make sure that changes are put through GitHub then added or some kind of way. DOES NOT HAVE TO BE GITHUB. Just let me know what way you do it. One thing to fix is just fix the x plane for the moving for the second brain since when i turn left or right it moves the opposite way. Only fix that part of it. Also when changing chats the names for each are hard to see. Change colors of letters. Also add a small button where I can change the chat name so it has the name I want instead of the AI. but keep the ai oputting its chat name.

Also for / commands make sure when you do that a menu pops up above it so that I can see all commands and as I type letters it finds the one I mean and if not found it uses a mini AI to predict which one I could mean or make one on the spot or lead me to the skills create menu

Also add a bar if the specific api has a usage limity and if not dont have it

Also add that vs code extension and add a tab for coding/file edit where i can click the large file and I tell it to use that and can be used like cursor, cluad ecode, and codex

Allow to check background for users such as Loki God of time basckground with animations done by AI or from a gif

Also when I switch to a different mdoel it doesnt switch but when I directly ask it switches for me. Please make suree it works a bit betetr for this and when it cant it tell;s me and switches  the mdoel on the drop down

After all above commands are finished. Make a new website for beta testers. Solely for that and make sure there are detailed steps on howe to do and download it

This issue is also persistant where I tell it something and it cant do it and proceeds to do soemthing else: For this site please make a donwlaod I can send my friends so they can download and run the AI then go to the website so that they can open and run you
  [pasted chat: "Expanded your request for the model" · gemini-flash-lite-latest 1181 ms · "I did not get a usable answer back — please ask again." (25 s) · owner: "please" · same empty answer (5.8 s)]

But also when I give a command it can do it does both the command and the past command it said it cant: sweitch to nvidia
  [pasted chat: nvidia · 1m 06s — it switched AND carried out the earlier download request: copied NyxIchos-Windows.zip / NyxIchos-windows-x64.zip into site/downloads and wrote friend instructions]

Also if I type something while anotehr prompt is going then at that time only make a second button which I can click to cue or make it run or interrupt or have anotehr  AI run at teh same time or branch it. Make the AI decidse
```

| Goal | Status |
|---|---|
| G1 Trading & finances: connect a brokerage, trade from Nyx, AI watches/predicts with the resources the owner allots | TODO |
| G2 Beta changes flow through a reviewed channel (say which) before testers get them | TODO |
| G3 Second Brain: left/right drag rotates the wrong way (x axis only) | TODO |
| G4 Chat list names readable; small rename button; AI still names new chats | TODO |
| G5 `/` command menu above the composer, filters as you type, mini-AI guess / make one / open skill creator | TODO |
| G6 Usage-limit bar for the active API, only when that API has a limit | TODO |
| G7 VS Code extension + Code tab (open a big file, tell Nyx to use it; Cursor/Claude Code/Codex style) | TODO |
| G8 Custom animated backgrounds (AI-made or GIF), e.g. "Loki, god of time" | TODO |
| G9 Model dropdown really switches; when it can't, say so and show the real model in the dropdown | TODO |
| G10 Separate beta-tester website with detailed download + run steps (after G1–G9, G11, G12) | TODO |
| G11 Refused/failed request must not leak into the next turn; empty "no usable answer" from gemini-flash-lite | TODO |
| G12 Typing while a turn runs → second button: queue / run now / interrupt / parallel / branch, AI picks the default | TODO |

Follow-up sent mid-session (2026-09-15, verbatim):

```text
In additoomn add a notes tab witrh a lot of variety such as voice, record lecture and convert to text ( this doesnt save the sound and just converts), draw and convert to notes teh Ai analyzes the draawing, smakeq notes mroe detailed. can generaster practice qwuizes and questions. Helps answqer questions step by step. Add a lot more these kinda ofd things that are useful to colege students and lecture
```

| Goal | Status |
|---|---|
| G13 Notes tab for college students: voice notes, lecture recording → text (audio never saved), draw → AI reads the drawing into notes, make notes more detailed, practice quizzes/questions, step-by-step answers, flashcards and more | TODO |

Follow-up sent mid-session (2026-09-15, verbatim):

```text
Once usage ends make a file for codexs to read to know what you think to add and where you left off as well as ghoals, time, sub agents for codex to spawn (not my ai) and whatnot
```

| Goal | Status |
|---|---|
| G14 `AI_HANDOFF/CODEX_HANDOFF.md`: where Claude left off, goals, time estimates, what to add next, Codex subagents to spawn (Codex's own, not Nyx's roster) — kept current during the session | IN PROGRESS |

Follow-up sent mid-session (2026-09-15, verbatim):

```text
Also when I create a chat it duplicates the current one then makes a new chat afdter i click the create chat again. Please fix to one click creates 1 chat. Make the duplication chat a separate feature and also branch adn forking chats should eb a feature eitehr by telling or by a button
```

| Goal | Status |
|---|---|
| G15 One click on New chat = one empty chat (bug: first click showed a copy of the current chat); Duplicate, Branch and Fork as their own features, from a button or by asking Nyx | TODO |

Follow-up sent mid-session (2026-09-15, verbatim):

```text
Also there is this issue, if it eprsists make sure it stops but just chat with it and see if it can  swithc modeks both with the drop down and with saying swithc mdoewls to the chat. Also if i make a sub agent or second agent or whatevr, it make sa place whwere I can see the agent and click on proeprties to change the mdoe, used, objective, and such
```

| Goal | Status |
|---|---|
| G16a Live check by chatting with Nyx: switching models works from the dropdown AND by saying "switch to X"; the old-request leak does not recur | TODO |
| G16b When a sub-agent / second agent is made, it shows up somewhere visible with a Properties sheet: model used, objective, role and the rest, editable | TODO |

Follow-ups sent mid-session (2026-09-15, verbatim):

```text
Also allow me to expand the chat windows
Both with a button and by dragging the side bar
```

| Goal | Status |
|---|---|
| G17 Chat window can be made wider: an expand button and a draggable side edge (remembered) | TODO |

## Request H — 2026-09-15 (after the usage reset; "These are the main things to fix")

```text
find the file which claude left so you knwo where to start. Also one thing to mainly focus on is in the code tab, make sure that there is a button where I can search my files and it opens file explorer and when I click on the folder or folders I want it takes thoser.

Now in the actual chat lets make it so that if I ask for a sub agent to be made it is created, also amek a tab specifricall for when I want a sub agent on the case where I select the model. Also when it does have it in the top bar next to team (#) I want a place to click so I can see all details of sub agents or agents. I want to be able  to edit goals, purpose, agent used, if they consult other agents. On heavy tasks auto consult with other agents booth on same model and other.

This error pops up when I trell to switch or other things:

Expanded your request for the model
offline rules · 1052 ms
Thinking
(1)
Steps
(1)
TypeError: ToolRegistry.call_tool() got multiple values for argument 'name'

switch toi nvidia
Thinking
(1)
Steps
(1)
TypeError: ToolRegistry.call_tool() got multiple values for argument 'name'

Finish the build tab with all circuit info, 3d print and build info, can connect to apps for 3d print, can find materials online, finds different solutions such as if I wnat to store an ai it  thinks of things like pi or ardueno and then finds a couple options and builds it. Also to build off this make a game studio tab to make games in 3d and 2d. Similar to making hollow knight and more it can import to unity.

Also the model keeps referring back to Gemini, try to make sure it does it only when needed and on hard questions. Make it similar to collaboration or coordination.

For connecting my  google to the ai, the app passwords doent work. In keys and models allow me to add a model for api key and I can type name, company, and api key, as well as s use it if there is a special one. Also allow me to add multiple api keys for one so if one fails it can be stored as dialed and can be retried every 5 attempts of so while the other ones are stored as working. Then the user is alerted after a while that it failed and asks if it can disregard only the one that doesn’t work.  Also it at times just disappears as in the text and teh speech bubble disappears after a long time of thinking even though it was getting to the output and working. Add graphing andd python boxes. When I tryt o change to a “paid” model it has an issue which says its paid but I do have an API key for free. Try to fix this and only ahev it as paid if the APi respinds with that or fix in a better way.

In code tab Make sure i can make new files in tehre, and have it do things without having thiongs in there. Start from sct=ratch as an options dn in there i can open a empty or premade fodler or make a new folder. Also when i  do the / command allow me to do multiple and i CAN add it anywhere in the text. So in the middle ro evn at the end./ The AI reads the skills first.

Add intent.md from Anthropocene and make sure the ai understands


Add a sources drop down in the AI respond bubble where I can clicck on links. Also make sure the linsk work correctly . ALso make sure it can show images in the chat.

In edit for tab give it a lot more freedom in changing background to even an image and as make it so taht it can add lists, charts, tracck things, actively do things, have timers for teh AI to do, compeitiions between AI and human. If i want a game bt dont want to run open in a file or separate tab it opens here and changes the background and text boxes.

These are the main things to fixz
```

| Goal | Status |
|---|---|
| H1 Code tab: "Browse" button opens Windows' folder picker; pick one or several folders and they open | TODO (main focus) |
| H2 Asking in chat for a sub-agent really creates it; a Sub-agents tab to create one with a chosen model; next to "Team (#)" a button showing every agent's details; edit goal, purpose, model, whether it consults others; heavy tasks auto-consult agents on the same and other models | TODO |
| H3 `TypeError: ToolRegistry.call_tool() got multiple values for argument 'name'` on switching and other requests | TODO (bug) |
| H4 Build tab: circuits, 3D-print and build info, open in 3D-print apps, find materials online, compare solutions (Pi vs Arduino…) and build the chosen one | TODO |
| H5 Game Studio tab: 2D and 3D games (Hollow Knight-like), export to Unity | TODO |
| H6 Stop defaulting back to Gemini; use strong models only for hard questions, as coordination/collaboration | TODO |
| H7 Google connection without app passwords | TODO |
| H8 Keys & Models: add a custom model (name, company, API key, special use); several keys per provider with failover, failed keys retried every ~5 uses, alert the owner and ask before dropping only the failing key | TODO |
| H9 Answer bubble disappears after a long thinking turn that was about to answer | TODO (bug) |
| H10 Graph and Python boxes in chat | TODO |
| H11 "Paid provider" refusal when the key is free — only call it paid if the API says so | TODO (bug) |
| H12 Code tab: new files, new folder, start from scratch (empty or template folder), Nyx can build in an empty folder | TODO |
| H13 `/` commands: several in one message, anywhere in the text; the AI reads the skills first | TODO |
| H14 Add intent.md ("from Anthropocene") and make sure the AI understands it | TODO — source to be located |
| H15 Sources drop-down in the answer bubble with working links; images shown in chat | TODO |
| H16 Tab editing: image backgrounds, lists, charts, trackers, live actions, AI timers, AI-vs-human competitions, games that run inside the tab | DONE — 2026-09-15 |

Request G leftovers still open: G2 UI (Settings → Updates channel/rollback; backend + release script done and tested), G10 beta-tester site.

Added when the same message was re-sent (2026-09-15, verbatim):

```text
Add a log out button so that it shuts off the app running in background. Make it so as you move your mosue onto the rectangukalr button it has a animation which the color blue fills in teh box. Then in the middle of teh screen have a confirmation with simialre aspects, not the same but siumialr appeal
```

| Goal | Status |
|---|---|
| H17 "Log out" button that shuts the background app down: blue fill sweeps in on hover; a centred confirmation with a related (not identical) look | TODO |


## Request I — 2026-09-15 (evening, sent while Request H was being built)

```text
Make sure it doesnt take too much storage as well. I dont want my entire computer getting too large

Make a 3d representation of a city, add to the second brain tab but have as a second option, here
create representations of traings, creating, adn working teh AI Agents. So when a subagent is created
it appears and as it works its way up it gets better and better. Not too needed but add whyat you
can. 3D so I can drag my mouse around, click on buildings and look inside and see agents named for
tehri taskls. Add an adult mode for images and such. Toggle in settings

Also for subagents allow me to start with or without the task so it runs in a chat. Also allow for
linking to a specific chat. Add much mroe things for this

Also for the city reverse left right
```

| Goal | Status |
|---|---|
| I1 Keep Nyx small on disk; nothing should make the whole computer large | DONE — `storage_budget.py` |
| I2 3D agent city as a second option in the Second Brain: buildings for agents, new sub-agents appear, they grow as they work, drag to orbit, click to look inside and see tasks | DONE — `components/brain/AgentCity.tsx` |
| I3 Adult mode for images and such, toggled in Settings | DONE — `content_mode.py` + Settings → Content |
| I4 Sub-agents: start with or without a task, run in a chat, link an agent to a specific chat | DONE — agent-owned chats |
| I5 City: reverse left/right drag | DONE |


## Request I — 2026-09-15 (evening, sent while Request H was being built)

```text
Make sure it doesnt take too much storage as well. I dont want my entire computer getting too large

Make a 3d representation of a city, add to the second brain tab but have as a second option, here
create representations of traings, creating, adn working teh AI Agents. So when a subagent is created
it appears and as it works its way up it gets better and better. Not too needed but add whyat you
can. 3D so I can drag my mouse around, click on buildings and look inside and see agents named for
tehri taskls. Add an adult mode for images and such. Toggle in settings

Also for subagents allow me to start with or without the task so it runs in a chat. Also allow for
linking to a specific chat. Add much mroe things for this

Also for the city reverse left right
```

| Goal | Status |
|---|---|
| I1 Keep Nyx small on disk; nothing should make the whole computer large | DONE — `storage_budget.py` |
| I2 3D agent city as a second option in the Second Brain: buildings for agents, new sub-agents appear, they grow as they work, drag to orbit, click to look inside and see tasks | DONE — `components/brain/AgentCity.tsx` |
| I3 Adult mode for images and such, toggled in Settings | DONE — `content_mode.py` + Settings → Content |
| I4 Sub-agents: start with or without a task, run in a chat, link an agent to a specific chat | DONE — agent-owned chats |
| I5 City: reverse left/right drag | DONE |


## Request J — 2026-09-16 (afternoon; with a screenshot of a glowing core in a particle field and glass HUD panels)

```text
Make a third tab in second brain and add usage gauges for each process, all agents, api, and such being used. Show sub agents and a way to run in from there and a way to dev and drop into a single project or press a plus to add them.  Ai should now auto use the sub agent it needs without me having to manually do this. Can make sub agents by itself and add to the sub agent tab as well as that third tab I just say. In third tab add what the image looks like that I attached. 


This should be clean and aesthetic. 

In improve tab add a place where I can approve or deny change s. Make a mode to analyze all in review or changes and then approve or ddeny and apply. Do this in the improve tab

Also when I want to add sub agents another rah is through / commands so basically when I make a sub agent or there is one the ai makes it also adds its name to / commands so that I can say /coder and it pulls up the coder agent and in [] I add how many of that agent to be made. Also when using the drag drop method or when the ai calls on it for specific situations it has a box or a place to say how many I want or I can drag a second one and it will show a second box. In each I can say what u want each to specifically do if I have different tasks.   Also in approve it tell it tro approve and auto check and whatnot but still doesnt, please ssee and amkew sure it can research, then appreoave on its own. Check this mplement approved changes Off = approve only; the code is left for you. Option since I cant tell if kit works correctly or nmot. In improve allow a deep and specific mode, clicking this shows a big box and I can paste or write specific improvements and such and it auto generates the time it thinks it will take and can increerate if needed. 

In add model it says chat completions url but I cant use it, please check and fix
```

Sent while it was being built (verbatim):

```text
This issue also occurs, make sure it fully chgecks and uses anotehr model to implement: 
Analysis found 0 improvements (Analysis model failed: No model could do 'Code & Architecture' — nvidia: skipped: it failed moments ago; gemini: Gemini (gemini-flash-lite-latest) answered 429: { "error": { "code": 429, "message": "You exceeded your current quota, please check your plan and
```

Root causes found before coding (2026-09-16, from `autopilot/runs.json` and `changes.json`):
- Auto-approve "never works": proposals are descriptions with empty `content`; the critic read "--- proposed content ---" (empty)
  and answered BLOCK "the diff is missing" — 94 of 101 blocked in one run. The same ~5 ideas were re-proposed every session
  (701 changes stuck in_review). Typing "Apply all" in the Improve box started a new improve run (no approval UI existed).
- Analysis model failure: `model_roles.run` *skipped* NVIDIA for 90 s after one outage and the only other configured
  provider (Gemini) was out of quota, so nothing ran; other NVIDIA models and the owner's custom models were never tried.
- "Chat completions URL": only shown for company "Other"; a local server (LM Studio/Ollama) was refused with "Set 'local'"
  and the form has no such option; a base URL (…/v1) was not completed to …/chat/completions.

| Goal | Status |
|---|---|
| J1 Code/analysis jobs never stop at "skipped: failed moments ago" — every working model is tried (other models on the same provider, custom models), cooling ones last | DONE — `model_roles.fallback_candidates` |
| J2 Auto-approve really works: research + implement in a sandbox + critic reviews the real tested diff, duplicates filtered, pre-existing test failures not blamed on the edit | DONE — `improve_review.py`, `self_patch.prepare/commit` (LIVE: research verdict on a real change) |
| J3 Improve tab: approve / deny changes; "Analyze all" mode reviews every pending change, recommends, then approve/deny and apply; "Implement approved changes" shows what it did | DONE — `panels/improve/ReviewQueue.tsx` |
| J4 Improve tab: Deep & specific mode — big box for exact improvements, auto time estimate, extends/iterates when needed | DONE — `improve_deep.py`, `panels/improve/DeepMode.tsx` |
| J5 Add a model: Chat completions URL works (any company, local servers, base URLs, check before adding) | DONE — `routes_key_pool.normalize_chat_url`, `/api/custom-models/check` |
| J6 Every agent (made by owner or AI) is a /command: `/coder [3] task` opens N boxes, each with its own task, + add another | DONE — `commands.agent_commands`, `agent_dispatch.py`, `components/agents/AgentBoxes.tsx` (LIVE: 2× Coder ran in parallel) |
| J7 Nyx picks the right sub-agent automatically and makes new ones itself (shown in Sub-agents tab, Core view, /commands); its dispatches show the same boxes | DONE — `agent_match.py`, tool `dispatch_agents`, `made_by` |
| J8 Second Brain third view like the screenshot: glowing core, usage gauges (processes, agents, APIs), sub-agents with Run, a project dock to drag agents into or add with + | DONE — `components/brain/CoreView.tsx`, `routes_core.py` |

Sent while it was being built (verbatim):

```text
Also for handoff, make sure even nyx can look at it sincce if I want it to start helping you it should be able to read it
```

| Goal | Status |
|---|---|
| J9 Nyx can read the handoff itself (current goal, owner requests, where work stopped, how to work in the repo) | DONE — `handoff_tools.py` (tool `read_handoff`, `/handoff`) |


## Request K — 2026-09-16 (sent while Request J was being built; "After this /goal")

```text
After this /goal is to make a second website for beta testers where they can apply changes to github, have a special paghe for collaboration where they send and show all changes and it auto uploads those changes to that tab
```

| Goal | Status |
|---|---|
| K1 A second website for beta testers (separate from the download site) | DONE — `site/collab/` (needs the owner's Vercel env, `docs/COLLAB_SETUP.md`) |
| K2 Testers can apply their changes to GitHub from it (reviewed; never a direct push to main) | DONE — `site/api/collab/submit.js` (branch + PR), Nyx Collab tab |
| K3 A collaboration page: testers send changes, every change is shown, and new ones appear there automatically | DONE — live list on the site and in Nyx's Collab tab |


## Request L — 2026-09-16 (sent while Request J was being built)

```text
Create a research (deep and standard) tab for researcha nd add lots of stuff as well as citations, paper publishing mode, and it can searcha dn research papers. It can also help train the model so it can upgrade
```

| Goal | Status |
|---|---|
| L1 A Research tab with Standard and Deep research modes, and much more in it | TODO — after J (and K, unless the owner reorders) |
| L2 Citations: every claim linked to its source, exportable citation styles | TODO |
| L3 Paper publishing mode: write a paper from the research (structure, references, export) | TODO |
| L4 Search and read research papers (scholarly sources) | TODO |
| L5 Research feeds Nyx's own training so it can upgrade (Nyx Core / super brain / distillation set) | TODO |


## Request M — 2026-09-16 (sent while Request J was being built)

```text
In models and api keys add a use for the 3d model center and allow multiple to work together since this is a heavy workload. Also when offline make sure that the model for ollama can self replicate and will be able to do work laods even if it is slower. Also amek sure I can add offline mdoels liek If i tell it to downlaod it and use it as a locally mdoel
```

| Goal | Status |
|---|---|
| M1 Keys & Models: a job ("use") for the 3D model center (Build studio), with several models working on it together | TODO |
| M2 Offline: the Ollama model runs several copies of itself for heavy work (slower is fine) | TODO |
| M3 Add offline models by asking: Nyx downloads the model (Ollama pull) and uses it as a local model | TODO |


## Request N — 2026-09-16 (sent while Request J was being built)

```text
Also for the voice make a conversation off on switch so I can talk and it imediatly responds so basically ahnds free
```

| Goal | Status |
|---|---|
| N1 Voice: a Conversation on/off switch — talk, and Nyx answers right away out loud, hands-free, then listens again | TODO |

Added (verbatim): "For the voicce also make sure it can also actevily talk so as it thinks it also responds. I will also end my chat weith it so you can work fully"

| Goal | Status |
|---|---|
| N2 Voice talks while it thinks: short spoken progress as the turn works, then the answer | TODO |


## Request O — 2026-09-16 ("Final thing after all this finishes")

```text
Fina thing after all this finsihes. Improve the new tab and editting. Make sure it knows it ahs freedom and put less emphasize on thatd default temp since it only genrates the 3 boxes and change generate buttons, lists, or a way to talk to the AI. Giuve it a pletehra of exmaples and implement the apple design sklill that we have
```

| Goal | Status |
|---|---|
| O1 New-tab creation and tab editing: the AI knows it has freedom; much less weight on the default template (it always made the same 3 boxes) | TODO — last in the queue |
| O2 Generated tabs use buttons, lists, and a way to talk to the AI inside the tab | TODO |
| O3 A plethora of examples for the tab designer | TODO |
| O4 Apply the apple-design skill (`skills/apple-design/`) to tab design | TODO |


## Request P — 2026-09-16 ("After that last command" — queued after Request O)

```text
After that last command Add a sytsem to the local model. Basically it can be as big as it wants but once it starts to get too  big detection sees and switches to a second approach whewre it satrts laying the parts it needs only when it truly needs it and it lays info in  a flat way. Follwoing the AirLLM model and also it will lay parts layer by layer ass mentioned and will have Flash attention but this is should only activate at the highest usage and most power needed. By default turnm it off
```

| Goal | Status |
|---|---|
| P1 Local models can be as big as wanted: detect when a model is too big for memory and switch approach | TODO — after O |
| P2 Second approach like AirLLM: load only the layers needed, one layer at a time, from flat per-layer files | TODO |
| P3 Flash attention in that mode | TODO |
| P4 Only at the highest power / heaviest use; OFF by default (a setting) | TODO |


## Request Q — 2026-09-17 (/apple-design, then "Try again")

```text
/apple-design Add a context bar and compact context skill
Try again
```

Found before coding: every turn sent the chat's whole history to the model (ChatService loads the last 40 stored
messages and nothing ever trims), so long chats got slower, dearer, and could overflow small context windows.

| Goal | Status |
|---|---|
| Q1 A context bar in the chat: how full the answering model's context window is, with numbers and what fills it | DONE — `components/chat/ContextBar.tsx`, `/api/chats/{id}/context` |
| Q2 Compact context: summarize earlier messages so the chat keeps going — a button, `/compact`, a tool Nyx can use, a built-in skill, and automatic compaction near full; undoable | DONE — `context_budget.py`, skill "Compact context", tool `compact_context` |


## Request R — 2026-09-17 (/apple-design, with two screenshots of a dark "Data Platform / News" analysis screen)

Built by a second Claude session (ai-dev-folder-0d) while another session builds Request L and Q. The screenshots show:
a top nav (Overview · Pipeline · Sentiment · Alt Data · News), a pipeline strip (Ingest · Dedupe · Tokenize · Entities ·
Topic model · Sentiment · Index), a left column (sliders, "Break a story", source filters, a queue of documents marked
Reading / Queued / Indexed with scores), a centre reader whose highlighted words are joined by curved lines to a Topic
List (Earnings, Capex, Cloud, Supply, Reg, Legal, Prod) whose bars fill as words are matched, a right column (document
summary, topic-share bars, sentiment, a live Dataset table), a Coverage ticker strip and a "Net sentiment — last 3
minutes" dot chart.

```text
Create a new tab called data absoeption/trianjng. In here it will basically just train itself and make itself smarter on all levels to the ollama model is smarter and all models are also smarter use the image as referenced for how it looks. The user can actively see as the at sorts through it. 2 modes 1 for the ai auto doing it and the user sees it pull up the document (papers, GitHub’s, anything and everything for high data collection keep in mind it shouldn’t take too much storage on a computer). And the second option is the user uploads the document or documents or a link or a few links or a combo of booth and the ai only looks through that. A third option is that it is given a specific prompt of what to search for and it goes off to specifically train on that. At the end or when I stop it, it will say what it leaned, what it added to itself like skills or agents or agent feature or faster things and will be done and can be relayed for different or same things for further study. Different from the improve tab but similar features. Try to copy the aesthetic from below. As seen below the ai highlights yeh words and a curved line goes form the high light to the specific topic list and a bar fills up as it does that. On the right the user can select which broad ropic the ai is studying since the ai studies multiple topics and multiple papers at once. Now the first 3 modes I talked about are in one mode called data analysis. This is what the image mainly has and copy format and what it shows. In a second overall topic will be called data process use. In this I can tell it to analyze data like a resume or group of resume or a code or spread sheet or whatever and it will be able to looks that and using its data analyze features explain what’s in it, sort, or do whatever the user wants. Put a lot of effort into what the ai can do with this it is very free range. Even financial analyzers can use this. Also the ai can suggest changes it can make to itself based on documents and only the user can approve. Make sure each big idea is condensed into separate boxes which can be expanded to see what is in there and the user approves. Also for both coding and improve make it so that when its working and editing field and I tell it a specific prompt to approve an improve or whatever it is make it so that it shows how many lien are affected and in which file. 

Another tab will be screen share so it views a persons screen and can help them using its cursor and typing. It works with the user and at its pace. This will mainly us ollama but it will be helpful for coding or more  sheets and such for finance could be a good use. Don’t allow it to have too mc control and instead just work properly. 


Now a more update feature should be for voice. For voice I want to add active talk so as I talk instead of saying send it just auto sends to the ai so it’s an active chat. You can hear as the ai thinks and works. It should be a faster model so maybe the local ollama model. In keys also add a way to add local models so basically it’s another part where if I have a download I click on it and it adds to the overall model. 
Add a model finder. It searches extremely hard to find more models for free and gives the link or search so the user can find and api key for it. Put this specifically in the key tab on the bottom. Last resort kind of thing. 

In the main tab, make it so that in both the text and the voice modes I can ask it to say make a fiagrms and a new tab opens as an overlay and it can draw or pull from an image which chaos sit. It can search and show an image. In the chat when i ask it to upload and image it a diagram or anything like it it has the ability to and and show it. Make sure it’s pdf and drawing is available and works. A command example is to show me a diagram of how you, the ai works and it shows me a diagram of its base agents, the other agebts it uses and uses design tricks and skills and tech to make it. Make sure this uses multiple agents at times for best experience yet least power use so it stays efficient and doesn’t force a crash. 

Make a tab called free will on here it gains opinions and more. Much more free and alive. Less restrictions on how it draws and crates. It can make anything here. A single chat box and it can search, improve, and everything. A basic combo do all things but highly guarded. Opening it the first time asks if you allow this bot to exist and it doesn’t age a specific agent and sets to agent decides. 

Add a apply tab and in this it is basically just a way to prompt the ai and also upload field, pictures m, and such so that the ai then follows it and applies to itself. In this tab what happens is basically improving the ai in changing its code, adding tabs, and more. Somali to vibe coding which I am doing now. It can use images to understand ui format. It uses apple and normal design skills together. Can search.  and more. 


Allow me to add qwen as a provider in key if not already done.
```

| Goal | Status |
|---|---|
| R1 Data Absorption tab, "Data Analysis" view styled after the screenshots: pipeline strip, source queue, reader whose highlighted words are joined by curved lines to a topic list whose bars fill, detail column, coverage strip, live chart | DONE 2026-09-18 |
| R2 Data Analysis — Auto: Nyx picks and pulls documents itself (papers, GitHub repos, pages), several topics and documents at once, storage-capped | DONE 2026-09-18 |
| R3 Data Analysis — Only what I give: uploaded files and/or links, any mix, nothing else is read | DONE 2026-09-18 |
| R4 Data Analysis — A prompt: Nyx searches for and studies one specific subject | DONE 2026-09-18 |
| R5 Pick which broad topic it focuses on from the topic list while it studies many at once | DONE 2026-09-18 |
| R6 Stop or finish → report: what it learned and what it added to itself (skills, agents, agent features, speed-ups); run again on the same or different material | DONE 2026-09-18 |
| R7 "Data Process Use" view: give it data (resumes, code, spreadsheets, financial statements, anything) and ask for anything — explain, sort, rank, compare, extract, compute, chart | DONE 2026-09-18 |
| R8 Self-change suggestions drawn from documents: each big idea in its own expandable box; nothing is applied without the owner's approval | DONE 2026-09-18 |
| R9 Code tab and Improve tab: every proposed or approved edit shows how many lines change and in which file | DONE 2026-09-18 |
| R10 Screen Share tab: Nyx watches the screen (mostly local Ollama vision) and helps with its cursor and typing at the owner's pace, with limited control | DONE 2026-09-18 |
| R11 Voice "active talk": what the owner says is sent as they talk (no Send), a fast (local) model answers, and Nyx is heard while it thinks and works (same wish as Request N) | DONE 2026-09-18 |
| R12 Keys: add local models — pick a model already downloaded and it joins the model list (same wish as Request M3) | DONE 2026-09-18 |
| R13 Keys: Model Finder at the bottom — searches hard for free models and gives the link or search to get a key; a last resort | DONE 2026-09-18 |
| R14 Chat (text and voice): "make a diagram" opens an overlay where Nyx draws or brings in a picture; it can search for and show images; PDFs and drawing work; "diagram of how you work" shows its agents, skills and tech; uses several agents when that helps, at low power | DONE 2026-09-18 |
| R15 Free Will tab: opinions, freer creation, one chat box that can search, improve and do everything, heavily guarded; the first open asks whether to allow it; its agent is "agent decides" | DONE 2026-09-18 |
| R16 Apply tab: a prompt plus files, pictures and links → Nyx applies it to itself (code, new tabs, more), like vibe coding; reads pictures for UI layout; Apple + general design skills; can search | DONE 2026-09-18 |
| R17 Qwen as a provider in Keys | DONE 2026-09-18 |


## Request S — 2026-09-18 ("the big kahuna"; /engineering:architecture) — Identity 0

Owner session: Claude Opus 5 session ai-dev-folder-be, working as the Manager with three Claude Code subagents
(Coder, Reviewer, Trainer = the AI/ML expert). Design record: `docs/adr/ADR-001-identity-0.md`.
Living design + progress doc: `docs/IDENTITY0.md`.

```text
Here is the big kahuna. Name big kahuna, secret/second name is Identity 0. This will be our best addition to the AI. After this make the guithub fully updated and uploaded, we will upload our beta tester link and we will finally get a passsword and username system with google and apple. So before all of that we want our Ai to run flawlessly. At the moment we only have a few APi keys taht work for free. Now we want ollama and the rest to be backups and collaboration. (First a collaboration that should working anyways then the backup for our neural network brain). So Identity 0 is our main brain.  The overall supercore and the Ai model powering it all. changes are run through it, it itself can eb changed. Powerful  and is able to use almost all resources. Basically the replacement for the current brains. Now this is a dev for an AI model. Basically train up, use other model details and data, and more and make a local Ai model. Extremely intelligent, powerful, and able to run everything. Look up mand try to implement parts of AirLLM and all the models we have already imported as a base and build from there. give it data from all things. Feed it google, wikapedia, books,s movies, and more. When it cant figure it out it tries to, collaborates with Ai added, and learns it. Make it hyper intelligent, able to make tabs it thinks and knows the suer needs. Add templetes for every coding, websites and moer. This is a jack of all trades. It will work alongside Ollama at first then detach to work on its own. This is the start for everyone's code. 2 models runing at once to then 1. This model can contact and collaborate with multiple Ai models. Take your time and train, make, and work with the AI. I want to ensure eventually it can have potienal to pass other local and non local models. Please do you best. Save data and progress ina  docs and update with key information for you or anyone else to go off of.
```

Sent during the same session:

```text
For this make as many subagents as needed. I would say make at most 4. 1 Manager who decies and looks at everything, 1 coder, 1 reviewer, and 1 trainer. 1 I would suggest it an expert this is an expert in coding and AI/ML who works alongside the manager and all other agents. Every agent is a master in their field and works perfectly.
By subagents I mean in claude not in Nyx
One thing I prefer is to keep it small so after all this work, please make sure to then shrink the size. But keep capabilities
```

Owner's answers to the session's questions (2026-09-18):
- PyTorch with CUDA in `.venv`: **yes** (installed: torch 2.11.0+cu128, sees the RTX 5080 Laptop GPU, sm_120; plus
  safetensors, tokenizers, gguf).
- Local model: "Too be honest I mean the model that is running locally. If there isnt one download qwen or the one that
  can best help you. I prefer you dont but if later you see you need a bot that isnt there downlaod it. Don't need to
  assk me just do it if you need." → Ollama installed with winget + `qwen3.5:9b` (6.6 GB; text + vision + tools +
  thinking, 256K context) — the only local model on this PC.
- Full-precision base weights for training: **don't download yet** (the training pipeline is built and tested on tiny
  stand-in models until the owner says go).
- Training data: **Safe mix** — Wikipedia, public-domain books (Project Gutenberg), film facts from Wikipedia/Wikidata,
  the owner's own chats, and answers from open-license models (Nemotron, Qwen, DeepSeek, local Ollama). Web/Google
  results are for lookup only, never for training. Never train on OpenAI, Anthropic, Gemini, Kimi or Perplexity
  answers (their terms forbid it; `NYX_MODEL_ROUTINE.md` already made this an accepted constraint).

| Goal | Status |
|---|---|
| S1 Identity 0 ("Big Kahuna") is the main brain: every chat turn goes through it; the other models (Ollama, free API keys) become its collaborators and its backups; a failure inside it never costs the turn | DONE — router provider `identity0`, first in the chain; a failure inside it costs one retry, never the turn |
| S2 Collaboration first: it contacts and works with several AI models at once (solo / race / panel / critique), picking members from what it has learned about each | DONE — members, competence table, panel/shadow/judge |
| S3 "When it can't figure it out it tries, collaborates, and learns it": weak spots are detected, collaborators are brought in, and the result is kept (memory now, training data later) | DONE — shadow + order-swapped judge → lessons in the super brain and training rows |
| S4 Its own neural network: a local model trained here (own PyTorch runtime, LoRA on an open base when the owner allows the download, a from-scratch "nano" seed now) | PARTLY — `nano-v1` trained from scratch and promoted, but weak (0.15 vs teacher 0.90); retraining on a 10× corpus |
| S5 Parts of AirLLM: flat per-layer weight files, load one layer at a time, prefetch the next, block-wise compression, flash attention; only at the highest power, off by default (this is Request P) | DONE — `identity0/model/layered.py` + `quant.py`, only at MAX power |
| S6 Data from everything: Wikipedia, books, films, papers, the web (lookup only), the owner's chats — storage-capped, license-checked | DONE — Safe-mix corpus, 341M characters and growing; web/Google stay lookup-only |
| S7 "2 models running at once, then 1": works alongside the local Ollama model first (twin mode, judged side by side), then graduates domain by domain and detaches to run on its own | DONE — twin stage runs the own model alongside the teacher; graduation is per domain (Wilson bound) |
| S8 Supercore: changes are run through it (it reviews self-changes), and it can itself be changed (its constitution, its weights) — the owner still approves what publishes | DONE — versioned constitution: the owner edits, Big Kahuna may only propose |
| S9 Uses almost all resources when allowed (power modes), without hurting the machine | DONE — jobs run below normal priority; layered mode only at MAX power |
| S10 Makes the tabs it thinks the owner needs (proposals from real usage; create on approval) | DONE — tab planner (proposals; auto-create behind a setting) |
| S11 Templates for every kind of coding, websites and more | DONE — 69 templates |
| S12 An honest scoreboard against other local and online models, so "pass them eventually" is measured, not claimed | DONE — fixed suite, `kahuna/scoreboard.jsonl`; first numbers in `docs/IDENTITY0.md` §5.1 |
| S13 Progress and key information saved in docs for any AI to continue (`docs/IDENTITY0.md`) | DONE — `docs/IDENTITY0.md` (design, contracts, build notes, results, progress log) |
| S14 Shrink the size at the end, keeping every capability | TODO — last step |

Added by the owner on 2026-09-21 (same request, verbatim):

```text
Make big kahuna/identity 0 as the base for everything. High adaption, rprediction, and everything. Prediction on what skills tro use and auto apply. Prediction and adaption to sub agents to use. Predict and create tabs automatically if user switches on in settings. Perfect for trading so it is extremely fast. Best for collaberation so it collaaborates with both local and cloud models for best answer. Aadd a final mopde called ID0 + All. This is basically all I said plus more. It uses active collabvoration, thinks in background, knows and predicts, has its own chat which is where the thinking occurs and can talk to the user even when the main chat is open. Can switch on and off. Similar to a companion. It is highly effective. This model can be used for tab naviagtion and much more. I can say in the voice to open gmaila nd type this email and it can open gmail before I say what to typoe then types extremely fast. Active voice and acvtive listen as i have said before will be extreemely useful so please ensrue it is prioroty
```

| Goal | Status |
|---|---|
| S15 Big Kahuna is the base for everything: high adaptation and prediction | DONE — every turn is planned by it; other features call `identity0/api.py` |
| S16 Predicts which skills a request needs and applies them automatically | DONE — `predict.skills`, learning from 👍/👎 |
| S17 Predicts and adapts which sub-agents to use | DONE — `predict.agents` |
| S18 Predicts and creates tabs automatically when the owner switches that on in Settings | DONE — `auto_tabs` setting |
| S19 Extremely fast for trading | DONE — speed mode: fastest member within 0.08 of the best, no helpers, no reasoning |
| S20 Collaborates with both local and cloud models for the best answer | DONE — local and cloud members together |
| S21 Final mode "ID0 + All": active collaboration, thinks in the background, knows and predicts, its own chat where the thinking happens, talks to the owner even while the main chat is open, on/off switch, a companion; tab navigation; voice like "open Gmail and type this email" opens Gmail before the owner finishes saying what to type, then fills it in extremely fast | DONE — ID0 + All companion window |
| S22 PRIORITY: active voice + active listening | DONE — active voice/listening first: intents on partial speech, actions before the sentence ends |

Queued after Request S, in the owner's order: **T** GitHub fully updated and uploaded → **U** upload the beta-tester link
→ **V** username + password accounts with Google and Apple sign-in.


## Project Null — 2026-09-21 (recorded, NOT started)

Verbatim text and a preparation index: `AI_HANDOFF/PROJECT_NULL.md`. The owner: "make sure this is known as plan null. The
biggest thing we are fixing updating and everything. Do not act on it prepare for it but thats it. Not changes."

## 2026-09-26 (session 1da8a0) — the website, GitHub, the mode switch, Accounts, and future ideas

```text
So I want my site to have a link to github, full over hall and redesign to match the design of the AI now. I would like the Ai to also have a better time for uploading websites or running locally. Then on the site I want there to be a download link for the site next to github. Make sure github is fully updated. Then publish it. Before publishing make sure everything is polished and has no errors.
```

```text
Site as in the website not the AI. https://nyx-ichos-268a6wxcj-shagnikpal-5976s-projects.vercel.app/#install. Also if you could rename it. I would rather just have the AI name in there and add to the github if not already in there
```

```text
Can you aalso finish the redessign for https://nyx-ichos-268a6wxcj-shagnikpal-5976s-projects.vercel.app/#install     and add the things I wanted like the downlaod button and updated everything. Then publish the giuthub
```

```text
After this one change is the normal, co work, and plan things mobve up and down really fast making it hard to clicka nd it wont stop until my mouse is placesd at a specific place, fix this and then update repo. Also add an accounts next to the logout place in the image. In here it locally creates a separaste file division between account if the suer wanst different acocunts for different things. Add a account creation with password if wanted, name of account *user1, NIS, or whastevr the suer weishes) and add a purpose to semi feed the AI to makes urie it knwos why thisaccount si specifal
```

Done (START_HERE.md, 2026-09-26 entries): the site at https://nyx-ichos.vercel.app, the repo pushed, scrubbed and made
public, the switch fix, Accounts. The owner's further ideas, sent in the same conversation, are verbatim in
`AI_HANDOFF/UPDATE_IDEAS.md` — not started.
