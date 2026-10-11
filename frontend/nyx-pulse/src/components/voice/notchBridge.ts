/** Voice state for the chat's voice band and the desktop notch (notch.py), without loading the 3D face. */

import { useEffect, useState } from "react";
import { api } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { useStore } from "../../state/store";
import { turnsStore } from "../../state/turnStore";
import { onVoice, onVoiceMode, setVoiceMode, speaking, voiceMode } from "../../voice/voiceBus";
import { useVoiceState as useEngineState } from "../../voice/voiceEngine";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

/** After a sentence is sent, "thinking" holds this long even before the turn shows up (a spoken command Big Kahuna
 * or Proto Voice handles never becomes a turn). */
const THINK_HOLD_MS = 6000;

/** One place that turns voice events into the face's state and tells the notch.
 *
 * Speaking beats thinking beats listening: Ichos's own voice playing → speaking; an answer being written (any chat
 * turn running) or a sentence just sent → thinking; voice on → listening. `drafting` (0–1) is voice2 thinking while
 * the owner is still talking — how finished the sentence sounds, 1 once the answer is already written. */
export function useVoiceState(report = false): { orb: OrbState; heard: string; on: boolean; drafting: number } {
  const [heard, setHeard] = useState("");
  const [on, setOn] = useState(voiceMode() !== "off");
  const [talking, setTalking] = useState(speaking() !== null);
  const [sentAt, setSentAt] = useState(0);
  const [, tick] = useState(0);
  const running = useStore(turnsStore, (s) => Object.keys(s.runningByChat ?? {}).length > 0);
  const engine = useEngineState();

  useEffect(() => onVoiceMode((mode) => setOn(mode !== "off")), []);
  useEffect(() => onVoice((event) => {
    if (event.type === "partial") { setHeard(event.text); setSentAt(0); }
    else if (event.type === "final") { setHeard(event.text); setSentAt(Date.now()); }
    else if (event.type === "stop") { setSentAt(0); setHeard(""); }
    else if (event.type === "speaking") { setTalking(Boolean(event.text)); if (event.text) setSentAt(0); }
    else if (event.type === "bargein") setTalking(false);
  }), []);
  // Let the hold run out by itself.
  useEffect(() => {
    if (!sentAt) return;
    const timer = window.setTimeout(() => tick((n) => n + 1), THINK_HOLD_MS + 50);
    return () => window.clearTimeout(timer);
  }, [sentAt]);

  const holding = sentAt > 0 && Date.now() - sentAt < THINK_HOLD_MS;
  const orb: OrbState = talking ? "speaking" : running || holding ? "thinking" : on ? "listening" : "idle";
  const drafting = engine.heard ? (engine.ready ? 1 : engine.complete) : 0;

  useEffect(() => {
    if (report) void api.post("/api/notch/state", { state: orb, text: heard.slice(0, 160), voice: on });
  }, [orb, heard, on, report]);
  return { orb, heard, on, drafting };
}

/** Mounted once by the app: the notch's Talk button reaches the page through the engine. */
export function useNotchCommands(): void {
  useEffect(() => onWorkspaceEvent((event) => {
    if (event.type !== "voice.toggle") return;
    setVoiceMode(voiceMode() === "off" ? "talk" : "off");
  }), []);
}

/** Mounted once in the shell: reports voice state to the desktop notch and obeys its Talk button, on every tab. */
export function NotchBridge(): null {
  useVoiceState(true);
  useNotchCommands();
  return null;
}
