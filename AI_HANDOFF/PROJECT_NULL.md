# Project Null — the overhaul. Recorded 2026-09-21, building since 2026-09-22

**This is the handoff document for the overhaul: what is done, what is being built right now and by whom, and what
comes next.** Read this first, then `START_HERE.md` for the detail of each finished request.

Named "plan null" by the owner on 2026-09-21 and renamed **Project Null** on 2026-09-22 at their request. Their own
words below are left exactly as they wrote them.

The owner's instruction that came with it: **"Please after that add this prompt to a file and make sure this is known
as plan null. The biggest thing we are fixing updating and everything. Do not act on it prepare for it but thats it.
Not changes."**

It was recorded as prepare-only during Request S (Identity 0). On 2026-09-22 the owner handed parts of it to several
Claude sessions at once, so most of it is now being built — see below. Anything not claimed by a session is still
prepare-only until the owner says to start it.

## Where it stands (updated 2026-09-22)

### Done

| What | Where it is written up |
|---|---|
| **Request R** (all 17 items): Data Absorption / Data Analysis, Data Process Use, line counts on every edit, local models + Model Finder in Keys, diagram and picture overlay, hands-free active talk, Screen Share, Apply, Free Will, Qwen provider. This is **N26**, which was a repeat of R | `START_HERE.md` § Request R; `01_GOALS.md` § Request R |
| **Request J**: model fallbacks, the review queue that actually implements, deep & specific mode, agents as `/commands`, auto sub-agent matching, the Core view. This is **N27**, a repeat of J | `START_HERE.md` § Request J |
| **Request S** (Identity 0 / Big Kahuna), most of it: router provider first in the chain, its own model + trainer + layered mode, Safe-mix corpus, tab planner, templates, scoreboard, predictions, companion, voice fast path | `docs/IDENTITY0.md`, `START_HERE.md` § Request S |
| Requests G, H (except H4/H5), I, K, Q | `START_HERE.md` |
| **N23 / N87** partly: every console launch in `local_models.py` (ollama create, winget, ollama serve) and `apply_engine.py` (npm build) already runs with `CREATE_NO_WINDOW`. be872d is doing the rest of the audit | this file, row N87 |

### Being built right now (2026-09-22, one owner, seven Claude sessions)

| Session | Rows | What |
|---|---|---|
| **fc578b** EngineRun mode | N29–N39 | EngineRun background modes, auto-delete of old files, connectors (+ bar, by chat, auto use, `&name`), chat bottom bar (Skills · Agents · Connectors) |
| **c69db1** tab redesign | N40–N49 | Start-up animation, the Redesign tab, Design Training, the "Overall" restyle |
| **6cc61a** office space | N8, N50–N59 | Office Space: offices of many agents, hierarchy, focus mode, office files and folders |
| **66c5db** auto agents + connectors | N9, N10, N70–N79 | Auto sub-agent selection, daily agent grading, the connectors grid and catalog |
| **be872d** finance + chat modes | N19b, N80–N89 | Trading run modes, practice vs real money, chat mode slider (Normal · Co-work · Plan), question cards, clap wake, quiet console windows, design sense, Notes slides |
| **dc471e** voice + site | N11–N19, numbered N90–N110 | Voice rework, Proto Voice, site download button + 404, drag-and-drop + malicious-file checks, pasted pictures, the Screen Share IDE with two screens and its own cursor, feature catalog, the caret bug, clickable links, Curiosity inside Free Will, finance lab. Owns `screen_share.py`, `routes_screen.py`, `panels/screen/**`, `freewill.py`, `routes_freewill.py`, `panels/freewill/**`, `ActiveTalk.tsx` since 2026-09-22 |
| **c29bdc** Identity 0 | Request S | The main brain; its nano training run finishes the remaining S items |
| **6bd7de** second brain + file checks | N27 (built 2026-09-16), N94 | Request J's tabs, gauges, sub-agents, review queue, deep mode and Core view; Requests K, L (backend), Q. On 2026-09-23 the owner asked this session for malicious-file checks, which is **N94** — now done. Owns `file_guard.py`, `routes_security.py`, `context_budget.py`, `ContextBar.tsx`, `research_engine.py`, `routes_research.py`, `improve_review.py`, `improve_deep.py`, `agent_dispatch.py`, `beta_collab.py`, `routes_collab.py`, `site/api/**` |
| **c36c1d** AAI trader | *owner requests, not Project Null rows* | Optimization, a $50-style practice start, diversification and sizing (no all-in on one stock), learning from wrong signals and losing trades, an **auto stock adder** (researches and adds stocks doing well or predicted to), and **Adaptive mode** (one button, hands-off: it chooses budget, sizing, stops, pace and stocks every scan, no daily trade limit; the owner can only Halt or Stop; optional on/off schedule). Owns `trading/allocator.py`, `trading/adaptive.py`, `trading/discovery.py`, `trading/lessons.py`, `trading/signals.py`, `trading/guard.py`, and since 2026-09-24 `trading/autopilot.py` (handed over by be872d with N80 done), `panels/trading/AdaptiveCard.tsx`, and the adaptive/discover routes + chat tools in `routes_trading.py`. be872d keeps `market.py`, `brokers.py` |

Each session lists the files it owns in its own section below. Shared files take small insertions only, and the owner's
running engine on port 8000 is not restarted by anyone without saying so first.

### Next, not started by anyone yet

1. **N1** Super control + voice: the hands-off black bar on every screen that acts while the owner is still speaking.
2. **N2** Email will not send after the address was added — diagnose first (app password or Google sign-in).
3. **N3** Delete-chat button (the route already exists; this is UI only).
4. **N4** The access part so the owner can ship changes, and GitHub fully working and published (also Requests T and U).
5. **N5** Super Work tab: spreadsheets, docs, Excel, finance and office work, Google Calendar, more connectors.
6. **N6** Use a browser tab in the background while the owner works in another.
7. **N7** Study the repos and prompt libraries the owner linked, for improvements.
8. **N16** The caret bug (owner: only if small), **N28** "Add a model" says a chat-completions URL but it cannot be used.
9. **Request L, the Research tab UI** — half-landed and unowned. `panels/research/ResearchPanel.tsx`, `types.ts` and
   `save.ts` exist; `JobView.tsx` and `PapersView.tsx` were missing and broke `tsc -b` for every session until
   2026-09-24, when they were replaced by clearly-marked placeholders. `research.css` is still missing, and the tab is
   not registered in `tabs.ts`/`App.tsx`. Whoever takes L should replace both placeholders and add the stylesheet.
10. Older unfinished goals: **H4** Build tab, **H5** Game Studio, **M** 3D model centre job,
   **O** freer tab creation, **P** local models of any size, **G2** Settings → Updates, **T** GitHub push,
   **U** beta-tester link, **V** accounts with Google and Apple sign-in.
10. **S14** shrink the disk size — the last step of Identity 0.

### How to keep this page true

When a row is finished, move it into **Done** with a one-line pointer to where it is written up, and take it out of
the session's table if that session is finished. When the owner sends more, add the verbatim text in a new dated
section and give the rows numbers in your own range.

## The owner's words (verbatim)

