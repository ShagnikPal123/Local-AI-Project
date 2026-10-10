/** Voice state for the chat's voice band and the desktop notch (notch.py), without loading the 3D orb. */

import { useEffect, useState } from "react";
import { api } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { onVoice, onVoiceMode, setVoiceMode, voiceMode } from "../../voice/voiceBus";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

/** One place that turns voice events into the orb's state and tells the notch. */
export function useVoiceState(report = false): { orb: OrbState; heard: string; on: boolean } {
  const [orb, setOrb] = useState<OrbState>("idle");
  const [heard, setHeard] = useState("");
  const [on, setOn] = useState(voiceMode() !== "off");
  useEffect(() => onVoiceMode((mode) => setOn(mode !== "off")), []);
  useEffect(() => onVoice((event) => {
    if (event.type === "partial" || event.type === "final") { setHeard(event.text); setOrb(event.type === "final" ? "thinking" : "listening"); }
    else if (event.type === "start") setOrb("listening");
    else if (event.type === "stop") setOrb("idle");
    else if (event.type === "speaking") setOrb(event.text ? "speaking" : "listening");
  }), []);
  useEffect(() => {
    if (report) void api.post("/api/notch/state", { state: on ? orb : "idle", text: heard.slice(0, 160), voice: on });
  }, [orb, heard, on, report]);
  return { orb, heard, on };
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

