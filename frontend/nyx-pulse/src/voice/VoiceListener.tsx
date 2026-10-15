/** The one microphone, mounted once for the whole app.
 *
 * Listening cannot live in the chat panel: Proto Voice "always listens", and the
 * chat panel is not mounted while the owner is on Settings or the Code tab. So
 * the engine runs here, at the top of the app, and whatever it hears is either
 * handled by Proto Voice or handed to the chat through one window event
 * (`nyx:voice-send`). The chat panel picks that up when it is on screen; when it
 * is not, the Nyx tab is opened first so the answer has somewhere to land.
 *
 * Voice to action (Fixer Upper S6, "like Jev opens tabs in a second"): with Ultra Fast on in Equalize, a spoken
 * desktop command ("open chrome", "volume up") is done at once by `/api/ultrafast` with no model and the reply is
 * said; only what is not a desktop command goes on to the chat.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { pushToast } from "../state/toastStore";
import { useStore } from "../state/store";
import { turnsStore } from "../state/turnStore";
import { useVoiceEngine } from "./voiceEngine";
import { onVoiceMode, voiceMode, type VoiceMode } from "./voiceBus";
import { sendToChat } from "./toChat";
import { speakText } from "./voicePlayer";

/** How often the Ultra Fast switch is re-read, besides the Equalize tab's own change event. */
const ULTRA_REFRESH_MS = 30_000;

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

  const ultrafast = useRef(false);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      const result = await api.get<{ settings: { ultrafast: boolean } }>("/api/equalize/assistant");
      if (alive && result.ok) ultrafast.current = Boolean(result.data.settings?.ultrafast);
    };
    const refresh = () => void load();
    window.addEventListener("nyx:equalize-changed", refresh);
    const poll = window.setInterval(refresh, ULTRA_REFRESH_MS);
    void load();
    return () => { alive = false; window.removeEventListener("nyx:equalize-changed", refresh); window.clearInterval(poll); };
  }, []);

  const send = useCallback(async (text: string, sessionId: string) => {
    if (ultrafast.current) {
      const fast = await api.post<{ handled: boolean; ok?: boolean; reply: string; ms: number }>(
        "/api/ultrafast", { text }, 10_000);
      if (fast.ok && fast.data.handled) {
        if (fast.data.reply) void speakText(fast.data.reply, { role: "reply" }).catch(() => undefined);
        pushToast(`${fast.data.reply || "Done"} (${Math.round(fast.data.ms)} ms)`, fast.data.ok === false ? "warn" : "info");
        return;
      }
    }
    sendToChat("nyx:voice-send", { text, sessionId });
  }, []);

  useVoiceEngine({ mode, busy, chatId, onSend: (text, sessionId) => void send(text, sessionId) });
  return null;
}
