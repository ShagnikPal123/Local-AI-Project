# Voice references: what was borrowed, and under which licence

The Fixer Upper plan (S2, S15) and the owner pointed at several voice projects. Each was read for its approach;
no code or model was copied or downloaded into this repo.

| Project | Licence | What we took | Why not more |
|---|---|---|---|
| kaymen99/AI-Voice-assistant | none published | The idea only: wake, listen, think, speak as separate steps with their own models. | No licence means no right to copy code. |
| vannu07/jarvis | MIT | Ideas: a wake phrase before listening, and LBPH face recognition (OpenCV) for later. | Face recognition is later work. |
| OpenBMB VoxCPM | Apache-2.0 | Nothing yet. | 2B parameters, needs Python < 3.13; the app runs on 3.14. |
| QwenLM Qwen3-TTS | Apache-2.0 | The approach: stream audio as it is made so playback starts at the first chunk (`tts.stream`, MediaSource in `voicePlayer.ts`), and keep a local model warm in one process. | A 0.6B streaming model fits the owner's 16 GB GPU and could be an offline neural voice later, run as a sidecar in its own venv. |
| SYSTRAN faster-whisper | MIT | Used as an optional package by `local_stt.py` (installed by the owner, not vendored). | — |

Windows dictation (System.Speech) is part of Windows and needs nothing installed.
