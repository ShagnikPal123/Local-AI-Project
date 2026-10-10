# UI/UX of AI creative and generative-media tools (as of 2026-10-10), for Ichos

Scope: reusable UI patterns for generating, iterating on and organising AI-made media, for Ichos's chat-opened windows (Create / 3D-game studio / World / Office), "Pin as tab", and "design your own tab". Higgsfield, Google Stitch and Agent Studio are covered elsewhere and are not repeated.

Source quality: official docs fetched for Ideogram Studio and Krea release notes. Midjourney docs and Freepik docs returned HTTP 403, so those findings use official-doc search snippets. Third-party guides are labelled as such. Dates show when each item applies. "(older)" means before 2026.

---

## 1. Prompt surfaces: one box vs structured fields, pills, presets, reference slots, chips, enhance

### Takeaway
By late 2026 the most common shape is one prompt box with a row of pills: model, aspect ratio, length or count, and references. References are moving from fixed slots, like Whisk's old Subject/Scene/Style, to named reusable assets you call with "@". Cost is shown before you run. Structured fields remain only for domains with a real vocabulary, such as camera, colour and duration in video.

### Cited Findings
- **Midjourney:** the web app is the default surface for prompting, editing, organising, retexturing and video. The start screen has a top bar that asks "What will you imagine?" (third-party, 2026) — [Unilink 2026 guide](https://www.unilink.us/blog/how-to-use-midjourney-2026). The official site map lists Create, Edit, Organize, Personalize (build an aesthetic by rating images) and Moodboards (curated image sets that define a look) — [Midjourney docs, Website Overview](https://docs.midjourney.com/docs/explore-page).
- **Luma Dream Machine:** the prompt field sits at the bottom of the Board/Ideas page. You pick the model there (Ray2 / Ray2 Flash), the length (5–10 s) and the aspect ratio, then type (third-party, 2025) — [Magic Hour guide](https://magichour.ai/blog/how-to-use-luma-ai-dream-machine). You can start from text, an image, keyframes or an existing video — same source.
- **Krea, 2026:**
  - A "Multiple Models" toggle in the image tool runs one prompt across several models and shows the results side by side (2026-04-14). — [Krea release notes](https://www.krea.ai/release-notes)
  - Image and video tools show an estimated compute cost before a run (2026-09-07). — same source
  - The Krea Agent composer has a "free credits left" pill (2026-09-10). — same source
  - In Seedance Studio, you create "Elements" in a References panel and attach them by typing "@" in the prompt (2026-09-09). — same source
  - Seedance Studio's "Camera, Scene, and Color controls" set focal length, aperture and camera movement, with annotations and a 3D camera control with keyframes (2026-08-27). — same source
  - Video tools have an "add effects" library that suggests tags for your prompt (2026-04-16). — same source
- **Krea app redesign (2026-03-02):** "unified navigation, transparent model selection, drag-and-drop workflows, customizable workspace" — [Chase Jarvis summary](https://chasejarvis.com/?p=37796) / [dupple review, Aug 2026](https://dupple.com/reviews/krea-ai) (secondary).
- **Google Flow:**
  - Whisk and ImageFX merged into Flow in February 2026, and Whisk shut down on 2026-04-30 — [Pillitteri](https://pasqualepillitteri.it/en/news/1411/google-whisk-shuts-down-april-30-flow-migration).
  - Whisk used three fixed slots (Subject, Scene, Style) plus a refinement text area (older) — same source.
  - Flow's "Ingredients" are saved reference assets, such as a character, that later generations draw on. Ingredients-to-Video takes up to 3 reference images of one subject (third-party) — [whiskailabs guide](https://whiskailabs.net/google-flow-ai-complete-guide/).
- **Ideogram Studio:** "AI edit" accepts up to 14 reference images. Count is 1–4. Reframe offers 10 aspect ratios from 1:1 to 21:9 — [Ideogram docs, Studio](https://docs.ideogram.ai/edit/studio).
- **Recraft styles:**
  - The Styles panel has a "Feed" tab, an "infinite style library" you search by keyword (e.g. "comics", "3D", "line art"), and a "My styles" tab — [Recraft docs, Styles](https://www.recraft.ai/docs/recraft-studio/styles/overview).
  - You can combine up to 5 library styles or upload up to 5 of your own images, then use a slider to weight them — [Recraft blog](https://www.recraft.ai/blog/new-tools-for-brand-style-consistency-and-control).
  - Saved styles can be shared with a team — same source.
- **Firefly Boards:**
  - "Describe Image" turns any image into an editable prompt. — [creatorstoolbox on the global launch](https://creatorstoolbox.beehiiv.com/p/adobe-firefly-boards-launches-globally-bringing-powerful-ai-models-and-new-creative-features-to-idea)
  - A model picker includes Firefly, Nano Banana and GPT Image. — [Adobe Boards page](https://www.adobe.com/uk/products/firefly/features/boards.html)
- **Leonardo Flow State:** you type a prompt and press generate, then "scroll to ideate more". Free users see a daily-limit percentage wheel at the top right — [Leonardo help, Flow State](https://intercom.help/leonardo-ai/en/articles/10002805-flow-state). Leonardo expands the prompt "in a whole myriad of different ways" — [Forbes AU interview](https://www.forbes.com.au/news/innovation/leonardo-ai-founder-jj-fiasson-on-flow-state-phoenix-and-google-cloud/).
- **Figma Make:**
  - Prompts can include text, pasted Figma frames and attached designs. Figma suggests pasting components into the prompt box as a visual reference — [Figma help](https://help.figma.com/hc/en-us/articles/31304485164695); [Figma blog](https://www.figma.com/blog/8-ways-to-build-with-figma-make/).
  - The older "Point and edit" button sits at the bottom of the prompt box — [Figma help](https://help.figma.com/hc/en-us/articles/42009840449175).
- **Suno Studio 2.0 (2026-08-13):** added a chat bar (beta) inside the DAW, and MIDI clips can act as the prompt for new audio — [Suno blog, Studio 2.0](https://about.suno.com/blog/studio-2); [MusicTech](https://musictech.com/news/gear/suno-studio-2-0-upgrade-new-features/).
- **Krea realtime canvas:** an "AI Strength" slider controls how closely output follows your drawing. On iPad (2026-03-02) you can speak while drawing. Vendor-adjacent sources claim renders under 50 ms — [dupple review](https://dupple.com/reviews/krea-ai); [theplanettools](https://theplanettools.ai/tools/krea-ai).

### Inferences
- For Ichos Create: use one composer, the same component chat already uses, plus a pill row: [Model] [Aspect] [Count 1–4] [Style] [+ Ref]. Put a local cost or time estimate before Run. For a local-first app that means estimated seconds and VRAM, not credits.
- "@" references are the bridge between chat and the media window. A saved character, style or scene in Ichos could be @-mentioned from chat or from any tool window.
- Use structured controls only where the domain needs them: camera and duration for video, BPM and key for music, polycount and format for 3D.

### Gaps
- Midjourney's current Create-page settings panel. My pre-2026 recall: aspect slider, Stylization/Weirdness/Variety sliders, Speed (Relax/Fast/Turbo), and an Image/Style/Omni reference drop zone in the imagine bar. Docs returned 403, so this is unverified for October 2026.
- "Enhance prompt" was not confirmed for any product in this sweep. Leonardo's automatic prompt expansion is the closest evidence.
- Pika, Kling's standalone app, Canva Magic Studio, Framer AI and Udio prompt surfaces: searches returned nothing usable.

---

## 2. Generation feedback: queues, progress, placeholders, variant counts and layout, per-result actions

### Takeaway
Variant counts have settled at 1–4 per run. Midjourney's 2×2 grid is the reference. Ideogram Studio and others let you pick a count of 1–4. Per-result actions follow a stable set: Vary (subtle/strong), Upscale, Remix, Rerun/Regenerate, Extend/Reframe, Use as reference, Download. Krea and Leonardo add a cross-model comparison and an endless "flow" of variants. Flow State and Midjourney show generation inline, with no separate queue page.

### Cited Findings
- **Midjourney variations:**
  - Click an image on Create or Organize to open it, then find "Creation Actions" → Vary → Subtle or Strong, and "your variations will immediately start generating" — [Midjourney docs, Variations](https://docs.midjourney.com/docs/variations).
  - If Vary is hidden, use "More options" to add it to the visible actions (a user-configurable action set) — same source.
  - Subtle keeps composition and colour. Strong changes composition and element count — same source.
  - Remix Mode lets you edit the prompt while varying — same source.
- **Ideogram Studio:**
  - Every canvas-tool run adds a thumbnail to a bottom "Version strip". Use ←/→ to switch versions, and Undo also steps back through switches. "+" duplicates the current version with its layers. Deleting asks you to confirm with "Delete image" — [Ideogram docs, Studio](https://docs.ideogram.ai/edit/studio).
  - Upscale offers 2x, 4x and "Ultra 8x". Sizes above 8192×8192 are greyed out rather than hidden — same source.
- **Krea:** the "Multiple Models" toggle shows results from several models side by side (2026-04-14). Cost is estimated before the run (2026-09-07) — [Krea release notes](https://www.krea.ai/release-notes).
- **Krea Node Agent (2026-03-18):** reads the canvas, proposes a pipeline and shows compute cost "before anything runs" — [yespress Krea summary](https://yespress.io/krea) (secondary).
- **Leonardo Flow State:** a continuous scroll of variants. "More Like This" on any image generates style variations of it — [Leonardo help](https://intercom.help/leonardo-ai/en/articles/10002805-flow-state). Variants differ in "vibe, angles, colour grading and lighting" — [Forbes AU](https://www.forbes.com.au/news/innovation/leonardo-ai-founder-jj-fiasson-on-flow-state-phoenix-and-google-cloud/).
- **Luma:** the recommended loop is to describe one shot, generate alternatives, then refine the best. Draft mode speeds up tests before a final render (third-party) — [Magic Hour](https://magichour.ai/blog/how-to-use-luma-ai-dream-machine).
- **Sora app (launch Sept 30 2025, older):** you remix any video "by simply describing the changes you want". Scrolling sideways on a video shows every remix of it — [The Neuron](https://www.theneuron.ai/explainer-articles/your-complete-guide-to-ai-video-memes-and-mayhem-with-openais-sora-2).
- **Runway workflows:** you can run a single node or the whole workflow — [Runway Academy](https://academy.runwayml.com/workflows/using-workflows). From 2026-08-20, agents can open a workflow from chat in the web editor, edit it and run it — [Runway changelog](https://runway.com/en/changelog).

### Inferences
- Ichos needs one result-card component with a fixed action set: Vary·subtle, Vary·strong, Upscale, Remix (edit prompt), Rerun, Use as ref, Pin/Save, Download. Make the visible actions configurable, like Midjourney's "More options".
- Add an Ideogram-style version strip to every editor window. It gives non-destructive history for free and matches Ichos's local undo model.
- Generation in progress should be a placeholder tile in the same grid slot, not a separate queue page. A "Multiple Models" compare row fits Ichos well because local models are free to run side by side.

### Gaps
- Exact placeholder and progress visuals (blur-in, percentage, shimmer) for Midjourney, Runway, Kling and Pika were not documented in sources I could reach. From pre-2026 recall, Midjourney shows a blurred progressive preview with a percentage. This is unverified.
- Queue UIs: no source described a dedicated multi-job queue panel for any of these products in 2026.

---

## 3. Galleries and organisation: grids, collections, history, recreate/remix, prompt transparency

### Takeaway
Organising is moving from flat history to three levels: (a) a personal searchable library (Midjourney Organize), (b) curated sets that also act as style inputs (Midjourney Moodboards, Krea Moodboards, Recraft "My styles", Flow Ingredients), and (c) a public feed where every item can be remixed (Midjourney Explore, Krea gallery, Sora feed). The best pattern is that a collection is also a generation input.

### Cited Findings
- **Midjourney Organize:** "the hub for managing everything you create", with search, filter and sort across images and videos — [Midjourney docs, Website Overview](https://docs.midjourney.com/docs/explore-page). Moodboards hold curated image sets that create a look. Personalize builds an aesthetic by rating images — same source.
- **Krea:**
  - Moodboards can be shared with a right-click and "Share". The dialog has "Create public link" and a "Link sharing" toggle (2026-05-13). — [Krea release notes](https://www.krea.ai/release-notes)
  - The gallery has a new feed layout with arrow navigation, and you can copy style references from it (2026-05-14/15). — same source
  - Workspace list has an "Add tags" picker (2026-09-16). — same source
- **Recraft:**
  - The Styles "Feed" is an infinite style library with search and type filters. "My styles" holds your saved styles — [Recraft docs](https://www.recraft.ai/docs/recraft-studio/styles/overview).
  - The full Infinite Canvas is desktop-only. Mobile is limited to prompt, style selection, style training and PNG download — [Recraft llms.txt](https://www.recraft.ai/llms.txt).
- **Google Flow:** Ingredients act as an asset-management layer for characters and prompts (third-party) — [whiskailabs](https://whiskailabs.net/google-flow-ai-complete-guide/).
- **Sora (older, launch-era):**
  - A vertical feed with Top / Latest / Following filters and autoplay with sound. — [zilliz FAQ](https://zilliz.com/ai-faq/how-is-soras-feed-social-app-designed-and-what-are-its-content-dynamics)
  - Remixes are threaded sideways from the original. — [The Neuron](https://www.theneuron.ai/explainer-articles/your-complete-guide-to-ai-video-memes-and-mayhem-with-openais-sora-2)
  - For cameos, every video featuring you is visible to you, and you can revoke access. — [Influencer Marketing Hub](https://influencermarketinghub.com/sora-2-ai-video-social-app/)
- **Krea Nodes:** workflows can be shared, and community templates serve as starting points — [Krea docs, Nodes](https://www.krea.ai/docs/de/user-guide/features/nodes.md).
- **Firefly Boards:** has a presentation mode for clients and real-time co-editing — [Adobe Boards page](https://www.adobe.com/uk/products/firefly/features/boards.html).
- **Runway Team plan (2026-09-04):** shared projects in one workspace, plus comments on individual generations — [Runway changelog](https://runway.com/en/changelog).
- **ElevenLabs Voice Library:**
  - Organised by gender, age, accent and use case. Previews play without spending credits (third-party review). — [hackceleration review](https://www.hackceleration.com/elevenlabs-review)
  - "10,000+ voices" — [ElevenLabs Studio page](https://join.elevenlabs.io/studio)
- **Luma:** suggests stamping model and settings on each Board tile for reproducibility (third-party advice, not a shipped feature) — [Magic Hour](https://magichour.ai/blog/how-to-use-luma-ai-dream-machine).

### Inferences
- Ichos can map these to local equivalents:
  - Library = all outputs across windows, searchable by prompt, model and date.
  - Boards/Moodboards = collections that also act as a style input, @-mentionable from chat.
  - No public feed. Instead, show the "recipe" (prompt, model, seed, refs) on every item with "Recreate" and "Remix" buttons. This gives the prompt-transparency benefit of Explore without a social layer.
- Previewing assets such as voices, styles and models should cost nothing and play instantly. Make audition free.

### Gaps
- Midjourney Organize's exact filter controls (folders, smart folders, sort keys) and Explore's "use prompt/use image" buttons could not be confirmed (403).
- Kling, Pika and Udio library UIs were not covered by sources I could reach.

---

## 4. Canvas/editor patterns: infinite canvas, layers, inpainting, realtime preview, timeline

### Takeaway
Three editor shapes now dominate:
1. **Infinite board** (Firefly Boards, Ideogram Studio, Recraft, Luma Boards): mixed media plus generation in place.
2. **Node canvas** (Krea Nodes, Freepik Spaces, Runway Workflows, tldraw computer): chained models, each node runnable on its own.
3. **Timeline** (ElevenLabs Studio, Suno Studio 2.0, Flow SceneBuilder): blocks on tracks.

All three now carry an embedded agent or chat bar that can read and edit the canvas. Region editing has moved from one mask to several regions, each with its own prompt.

### Cited Findings
- **Ideogram Studio layout** (the former Canvas, renamed "Studio") — [Ideogram docs, Studio](https://docs.ideogram.ai/edit/studio):
  - Left toolbar: Select, Upload, My Images, Text.
  - Right sidebar: Canvas tools when nothing is selected, plus a resizable Layers list. Selecting a layer swaps in that layer's tools.
  - Bottom: Version strip.
  - Bottom right: Undo, Redo, zoom 50–300% (click the badge to fit).
  - Top left: "Studio" label, which reads "Exit" on hover.
  - Top right: credit balance and Export.
  - Layer tools: Replace image, AI edit, Remix, Extend, Crop, "Select area" (brush 10–80) → Generate, Upscale, Remove background, Layerize text.
  - "Quick edit": press Tab, or use a floating bar with Duplicate, Download, Delete and More.
  - Space+drag pans.
- **Ideogram Magic Fill (older, Oct 2024):** mask → "Next" → adjust the position and size of the generation window. Extend outpaints — [Ideogram Canvas page](https://ideogram.ai/features/canvas/).
- **Krea Edit (2026-03-26):** "multiple marked-up regions, each with its own prompt, generated in a single pass" — [dupple review](https://dupple.com/reviews/krea-ai) (secondary).
- **Krea Nodes:** an infinite canvas that chains image, video, audio and 3D models. You connect inputs, parameters and outputs — [Krea docs, Nodes](https://www.krea.ai/docs/de/user-guide/features/nodes.md).
- **Freepik Spaces:**
  - Infinite canvas, left node panel (groups: Media, Text, Image, Video, Audio, Utilities, Designer) and a top toolbar.
  - Minimap at bottom right.
  - Space bar or "/" opens "Spotlight", a command palette.
  - Real-time collaboration with notes pinned to frames or nodes. — [Freepik docs, Getting started](https://www.freepik.com/ai/docs/your-first-space) (via search snippet; fetch 403); [BusinessWire launch, 2025-11-04](https://www.businesswire.com/news/home/20251104023735/en/Freepik-Launches-Freepik-Spaces-to-Power-AI-Visual-Creation-and-Collaboration-in-Real-Time)
- **Runway Workflows:** right-click the canvas to add nodes. Click to move, Delete to remove. Run one node or the whole graph — [Runway Academy](https://academy.runwayml.com/workflows/using-workflows).
- **Firefly Boards:**
  - One canvas holds imported images and video, generated variations, Stock, shapes, text and multiple artboards — [josephnilo.com](https://josephnilo.com/blog/adobe-firefly-boards/).
  - 2D→3D conversion on the canvas — [Adobe](https://www.adobe.com/uk/products/firefly/features/boards.html).
  - Hands off to Premiere for finishing, shown at NAB 2026 — [CineD](https://www.cined.com/adobe-firefly-at-nab-2026-from-location-scout-to-premiere-timeline-with-ai/).
- **Figma Make:**
  - The newer "Edit tool and properties panel" stages edits above the prompt box until you click "Apply". You can shift-select several elements. — [Figma help](https://help.figma.com/hc/en-us/articles/42009840449175)
  - Annotations dropped on the rendered UI are sent together as one prompt. — same source
  - You can view and edit the generated code in a built-in editor. — [Figma](https://www.figma.com/solutions/ai-code-generator/)
- **tldraw:** "Make Real" turns a selected area of the canvas into working HTML/CSS through a vision model (Nov 2023, older) — [tessl talk summary](https://tessl.io/registry/skills/github/jscraik/Agent-Skills/talk-ruiz-agents-on-canvas-tldraw). The 2026 direction is visible agents ("fairies") working on the canvas. Ruiz argues this feels more natural than delegating through a sidebar — [AI Engineer talk](https://ai.engineer/talks/agents-on-the-canvas-in-tldraw); [GitNation](https://gitnation.com/contents/agents-on-the-canvas-with-tldraw).
- **ElevenLabs Studio:**
  - A timeline at the bottom holds audio blocks, one per text section. Blocks can be reordered, trimmed and spaced. — [feisworld 2026 tutorial](https://www.feisworld.com/blog/elevenlabs-tutorial)
  - Voiceover, music and SFX sit on one timeline. You can import MP4/MOV. Different voices can be assigned to different script sections. — [ElevenLabs Studio](https://join.elevenlabs.io/studio)
  - Shared links take time-stamped comments. — same source
  - The old Voiceover Studio was discontinued on 2026-05-15. — [ElevenLabs docs](https://elevenlabs.io/docs/de/eleven-creative/audio-tools/voiceover-studio)
- **Suno Studio 2.0:**
  - Multitrack browser timeline with MIDI, audio recording, a wavetable synth, effects (compressor with sidechain, EQ, reverb, delay…), automation, stem split, and 32-bit/48 kHz export.
  - No phones, no Safari Web MIDI, no VST hosting. — [Suno blog](https://about.suno.com/blog/studio-2); [Dubspot](https://blog.dubspot.com/suno-studio-2-0)
  - MusicTech rated v1 6/10 in Jan 2026 — [MusicTech review](https://musictech.com/reviews/digital-audio-workstations/suno-studio-review/).
- **Google Flow SceneBuilder:** a timeline where you drag clips and images into order, adjust timing, add transitions, preview and export. Chained clips run roughly 1–2.5 minutes (third-party) — [whiskailabs](https://whiskailabs.net/google-flow-ai-complete-guide/).
- **Krea realtime:** output updates as you type, draw, move shapes, stream a webcam or share a screen — [theplanettools](https://theplanettools.ai/tools/krea-ai). Realtime Director takes prompt-only input plus an optional first-frame reference (2026-09-07) — [Krea release notes](https://www.krea.ai/release-notes).
- **3D:**
  - Meshy: text/photo→3D, remesh, AI texturing, animation, export to engines and printers. — [SelfCAD Meshy vs Tripo](https://www.selfcad.com/blog/meshy-vs-tripo)
  - Tripo: text/image→3D, texturing, auto-rigging, segmentation, retopology; exports FBX/OBJ/STL/GLB/USD/3MF. — [Krea blog, best 3D generators 2026](https://www.krea.ai/blog/best-ai-3d-model-generators-2026)
  - Spline: AI text-to-3D inside a collaborative editor; exports React/Three.js. Source is competitor-promotional. — [Neural4D](https://blog.neural4d.com/?p=1104)

### Inferences
- For Ichos windows:
  - **Create:** Ideogram Studio's layout is a near-direct template. Tools on the left, a context panel on the right that changes with selection, a version strip at the bottom, zoom bottom right, Exit top left, Export top right.
  - **3D/game studio:** viewport plus a right panel with Texture, Remesh, Rig and Export (GLB first) as the pipeline steps.
  - **Studio timeline (audio/video):** ElevenLabs-style blocks on tracks.
  - **"Design your own tab":** best served by a Freepik/Krea node canvas with a Spotlight ("/") palette and per-node Run.
- Figma Make's "stage edits above the prompt, then Apply" pattern suits Ichos's agent edits to a pinned tab. The agent proposes, the user sees a diff chip, then applies.
- tldraw's "visible agent on the canvas" argument supports showing Ichos's agent as a cursor or presence inside the window, not only as chat text.

### Gaps
- Runway's current editor (timeline vs canvas), Pika's editor, Kling's Motion Brush and Canva's Magic Edit were not documented by reachable 2026 sources.
- Spline AI's and Meshy's actual workspace layouts were not found in primary docs. 3D details are secondhand.

---

## 5. Visual identity: colour, type, radii, density; quiet chrome

### Takeaway
Few vendors publish measurable tokens, and I could not extract live CSS in this sweep. The observable structural pattern is consistent: media fills the space, chrome lives at the edges, prompt and actions float or dock, and controls appear on selection or hover.

### Cited Findings
- **Ideogram Studio chrome:**
  - Edge-docked: left toolbar, right panel, bottom strip, corner zoom. The Studio label only turns into "Exit" on hover. A floating Quick-edit bar appears on selection. — [Ideogram docs](https://docs.ideogram.ai/edit/studio)
  - Unavailable options are greyed out rather than hidden (Upscale sizes, Regenerate for uploads). — same source
- **Freepik Spaces:** node panel left, toolbar top, minimap bottom right, command palette on "/" — [Freepik docs](https://www.freepik.com/ai/docs/your-first-space).
- **Midjourney:** hidden actions are revealed through "More options" so the default set stays short — [Midjourney docs, Variations](https://docs.midjourney.com/docs/variations).
- **Credit meters:**
  - Ideogram puts the credit balance at top right next to Export. — [Ideogram docs](https://docs.ideogram.ai/edit/studio)
  - Leonardo shows a percentage wheel at top right. — [Leonardo help](https://intercom.help/leonardo-ai/en/articles/10002805-flow-state)
  - Krea puts a "free credits left" pill inside the composer. — [Krea release notes](https://www.krea.ai/release-notes)
  - All are small and corner-placed.

### Inferences
- Ichos should keep chrome on the window edges, show tools on selection, keep one accent colour, and put the meter in a corner. For a local-first app, swap credits for a GPU/VRAM or queue chip.

### Gaps
- Measurable tokens (hex, fonts, radii) for Midjourney, Krea, Runway, Luma, Suno and ElevenLabs could not be verified. Getting them requires inspecting live CSS, which was not done in this sweep. From pre-2026 recall: Midjourney's web app is near-black with white type and small radii, and Runway and Krea are dark-first. These are unverified. Do not use them as tokens.

---

## Patterns Ichos should adopt

1. **One composer with a pill row** (Model · Aspect · Count 1–4 · Style · +Ref) and a cost/time estimate before Run. Sources: Krea release notes (cost estimate, Multiple Models), Luma prompt field, Ideogram Count 1–4.
2. **"@"-mentionable reusable references** (characters, styles, scenes) shared by chat and every window. Sources: Krea Seedance "Elements" via "@" (2026-09-09); Google Flow Ingredients.
3. **Fixed per-result action set** (Vary subtle/strong, Upscale, Remix, Rerun, Use as ref, Save, Download) with user-configurable visibility. Source: Midjourney Creation Actions plus "More options".
4. **Bottom version strip with ←/→ keys and "+" duplicate**, where Undo also steps through versions. Source: Ideogram Studio.
5. **Edge-docked editor layout**: tools left, a right panel that changes with selection (with Layers), Exit top left, Export and meter top right, zoom bottom right, floating quick-edit bar on Tab. Source: Ideogram Studio.
6. **Multi-region edit**: several masked regions, each with its own prompt, run in one pass. Source: Krea Edit (2026-03-26).
7. **Side-by-side multi-model compare**, especially cheap with local models. Source: Krea "Multiple Models" (2026-04-14).
8. **Endless "flow" mode with "More like this"** for low-stakes ideation. Source: Leonardo Flow State.
9. **Collections that double as style inputs** (moodboards/styles), with a library feed and a "My styles" tab. Sources: Midjourney Moodboards/Personalize; Recraft Styles Feed and My styles; Krea Moodboards.
10. **Visible recipe on every item** (prompt, model, seed, refs) with Recreate/Remix. Sources: Midjourney Explore/Organize; Luma reproducibility guidance; Krea gallery "copy style references".
11. **Node canvas with a Spotlight palette ("/" or Space), minimap, and per-node Run** for "design your own tab". Sources: Freepik Spaces; Runway Workflows; Krea Nodes.
12. **Agent that reads the canvas and proposes a pipeline, showing cost before anything runs.** Sources: Krea Node Agent (2026-03-18); Runway agents opening workflows from chat (2026-08-20).
13. **Staged agent edits ("changes appear above the prompt box", then Apply)** for agent changes to pinned tabs. Source: Figma Make Edit tool.
14. **Annotations on the output, submitted together as one prompt.** Sources: Figma Make annotations; tldraw Make Real.
15. **Block timeline for audio/video** (one block per script section, reorder/trim/space, per-section voice, time-stamped comments). Sources: ElevenLabs Studio; Google Flow SceneBuilder.
16. **Chat bar inside the pro editor**, not only outside it. Sources: Suno Studio 2.0 chat bar (beta); Runway MCP workflows.
17. **Free, instant audition** of voices, styles and models before generating. Source: ElevenLabs voice library previews.
18. **Realtime mode with a "strength/adherence" slider** for drawing in Create. Source: Krea realtime "AI Strength".
19. **Presentation/share mode for a board** (useful for the World/Office windows). Sources: Firefly Boards presentation mode; Krea Moodboard "Create public link".
20. **3D pipeline as ordered steps** (Generate → Texture → Remesh → Rig → Export GLB/FBX). Sources: Tripo and Meshy feature sets (secondhand).

## Patterns to avoid

1. **Fixed, unlabeled reference slots** (Whisk's Subject/Scene/Style). The product was folded into Flow and shut down on 2026-04-30 in favour of named Ingredients — [Pillitteri](https://pasqualepillitteri.it/en/news/1411/google-whisk-shuts-down-april-30-flow-migration).
2. **Node canvas as the default entry point for beginners.** Reviews call Freepik Spaces "overwhelming for beginners used to simple text-to-image prompts" — [framia review](https://framia.converge.ai/it/blog/freepik-review). Offer it as an advanced tab, not the first screen.
3. **Hiding the canvas on smaller form factors without saying so.** Recraft keeps the Infinite Canvas desktop-only — [Recraft llms.txt](https://www.recraft.ai/llms.txt). If Ichos windows drop features when narrow, say so in the UI.
4. **Infinite feeds that silently burn budget.** Leonardo Flow State scrolling consumes daily allowance — [Leonardo help](https://intercom.help/leonardo-ai/en/articles/10002805-flow-state). In Ichos, cap auto-generation and show the cost or GPU time.
5. **Social, autoplay-with-sound feeds as the organising surface.** Sora's TikTok-style feed (launch-era) is the wrong model for a private, local-first assistant — [zilliz](https://zilliz.com/ai-faq/how-is-soras-feed-social-app-designed-and-what-are-its-content-dynamics).
6. **Edits that charge silently.** Figma Make's properties-panel tweaks consume AI credits — [Figma help](https://help.figma.com/hc/en-us/articles/42009840449175). Mark any control that triggers a model run.
7. **Shipping a "pro editor" too thin to replace the real tool.** Suno Studio v1 scored 6/10, with no VST/DAW sync — [MusicTech](https://musictech.com/reviews/digital-audio-workstations/suno-studio-review/). Ichos windows should export cleanly to real tools (GLB, WAV stems, PNG layers) rather than imitate them.
8. **Duplicate product surfaces that later need migration.** ElevenLabs retired Voiceover Studio for Studio on 2026-05-15 — [ElevenLabs docs](https://elevenlabs.io/docs/de/eleven-creative/audio-tools/voiceover-studio). Build one window framework for Create, 3D, World and Office, not one per feature.