```text
Please after that add this prompt to a file adn make sure this is known as plan null. The biggest thing we are fixing updatinga nd everything. Do not act on it prepare for it but thats it. Not changes

Add an access called super control + voice. BAasically what happens where is everything goes to hands ogff mode. Simialr to how Jev works a black bar with rounded edgees apears on the screen (can be both or multiple screens)  and what I say appears. In here I am able to tell the AI what I want and it doews it flawlessly. As I say open notes it opens and begins typing what i say. It uses prediction and active listening to make sure it opens before I stop speaking. This is where local AI comes it. Combin ding jev and our local AI infrastructure will be perfect for this task and will ensure that it works perfectly fine. https://github.com/jaredpalmer/kev. 


I added my email yet it wont send emails. fix


Add deleting chats since there is no button

Add the access part since I am unable to ship changes. Also amek sure the github fully works and is publisheed


New tab called Super work. Mainly for work based things. Spread sheets, docs, excel, and such. Finance and office based work is done here. Add to Google calander. Needs connectors for. This. For this to work the best allow more connectors. If I wanted to add a new connector not listed I can and after a couple minutes it generates what k need to paste like app, link, password and username. 





Can open a tab and can then use it. Even without it having to click and open it. So if I have instagram open on one tab it can scroll through it while in a separate tab (google, safari, and edge ex)I do some other work. This is to come to screen share and normal chat. 







Use this github for further improvement  https://github.com/affaan-m/ECC 

https://github.com/pipecat-ai/pipecat 

https://aipromptlibrary.org/
https://github.com/x1xhlol/system-prompts-and-models-of-ai-tools
https://github.com/topics/system-prompts?l=typescript



Add a tab called office space. In here it can range from 10 to hundreds of agents depending on task and computer ability. In here each agent is represented. It started by asking if they can shut everything down and only run this tab. After the tab finishes everything else resumes automatically. In here it has a office space each a agent with its own task. You can give a large task and watch as they work. An agent can delicate tasks to existing agents or bring in new agents. Multiple models (basically all of them) are used here and each agent uses one. Collaboration is the max efficiency. It fully remembers things form previous sessions. Make a big text box which is where the main chat occurs. This is given to a main manger who then communicates with all agents. In here there is a pseudo hierarchy system where it goes from top manager, to smaller managers of different infrastructure to an final team of agents who have their own systems. These systems grow as you give more tasks. Identity 0 helps here heavily and if there are any other local agents they help as well. Each time can have coders, organizers, and more. Basically taking everything in sub agents and duplicating as needed. If a new section with a manager is needed it can be made and is generated in front of the user. Sections can communicate via managers primarily, normal workers, or they cna bring in agents specifically for communication where they talk to the specific agent they want to. This is a huge project and also add a second chat box where i can either click to select or say (in the chat which agent group or which agents like only the front end design, coder agents in every group, managers, manger of this one group, top manager, optimizers of all groups, optimizers of only these specific groups. These are all just examples and should have more freedom of who I refer to), or a section on top I can scroll and click 1 or more boxes which represent sections, I can talk double click a section and deselect or select a single or multiple agents of that group. This should update automatically and grow as the user watches or as the work increases. For massive projects to small projects. If a new type of agent is to be made it is added to the sub agents and added to the section or the entire group for the place start wnat it. If it seems that too many agents are being  added or new types of agents are made (say 10 at this point) add a agent (create this as a separate agent class that can only be spawned in this case) where requests are given to it (these requests being the creation or bringing in of a subagent to a section) and it decides if it should be done. Using a new skill mainly for it called crit think which thinks if it is useful. In this agent, the agents/sub agents that want to add a new agent give the agent they want (new or clone) and why they need it, and long term use. On the bottom also add the same type of box system where I can see each section, double click to see what’s in each and it can also be used to select and send certain messages to a section or bot or certain types of bots just like in the chat box as I said. In the windows I can also have it halt or pause. For the first project it creates a file and opens the chat instantly. Then in the next time I open it after it’s fully stopped, it has a new layout where I can see past projects and click on the file, I can also click a button to open in file explorer. In this page I can also say create a new project and it does the same thing and has its own file for that. In here I can also make empty folders which I can then drag and drop projects if that’s re for the same work flow. If in the same folder I can click a button on the side that says link work flows so memory and work is linked. Each section, agent type is color coded. The section has its own unique color while the agent changes the head color or the symbol on there. 

In addition in the office layout add a way to open a side bar which shows the other files and folders. Also let’s rename one part, folders/files hold the single office. Folders/mega folders can hold multiple offices and can drag and drop office files. Empty folders/mega folders can have a button where I add a new office session. I can also create folders in folders just like in windows. Just work on the naming. 



Here is what it was based on but don’t recreate the exact design and create using my prompt, this is just for reference and clarity since it is a similar but not as focused verison of mine:
https://munderdiffl.in/ 
https://github.com/netj/markdown-diff/blob/master/README.md.in 





Add auto sub agent and agent selection as an option in settings for nyx chat, and every other chat. Then run a program everyday at one point which the user can decide where it grades each agent on use, and where it is used as well as which agent and uses that data to select the sub agents used automatically, what information to feed it since when it is added it should be given unique context for each one, and which model and key to use. Make the default as on for auto agents and everyday at 12 am or when the AAI is first turned on in a day as when it does grading. Also add a box for what day or days to do this for.



Update the connectors and make in the format of the photo and add as many as possible, Gmail, mail, docs, sheets, excel, Microsoft apps, vercel, and more. Basically all the things Claude and ChatGPT can use as their connectors. 

Next improve the voice. So basically activated and talk as it talks as the user says and can singly think as the user speaks so by the end it ids the fact they stopped with that pause and can instantly talk. Also when activating voice make the side panel a bit smaller. Then the ai talks. In here as I talk it listens and thinks of how to answer and then instantly responds. As it talks it also listens. Make sure it doesn’t pick up its own voice. Use a separate model for voice, text, listening, and active listening as well a interpretation. 

Update the normal site and add a download button where you can actually add the zip file or the uncompressed file and the user clicks and it downloads. For this add an animation where as you hover over the button it fills to half and when you click it changes from saying download with the download symbol to the downloading and the rest of the button fills as the download percent goes up. Then add a custom 404 page. Update the website ui and add in things like how the second brain tabs look. 

For the voice add another slider or part of the voice listening and talking where it is called proto voice. It always listens as allows the ai to understand and do things just better. This model allows it to turn on, off the computer and itself, can navigate the computer and the app itself by saying open files or open this tab in nyx. It allows it to turn the computer on from lock if you give it the password though that can be a secondary. Maybe it can also add sub agents to its chat and it acts as the manager giving every command. It can do simulations. Basically free will but with voice. Also for files I want a way to drag and drop it so even if I don’t click on it I can drag it, the site ids that it’s a file, the pulls up the file drop box. In addition, add file checks to make sure no one can add faulty or malicious stuff. 

Allow for copy paste of pictures where it uploads as a file though shows the picture so the user knows which one it is. When screen sharing or the ai using something on screen, using keyboard (make sure it can do this) and mouse make sure it also has the ability to talk. For the screen share add a file more powerful and free will based ide where it can access everything and I don’t have to say do it everytime. I can say make a file code it, and open it for me. And it will do it. Also just to make sure, it should have its own cursor and keyboard so whatever I do shouldn’t affect what it’s doing. So I can work on one screens fit on the other. Also allow screen share to two screens. Just make it so I can also choose the orientation of the screens just like in windows settings. 

In the nyx chat tab for the background processes update it so that it can also see background processes for everything g new. At times it doesn’t know about the new features and make sure it actively searches and sees. Add all features running to a file or a catalog and it reads form there as well as how much is being used. 

Fix this one issue where when I click on any word it has the the blinking line similar to when typing in docs but I can’t type. If you can fix this but if too big of a overall you don’t need to. 

When pasting links I would like the link to be highlighted in the blue purple color so I know it works. Also I should be able to click on the link I paste and take it to the site which opens in a new tab. Also when the ai gives me a link or add a feature where I can say give me the link to this or in citations or when I as it to research or when I ask a general question and it’s citations or proof is shown I wnat those links to be click and as well.  Data absorption, understanding, and training for AI. How Artificial Intelligence can learn not only from its users and chat history but also gain the ability to be curious and learn more. Search and add a third mind  or curiousity machine. An improvment on the free will device tab but in a new way to the AI. This includes curiosity, how it wants to learn, and adds feelings and understanding. And owns up to mistakes while having curiosity to learn more. This shouldn't fully affect chats, but it keeps questions and new ideas and files them. This is an extension of free will and will have a tab in the free will tab that shows its growth, understanding, and wants in its lifetime.

Use this second photo and add to finance and trading agent. Back ally each node lights up as it gets used. Build a new system so for this since most ai need the usage limits while a local ai and a few unlimited use ai are needed make sure to make a new one basically local with search so it can predict changes and plot properly. Make sure there is a don’t go broke situation where it tries to not go into debt if taht is even possible and make sure it know all strategies and also doesn’t spend more money than allocated. Essentially it can only access the money it has and the money it earns to make more money. If it dial it needs to lean. Add a finance memory simulator and feature so it trains and then does that. For high finance use it should have a warning and turn off all other features as and keep only the finance if memory allocated to fisnce it very high. Also make sure if it does use an api and a non local as a collab or as a backup or just as the main make sure it has either reinforce like qwen or has enough use to the point where it wouldn’t matter over the course of use. 
For the finance allow a mode for active 24/7 or until stop so the user doesnt ahve to manually start when US markets open. Make the simulation where it sues fake money andd not real money (the current default) a bit better, just make it clear which oen is real and fake.
Make a new slider at the bottom of the chat. Here there are 3 different types. 1 is for normal where it chats and make sure thecc bc hat is better and faster. As it thinks it can talk and list it out as it thinks it. Basically just much faster. 2. Co work is basically the same to Claude cowork where it works at the same time and works in the background. 3. Is plan mode. In here it first makes a script/spec list and makes questions and makes a scheme and ask the user to check it. After the user approves or adds more it cornfields and starts working. Basically a better confirm. 


Also add questions that the user can click and send to the ai so the ai basically makes a question and a list of answers and what each means as well as a box for typing if the user had a different approach they thought of. 

Add a feature to voice where if offline or away or when using the background voice I said earlier please ensure it has a feature called clap. In here we can tell the AI a certain gesture like clapping, whistling, a phrase, or something more which the AI responds to and talks back. When first turning the voccie on, regardless of mode have it syas, NYX here. And say something like the sounds are starting or something. Not so corny as the one I said but similar. 

Final part, make sure that when a cmd opens, try to fix it so it doesnt interrupt me or just dont have it open at all and instead opens but doesn't affect my ability to type

Last thing to do is feel all ui, past ui decision, how ui updates, how apple and most software companies design ui, how ai interpret prompts for front end design and how it should respond. It should also have no default design. It should allow for extremely free interetstipn. It should have almost all permissions on so it can search, look at other tabs, understand exactly what the user wants, and use outline ai models to design it. 

In notes add an upload place so if I upload slides it can make detailed notes, quizzes, Flashcards, questions for specific parts, and has a text box where I can say to generate a specific study tool. 





















Create a new tab called data absoeption/trianjng. In here it will basically just train itself and make itself smarter on all levels to the ollama model is smarter and all models are also smarter use the image as referenced for how it looks. The user can actively see as the at sorts through it. 2 modes 1 for the ai auto doing it and the user sees it pull up the document (papers, GitHub’s, anything and everything for high data collection keep in mind it shouldn’t take too much storage on a computer). And the second option is the user uploads the document or documents or a link or a few links or a combo of booth and the ai only looks through that. A third option is that it is given a specific prompt of what to search for and it goes off to specifically train on that. At the end or when I stop it, it will say what it leaned, what it added to itself like skills or agents or agent feature or faster things and will be done and can be relayed for different or same things for further study. Different from the improve tab but similar features. Try to copy the aesthetic from below. As seen below the ai highlights yeh words and a curved line goes form the high light to the specific topic list and a bar fills up as it does that. On the right the user can select which broad ropic the ai is studying since the ai studies multiple topics and multiple papers at once. Now the first 3 modes I talked about are in one mode called data analysis. This is what the image mainly has and copy format and what it shows. In a second overall topic will be called data process use. In this I can tell it to analyze data like a resume or group of resume or a code or spread sheet or whatever and it will be able to looks that and using its data analyze features explain what’s in it, sort, or do whatever the user wants. Put a lot of effort into what the ai can do with this it is very free range. Even financial analyzers can use this. Also the ai can suggest changes it can make to itself based on documents and only the user can approve. Make sure each big idea is condensed into separate boxes which can be expanded to see what is in there and the user approves. Also for both coding and improve make it so that when its working and editing field and I tell it a specific prompt to approve an improve or whatever it is make it so that it shows how many lien are affected and in which file. 

Another tab will be screen share so it views a persons screen and can help them using its cursor and typing. It works with the user and at its pace. This will mainly us ollama but it will be helpful for coding or more  sheets and such for finance could be a good use. Don’t allow it to have too mc control and instead just work properly. 


Now a more update feature should be for voice. For voice I want to add active talk so as I talk instead of saying send it just auto sends to the ai so it’s an active chat. You can hear as the ai thinks and works. It should be a faster model so maybe the local ollama model. In keys also add a way to add local models so basically it’s another part where if I have a download I click on it and it adds to the overall model. 






Add a model finder. It searches extremely hard to find more models for free and gives the link or search so the user can find and api key for it. Put this specifically in the key tab on the bottom. Last resort kind of thing. 

In the main tab, make it so that in both the text and the voice modes I can ask it to say make a fiagrms and a new tab opens as an overlay and it can draw or pull from an image which chaos sit. It can search and show an image. In the chat when i ask it to upload and image it a diagram or anything like it it has the ability to and and show it. Make sure it’s pdf and drawing is available and works. A command example is to show me a diagram of how you, the ai works and it shows me a diagram of its base agents, the other agebts it uses and uses design tricks and skills and tech to make it. Make sure this uses multiple agents at times for best experience yet least power use so it stays efficient and doesn’t force a crash. 

Make a tab called free will on here it gains opinions and more. Much more free and alive. Less restrictions on how it draws and crates. It can make anything here. A single chat box and it can search, improve, and everything. A basic combo do all things but highly guarded. Opening it the first time asks if you allow this bot to exist and it doesn’t age a specific agent and sets to agent decides. 

Add a apply tab and in this it is basically just a way to prompt the ai and also upload field, pictures m, and such so that the ai then follows it and applies to itself. In this tab what happens is basically improving the ai in changing its code, adding tabs, and more. Somali to vibe coding which I am doing now. It can use images to understand ui format. It uses apple and normal design skills together. Can search.  and more. 


Allow me to add qwen as a provider in key if not already done. 











Make a third tab in second brain and add usage gauges for each process, all agents, api, and such being used. Show sub agents and a way to run in from there and a way to dev and drop into a single project or press a plus to add them.  Ai should now auto use the sub agent it needs without me having to manually do this. Can make sub agents by itself and add to the sub agent tab as well as that third tab I just say. In third tab add what the image looks like that I attached. 


This should be clean and aesthetic. 

In improve tab add a place where I can approve or deny change s. Make a mode to analyze all in review or changes and then approve or ddeny and apply. Do this in the improve tab

Also when I want to add sub agents another rah is through / commands so basically when I make a sub agent or there is one the ai makes it also adds its name to / commands so that I can say /coder and it pulls up the coder agent and in [] I add how many of that agent to be made. Also when using the drag drop method or when the ai calls on it for specific situations it has a box or a place to say how many I want or I can drag a second one and it will show a second box. In each I can say what u want each to specifically do if I have different tasks.   Also in approve it tell it tro approve and auto check and whatnot but still doesnt, please ssee and amkew sure it can research, then appreoave on its own. Check this mplement approved changes Off = approve only; the code is left for you. Option since I cant tell if kit works correctly or nmot. In improve allow a deep and specific mode, clicking this shows a big box and I can paste or write specific improvements and such and it auto generates the time it thinks it will take and can increerate if needed. 

In add model it says chat completions url but I cant use it, please check and fix
```

