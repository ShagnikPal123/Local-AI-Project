# Voice assistant UX: custom voice commands, wake phrases and multi-step routines (as of October 2026)

Scope: patterns for Ichos (local-first Windows 11 desktop assistant, browser mic capture + Python backend) so the owner can record their own commands ("open up", "warm up my game") that trigger fixed-step, gated routines. Research date 2026-10-10. Searches covered about 16 tool calls, so some products are thin (see Gaps).

## 1. Consumer routines UX: how people create, name, test, edit and debug voice routines

### Takeaway
Every major system builds a routine the same way: a trigger phrase you type or say, then an ordered list of typed actions picked from a fixed menu, with an explicit Wait step and a cap on length. Testing is weak almost everywhere. The best debugging aid is Alexa's: it shows what the recognizer actually heard, and you then copy that wording into the trigger. Confirmation-before-running exists as a per-routine toggle (Apple), not as a per-step risk model.

### Cited Findings
**Windows Voice Access (closest analogue to Ichos, same OS)**
- Voice shortcuts are created in the "Voice access commands" window: Voice shortcuts > Create new shortcut > "When I say" (type or dictate the phrase) > "Perform action(s)" drop-down > Apply > choose group > Save. — [Microsoft Support](https://support.microsoft.com/en-us/Accessibility/windows/voice-access/use-voice-to-create-voice-access-shortcuts); [ElevenForum tutorial](https://elevenforum.com/t/create-voice-shortcuts-for-custom-commands-in-voice-access-in-windows-11.20715/)
- There are exactly five action types: Paste text and media; Open folders/files/applications/URL; Press keyboard keys; Press mouse click; Add wait time. — [Microsoft Support](https://support.microsoft.com/en-us/Accessibility/windows/voice-access/use-voice-to-create-voice-access-shortcuts)
- A shortcut can chain "a maximum of eight actions"; you add steps with "Click add next action". No variables or placeholders in phrases are documented, and no test or preview step is documented. — [Microsoft Support](https://support.microsoft.com/en-us/Accessibility/windows/voice-access/use-voice-to-create-voice-access-shortcuts). One third-party blog claims only single actions are supported, which contradicts Microsoft — [Spokenly](https://spokenly.app/blog/voice-access-windows-11)
- To manage a shortcut: "Toggle <name>" enables or disables it; you edit through its edit page; Delete is a button there. Available in English (US, UK, India, NZ, Canada, Australia) only. — [Microsoft Support](https://support.microsoft.com/en-us/Accessibility/windows/voice-access/use-voice-to-create-voice-access-shortcuts)
- The required builds were 22631.3374 (stable) and later. — [ElevenForum](https://elevenforum.com/t/create-voice-shortcuts-for-custom-commands-in-voice-access-in-windows-11.20715/); [GeekRewind](https://geekrewind.com/learn-how-to-list-and-create-custom-voice-access-commands-in-windows-11)

**Amazon Alexa Routines**
- Trigger = a phrase you choose ("When you say"); you then add multiple actions and can reorder them. — [Online Tech Tips](https://www.online-tech-tips.com/how-to-create-a-routine-with-amazon-alexa/); [Tom's Guide](https://www.tomsguide.com/us/how-to-create-an-alexa-routine%2Creview-4931.html)
- A "Custom" action is typed "just as you might say by voice, but without the wake word". There is a **"Preview this action"** button to check that Alexa responds correctly. — [Amazon help](https://digprjsurvey.amazon.com/csad/help/node/GLXY7RFX3L5GH2VR)
- Debugging pattern: open **Activity > Voice History** to see what Alexa heard, then put the wording that works into the action. — [Amazon help](https://digprjsurvey.amazon.com/csad/help/node/GLXY7RFX3L5GH2VR)
- If steps overlap, Amazon advises inserting a Wait action. Waits can be up to 4 hours. — [Amazon help](https://digprjsurvey.amazon.com/csad/help/node/GLXY7RFX3L5GH2VR); [Online Tech Tips](https://www.online-tech-tips.com/how-to-create-a-routine-with-amazon-alexa/)
- Trigger matching is brittle: a routine on "when is bedtime" did not fire for "what time is bedtime". — [Online Tech Tips](https://www.online-tech-tips.com/how-to-create-a-routine-with-amazon-alexa/)

**Google Home (script editor, Gemini "Help me create")**
- "Help me create" (Gemini for Home) generates an automation from a natural-language description, which the user then customizes before saving. It needs Google Home Premium, is limited to non-minor home admins, and some devices are unsupported. — [Google Nest Help](https://support.google.com/googlenest/answer/15684131)
- Example prompt: "At 11 pm when someone is home, turn off lights, TV, change temp to 68 degrees, and broadcast bed time on all my speakers." — [Google Nest Help](https://support.google.com/googlenest/answer/15684131)
- The older "Help me script" generated YAML code for the script editor, which the user pasted in and activated. — [Google blog](https://blog.google/products/google-nest/google-home-custom-routines-ai/); [9to5Google](https://9to5google.com/2024/12/05/google-home-help-me-create/)

**Apple Shortcuts**
- Personal automations default to asking for confirmation. Turning off "Ask Before Running" requires a second confirm ("Don't Ask"), after which the automation runs silently. Some triggers (e.g. "Before I Commute") can never run automatically. Individual actions may also need to be set to run automatically. — [Apple Shortcuts User Guide](https://support.apple.com/guide/shortcuts/apd602971e63/ios)
- After a Siri-run shortcut, Siri speaks a completion line ("That's done"), and users look for ways to suppress it. — [iMore](https://www.imore.com/stop-siri-announcing-shortcut-has-finished-simple-tip)

**Samsung Bixby Routines / Modes**
- Routines are built as If (conditions, add more with "Add condition") / Then (actions). Recommended routines can be edited. — [Samsung US Support](https://www.samsung.com/us/support/answer/ANS10002624/)
- Modes (Sleep, Driving, Exercise, Relax, Work, Custom) can be switched on automatically or manually. — [Samsung Community (One UI 5)](https://r2.community.samsung.com/t5/Tech-Talk/Lifestyle-Modes-Bixby-Routines-One-UI-5/m-p/16228986/highlight/true)

**Home Assistant Assist**
- The simplest custom voice command is an automation with a **Sentence trigger**: list several phrases (no punctuation), and any of them fires the automation. — [HA: custom sentences](https://www.home-assistant.io/voice_control/custom_sentences/)
- Advanced use: extend built-in intents (e.g. make "activate" mean "turn on") or define new intents in config, with `intent_script` able to run any action and return a spoken response. — [HA docs: Assist custom sentences](https://www.home-assistant.io/docs/assist/custom_sentences)
- The community has asked to map different wake words to different pipelines; this is not supported yet. — [HA Community](https://community.home-assistant.io/t/allow-assist-pipelines-to-be-selected-based-on-on-device-wake-word/1017008)

**Talon Voice**
- Commands live in plain-text `.talon` files. Above a `-` line is a context header (e.g. `app.name: Chrome`), and below it are lines of the form `phrase: action`. Example: `hello talon: "hello world"`. Lists are kept in Python or CSV files that Talon can open for editing. — [Talon docs](https://talonvoice.com/docs/); [ejfox wiki](https://archive.ejfox.com/wiki/Talon_Voice_Control)

### Inferences
- The common pattern is phrase plus an ordered list of fixed, typed actions plus a Wait step plus a length cap (Windows: 8). This matches the Ichos constraint that routines are data with fixed step types. Windows Voice Access is the closest same-platform precedent, and its 8-step cap is a sensible default.
- Alexa's "what I heard" history is the strongest debugging pattern found. Ichos should store and show the transcript that matched (or nearly matched) each phrase.
- Exact-phrase triggers fail on paraphrase (the Alexa "bedtime" case). Letting the user list several phrasings (HA's multiple sentences per trigger) is the cheap fix. Gemini or LLM-based fuzzy intent is the expensive one.
- Apple's model (confirm by default, the user can turn it off with a double confirm) is the closest to Ichos's "ask once before first run".

### Gaps
- No source found on Dragon (Nuance) custom commands as of 2026, Google Home's script-editor test/debug UI, or Bixby voice-triggered routines. Only the general If/Then pattern was confirmed.
- No consumer system was found that documents per-step risk confirmation (e.g. confirm only before "close app"). This appears to be an open design space.

## 2. Realtime voice UI: states, barge-in, captions, mute, push-to-talk

### Takeaway
2025–26 voice UIs converge on a few visible states (idle, listening, thinking, speaking, interrupted) around an animated orb or waveform, with barge-in as table stakes. The new trend is that the assistant interrupts the user *less* (it waits through pauses). Barge-in sensitivity is a tunable threshold in the hundreds of milliseconds, and the client must flush queued audio itself.

### Cited Findings
- ChatGPT moved voice into the main chat window in November 2025 (on by default; "Separate Mode" stays in Settings > Voice). The old standalone screen was the blue orb, with a mute button, live video, and an X to exit. — [CreateWith](https://www.createwith.com/tool/chatgpt/updates/chatgpt-integrates-voice-mode-directly-into-main-chat-interface); [SpeedGuide](https://speedguide.net/news/now-you-can-use-chatgpt-voice-without-leaving-your-chat-8705)
- Mid-2026 reports describe a full-duplex ChatGPT voice model (reported as gpt-bidi-1 / GPT-Live-1; names conflict between sources) built to interrupt users less. It waits through mid-sentence pauses and can be told to stay silent until spoken to. Reports say the older mode "freezes" when the user talks over it. — [Noqta](https://noqta.tn/en/news/openai-gpt-bidi-1-bidirectional-voice-chatgpt-2026); [Mezha](https://mezha.ua/en/news/gpt-live-1-voice-mode-313064/amp/); [AINauten](https://news.ainauten.com/markdown/chatgpts-upgraded-voice-mode-is-better-at-shutting-up). These are secondary sources, and the model names are inconsistent.
- Hume EVI: when user speech is detected during a response, EVI stops generating and sends a `user_interrupt` message (the docs also say `user_interruption`). The **client** must stop playback and clear queued audio. `min_interruption_ms` (default 800 ms, range 50–2000 ms) sets how long the user must speak before EVI yields. — [Hume docs: interruptibility](https://dev.hume.ai/docs/speech-to-speech-evi/features/interruptibility); [Hume docs: interruption config](https://dev.hume.ai/docs/speech-to-speech-evi/configuration/interruption)
- Gemini Live has a "Tap to interrupt" control and an "Interrupt Live responses" on/off setting. Captions show only Gemini's speech, not the user's live transcript (the user's transcript is available after the session). Captions sit mid-screen in audio mode and at the top during video. — [9to5Google](https://9to5google.com/2025/06/25/gemini-live-android-captions/); [9to5Google](https://9to5google.com/2025/06/05/gemini-live-captions/); [Android Authority](https://www.androidauthority.com/gemini-live-captions-apk-3526862)
- Pipecat (an open-source voice agent framework) treats interruptions as a core pipeline concept. — [Pipecat docs](https://docs.pipecat.ai/pipecat/fundamentals/interruptions.md)

### Inferences
- Ichos's notch should show at least: idle, armed (wake detection only), listening (capturing a command), thinking/matching, speaking, interrupted, muted. A routine-run state with step progress is Ichos-specific and adds a "running n/m" state.
- Barge-in for Ichos's spoken lines: stop TTS on detected speech after about 300–800 ms of voice (Hume's default is 800 ms), and flush the queue on the client.
- Captions for both sides (user transcript plus assistant line) help a command-matching app more than Gemini's assistant-only captions, because seeing what was heard is the debugging tool (see §1).

### Gaps
- No sources were retrieved on Copilot Voice, Sesame, or the 2026 Siri UI states. Push-to-talk availability in ChatGPT 2026 is unconfirmed. No official Google state-machine spec for Gemini Live was found.

## 3. Wake word and custom phrase technology (local and free first)

### Takeaway
For a free, local, English stack on Windows in 2026: **openWakeWord** (Apache-2.0 code, ONNX on Windows, but non-commercial models and a heavy, aging training pipeline) for a fixed wake phrase, and **text-level matching on a local ASR transcript** (Vosk with a restricted phrase list, or a sherpa-onnx keyword spotter with per-keyword thresholds) for owner-defined command phrases. Picovoice Porcupine is no longer a free option: its free tier ended on 30 June 2026. Azure custom keyword is free to build but cloud-tooled and limited to en-US and zh-CN.

### Cited Findings
**openWakeWord**
- Default threshold 0.5. Targets: false-reject under 5% and false-accept under 0.5 per hour. Optional Silero VAD gate (`vad_threshold`) cuts non-speech false triggers. Speex noise suppression is Linux only. — [openWakeWord README](https://github.com/dscripka/openWakeWord)
- Audio: 16-bit, 16 kHz PCM in 80 ms multiples. Windows installs onnxruntime only (no tflite). English only. A Raspberry Pi 3 core runs 15–20 models in real time. — [openWakeWord README](https://github.com/dscripka/openWakeWord)
- Licence: code Apache 2.0; pre-trained models **CC BY-NC-SA 4.0** (non-commercial). — [openWakeWord README](https://github.com/dscripka/openWakeWord)
- **Custom verifier models**: speaker-specific second-stage filters that pass only activations likely from known voices, at the cost of responsiveness to new voices. This is the closest built-in "speaker verification". — [openWakeWord README](https://github.com/dscripka/openWakeWord)
- Models are trained on 100% synthetic TTS speech, augmented with rooms, distances and noise, so the user does not record samples. But the official training pipeline pins 2022-era PyTorch 1.13.1 and TF 2.8.1. Community Colab fixes report about 75–90 min on Colab Pro. A Docker pipeline needs an NVIDIA GPU and about 45 GB of disk. — [openwakeword-colab-2026](https://github.com/alfiedennen/openwakeword-colab-2026); [atlas-voice-training](https://github.com/briankelley/atlas-voice-training); [HA blog ch.4](https://home-assistant.io/blog/2023/10/12/year-of-the-voice-chapter-4-wakewords)
- microWakeWord (on-device ESP32) models are a different format from openWakeWord. Changing the wake word requires recompiling firmware. — [HA Voice Chapter 6](https://home-assistant.io/blog/2024/02/21/voice-chapter-6); [HA Community](https://community.home-assistant.io/t/taking-requests-custom-v2-microwakewords/1023218)

**Picovoice Porcupine**
- Picovoice confirmed that Free Tier AccessKeys stop working after **30 June 2026**, with no non-commercial tier planned. The SDK is Apache-2.0 but does not run without a valid key. — [HA Community (Picovoice reply quoted)](https://community.home-assistant.io/t/fyi-picovoice-confirmed-free-tier-accesskeys-will-stop-working-after-june-30-2026/1012744); [HA Community](https://community.home-assistant.io/t/porcupine-free-tier-shutdown-alternatives-for-home-assistant-voice-users/1012382); older terms in [Picovoice blog (Jan 2025)](https://picovoice.ai/blog/introducing-picovoices-free-tier)

**Azure custom keyword**
- Built only in Speech Studio. The Basic model (prototyping) takes about 15 minutes; Advanced (product) can take up to a day and depends on region. Model creation is free. Output is a `.table` file run on-device by the Speech SDK. You can test in the browser. Keyword verification is an optional cloud second stage, billed as speech-to-text. en-US and zh-CN only. — [MS Learn: keyword recognition overview](https://learn.microsoft.com/en-us/azure/ai-Services/Speech-Service/keyword-recognition-overview); [MS Learn: custom keyword basics](https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/custom-keyword-basics)
- Basic-model builds have hung for 30+ hours during outages. — [MS Q&A](https://learn.microsoft.com/it-it/answers/questions/2045527/endless-processing-for-a-new-speech-studio-custom)

**Grammar-constrained / open-vocabulary local recognition**
- Vosk supports changing the vocabulary at runtime only on models with a dynamic graph; big static-graph models don't support it. — [Vosk adaptation](https://alphacephei.com/vosk/adaptation)
- Classic keyword spotting pairs keyword models with filler/garbage models for non-keyword speech. Running full ASR and then searching the text performs much better but costs more compute. — [MIT SLS ICASSP'97](https://sls.csail.mit.edu/publications/1997/icassp97-ale.pdf)
- sherpa-onnx lists keyword spotting next to ASR and VAD. Keywords in its format carry a per-keyword threshold and boost (example `LIGHT UP|▁ L IGHT ▁UP:0.25:2.0`). A mismatched BPE tokenization can cause misses, so pre-tokenize keywords. — [m5stack sherpa-onnx docs](https://docs.m5stack.com/en/stackflow/ai_pyramid/sherpa-onnx); [soniqo wake-word guide](https://soniqo.audio/vi/guides/wake-word); [react-native-sherpa-onnx hotwords](https://www.mintlify.com/XDcobra/react-native-sherpa-onnx/advanced/hotwords). These are third-party wrappers, not the primary k2-fsa docs.
- Two-stage design: a local trigger listens continuously, then a command phase uses a "recognition set" of allowed phrases. — [US Patent 7720683](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7720683)
- Amazon's architecture: a local wake word engine, then cloud verification of the wake word (two-stage false-accept reduction). — [Voicebot](https://voicebot.ai/?p=3938)

**Thresholds**
- Consumer products commonly target fewer than about 0.1 false accepts per hour. Compare engines by false-reject rate at a fixed false-accept rate (e.g. 1 per hour). — [Picovoice benchmarks](https://picovoice.ai/blog/wake-word-benchmarks/); [Soniox wiki](https://soniox.com/wiki/keyword-spotting-wake-words)

### Inferences
- For Ichos (browser capture, Windows, English, owner-only), the lowest-risk path is: keep the existing transcript-based wake match ("Nyx"/"hey Nyx"), and match owner command phrases at **text level** against a small local phrase set (Vosk small model with phrase list + `[unk]`, or sherpa-onnx KWS). This avoids training a neural model per phrase. openWakeWord is worth adding only for an always-on, low-CPU wake word, and its NC model licence matters if Ichos is ever sold.
- The "record it 3 times" step is most useful as a **recognizer-consistency check** (do all three takes transcribe to the same or close text?), not as model training. It mirrors Alexa's Voice History fix and needs no stored audio, which fits Ichos's "shape only, no audio" privacy rule.
- An openWakeWord custom verifier (speaker-specific) or a stored feature "shape" can act as an optional owner-voice second stage. Treat it as a false-trigger filter, not as security.

### Gaps
- No primary source was retrieved for the exact Vosk phrase-list API (`[unk]` usage) or the official sherpa-onnx KWS parameter defaults. Verify against the k2-fsa and alphacephei repos before implementing.
- No reliable source found on few-shot (about 3-sample) neural custom keyword spotting that is production-ready and free on Windows in 2026. No sample count was found for openWakeWord custom verifiers (the details are in `docs/custom_verifier_models.md`, which was not fetched).
- whisper.cpp grammar-constrained decoding was not researched in this pass.

## 4. Phrase design guidance

### Takeaway
Use multi-syllable, phonetically varied phrases (at least 6 phonemes, about 3–4 syllables). Avoid common everyday phrases. Add a prefix ("Hey …") to short words. Test candidates against confusable words and normal conversation before accepting them.

### Cited Findings
- Fewer than 6 phonemes is not recommended (harder to detect, more false positives). Prepend "Hey" or "OK" to short words. Prefer a variety of sounds. — [Picovoice: choosing a wake word](https://picovoice.ai/docs/tips/choosing-a-wake-word/)
- 3–4 syllables is typical. Plosives and affricates/fricatives (/k/, /g/, /tʃ/) separate well from noise. — [Sensory 2026 guide](https://sensory.com/custom-wake-words-branded-voice-ux-guide-2026/)
- Phonetically dissimilar, low-frequency words gave "drastically fewer" misactivations than popular wake words (UVA studies using phonetic edit distance plus word frequency). — [UVA thesis](https://libraetd.lib.virginia.edu/public_view/xs55mc908); [UVA thesis 2](https://libraetd.lib.virginia.edu/public_view/gq67jr88z)
- A naive wake model fired on "app", "salad", "testing" etc. Generate negatives for every confusable sound. — [Deepgram](https://deepgram.com/learn/naively-training-a-wake-word-model-from-scratch)
- A patented approach rejects a user's custom wake word if it predicts more than a threshold rate of false detections. — [US11790891B2](https://patents.google.com/patent/US11790891)
- Custom Alexa wake words reportedly need at least two syllables and no personal information. This comes from consumer blogs, which conflict with each other on whether custom words exist at all. — [ForestVPN](https://forestvpn.com/blog/smart-home-devices/alexa-wake-word-list); [Android Central](https://androidcentral.com/how-change-alexa-wake-word-your-amazon-echo)

### Inferences
- "Open up" is a risky trigger: two short common words with few phonemes that often appear in normal speech ("open up the file", "she opened up"). Gate it behind the existing wake word, or suggest a more distinctive variant.
- "Warm up my game" is fine *after* a wake word (5 words, varied sounds), but "warm up" alone collides with everyday speech.
- An earcon (short tone) on wake-accept and on run-complete or fail is standard practice. I found no specific 2026 source for earcon guidelines in this pass (gap).

### Gaps
- No official Amazon or Google phrase-design guide was found (Amazon's public docs only cover invocation). No primary source on earcon design was retrieved.

## Recommended design for Ichos voice commands

(Synthesis from the findings above. Choices not directly sourced are marked as design judgement.)

**Recognition architecture (two-stage, local)**
1. Stage A: the wake gate. Existing "Nyx"/"hey Nyx" transcript match, or the clap/whistle/taught sound. Optionally openWakeWord later for low-CPU always-on detection (respect its NC model licence).
2. Stage B: a command window of about 5–8 s (design judgement) after the wake gate. The transcript is matched against the owner's phrase set: normalize the text, then exact or alias match, then fuzzy match (token edit distance) with a per-phrase threshold. A restricted-vocabulary recognizer (Vosk dynamic-graph small model + phrase list, or sherpa-onnx KWS with a per-keyword threshold) can replace free ASR if accuracy needs it.
3. "Bare" phrases without a wake word are allowed only if they pass the distinctiveness check (below) and the owner opts in per phrase.

**Recording flow (step by step)**
1. Owner clicks "New voice command" and types the phrase (the canonical text). As in Windows and Alexa, typing is the source of truth.
2. Lint the phrase: flag fewer than 6 phonemes or 3 syllables, phrases made of common words ("open up", "warm up"), phrases within a small edit distance of existing phrases, the wake word, or built-ins. Suggest a prefix ("Nyx, …").
3. "Say it 3 times": capture three takes. For each, show the live transcript ("I heard: …"). Pass if all three match the canonical text, or reach the fuzzy threshold; otherwise offer to add the heard variant as an alias (the Alexa Voice History pattern, built in).
4. Optional: store the feature "shape" per take (the existing taught-sound mechanism) as an owner-voice second check. **Never store audio.**
5. Collision test: a 20–30 s "talk normally" step, or a replay of recent dictation transcripts, to confirm the phrase doesn't trigger (design judgement).
6. Bind to a routine (new or existing), then Preview (dry run: list the steps without executing), then Save. The routine is marked "needs first-run confirmation".

**Routine editor fields**
- `id`, `name`, `phrases[]` (canonical + aliases, as in HA's multi-sentence triggers), `require_wake` (default true), `match_threshold`, `enabled` toggle (as in Windows "Toggle <name>"), `steps[]` (max 8, following Windows Voice Access), `on_error` (stop | continue), `confirm_policy` (first_run | always | never-after-approved), `approved_hash` (hash of steps at approval), `last_run` {time, heard_text, per-step results}, `created/edited` timestamps.

**Step types (fixed, data-only)**
- `open_app` {app id or resolved exe path from an allowlist / Start-menu index}
- `open_path` {folder/file}
- `open_url` {http/https only}
- `wait` {seconds, capped, e.g. ≤60 s (design judgement; Alexa allows 4 h)}
- `speak` {text, voice}
- `set_layout` {named layout preset}
- `notify` {text in the notch/toast}
- Deliberately excluded at first: arbitrary shell commands, keystroke injection and mouse clicks (Windows offers them, but they are hard to make safe). Add them later only behind the safety gate with an always-confirm policy.

**Notch states**
`idle` → `armed` (wake detection only) → `listening` (command window, live caption of the user) → `matching` → `confirming` (first run / risky: "Run 'Warm up my game'? 3 steps" with Yes/No by voice or click) → `running n/m` (current step label) → `speaking` (assistant caption; barge-in stops TTS and flushes the queue) → `done` / `partial` / `failed` → back to `idle`. Also `muted` (mic off, distinct icon) and `interrupted`. Earcons for wake-accept, done and failed (design judgement).

**Failure handling**
- Per-step result {ok | skipped | failed + reason}. If one step fails and `on_error=continue`, keep going. Speak or show a one-line summary ("2 of 3 done: OBS wasn't found").
- No match: show "I heard '<text>'", the closest phrase, and buttons "Run it" / "Add as alias".
- A run log is kept per routine (heard text, match score, step results), modelled on Alexa's Voice History.
- Startup validation: flag routines whose app paths no longer resolve.

**Safety rules**
- All steps go through the existing safety gate. A routine is approved once, on first run, after showing the full step list. Any edit changes `approved_hash` and requires re-approval (design judgement extending Apple's Ask Before Running).
- No step runs from untrusted text. Phrases only *select* a stored routine and never pass parameters into step targets.
- Cap steps (8) and total wait. One routine runs at a time. Allow a voice or keyboard "stop".
- Owner-voice shape and speaker verifiers lower false triggers but are not authentication. Never rely on them for risky steps.
- Privacy: no audio stored, only transcripts of matched commands (with an option to turn off logging) and feature shapes.

## Pitfalls
- **Common-phrase triggers** ("open up", "warm up") fire during normal speech or games. Default to `require_wake=true`. — see §4 (Picovoice, UVA)
- **Exact-match brittleness**: paraphrases miss (Alexa "bedtime" example). Use aliases and fuzzy matching, and show what was heard. — [Online Tech Tips](https://www.online-tech-tips.com/how-to-create-a-routine-with-amazon-alexa/)
- **Overlapping steps**: launching Steam, Discord and OBS at once and then setting a layout before their windows exist. Insert waits, or have `set_layout` wait for windows. — [Amazon help (wait between overlapping actions)](https://digprjsurvey.amazon.com/csad/help/node/GLXY7RFX3L5GH2VR)
- **The assistant's own TTS triggering commands** (e.g. a `speak` line containing a phrase). Suppress command matching while speaking, or use echo cancellation (inference).
- **Licence traps**: openWakeWord pre-trained models are CC BY-NC-SA; Porcupine free keys are dead after 30 June 2026; Azure custom keyword is en-US/zh-CN only and needs cloud tooling. — §3 sources
- **Training-pipeline rot**: openWakeWord training needs 2022-era pins, a GPU or Colab, and up to about 45 GB of disk. Don't make it a user-facing "record your wake word" flow. — [atlas-voice-training](https://github.com/briankelley/atlas-voice-training)
- **Barge-in too sensitive or too sluggish**: tune a minimum speech duration (Hume default 800 ms), and flush client audio yourself. — [Hume docs](https://dev.hume.ai/docs/speech-to-speech-evi/features/interruptibility)
- **Silent auto-runs**: Apple requires a double confirm to disable asking. Don't let routines drift into running unseen after edits (re-approve on change). — [Apple guide](https://support.apple.com/guide/shortcuts/apd602971e63/ios)
- **English-only**: openWakeWord, Windows voice shortcuts and Azure custom keyword are all English or limited-language. — §1, §3 sources
