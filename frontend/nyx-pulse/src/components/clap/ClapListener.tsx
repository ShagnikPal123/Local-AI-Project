/** The ear that is open when you are not at the keyboard (Project Null N86).
 *
 * Mounted once, next to the app. It decides when the clap detector should be
 * running — away, offline, or with the background voice on, exactly as the owner
 * asked — matches what it hears against the sounds they taught, and speaks the
 * answer. It also says the one line at the start of every voice session, in every
 * mode: "Nyx here."
 *
 * Deaf while Nyx is talking, so a clap in its own answer cannot set it off.
 */

import { useEffect, useRef } from "react";
import { api } from "../../api";
import { pushToast } from "../../state/toastStore";
import {
  clapListening, muteClap, onClap, setClapSensitivity, setTaughtSounds,
  startClapListening, stopClapListening,
} from "../../voice/clapDetector";
import { onVoice, setVoiceMode, voiceMode, type VoiceMode } from "../../voice/voiceBus";
import { speakText } from "../../voice/voicePlayer";

interface Gesture {
  id: string; name: string; kind: string; enabled: boolean; when: string[];
  action: string; say: string; text: string; template: number[][];
}
interface ClapState {
  enabled: boolean;
  sensitivity: number;
  greeting: { enabled: boolean; text: string; when: string };
  gestures: Gesture[];
}

const GREETED_KEY = "nyx.voice.greeted";

function greetedToday(): boolean {
  try { return localStorage.getItem(GREETED_KEY) === new Date().toDateString(); } catch { return false; }
}

function markGreeted(): void {
  try { localStorage.setItem(GREETED_KEY, new Date().toDateString()); } catch { /* fine */ }
}

export function ClapListener() {
  const state = useRef<ClapState | null>(null);
  const away = useRef(false);
  const mode = useRef<VoiceMode>(voiceMode());
  /** This listening session has been greeted (or a clap already spoke for it). */
  const greetedSession = useRef(false);

  useEffect(() => {
    let alive = true;

    const load = async () => {
      const result = await api.get<ClapState>("/api/voice/gestures");
      if (!alive || !result.ok) return;
      state.current = result.data;
      setClapSensitivity(result.data.sensitivity ?? 0.6);
      setTaughtSounds(result.data.gestures.filter((g) => g.kind === "taught" && g.enabled)
        .map((g) => ({ id: g.id, template: g.template })));
      decide();
    };

    /** Should the ear be open right now? */
    const decide = () => {
      const current = state.current;
      if (!current?.enabled) { if (clapListening()) stopClapListening(); return; }
      const offline = !navigator.onLine;
      const active = current.gestures.some((gesture) => gesture.enabled && gesture.when.some((when) =>
        when === "always"
        || (when === "away" && away.current)
        || (when === "offline" && offline)
        || (when === "proto" && mode.current === "proto")
        || (when === "talk" && mode.current === "talk")));
      if (active && !clapListening()) void startClapListening();
      if (!active && clapListening()) stopClapListening();
    };

    const heard = onClap((event) => {
      const current = state.current;
      if (!current) return;
      const gesture = current.gestures.find((g) => g.enabled && (
        event.kind === "taught" ? g.id === event.id : g.kind === event.kind));
      if (!gesture) return;
      void (async () => {
        const answer = await api.post<{ speak: string; action: string; text: string }>(
          `/api/voice/gestures/${gesture.id}/heard`, {}, 20_000);
        if (!answer.ok) return;
        const { speak, action, text } = answer.data;
        if (speak) void speakText(speak, { role: "reply" });
        // The clap's own line is the hello; the listening it starts must not add the intro on top.
        if (action === "listen") { if (speak) greetedSession.current = true; setVoiceMode("talk"); }
        if (action === "command" && text.trim()) {
          window.dispatchEvent(new CustomEvent("nyx:chat-send", { detail: { text: text.trim() } }));
        }
        pushToast(`Heard “${gesture.name}”.`, "info");
      })();
    });

    const voice = onVoice((event) => {
      if (event.type === "start") {
        mode.current = event.mode;
        // Turning voice on announces "start" twice (the switch, then the microphone); greet on the first only.
        // The server also drops a greeting asked for moments after the last one, which covers a second window.
        const repeat = greetedSession.current;
        greetedSession.current = true;
        if (repeat) { decide(); return; }
        void (async () => {
          const first = !greetedToday();
          const result = await api.get<{ text: string }>(`/api/voice/greeting?first=${first ? "true" : "false"}`);
          if (result.ok && result.data.text) {
            markGreeted();
            void speakText(result.data.text, { role: "reply" });
          }
        })();
        decide();
      }
      if (event.type === "stop") { mode.current = "off"; greetedSession.current = false; decide(); }
      if (event.type === "away") { away.current = event.on; decide(); }
      // Never answer its own voice.
      if (event.type === "speaking") muteClap(event.text !== null);
    });

    const online = () => decide();
    window.addEventListener("online", online);
    window.addEventListener("offline", online);
    const refresh = () => void load();
    window.addEventListener("nyx:clap-changed", refresh);
    void load();

    return () => {
      alive = false;
      heard();
      voice();
      window.removeEventListener("online", online);
      window.removeEventListener("offline", online);
      window.removeEventListener("nyx:clap-changed", refresh);
      stopClapListening();
    };
  }, []);

  return null;
}