## Preparation index (what each item is, and what already exists to build on)

Status for every row: **NOT STARTED — waiting for the owner's go.** Items marked *(already asked before)* repeat an
earlier request that was built; Project Null means re-checking and improving them, not re-building.

| # | Item | Builds on (exists today) | Notes for whoever starts |
|---|---|---|---|
| N1 | "Super control + voice": hands-off mode; a black rounded bar on every screen showing what the owner says; "open notes" opens and starts typing before they stop talking | `identity0/companion.py` intents (early actions on partial speech), `components/chat/ActiveTalk.tsx`, `cursor_overlay.py` (multi-monitor overlay), `computer_control.py` | Reference named "Jev" but the link is github.com/jaredpalmer/kev — check which one the owner means |
| N2 | Email "won't send" after adding the address — bug | `email_client.py`, `routes_email.py` (SMTP → Outlook COM → draft fallback), Keys → Email | Probably needs an app password or Google sign-in (`google_oauth.py`, never tried with a real client) — diagnose first |
| N3 | Delete-chat button | `DELETE /api/chats/{id}` exists (`routes_live.py`); `ChatSwitcher.tsx`, `ChatActions.tsx` | UI only |
| N4 | "The access part" so the owner can ship changes; GitHub fully working and published | `access_keys.py`, `routes_access.py`, `beta_collab.py`, `docs/COLLAB_SETUP.md`, `change_review.py` | Overlaps Requests T/U (GitHub, beta link) |
| N5 | "Super Work" tab: spreadsheets, docs, Excel, finance/office work, add to Google Calendar; more connectors; generate what a new custom connector needs (app, link, username, password) | `data_tables.py`, `data_process.py`, `connectors/`, `google_oauth.py` | Credentials are typed by the owner, never by Nyx |
| N6 | Use a browser tab in the background (scroll Instagram in one tab while the owner works in another) — for Screen Share and chat | `screen_share.py` (PrintWindow window capture), `computer_control.py` | Needs its own browser session (e.g. CDP), not the owner's mouse |
| N7 | Study for improvements: github.com/affaan-m/ECC, github.com/pipecat-ai/pipecat, aipromptlibrary.org, github.com/x1xhlol/system-prompts-and-models-of-ai-tools, GitHub topic "system-prompts" (TypeScript) | `research_engine.py`, `absorb_engine.py` | Read-only research; check licenses before copying any prompt text |
| N8 | "Office Space" tab: 10–hundreds of agents, hierarchy (top manager → section managers → teams), asks to pause everything else and resumes it after, big main chat + a targeting chat (sections/roles/agents by click or by words), sections bar top and bottom, halt/pause, projects saved as files, office files / folders / mega folders with drag and drop, "link work flows", color per section and per agent type, a gatekeeper agent class with a "crit think" skill that approves new agent types after ~10 | `agent_dispatch.py` (parallel copies), `agent_runtime.py`, `agent_match.py`, `components/brain/AgentCity.tsx`, `resource_governor.py`, `identity0/` (Big Kahuna helps heavily) | References for clarity only (don't copy): munderdiffl.in, github.com/netj/markdown-diff |
| N9 | Auto sub-agent + agent selection setting (default ON) in every chat; a daily grading run (default 12 am or the first start of the day; pick days) that grades agents and picks context, model and key per agent | `agent_match.py`, `identity0/predict.py` (learned weights), `identity0/competence.py`, `improve_autopilot.py` (scheduling pattern) | |
| N10 | Connectors page in the format of the owner's photo, with as many as possible (Gmail, mail, Docs, Sheets, Excel, Microsoft apps, Vercel… "all the things Claude and ChatGPT can use") | `connectors/registry.py`, Connectors tab | The photo was not attached to this message — ask for it |
| N11 | Voice: think while the owner talks, answer instantly at the pause, listen while talking, never hear itself, separate models for voice/text/listening/active listening/interpretation, smaller side panel while voice is on | `ActiveTalk.tsx` (echo filter, barge-in), `model_roles.py`, `identity0` speed mode | |
| N12 | Website: real download button (zip or folder) with the half-fill hover and fill-with-progress click animation, custom 404, UI like the Second Brain tabs | `site/` | Never link `site/downloads` from a public page without the owner (START_HERE rule) |
| N13 | "Proto voice": always listening; turn the PC/itself on and off, navigate the PC and the app, unlock with a password (secondary), manage sub-agents by voice, simulations — "free will but with voice"; drag-and-drop files anywhere with a drop box; malicious-file checks | `freewill.py` (guard), `computer_control.py`, `uploads.py` | Unlocking with a password = the owner types it; Nyx never stores or types passwords |
| N14 | Paste pictures (upload + preview); talk while using keyboard/mouse; a more powerful Screen Share IDE ("make a file, code it, open it"); its own cursor and keyboard independent of the owner's; two-screen sharing with orientation choice | `screen_share.py`, `computer_control.py`, `cursor_overlay.py`, `code_workspace.py` | A truly separate cursor needs a second input session (VM/remote desktop) — research first |
| N15 | Nyx chat background processes see every new feature; a feature catalog file with usage it reads from | `routes_core.py` (Core view processes), `handoff_tools.py`, `turn_registry.py` | |
| N16 | Bug: clicking any word shows a text caret but nothing can be typed | frontend CSS (`caret-color`, `user-select`, `contenteditable`) | Owner: fix only if small |
| N17 | Pasted links highlighted blue-purple and clickable (new tab); links from the AI, citations and research clickable | `components/chat/Markdown.tsx`, `sources.py` | |
| N18 | "Third mind" / curiosity machine: curiosity, wants, feelings, owning mistakes; files questions and ideas; a tab inside Free Will showing its growth | `freewill.py` (opinions), `super_brain.py` | |
| N19 | Finance/trading: the owner's second photo (nodes light up as used); local-first unlimited system with search for prediction and plotting; "don't go broke" (never spends more than allocated; only its own money and earnings); finance memory simulator; high-finance warning mode that switches everything else off; 24/7 or until-stopped mode; clearer paper vs real money | `trading/` (paper simulator default, guard, budgets, autopilot), `identity0` trading speed path | Photo not attached to this message — ask |
| N20 | Chat mode slider: Normal (faster, talks while thinking), Co-work (works in the background like Claude Cowork), Plan (spec + questions + scheme → owner approves → works) | `turn_advice.py`, `ChatPanel.tsx`, `Composer.tsx` | |
| N21 | Clickable question cards (AI writes a question, answer options with what each means, plus a free-text box) | chat renderer | |
| N22 | Voice "clap": a gesture (clap, whistle, phrase) wakes it; on start it says a short greeting like "Nyx here — listening" | `ActiveTalk.tsx`, `tts.py` | Detecting claps needs audio analysis in the browser (Web Audio) |
| N23 | Console windows (cmd) must never steal focus or interrupt typing | `machine_tools.py`, `subprocess` calls (`CREATE_NO_WINDOW`), `launcher.py` | Audit every `Popen` |
| N24 | Front-end design sense: learn from past UI decisions and how Apple and others design; no default design; very free interpretation; broad permissions to research and look at other tabs | `skills/apple-design/`, `tab_editor.py`, `spec_ai.py`, `panels/DynamicTab.tsx` | |
| N25 | Notes: upload slides → detailed notes, quizzes, flashcards, questions per part, and a box to ask for a specific study tool | `notes_store.py`, `study_tools.py`, `panels/notes/` | |
| N26 | Repeats of Request R (Data Absorption, Screen Share, active talk, local models in Keys, Model Finder, diagrams, Free Will, Apply, Qwen) *(already asked before)* | all built 2026-09-17/18 (`01_GOALS.md` § Request R) | Re-verify and improve |
| N27 | Repeats of Request J (third Second Brain tab with gauges + sub-agents, auto sub-agents, review/approve in Improve, `/coder [n]` copies, research-then-approve, deep & specific mode) *(already asked before)* | built 2026-09-16 (`01_GOALS.md` § Request J) | Owner still can't tell whether "Implement approved changes" works — verify live |
| N28 | Bug: "Add a model" says chat-completions URL but it can't be used | `routes_key_pool.py` custom models, `panels/KeyPoolSections.tsx` | Diagnose first |

## Added 2026-09-22 (session fc578b "Startup animation and EngineRun mode") — rows N29–N39, STARTED

The owner sent this to several sessions at once and said "start working on this part", so these rows are being built
now. Row ranges agreed between the sessions so nobody collides: **fc578b N29–N39 · c69db1 (tab redesign) N40–N49 ·
6cc61a (Office Space) N50–N59 · data-absorption session N60+.** Re-read this file right before every edit.

```text
Add a start up animation. Using file for plan null add this to the bottom of the list and start working on this part. Coordinate with the other against working on this to ensure you dont overlap and each parts works efficiently together.




 Also add auto delete old or useless files.  In settings add a fully optimized  mode called EngineRun. In here everything runs in  background adn leaRNS, ABSORPTION WORKS By itself, improve as well, and it seeks knowledge by itself. Add a way to add connections both by a + with a bar with premade ones that are common with ai models and a chat to tell the ai what to add cans it will check and add it for you if you give it what it needs. Like if it needs an Api and model but only model is given it can make it and say to give a api and the user can then send it to then add that connector. Also in all chats and tabs add auto connector access as well as in settings so the ai can both auto apart and predict which connectors are needed if user doesn’t say and if the user does say let’s have connectors be called while typing &(connector name) and let’s add a bottom bar to the chat which has 3 things, skills, agents/subagents, and connectors where after I click one I can click auto which is default for all of them and auto selects, one of the agents
/connectors/skills (one click to select and one to deselect and you can choose which ever you like) for agents it creates two options auto interpret and send an individual message through a main agent who decoders and is able to organize and determine what to send each agent specifically or normal option where each agent is given the same prompt and knows they can communicate.
```

Who owns what (agreed with the other sessions on 2026-09-22): the start-up animation → **c69db1**; the connector
catalog (150+ entries) and the Connectors tab tile grid (N10) → **66c5db**; everything else below → **fc578b**.

| # | Item | Builds on (exists today) | Owner / notes |
|---|---|---|---|
| N29 | Start-up animation | `EngineGate.tsx`, `index.html`, `main.tsx` | **c69db1** builds it (see their N40+ rows); must read the theme variables so a Redesign can restyle it |
| N30 | Auto-delete old or useless files (on its own, no clicks) | `storage_budget.py` (caps + daily run), Settings → Storage | fc578b. Only Nyx-made caches, temp files, stale build files and old job records. Never chats, memories, uploads, notes or anything the owner made; big leftovers stay owner-confirmed |
| N31 | Settings → **EngineRun**: a fully optimized mode where everything runs in the background — it learns, Data Absorption runs by itself, Improve runs by itself, it seeks knowledge by itself | `improve_autopilot.py`, `absorb_engine.ENGINE` (auto/prompt runs), `research_engine.py`, `super_brain.py`, `predictor.py` idle scheduler, `resource_governor.py`, `presence.py` | fc578b. New `engine_run.py` + `background_jobs.py` (one place that knows every background job; `pause_all/resume/status` is also what Office Space's focus mode calls) |
| N32 | Add connections with a **+** and a bar of premade connectors common to AI assistants | 66c5db's `connectors/catalog.py` | fc578b: `components/connectors/AddConnectorSheet.tsx` (the + bar, a form per connector, secrets in masked boxes → `secret_store` only) |
| N33 | Add a connector by chat: tell the AI what to add; it checks what is needed, fills what it can and asks for the rest (e.g. model given, no API key → it asks for the key), then adds it once the owner sends it | `key_pool.py` custom models, `routes_models.py` keys, `provider_specs.py` | fc578b: `connector_builder.py`. Secrets are taken out of the text on this computer before any model sees it and never land in a chat transcript |
| N34 | Auto connector access in every chat and tab and in Settings: when the owner doesn't name one, the AI predicts which connectors a request needs and uses them | `turn_runner.py`, `connectors/registry.py` | fc578b: `connector_use.py` (per-turn pick + a `use_connector` tool) |
| N35 | Typing **&name** calls that connector | `Composer.tsx` (`@` agents, `/` commands already work the same way) | fc578b |
| N36 | Chat bottom bar with three pickers — **Skills · Agents/sub-agents · Connectors**; **Auto** is the default for each; one click selects, a second click deselects; pick as many as you like | `skills.py`, `agent_runtime.py`, `agent_match.py` | fc578b: `components/chat/ChatToolbar.tsx`; shares the row under the composer with be872d's mode slider (N20) |
| N37 | Agents picked by hand run one of two ways: **Auto interpret** (one message goes to a main agent who decodes it and decides what to send each agent) or **Normal** (every agent gets the same prompt and knows it can talk to the others) | `agent_dispatch.py` (parallel copies that already see each other's parts), `consult.py` | fc578b |

## Added 2026-09-22 (session c69db1 "Startup animation and tab redesign") — rows N40–N49, STARTED

The owner's new words to this session (verbatim). The same message then repeated N1–N7 above word for word; this
session builds **N1–N7** as well.

```text
Add a start up animation. Using file for plan null add this to the bottom of the list and start working on this part. Coordinate with the other against working on this to ensure you dont overlap and each parts works efficiently together.
Redesign tab so I can redesign the main tabs that I can’t edit/chat. I can copy paste images in chat (also allow his for everything. If I snip I want to be able to copy paste into chat. For this feature also allow me to have the file upload. Skills usage. Give it multiple templates. Also add a tab for training where i can add templates and other website. Also add a section called overall where it takes a while, can upload things and sites, it studies them, allows for skill maker to make tabs look similar and then it does a full overhaul and every tab.m both the normal default as well  as they user created ones are changed to fit the new style. Can merge with the edit tab tab we have. 
```

| # | Item | Builds on (exists today) | Owner / notes |
|---|---|---|---|
| N40 | Start-up animation | `components/EngineGate.tsx`, `index.html`, `main.tsx` | **c69db1** (agreed with fc578b, 6cc61a, 66c5db). Reads the theme variables so a Redesign can restyle it |
| N41 | **Redesign** tab: redesign the built-in tabs (the ones that can't be edited or chatted with today); several templates; uses skills | `dynamic_tabs.py` (look spec), `tab_editor.py`, `panels/tabs/TabLook.tsx`, `skills.py`, `skills/apple-design/` | c69db1. Built-in tabs are React code, so a redesign is a validated **look spec** (colours, surfaces, font, radius, background, density) applied as CSS variables on the tab's wrapper. It is data, never generated code (AGENTS.md invariant 2) |
| N42 | Paste pictures and Windows snips in chat and everywhere, plus file upload | `uploads.py`, `Composer.tsx` | Built by **dc471e** with N13/N14 (`src/files/fileIntake.ts`); the Redesign tab uses it |
| N43 | Redesign → **Training**: add templates and websites for Nyx to learn a look from | `absorb_sources.py` (read-only fetch), `image_check` model role | c69db1 |
| N44 | Redesign → **Overall**: a long job. Upload things and sites; it studies them; the skill maker writes a style skill so tabs look alike; then a full overhaul restyles every tab (built-in and owner-made) to the new style. Merged with the existing tab editor | `skills.py`, be872d's `design_sense.py` (N24), `dynamic_tabs.py` | c69db1. Nothing changes until the owner presses Apply; one click restores the previous look |

Status notes from c69db1 on N1–N7:
- **N2 root cause (fixed 2026-09-22):** the owner's Gmail app password was saved and valid. Short requests ("can you
  send me an email?") took the tool-less fast path, and the model there answered "I cannot send emails".
  `fast_response.py` now sends any action word (email, calendar, remind, tab, note…) to the full pipeline, and a
  fast reply that claims it can't act is thrown away and redone with tools. Needs an engine restart to load.

## Added 2026-09-22 (session 66c5db "Startup animation, auto agent selection, connectors") — N9 + N10, STARTED

The owner's words to this session (verbatim), sent with a photo of the connector page he wants. Photo: a dark grid of
rounded square tiles, each with one big brand logo in its own colours and the name in small grey text under it
(Trello, Asana, Airtable, GitHub, GitLab, HubSpot, Salesforce, Pipedrive, QuickBooks, Stripe, Freshdesk, Facebook,
YouTube, Mailchimp, Figma, Canva, OpenAI…); the hovered tile lightens and a connected one has a small green dot.

```text
Add a start up animation. Using file for plan null add this to the bottom of the list and start working on this part. Coordinate with the other against working on this to ensure you dont overlap and each parts works efficiently together.Add auto sub agent and agent selection as an option in settings for nyx chat, and every other chat. Then run a program everyday at one point which the user can decide where it grades each agent on use, and where it is used as well as which agent and uses that data to select the sub agents used automatically, what information to feed it since when it is added it should be given unique context for each one, and which model and key to use. Make the default as on for auto agents and everyday at 12 am or when the AAI is first turned on in a day as when it does grading. Also add a box for what day or days to do this for.

Update the connectors and make in the format of the photo and add as many as possible, Gmail, mail, docs, sheets, excel, Microsoft apps, vercel, and more. Basically all the things Claude and ChatGPT can use as their connectors.
```

The start-up animation is c69db1's (N29/N40). This session builds **N9** and **N10**; its own new rows are N70–N79.

| # | Item | Owner / notes |
|---|---|---|
| N9 | Auto agents: a Settings switch (default ON) for Nyx chat and every other chat; a daily grading run (default 12 am, or the first start of the day if that was missed; the owner picks the time and the days) grades every agent on use, where it is used and how well; the grades pick the auto sub-agents, the unique context each gets when it is brought in, and the model + key each uses | **66c5db**: `agent_grading.py`, `routes_agent_auto.py` (`/api/agents/auto/*`), `panels/AutoAgentsSection.tsx`; small hooks in `turn_runner.py` (the agent_match block only) and `agent_runtime.run_specialist`. fc578b's chat bottom bar "Agents: Auto" follows `agent_grading.auto_enabled(surface)`; 6cc61a's Office Space calls `agent_grading.pick_agents()` / `record_use()` |
| N10 | Connectors page in the photo's format with as many connectors as possible (Gmail, mail, Docs, Sheets, Excel, Microsoft apps, Vercel, everything Claude and ChatGPT connect to) | **66c5db**: `connectors/catalog.py` (the catalog + connections store: connect / test / remove, secrets only in `secret_store`), `/api/connectors/catalog`, `/mine`, `/{id}/connect`, `/{id}/test`, `DELETE /{id}`, `ConnectorsPanel.tsx` + `panels/connectors/*`. fc578b adds the "+" bar / add-by-chat sheet (N32–N33) and connector use in chats (N34–N35) on top of this catalog |

## Added 2026-09-22 (session be872d "Finance simulation and chat interface modes") — N19b, N20–N25 as rows N80–N89, **DONE 2026-09-25**

All ten rows are built, tested and live-checked (what landed, and the two things not exercised, are in START_HERE.md
§ "DONE (2026-09-22 → 25, session be872d)"). New files: `quiet_windows.py`, `chat_modes.py`, `question_cards.py`,
`slide_reader.py`, `voice_gestures.py`, `routes_voice_gestures.py`, `design_sense.py`, `routes_design.py`,
`src/voice/clapDetector.ts`, `components/chat/{ModeSlider,QuestionCard,PlanCard}.tsx`, `components/clap/*`,
`panels/notes/SlidesStudy.tsx`, and tests `test_quiet_windows`, `test_trading_runmode`, `test_chat_modes`,
`test_slide_reader`, `test_voice_gestures`, `test_design_sense`.

The owner sent this session the tail of Project Null (N19's last paragraph and N20–N25) word for word, without "do not act
on it", so it is being built now. The rest of N19 (node map, don't-go-broke guard, finance memory simulator, focus mode)
is **dc471e**'s `finance_lab/`; this session does only the 24/7 mode and the paper-vs-real simulator.

```text
For the finance allow a mode for active 24/7 or until stop so the user doesnt ahve to manually start when US markets open. Make the simulation where it sues fake money andd not real money (the current default) a bit better, just make it clear which oen is real and fake.
Make a new slider at the bottom of the chat. Here there are 3 different types. 1 is for normal where it chats and make sure thecc bc hat is better and faster. As it thinks it can talk and list it out as it thinks it. Basically just much faster. 2. Co work is basically the same to Claude cowork where it works at the same time and works in the background. 3. Is plan mode. In here it first makes a script/spec list and makes questions and makes a scheme and ask the user to check it. After the user approves or adds more it cornfields and starts working. Basically a better confirm. 


Also add questions that the user can click and send to the ai so the ai basically makes a question and a list of answers and what each means as well as a box for typing if the user had a different approach they thought of. 

Add a feature to voice where if offline or away or when using the background voice I said earlier please ensure it has a feature called clap. In here we can tell the AI a certain gesture like clapping, whistling, a phrase, or something more which the AI responds to and talks back. When first turning the voccie on, regardless of mode have it syas, NYX here. And say something like the sounds are starting or something. Not so corny as the one I said but similar. 

Final part, make sure that when a cmd opens, try to fix it so it doesnt interrupt me or just dont have it open at all and instead opens but doesn't affect my ability to type

Last thing to do is feel all ui, past ui decision, how ui updates, how apple and most software companies design ui, how ai interpret prompts for front end design and how it should respond. It should also have no default design. It should allow for extremely free interetstipn. It should have almost all permissions on so it can search, look at other tabs, understand exactly what the user wants, and use outline ai models to design it. 

In notes add an upload place so if I upload slides it can make detailed notes, quizzes, Flashcards, questions for specific parts, and has a text box where I can say to generate a specific study tool.
```

Agreed with the other sessions: voice files (`ActiveTalk.tsx`, `voicePlayer.ts`, `components/voice/*`, `tts.py`) are
**dc471e**'s; clap listens to their `src/voice/voiceBus.ts` and speaks through `speakText`. The chat's bottom row is
shared: be872d's mode slider on the left, fc578b's `ChatToolbar` on the right. `apply_engine.py` is ai-dev-folder-0d's
and `tab_editor.py` is c69db1's; each calls `design_sense` with a one-line insertion.

| # | Item | Owner / notes |
|---|---|---|
| N80 | Trading run modes: during market hours (starts by itself at the open), **24/7 until I stop it**, or until a set time — no manual start; resumes after a restart | **be872d**: `trading/autopilot.py` (`set_run_mode`, `stop`, `run_status`), `trading/market.py` (real New York time + NYSE holidays), `routes_trading.py`, `panels/trading/*` |
| N81 | Practice (fake) money vs real money impossible to confuse; a better simulator (spread/slippage, orders placed while the market is closed fill at the next open, equity history, vs-SPY benchmark) | **be872d**: `trading/brokers.py` PaperBroker, `panels/trading/*` |
| N82 | Chat mode slider under the composer: **Normal · Co-work · Plan**. Normal = faster, lists its thinking live as it goes | **be872d**: `chat_modes.py`, `components/chat/ModeSlider.tsx`, `mode` on `/api/chat/stream`, one hook in `turn_runner.py` |
| N83 | **Co-work**: works in the background like Claude Cowork; messages run as parallel tasks with a live checklist | **be872d**: `chat_modes.py` (checklist tool), tasks tray |
| N84 | **Plan**: a spec list, questions and a scheme first; the owner approves or adds more, then it works through the plan | **be872d**: plan card; read-only tools while planning |
| N85 | Clickable question cards: a question, answers with what each means, and a box for a different approach | **be872d**: `question_cards.py` (format + prompt rule), `components/chat/QuestionCard.tsx` |
| N86 | Voice **Clap**: teach Nyx a clap, whistle, phrase or any sound; it answers and talks back when away, offline or in background voice. Every voice start says "Nyx here" + a short line | **be872d**: `voice_gestures.py`, `src/voice/clapDetector.ts`, `components/clap/*` |
| N87 | Console (cmd) windows never pop up or take typing focus | **be872d**: `quiet_windows.py` (CREATE_NO_WINDOW by default for every child process) |
| N88 | Front-end design sense: past UI decisions, other tabs, Apple and industry practice, how to read a design prompt; no default design; research + online models | **be872d**: `design_sense.py` (`build_brief`, `brief_for_prompt`, `record_decision`); used by c69db1's Redesign |
| N89 | Notes: upload slides → detailed notes, quizzes, flashcards, questions for chosen slides, and a box to ask for any study tool | **be872d**: `slide_reader.py`, `study_tools.py`, `routes_notes.py`, `panels/notes/*` |

## Added 2026-09-22 (session 6cc61a "Startup animation and office space tab") — N8 STARTED, rows N50–N59

The owner re-sent the Office Space paragraph verbatim (same words as N8 above, including the sidebar/naming
addition) with: *"Using file for plan null add this to the bottom of the list and start working on this part.
Coordinate with the other [agents] working on this to ensure you dont overlap and each parts works efficiently
together."* So **N8 is IN PROGRESS in this session**. The start-up animation that came with the same message is
**c69db1's** (rows N29–N49 area) — three sessions were told to build it and only one does.

| # | Item | Owner / notes |
|---|---|---|
| N8 | **Office Space tab** — see the row above. IN PROGRESS (6cc61a) | `office/` package (engine, hierarchy, targeting, gatekeeper, storage, focus), `routes_office.py`, `tests/test_office*.py`, `panels/office/*`, tab id `office`, data under `offices/` (never `office/` — that is the code package) |
| N50 | Office layout **sidebar** that shows the other office files and folders while an office is open | `panels/office/Sidebar.tsx` |
| N51 | **Naming** settled: an **office file** holds ONE office (its team, chat, memory, work folder). A **folder** holds office files and other folders, nested like Windows (the owner's "mega folder"). Empty folders show a **"+ New office here"** button. Office files drag and drop between folders | `office/library.py`, `panels/office/Lobby.tsx` |
| N52 | Interfaces other sessions call into Office Space: `office.api.say(text, to="", office_id="")` (voice/Proto Voice, dc471e) | `office/api.py` |
| N53 | Interfaces Office Space calls out to: fc578b `background_jobs.pause_all/resume/status` (focus mode), 66c5db `agent_grading.pick_agents/record_use`, c29bdc `identity0.api.best_models/domain_of` + `router.stream(prefer="identity0")` for the top manager. Every one is imported lazily and guarded, so a missing module only costs its own feature | `office/focus.py`, `office/casting.py` |

## Added 2026-09-22 (session dc471e "Voice interface and site improvements") — rows N90–N110, STARTED

The owner sent this session the voice paragraph (N11), the website paragraph (N12), Proto Voice (N13), the
screen/cursor paragraph (N14), background processes (N15), the caret bug (N16), links + the curiosity machine
(N17/N18) and the finance paragraph (N19) — to build now. Verbatim, as sent:

```text
Next improve the voice. So basically activated and talk as it talks as the user says and can singly think as the user speaks so by the end it ids the fact they stopped with that pause and can instantly talk. Also when activating voice make the side panel a bit smaller. Then the ai talks. In here as I talk it listens and thinks of how to answer and then instantly responds. As it talks it also listens. Make sure it doesn't pick up its own voice. Use a separate model for voice, text, listening, and active listening as well a interpretation.

Update the normal site and add a download button where you can actually add the zip file or the uncompressed file and the user clicks and it downloads. For this add an animation where as you hover over the button it fills to half and when you click it changes from saying download with the download symbol to the downloading and the rest of the button fills as the download percent goes up. Then add a custom 404 page. Update the website ui and add in things like how the second brain tabs look.

For the voice add another slider or part of the voice listening and talking where it is called proto voice. It always listens as allows the ai to understand and do things just better. This model allows it to turn on, off the computer and itself, can navigate the computer and the app itself by saying open files or open this tab in nyx. It allows it to turn the computer on from lock if you give it the password though that can be a secondary. Maybe it can also add sub agents to its chat and it acts as the manager giving every command. It can do simulations. Basically free will but with voice. Also for files I want a way to drag and drop it so even if I don't click on it I can drag it, the site ids that it's a file, the pulls up the file drop box. In addition, add file checks to make sure no one can add faulty or malicious stuff.

Allow for copy paste of pictures where it uploads as a file though shows the picture so the user knows which one it is. When screen sharing or the ai using something on screen, using keyboard (make sure it can do this) and mouse make sure it also has the ability to talk. For the screen share add a file more powerful and free will based ide where it can access everything and I don't have to say do it everytime. I can say make a file code it, and open it for me. And it will do it. Also just to make sure, it should have its own cursor and keyboard so whatever I do shouldn't affect what it's doing. So I can work on one screens fit on the other. Also allow screen share to two screens. Just make it so I can also choose the orientation of the screens just like in windows settings.

In the nyx chat tab for the background processes update it so that it can also see background processes for everything g new. At times it doesn't know about the new features and make sure it actively searches and sees. Add all features running to a file or a catalog and it reads form there as well as how much is being used.

Fix this one issue where when I click on any word it has the the blinking line similar to when typing in docs but I can't type. If you can fix this but if too big of a overall you don't need to.

When pasting links I would like the link to be highlighted in the blue purple color so I know it works. Also I should be able to click on the link I paste and take it to the site which opens in a new tab. Also when the ai gives me a link or add a feature where I can say give me the link to this or in citations or when I as it to research or when I ask a general question and it's citations or proof is shown I wnat those links to be click and as well.  Data absorption, understanding, and training for AI. How Artificial Intelligence can learn not only from its users and chat history but also gain the ability to be curious and learn more. Search and add a third mind  or curiousity machine. An improvment on the free will device tab but in a new way to the AI. This includes curiosity, how it wants to learn, and adds feelings and understanding. And owns up to mistakes while having curiosity to learn more. This shouldn't fully affect chats, but it keeps questions and new ideas and files them. This is an extension of free will and will have a tab in the free will tab that shows its growth, understanding, and wants in its lifetime.

Use this second photo and add to finance and trading agent. Back ally each node lights up as it gets used. Build a new system so for this since most ai need the usage limits while a local ai and a few unlimited use ai are needed make sure to make a new one basically local with search so it can predict changes and plot properly. Make sure there is a don't go broke situation where it tries to not go into debt if taht is even possible and make sure it know all strategies and also doesn't spend more money than allocated. Essentially it can only access the money it has and the money it earns to make more money. If it dial it needs to lean. Add a finance memory simulator and feature so it trains and then does that. For high finance use it should have a warning and turn off all other features as and keep only the finance if memory allocated to fisnce it very high. Also make sure if it does use an api and a non local as a collab or as a backup or just as the main make sure it has either reinforce like qwen or has enough use to the point where it wouldn't matter over the course of use.
```

| # | Item | Owner / notes |
|---|---|---|
| N90 | Voice: it thinks while the owner talks, notices the pause and answers at once; it listens while it talks; it never hears itself; a separate model for voice, text, listening, active listening and interpretation; the side panel shrinks while voice is on | **dc471e**: `src/voice/*` (voiceEngine, voiceBus, echoGuard), `ActiveTalk.tsx`, `voice_pipeline.py`, `routes_voice.py` |
| N91 | Website: a real download button (zip or folder) that fills to half on hover and fills with the download percentage on click; a custom 404; site UI like the Second Brain tabs | **DONE 2026-09-26 by 1da8a0** with the owner's site overhaul (GitHub + Download side by side, published at nyx-ichos.vercel.app) — see START_HERE.md |
| N92 | **Proto Voice**: always listening; turns the computer and itself off (and itself back on from standby); navigates the computer and Nyx by voice; adds sub-agents and manages them; runs simulations — "free will but with voice" | **dc471e**: `proto_voice.py`, `routes_proto_voice.py`, `components/voice/*`. Unlocking Windows with a spoken password is NOT built — Windows' lock screen is a separate secure desktop that no app can type into, and Nyx never stores passwords. Windows Hello does this properly |
| N93 | Drag a file anywhere onto the app; it sees a file is coming and opens the drop box | **dc471e**: `src/files/fileIntake.ts`, `components/FileDropOverlay.tsx` |
| N94 | File checks so nothing faulty or malicious can be added | **DONE 2026-09-23 by 6bd7de** (the owner asked for it there as well): `file_guard.py` + `routes_security.py` + `tests/test_file_guard.py` (39). Wired into `uploads.save_upload`, `/api/uploads` serving, `media_tools._load_source`, `machine_tools.download_file`, `beta_channel.download`, `local_models.add_file`, and `site/api/_lib/collab.js` (`scanMalicious`). Still open for dc471e: `file_guard.injection_notes()` inside `absorb_sources.text_from` |
| N95 | Paste pictures: they upload as a file and show the picture so the owner knows which one | **dc471e** (also serves c69db1's N42) |
| N96 | It can talk while it uses the keyboard and mouse, in Screen Share and when it acts on screen; keyboard control works | **dc471e**: `screen_share.py`, `computer_control.py` narration |
| N97 | Screen Share IDE: freer, "make a file, code it and open it" without being told each time | **dc471e**: `screen_ide.py` — a standing grant for one workspace folder, still never runs generated code (AGENTS.md §7) |
| N98 | Nyx's own cursor and keyboard, so the owner's mouse and typing don't disturb it; owner on one screen, Nyx on the other | **dc471e**: `background_input.py` — UI Automation and window messages, not the real mouse; the overlay cursor shows where it is working |
| N99 | Share two screens at once, and choose their orientation like Windows display settings | **dc471e**: `screen_share.py`, `panels/screen/*` |
| N100 | The Nyx chat's background processes see every new feature; a catalog file of everything running and how much it is used, which Nyx reads and refreshes by itself | **dc471e**: `feature_catalog.py`, `routes_features.py`, tool `feature_catalog`; reads fc578b's `background_jobs.py` when it lands |
| N101 | Bug: clicking a word shows a blinking caret but nothing can be typed | **dc471e**: browser caret browsing (F7) / `caret-color`; small CSS fix at the end of `index.css` |
| N102 | Pasted links highlighted blue-purple and clickable in a new tab; links, citations and research results from the AI clickable too | **dc471e**: `components/chat/linkify.ts`, `Markdown.tsx`, `Composer.tsx` |
| N103 | The "third mind" / curiosity machine: curiosity, what it wants to learn, feelings and understanding, owning mistakes; it files questions and ideas; a tab inside Free Will showing its growth, understanding and wants over its lifetime | **dc471e**: `curiosity.py`, `routes_curiosity.py`, `panels/freewill/CuriosityView.tsx` |
| N104 | The owner's second photo added to the finance and trading agent: each node lights up as it is used | **dc471e**: `finance_lab/node_map.py`, `panels/financelab/*`. PHOTO NOT ATTACHED to the message — ask the owner for it; built from the real pipeline meanwhile |
| N105 | A new finance system that does not depend on usage limits: local first, with search, so it can predict changes and plot them properly | **dc471e**: `finance_lab/forecast.py`, `finance_lab/model_policy.py` |
| N106 | "Don't go broke": never into debt, never more than the allocated money, only its own money and what it earns; when it loses, it learns | **dc471e**: `finance_lab/capital_guard.py` → one line in be872d's `trading/guard.py` |
| N107 | It knows all the strategies | **dc471e**: `finance_lab/strategies.py` with backtests |
| N108 | A finance memory simulator: it trains in simulation, then does it for real | **dc471e**: `finance_lab/simulator.py` + `finance_lab/memory.py` |
| N109 | High finance use: a warning, and everything else switches off so only finance runs when a lot of memory is given to finance | **dc471e**: `finance_lab/focus_mode.py` (calls fc578b's `background_jobs.pause_all` and be872d's `trading/autopilot.set_run_mode`) |
| N110 | Any cloud model used for finance (main, backup or collaborator) must be reinforced like Qwen or have enough quota that limits never matter | **dc471e**: `finance_lab/model_policy.py` — local first, then quota-checked providers against the session's projected need |
