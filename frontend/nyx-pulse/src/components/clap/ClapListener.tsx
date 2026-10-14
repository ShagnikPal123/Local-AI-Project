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
import { sendToChat } from "../../voice/toChat";
import { startWakePhrase, stopWakePhrase } from "../../voice/wakePhrase";

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

/** What the Equalize setup says about waking it (equalize_assistant.py): talk on, and which gestures. */
interface EqualizeWake { talk: boolean; gestures: string[]; phrase: string }
const NO_WAKE: EqualizeWake = { talk: false, gestures: [], phrase: "" };
/** The notch window saves these settings too, so they are read again now and then. */
const EQUALIZE_REFRESH_MS = 30_000;

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
  const equalize = useRef<EqualizeWake>(NO_WAKE);

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

    const loadEqualize = async () => {
      const result = await api.get<{ settings: { talk: boolean; activation: { gestures: string[]; phrase: string } } }>(
        "/api/equalize/assistant");
      if (!alive || !result.ok) return;
      const s = result.data.settings;
      equalize.current = { talk: Boolean(s.talk), gestures: s.activation?.gestures ?? [], phrase: s.activation?.phrase ?? "" };
      decide();
    };

    /** Equalize's "Talk: yes" with a wake sound chosen, and voice is off: a clap or whistle should turn it on. */
    const equalizeWakesOn = (kind: string): boolean => {
      const eq = equalize.current;
      if (!eq.talk || mode.current !== "off") return false;
      return (kind === "double_clap" && eq.gestures.includes("clap")) || (kind === "whistle" && eq.gestures.includes("whistle"));
    };

    /** Voice on from a wake gesture. Words said right after the phrase go to the chat as the first thing heard. */
    const wake = (rest = "") => {
      setVoiceMode("talk");
      if (rest.split(/\s+/).filter(Boolean).length >= 2) {
        window.setTimeout(() => sendToChat("nyx:voice-send", { text: rest }), 300);
      }
    };

    /** Should the ear be open right now? */
    const decide = () => {
      const current = state.current;
      const eq = equalize.current;
      const wakeBySound = eq.talk && mode.current === "off" && (eq.gestures.includes("clap") || eq.gestures.includes("whistle"));
      // The wake phrase needs the recognizer, which the voice engine holds while voice is on.
      if (eq.talk && mode.current === "off" && eq.gestures.includes("phrase") && eq.phrase.trim()) startWakePhrase(eq.phrase, wake);
      else stopWakePhrase();
      if (!current?.enabled && !wakeBySound) { if (clapListening()) stopClapListening(); return; }
      const offline = !navigator.onLine;
      const active = wakeBySound || Boolean(current?.enabled && current.gestures.some((gesture) => gesture.enabled && gesture.when.some((when) =>
        when === "always"
        || (when === "away" && away.current)
        || (when === "offline" && offline)
        || (when === "proto" && mode.current === "proto")
        || (when === "talk" && mode.current === "talk"))));
      if (active && !clapListening()) void startClapListening();
      if (!active && clapListening()) stopClapListening();
    };

    const heard = onClap((event) => {
      if (event.kind !== "taught" && equalizeWakesOn(event.kind)) { wake(); return; }
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
          // Voice to action (Fixer Upper S6, "like Jev opens tabs in a second"): a desktop command ("open chrome") is
          // done by Ultra Fast at once, with no model; only what is not a desktop command goes to the chat.
          const fast = await api.post<{ handled: boolean; ok?: boolean; reply: string; ms: number }>(
            "/api/ultrafast", { text: text.trim() }, 10_000);
          if (fast.ok && fast.data.handled) {
            if (fast.data.reply) void speakText(fast.data.reply, { role: "reply" });
            pushToast(`Heard “${gesture.name}” — ${fast.data.reply} (${Math.round(fast.data.ms)} ms)`, fast.data.ok === false ? "warn" : "info");
            return;
          }
          sendToChat("nyx:chat-send", { text: text.trim() });
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
    const refreshEqualize = () => void loadEqualize();
    window.addEventListener("nyx:equalize-changed", refreshEqualize);
    const poll = window.setInterval(refreshEqualize, EQUALIZE_REFRESH_MS);
    void load();
    void loadEqualize();

    return () => {
      alive = false;
      heard();
      voice();
      window.removeEventListener("online", online);
      window.removeEventListener("offline", online);
      window.removeEventListener("nyx:clap-changed", refresh);
      window.removeEventListener("nyx:equalize-changed", refreshEqualize);
      window.clearInterval(poll);
      stopWakePhrase();
      stopClapListening();
    };
  }, []);

  return null;
}
