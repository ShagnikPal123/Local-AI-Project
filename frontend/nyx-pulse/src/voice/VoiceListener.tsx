/** The one microphone, mounted once for the whole app.
 *
 * Listening cannot live in the chat panel: Proto Voice "always listens", and the
 * chat panel is not mounted while the owner is on Settings or the Code tab. So
 * the engine runs here, at the top of the app, and whatever it hears is either
 * handled by Proto Voice or handed to the chat through one window event
 * (`nyx:voice-send`). The chat panel picks that up when it is on screen; when it
 * is not, the Nyx tab is opened first so the answer has somewhere to land.
 */

import { useCallback, useEffect, useState } from "react";
import { useStore } from "../state/store";
import { turnsStore } from "../state/turnStore";
import { useVoiceEngine } from "./voiceEngine";
import { onVoiceMode, voiceMode, type VoiceMode } from "./voiceBus";

/** The chat the owner is in, as the chat panel remembers it. */
function activeChat(): string {
  try { return localStorage.getItem("nyx.chat.active") || ""; } catch { return ""; }
}

export function VoiceListener() {
  const [mode, setMode] = useState<VoiceMode>(() => voiceMode());
  useEffect(() => onVoiceMode(setMode), []);
  const chatId = activeChat();
  const running = useStore(turnsStore, (s) => s.runningByChat);
  const busy = Object.keys(running ?? {}).length > 0;

  const send = useCallback((text: string, sessionId: string) => {
    window.dispatchEvent(new CustomEvent("nyx:voice-send", { detail: { text, sessionId } }));
  }, []);

  useVoiceEngine({ mode, busy, chatId, onSend: send });
  return null;
}
