/** The voice bar across the top of the app (Update 1, U26).
 *
 * The owner: "on only the app a top bar will show up when activating whether by calling name, gesture, or clicking
 * to talk. In bar you can see what you are saying and 3 dots bouncing to show the AI listening and doing."
 *
 * It reads the one microphone (`useVoiceState`, mounted once by `VoiceListener`) and the voice bus, so every way of
 * starting — saying its name in Proto Voice, a clap (`ClapListener`), the Talk switch in the chat — brings up the same
 * bar. It sits in the page's flow above the app's own bar, so while it shows it pushes the app down instead of
 * covering anything, and it is gone the moment listening is switched off.
 *
 *   Listening — your words as you say them, dots bouncing gently.
 *   Working   — what you said, dots bouncing quickly while Nyx works on it.
 *   Speaking  — the line Nyx is saying out loud.
 */

import { useEffect, useState } from "react";
import { useStore } from "../../state/store";
import { turnsStore } from "../../state/turnStore";
import { onVoice, onVoiceMode, setVoiceMode, voiceMode, type VoiceMode } from "../../voice/voiceBus";
import { useSpeakingText, useVoiceState } from "../../voice/voiceEngine";
import "./voice.css";

type Phase = "listening" | "working" | "speaking" | "waking";

export function VoiceTopBar() {
  const [mode, setMode] = useState<VoiceMode>(() => voiceMode());
  useEffect(() => onVoiceMode(setMode), []);
  const engine = useVoiceState();
  const speaking = useSpeakingText();
  const running = useStore(turnsStore, (s) => s.runningByChat);
  const busy = Object.keys(running ?? {}).length > 0;
  const [said, setSaid] = useState("");

  // The last finished sentence stays on the bar while Nyx works on it.
  useEffect(() => onVoice((event) => {
    if (event.type === "final") setSaid(event.text);
    if (event.type === "stop") setSaid("");
  }), []);

  if (mode === "off") return null;

  const phase: Phase = speaking ? "speaking"
    : engine.heard ? "listening"
      : busy || engine.waiting ? "working"
        : engine.listening ? "listening" : "waking";
  const label = { listening: "Listening", working: "Working on it", speaking: "Speaking", waking: "Starting the microphone" }[phase];
  const line = phase === "speaking" ? speaking
    : engine.heard || (phase === "working" ? said : "")
      || (engine.error ? engine.error : mode === "proto" ? "Say “Nyx” and what you need" : "Say what you need");

  return (
    <div className={`vbar is-${phase}${engine.error ? " has-error" : ""}`} role="status" aria-live="polite"
         aria-label={`Voice: ${label}`}>
      <span className="vbar__mic" aria-hidden="true" />
      <span className="vbar__label">{label}</span>
      <span className={`vbar__text${engine.heard || phase === "speaking" ? " is-live" : ""}`}>{line}</span>
      {engine.ready && phase === "listening" && <span className="vbar__ready" title="The answer is already drafted">ready</span>}
      <span className="vbar__dots" aria-hidden="true"><i /><i /><i /></span>
      <button type="button" className="vbar__stop" onClick={() => setVoiceMode("off")} title="Stop listening">Stop</button>
    </div>
  );
}
