# UI/UX patterns in leading consumer AI chat and assistant products (as of 2026-10-10)

Scope: Gemini, Microsoft Copilot, Grok, Le Chat, Meta AI, Poe, DeepSeek, Kimi, Character.ai, Notion AI, Dia, Siri app (iOS 27), ChatGPT Canvas/Agent, Claude Artifacts. Products listed as "already covered" in the brief (Claude home, Codex, ChatGPT home, Perplexity home, the open-source clients) are only mentioned where something changed.
Method: about 19 search and fetch calls, using official release notes and help pages where they were reachable. help.openai.com returned 403, so the OpenAI material comes from its mirrored help snippet and the help-center search index. Many claims rely on third-party guides, and those are flagged.
Dating: anything sourced from before 2025 is marked "(possibly outdated)".

---

## 1. Home / empty state and composer controls

### Takeaway
Across these products, mode and tool switches have moved into the composer: a model dropdown, one or two "think harder" toggles, a Tools/"+" menu, attach, and mic or Live. The sidebar keeps navigation only. Typical composers show 3–6 visible controls and push everything else behind "+" or "Tools". The newest direction, Microsoft 365 Copilot's "prompt surface", is a composer that grows and reveals options as you type.

### Cited Findings
**Gemini (Google)**
- Canvas is selected from the prompt bar (2025-03-18). Deep Think has its own prompt-bar control, with "Thinking" chosen in the model dropdown (2025-12-04). By 2026-02-12, Deep Think is "selected from the prompt bar". — [Gemini release notes](https://gemini.google/release-notes/)
- Model dropdown labels are short tiers: "Fast", "Thinking", "Pro" (Dec 2025), then version labels "3.5 Flash" (2026-05-19) and "3.6 Flash" (2026-07-21). — [Gemini release notes](https://gemini.google/release-notes/)
- The Tools menu holds experimental "Labs" entries, for example "Visual layout" and "Dynamic view" (2025-11-18). A "Create" menu in Canvas generates web pages, infographics, quizzes and Audio Overviews (2025-05-20). — [Gemini release notes](https://gemini.google/release-notes/)
- Learning mode is a composer chip: "Guided Learning" on desktop, "Learn" on mobile (2025-08-06). — [Gemini release notes](https://gemini.google/release-notes/)
- Gemini Live is now merged into the chat (2026-05-19). Users switch between talking and typing in the same thread, and Live shows real-time map and weather cards while talking. — [Gemini release notes](https://gemini.google/release-notes/)
- Desktop summon hotkeys: Option+Space on Mac (2026-04-15, with "share a window for context") and Alt+Space on Windows (2026-09-10). On macOS, holding Fn dictates into the active window (2025-07-29). — [Gemini release notes](https://gemini.google/release-notes/)

**Microsoft Copilot**
- The Copilot Vision entry point is a glasses icon in the composer. The user picks a screen or app (max 2 apps, or the whole desktop since v1.25071.125), and a glowing orange outline surrounds whatever is shared. "Start with text" is the default. "Start with voice" shows a floating toolbar with Vision and Voice controls. To stop, use "Stop" or "X" in the composer. — [Microsoft Support: Using Copilot Vision](https://support.microsoft.com/en-us/microsoft-copilot/using-copilot-vision-with-microsoft-copilot); [Pureinfotech (Jul 2025)](https://pureinfotech.com/use-copilot-vision-windows-11/); [Windows Insider blog, Oct 2025](https://blogs.windows.com/windows-insider/2025/10/28/copilot-on-windows-vision-with-text-input-begins-rolling-out-to-windows-insiders/)
- Microsoft 365 Copilot (late May 2026) introduced a "prompt surface" that changes size and reveals functions as you type. A research or visual request expands it to show file or visual-response options. The consumer Copilot app keeps an older, more colourful look. — [Engadget](https://engadget.com/2183246/microsoft-debuts-a-more-buttoned-up-look-for-copilot)

**DeepSeek**
- DeepSeek has no model dropdown. Two toggles sit by the text box, "DeepThink" (reasoning) and "Search" (web), plus a paperclip for attachments. Sources disagree on placement: one says below the field, another says above the prompt bar. These are R1-era descriptions from early 2025 (possibly outdated). — [Yahoo Tech review](https://tech.yahoo.com/ai/articles/deepseek-review-middling-chatbot-profound-145940879.html); [LearnPrompting guide](https://learnprompting.org/blog/guide-deepseek-chatbot)

**Siri app (iOS 27, public beta Aug 2026)**
- A "+" button attaches an image or document. Leaked mockups label the field "Ask Siri" with mic and paperclip. System-wide entry is a "Search or Ask" pill in the Dynamic Island, and a results card can be swiped up into a full iMessage-like conversation. — [Engadget, 2026-08-29](https://engadget.com/2242748/how-to-use-the-new-siri-app-in-ios-27/); [tbreak (leak)](https://tbreak.com/ios-27-siri-leak-standalone-app-text-chat/); [tbreak redesign leak](https://tbreak.com/ios-27-siri-redesign-dedicated-app/)

**Le Chat (Mistral)**
- Agents are invoked inline by typing "@" and choosing an agent. The tool set is web search, Canvas, image generation (Flux Ultra), code interpreter, OCR, and a no-code agent builder (May 2026 guide). A 2025 tutorial describes "a prompt box with settings and features at the center of the page". — [TechJack Solutions](https://techjacksolutions.com/ai-tools/mistral/how-to-use-mistral/); [Dupple tutorial](https://dupple.com/tutorial/an-introduction-to-mistral-ai)

**Poe**
- Multi-bot chat lets the user "@-mention" any bot inside one thread and compare answers from recommended bots with one click. This dates from the 2024 launch (possibly outdated). — [CDOTrends](https://www.cdotrends.com/story/3941/poe-unveils-multi-bot-chat-feature)

**Grok**
- Imagine returns four images side by side, with "Generate More" and "Think Harder" buttons beneath (third-party 2026 guide). — [Christopher Alarcon, 2026](https://christopheralarcon.com/blog/how-to-use-grok)

**Meta AI**
- The standalone app (Apr 2025) has a "Discover" feed of others' prompts, which users can remix, and a full-duplex voice mode with a "Ready to talk" preference and a visible mic-on icon. — [AlternativeTo (Apr 2025)](https://alternativeto.net/news/2025/4/meta-ai-launches-standalone-app-for-android-and-ios-with-social-discover-feed-and-voice-mode); [CO/AI](https://getcoai.com/news/new-meta-ai-app-unifies-smart-glasses-and-phone-experiences)

**Dia browser**
- The Skills menu (saved prompts such as summarise page or extract data) sits on the new-tab page. Users can edit the defaults or write new skills in plain language, and chat is also available in a side-by-side sidebar. — [Thurrott](https://www.thurrott.com/cloud/web-browsers/322287/the-browser-company-explains-its-vision-for-dia); [Tabbit review (competitor, biased)](https://go.tabbit-ai.com/dia-browser-review)

### Inferences
- The common composer has about five controls: [+ / attach] [Tools or mode chip(s)] … [model dropdown] [mic / Live]. Reasoning depth ("Thinking", "Deep Think", "DeepThink") is a composer toggle in Gemini and DeepSeek, not a sidebar or settings choice.
- Gemini's move from version-heavy model names to "Fast / Thinking / Pro", and later back to version labels, suggests Ichos should label local models by capability tier, with the file name secondary.
- Copilot Vision's orange outline shows a strong convention: any time the assistant can see something, visible chrome on the shared surface says so.

### Gaps
- No primary source gave greeting copy or suggestion-chip counts for Gemini, Copilot, Grok, Le Chat, Qwen, Kimi or Pi in 2026. No Qwen or Pi UI material was found at all.
- DeepSeek's current (V3.x/V4 era) composer was not verified, because the only sources date from the R1 era.

---

## 2. Sidebar information architecture

### Takeaway
Sidebars are shrinking toward New chat, Search, a few fixed destinations (3–5) and Recents. Notion's 2026 sidebar uses five tabs. Gemini added a "Temporary chat" icon next to New chat and a Spark tab for its always-on agent. On desktop, Copilot is experimenting with docking the whole app as an edge sidebar instead of adding more navigation.

### Cited Findings
- **Gemini:** a "Temporary Chat" icon sits beside "New Chat" (2025-08-13). Chat search opens from the nav via a magnifier or a "Search for chats" bar (2025-08-21). A "Spark" tab (24/7 agent) was added to the app menu (2026-05-19), and a student hub followed (2026-08-19). Gems will be replaced by stackable "Skills" (announced 2026-09-30). Gems are shared from a Gem manager with "Share" beside each Gem (2025-09-18). — [Gemini release notes](https://gemini.google/release-notes/)
- **Notion (new sidebar):** top tabs are Home, Chats (Notion AI), Meetings, Inbox, and Search. It is opted into via the workspace switcher → "Try the New Sidebar". The Chats tab lists threads by recency, a blue dot marks an unread AI response, and the row menu offers rename, change icon, or delete. The Home tab holds Recents, Favorites, Teamspaces, and Agents. Agents are sorted by recent use, and favouriting one pins it to the sidebar. — [Notion Help: sidebar](https://www.notion.com/help/sidebar)
- **Notion:** custom-agent settings moved from a full page to a side sheet (Feb 2026 test). A floating AI chat button sits bottom-right of pages, with Shift+Cmd/Ctrl+J. Third-party sources disagree on the entry point. — [TestingCatalog](https://www.testingcatalog.com/notion-tests-agents-2-0-with-scripting-tools-and-workers.md); [eesel review](https://eesel.ai/blog/notion-ai-review)
- **Copilot on Windows:** a title-bar dropdown switches between floating window, picture-in-picture, dock left, and dock right. When docked, other apps resize around it. This was a staged test reported May 2026 with no official announcement, and it is "the sixth Copilot UI redesign in two years" per Notebookcheck. — [Guru3D](https://guru3d.com/story/microsoft-returns-copilot-to-sidebar-layout-in-windows-11/); [Notebookcheck](https://notebookcheck.net/Windows-11-Microsoft-backpedals-on-Copilot-decision.1306140.0.html); [Let's Data Science](https://letsdatascience.com/news/microsoft-restores-docked-copilot-sidebar-in-windows-11-74db46fd)
- **Copilot:** profile icon → "Give feedback" is where feedback lives (2026-03). — [Windows Insider blog](https://blogs.windows.com/windows-insider/2026/03/04/copilot-app-on-windows-opening-web-links-alongside-your-conversations-begins-rolling-out-to-windows-insiders/)
- **Le Chat:** a dedicated "Agents" tab lets users build or browse agents, and "Libraries" hold uploaded documents for grounding. — [TestingCatalog](https://www.testingcatalog.com/mistral-ai-rolls-out-faster-more-powerful-agents-inside-le-chat.md); [Mistral docs](https://docs.mistral.ai/getting-started/le-chat-studio-admin)
- **Grok:** an extension author claims xAI removed sidebar functionality in March 2026. Another 2026 guide still places Imagine "in the sidebar". This is unconfirmed and conflicting. — [Grok UI Tools listing](https://addons.mozilla.org/addon/grok-ui-tools/); contradicted by [Alarcon guide](https://christopheralarcon.com/blog/how-to-use-grok)
- **Siri app:** the main screen has a search button and a top-right toggle between list view and card grid of past conversations. Press-and-hold a conversation to pin, rename, or delete it. — [Engadget, 2026-08-29](https://engadget.com/2242748/how-to-use-the-new-siri-app-in-ios-27/)

### Inferences
- The convergent IA is: New chat (+ temporary/incognito next to it) · Search · 3–5 destinations (Agents/Skills, Projects/Libraries, Spark/Tasks) · Recents with pinned on top. Notion stops at five tabs before anything goes under "More".
- An unread dot on a chat row (Notion) is the lightweight signal that a background or long-running answer finished. This fits Ichos's "summoned windows" model.
- Copilot's dock modes (float / PiP / dock-left / dock-right) map directly onto a Windows 11 assistant. They are worth offering as window states rather than as separate apps.

### Gaps
- No sources found for current Gemini web sidebar item order, ChatGPT Projects sidebar grouping (2026), Kimi/Qwen sidebars, or Le Chat's 2026 sidebar.

---

## 3. Side-by-side output (artifacts / canvas / pages / link panes)

### Takeaway
Long or editable output opens in a right-hand panel with a small top toolbar (versions, diff, copy, share, download, close). Short answers stay inline. Copilot now applies the same side-pane idea to web links clicked from chat and saves those tabs with the conversation.

### Cited Findings
- **ChatGPT Canvas:** arrows in the top toolbar step through versions, and an earlier one can be restored. A "Show changes" button shows additions and deletions for docs and code, and a copy button is also in the toolbar. Share comes from the canvas toolbar, Download sits top-right, and it is available on Web, Windows and macOS. — [OpenAI Help: canvas](https://help.openai.com/en/articles/9930697-what-is-the-canvas-feature-in-chatgpt-and-how-do-i-use-it)
- **Claude Artifacts:** a dedicated panel to the right of chat with Preview and Code tabs and a version selector. Guides disagree on whether the version dropdown is at the top of the panel or at the bottom-left. "Live Artifacts" (auto-refreshing dashboards) arrived in Cowork in Apr 2026. All of these are third-party sources. — [Guideflow tutorial](https://www.guideflow.com/tutorial/how-to-view-version-history-of-an-artifact-in-claudeai); [ClickUp 2026](https://clickup.com/blog/claude-artifacts/); [CometAPI](https://www.cometapi.com/how-to-use-claude-artifacts/)
- **Copilot (Windows, Insider Mar 2026):** clicking a link opens it "in a sidepane next to your conversation without leaving the app". Tabs opened in a conversation are saved with it, and Copilot can read them only within that conversation and only with permission. — [Windows Insider blog](https://blogs.windows.com/windows-insider/2026/03/04/copilot-app-on-windows-opening-web-links-alongside-your-conversations-begins-rolling-out-to-windows-insiders/)
- **Microsoft 365 Copilot:** the AI now sits "in a consistent location across all Microsoft 365 apps — a side pane". — [Engadget](https://engadget.com/2183246/microsoft-debuts-a-more-buttoned-up-look-for-copilot)
- **Gemini Canvas** has a "Create" menu that converts content into web page, infographic, quiz, or Audio Overview. — [Gemini release notes](https://gemini.google/release-notes/)
- **Grok Imagine** shows four variants side by side, with "Generate More" and "Think Harder" below. — [Alarcon](https://christopheralarcon.com/blog/how-to-use-grok)
- **Poe** compares answers from several bots "with one click" in the same thread (2024, possibly outdated). — [CDOTrends](https://www.cdotrends.com/story/3941/poe-unveils-multi-bot-chat-feature)

### Inferences
- The minimum panel toolbar is: title · version ‹ › (or dropdown) · Show changes · Copy · Share/Export · Download · Close. Preview/Code tabs are added for renderable output.
- There are two ways to show variants. Version history is sequential (ChatGPT Canvas, Claude), and parallel variants appear as a grid (Grok Imagine ×4, Poe compare). Ichos can use one versions control for both: arrows for sequential versions, a grid for parallel ones.
- Copilot saves link-pane tabs to the conversation, which suggests every summoned Ichos window should belong to the chat that opened it and reopen with that chat.

### Gaps
- The criteria for staying inline versus opening a panel (length or type thresholds) are not documented by any vendor I found.
- Gemini Canvas share and export controls, and Copilot Pages UI, were not found. Copilot Pages had no 2025–26 hits.

---

## 4. Agentic / long-running tasks

### Takeaway
Every agent product uses the same control set. It shows a plan or to-do list, a live view of the virtual computer or browser, a confirmation before consequential actions, and always-visible "Take control" or "Pause" plus "Stop". Long runs end with a notification. Kimi shows the to-do list and intermediate files, and ChatGPT stops capturing screenshots while the user is in control.

### Cited Findings
- **ChatGPT agent:** at a login step the agent pauses and asks the user to take control of its virtual browser via the "…" menu. Screenshots are not captured during user takeover, and after the user hands back, the agent resumes or may need to restart. It can run logged-out and won't use existing cookies without approval. — [OpenAI Help: ChatGPT agent (mirror)](https://help-lb.openai.com/en/articles/11752874-chatgpt-agent)
- **ChatGPT Atlas agent:** a notification bar shows "Take control" and "Stop". The agent "asks before many important actions", and the user can pause, interrupt, or take over at any time. — [Simon Willison, Oct 2025](https://simonwillison.net/2025/Oct/21/introducing-chatgpt-atlas/)
- **Gemini Agent (web, 2025-11-18):** asks for confirmation before critical actions, and the user can pause or take over at any time. Gemini Spark (2026-05-19) is a 24/7 agent with its own tab. Deep Think's only progress cue is a notification when the answer is ready, after a few minutes. — [Gemini release notes](https://gemini.google/release-notes/)
- **Kimi OK Computer / Agent mode:** a start screen shows the cloud computer booting, then a to-do list the agent ticks through item by item. Users can see planned to-dos and intermediate files, with thumbs up and down for feedback. Tools are file system, browser, terminal, code, image, and audio. — [MIT AI Agent Index](https://aiagentindex.mit.edu/2025/kimi-ok-computer); [woshipm hands-on (CN)](https://www.woshipm.com/ai/6276089.html); [Kimi help](https://www.kimi.ai/help/agent/agent-overview)
- **Grok Bot** is "a bot with its own cloud computer that runs jobs for you". There are no UI details. — [Alarcon](https://christopheralarcon.com/blog/how-to-use-grok)
- **Dia:** a reviewer recommends approvals and guardrails when a skill touches accounts or purchases. This is opinion from a competitor. — [Tabbit review](https://go.tabbit-ai.com/dia-browser-review)

### Inferences
- A standard agent card has a header (task title + status + elapsed time), a checklist of steps (current step animated), a live viewport thumbnail that expands into a window, and footer buttons [Take control] [Pause] [Stop]. Ichos's "summon as a window beside chat" model fits this exactly: the chat shows the compact card and the window shows the live view.
- Pausing screenshot or log capture during user takeover (ChatGPT) is a cheap trust win for a local app that records agent activity.

### Gaps
- No primary source on Claude Research mode's progress UI or ChatGPT Tasks (scheduled) UI in 2026. help.openai.com returned 403 and no Anthropic help page surfaced.
- Exact approval-dialog wording for Gemini Agent and ChatGPT agent was not retrieved.

---

## 5. Trust / control patterns (citations, thinking, retry/branch, feedback, memory, AI disclosure)

### Takeaway
Memory and retention controls are now explicit, user-chosen settings. Gemini has off-by-default "Personal Intelligence" with per-app connection plus import of memories. Siri offers "Keep Conversations" for 30 days, 1 year, or forever, and Copilot reads tabs only per conversation with permission. Products also mark when the AI can see something (orange outline) and keep temporary or incognito chat one click from New chat.

### Cited Findings
- **Gemini:** past-chat referencing comes with review, delete, and retention controls (2025-02-12). "Personal Intelligence" connects Google apps and is off by default, with per-app choice and an off switch (2026-01-20). Settings can import memories and chat history, and "Past chats" was renamed "memories" (2026-03-26). — [Gemini release notes](https://gemini.google/release-notes/)
- **Siri:** Settings > Siri > Keep Conversations offers 30 days / one year / forever, synced via iCloud. Short commands ("set a timer") aren't saved to history. — [Engadget, 2026-08-29](https://engadget.com/2242748/how-to-use-the-new-siri-app-in-ios-27/); [Soy de Mac](https://en.soydemac.com/Siri-in-iOS-27-launches-its-own-app-with-automatic-chat-deletion/)
- **Copilot Vision** is opt-in per session, with an orange outline around the shared surface. Microsoft says, unlike Recall, that screenshots are not taken and stored. — [Microsoft Support](https://support.microsoft.com/en-us/microsoft-copilot/using-copilot-vision-with-microsoft-copilot); [Pureinfotech](https://pureinfotech.com/use-copilot-vision-windows-11/)
- **Meta AI:** posting to the Discover feed is opt-in, and a visible icon shows when the mic is on. — [AlternativeTo](https://alternativeto.net/news/2025/4/meta-ai-launches-standalone-app-for-android-and-ios-with-social-discover-feed-and-voice-mode)
- **DeepSeek:** DeepThink shows its reasoning before the final answer. — [LearnPrompting](https://learnprompting.org/blog/guide-deepseek-chatbot)
- **Dia:** content is stored locally by default and only sent when the user starts a request. The opt-in History feature can reference up to 7 days of browsing. — [SupaSidebar (biased)](https://supasidebar.com/blog/dia-browser-mac-review-2026); [Tabbit](https://go.tabbit-ai.com/dia-browser-review)
- **Character.ai (2026):** swipe-to-regenerate alternate replies now costs "Charms" on the free tier, which also carries mid-chat ads. — [aicompanionpick](https://aicompanionpick.com/character-ai-launches-new-features-in-2026-full-breakdown); [aiindigo](https://aiindigo.com/blog/character-ai-review-the-state-of-ai-persona-interaction-in-2026)
- **Kimi agent** has thumbs up and down feedback per output. — [MIT AI Agent Index](https://aiagentindex.mit.edu/2025/kimi-ok-computer)

### Inferences
- For a local-first app, the strongest trust UI combines several of these. A retention picker per chat or global (Siri), per-source connect toggles that are off by default (Gemini), a "can see" outline or badge whenever screen or file context is shared (Copilot), and temporary chat next to New chat (Gemini).
- Swipe-regenerate (Character.ai) and version arrows (ChatGPT Canvas) are the same control. Ichos should use one "‹ 2/3 ›" variant switcher on messages and panels.

### Gaps
- No 2026 primary sources found on citation chip styling (Gemini "double-check", Copilot footnotes), branch/edit UI, or explicit "AI-generated" labelling in any of these products.

---

## 6. Measurable tokens and named design systems

### Takeaway
Few hard tokens are public. The one named system is Google's Material 3 Expressive, which Gemini's 2026 "Neural Expressive" redesign builds on with thin Roboto Flex type. Microsoft 365 Copilot's 2026 redesign is described as "more buttoned-up" but without published tokens.

### Cited Findings
- Gemini's full redesign (hands-on 2026-05-22) uses "Neural Expressive", Google's "vibrant, dynamic and completely reimagined design language for Gemini". The reviewer calls it a usability step backward. — [Android Authority](https://www.androidauthority.com/gemini-neural-expressive-android-app-hands-on-3668985/)
- The Gemini typeface is reported as a thinned Roboto Flex, a "living font" scaling with the UI. No source confirms Google Sans Flex. — [Android Authority](https://androidauthority.com/gemini-new-design-makes-me-worried-future-android-ui-3677170)
- The Gemini Android overlay starts as a small circle above the gesture bar and expands into a rounded pill, in the Material 3 Expressive style. It needs Google app v16.30+. — [Yahoo Tech](https://tech.yahoo.com/ai/articles/google-rolls-rounded-colorful-material-153757903.html); [TuttoAndroid, Apr 2026](https://www.tuttoandroid.net/news/2026/04/07/gemini-app-supporto-colori-dinamici-overlay-in-sviluppo-1147781/)
- Material 3 Expressive (2025) is described as "flexible and customizable … colors, fonts, animations, and interactions". — [WebProNews](https://www.webpronews.com/googles-gemini-app-is-getting-a-visual-overhaul-and-it-tells-us-more-than-youd-think-about-androids-future/)
- The consumer Copilot keeps "its older, more colourful look". M365 Copilot moved to a restrained side-pane style. — [Engadget](https://engadget.com/2183246/microsoft-debuts-a-more-buttoned-up-look-for-copilot)

### Inferences
- Thin, variable-weight type with large radii is the 2026 Google direction. A reviewer criticises its reduced density, which is a warning for a dense desktop tool like Ichos.

### Gaps
- No published hex colours, radii, or composer height values were found for any covered product. Extracting them would need live DOM inspection, which was not done here.

---

## Patterns Ichos should adopt

1. **Composer holds the modes, with ≤6 visible controls:** [+ attach/tools] [mode chip] … [model tier dropdown] [mic/Live]. Put reasoning depth in a composer toggle ("Think"). — Gemini prompt bar Deep Think / Fast·Thinking·Pro ([release notes](https://gemini.google/release-notes/)); DeepSeek DeepThink/Search ([LearnPrompting](https://learnprompting.org/blog/guide-deepseek-chatbot))
2. **Composer grows with intent:** reveal file or visual options when the prompt implies them instead of showing them permanently. — M365 Copilot "prompt surface" ([Engadget](https://engadget.com/2183246/microsoft-debuts-a-more-buttoned-up-look-for-copilot))
3. **Temporary chat icon right beside New chat; chat search as a bar at the top of the sidebar.** — Gemini 2025-08 ([release notes](https://gemini.google/release-notes/))
4. **Sidebar = ≤5 fixed destinations + Recents.** Use an unread dot on chats whose background answer has finished, and a row menu with rename / icon / delete / pin. — Notion new sidebar ([Notion Help](https://www.notion.com/help/sidebar)); Siri pin/rename/delete ([Engadget](https://engadget.com/2242748/how-to-use-the-new-siri-app-in-ios-27/))
5. **@-mention to summon an agent or persona inline** instead of navigating to it. — Le Chat "@" agents ([TechJack](https://techjacksolutions.com/ai-tools/mistral/how-to-use-mistral/)); Poe @-bot ([CDOTrends](https://www.cdotrends.com/story/3941/poe-unveils-multi-bot-chat-feature))
6. **Output windows beside chat with a fixed toolbar:** version ‹ › · Show changes · Copy · Share/Export · Download · Close, plus Preview/Code tabs for renderables. — ChatGPT Canvas ([OpenAI Help](https://help.openai.com/en/articles/9930697-what-is-the-canvas-feature-in-chatgpt-and-how-do-i-use-it)); Claude Artifacts ([ClickUp](https://clickup.com/blog/claude-artifacts/))
7. **Links and side content open in a pane owned by the conversation** and are restored with it, and the assistant reads them only with permission. — Copilot link sidepane ([Windows Insider](https://blogs.windows.com/windows-insider/2026/03/04/copilot-app-on-windows-opening-web-links-alongside-your-conversations-begins-rolling-out-to-windows-insiders/))
8. **Window states for the whole app:** floating, picture-in-picture, dock-left, dock-right, plus a global hotkey (Alt+Space). — Copilot dock test ([Guru3D](https://guru3d.com/story/microsoft-returns-copilot-to-sidebar-layout-in-windows-11/)); Gemini Windows Alt+Space ([release notes](https://gemini.google/release-notes/))
9. **Agent run card + live window:** to-do checklist ticking item by item, intermediate files list, live viewport, and always-visible [Take control] [Pause] [Stop]. Confirm before critical actions and pause recording during takeover. — Kimi ([MIT index](https://aiagentindex.mit.edu/2025/kimi-ok-computer)); ChatGPT agent ([OpenAI Help mirror](https://help-lb.openai.com/en/articles/11752874-chatgpt-agent)); Gemini Agent ([release notes](https://gemini.google/release-notes/)); Atlas ([Willison](https://simonwillison.net/2025/Oct/21/introducing-chatgpt-atlas/))
10. **Notify on completion for long thinking or research,** rather than a spinner the user must watch. — Gemini Deep Think ([release notes](https://gemini.google/release-notes/))
11. **Visible "it can see" chrome:** an outline or badge on any shared window or screen, with Stop/X in the composer. — Copilot Vision ([Microsoft Support](https://support.microsoft.com/en-us/microsoft-copilot/using-copilot-vision-with-microsoft-copilot))
12. **Memory and retention as plain settings:** "Keep conversations: 30 days / 1 year / forever", don't log trivial commands, per-source connectors off by default, and import of memories. — Siri ([Engadget](https://engadget.com/2242748/how-to-use-the-new-siri-app-in-ios-27/)); Gemini Personal Intelligence & memories ([release notes](https://gemini.google/release-notes/))
13. **Parallel variants as a grid with "More" / "Think harder"** for generative output, alongside sequential version arrows. — Grok Imagine ([Alarcon](https://christopheralarcon.com/blog/how-to-use-grok))
14. **Voice and text in one thread** (Live merged into chat), with rich cards (maps/weather) inline during voice. — Gemini 2026-05-19 ([release notes](https://gemini.google/release-notes/))
15. **Stackable "Skills"** (saved prompt/agent recipes) as one concept, replacing a separate personas/Gems silo. Edit them in a side sheet, not a full page. — Gemini Skills replacing Gems ([release notes](https://gemini.google/release-notes/)); Dia Skills ([Thurrott](https://www.thurrott.com/cloud/web-browsers/322287/the-browser-company-explains-its-vision-for-dia)); Notion agent settings side sheet ([TestingCatalog](https://www.testingcatalog.com/notion-tests-agents-2-0-with-scripting-tools-and-workers.md))

## Patterns to avoid

1. **Constant layout churn.** Copilot's "sixth UI redesign in two years" and backtracking on the docked sidebar erode familiarity. Pick the one-sidebar/one-composer model and keep it stable. — [Notebookcheck](https://notebookcheck.net/Windows-11-Microsoft-backpedals-on-Copilot-decision.1306140.0.html)
2. **Expressive styling that costs density.** A reviewer says Gemini's Neural Expressive thin type and spacing are "a step backward" for utility. Keep Ichos dense and legible on desktop. — [Android Authority](https://www.androidauthority.com/gemini-neural-expressive-android-app-hands-on-3668985/)
3. **Removing navigation without a replacement.** Grok users reportedly lost the sidebar in Mar 2026 (unconfirmed claim). — [Grok UI Tools listing](https://addons.mozilla.org/addon/grok-ui-tools/)
4. **Metering or monetising retry/regenerate,** or putting ads mid-chat. This damages trust in the retry control. — Character.ai Charms ([aicompanionpick](https://aicompanionpick.com/character-ai-launches-new-features-in-2026-full-breakdown))
5. **A social or public feed of prompts in a personal assistant.** Meta's Discover feed is opt-in but still mixes private and public. That is wrong for a local-first app. — [AlternativeTo](https://alternativeto.net/news/2025/4/meta-ai-launches-standalone-app-for-android-and-ios-with-social-discover-feed-and-voice-mode)
6. **Hiding takeover inside an overflow menu.** ChatGPT agent puts "take control" under "…". Ichos should keep Take control and Stop as visible buttons, as Atlas's notification bar does. — [OpenAI Help mirror](https://help-lb.openai.com/en/articles/11752874-chatgpt-agent); [Willison](https://simonwillison.net/2025/Oct/21/introducing-chatgpt-atlas/)
7. **Agent mode that hides its plan.** Kimi critics found the agent opaque or "useless" in places. Ichos should always show the to-do list and files, and treat unseen progress as a failure. — [Ludditus critique](https://ludditus.com/?p=70393); [MIT index](https://aiagentindex.mit.edu/2025/kimi-ok-computer)
