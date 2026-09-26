/** The listening half of talking to Nyx.
 *
 * The owner: "as I talk it listens and thinks of how to answer and then
 * instantly responds. As it talks it also listens. Make sure it doesn't pick up
 * its own voice."
 *
 * What makes that work:
 *
 *  • **It thinks along.** Every few hundred milliseconds the words so far go to
 *    `/api/voice/think`, which scores whether the sentence is finished, fetches
 *    what the answer will need, and starts writing the answer once the sentence
 *    looks complete. The turn that follows often has its answer already.
 *  • **The pause is measured, not guessed.** The engine waits for the pause
 *    length the backend asked for — short after a finished question, long after
 *    a trailing "and" — and it times the pause on the microphone itself
 *    (`micVad`), not on how quickly the recognizer decided to report.
 *  • **It keeps listening while it speaks.** Nyx's own words are registered in
 *    the echo guard; anything matching them is dropped. A real interruption
 *    (words that are not an echo, with the echo-cancelled microphone showing
 *    someone talking) stops the speech at once and starts the next turn.
 *
 * Big Kahuna's early actions are untouched: interim text still goes to
 * `readIntent(text, false)` on a 250 ms debounce, each action runs once, and the
 * final transcript goes to `readIntent(text, true)`, so "open Gmail…" still
 * opens before the sentence ends.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { kahunaAllOn, readIntent, runAction } from "../state/kahuna";
import { speakText, stopSpeaking } from "./voicePlayer";
import { isEcho } from "./echoGuard";
import { startVad, stopVad, vadRunning, vadState } from "./micVad";
import { emitVoice, onVoice, speaking, type VoiceMode } from "./voiceBus";

/** Fallback pause when the engine has not answered yet. */
const DEFAULT_WAIT_MS = 900;
/** At least this much text before anything is sent. */
const MIN_WORDS = 2;
/** How often the words so far may be sent to the thinking endpoint. */
const THINK_EVERY_MS = 380;

type Recognition = {
  continuous: boolean; interimResults: boolean; lang: string;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onend: (() => void) | null; onerror: ((e: { error?: string }) => void) | null;
  start: () => void; stop: () => void; abort?: () => void;
};

function speechRecognition(): (new () => Recognition) | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function voiceSupported(): boolean {
  return speechRecognition() !== null;
}

export type ThinkReply = {
  utterance_id: string;
  complete: number;
  wait_ms: number;
  kind: string;
  means: string;
  handled: boolean;
  draft_ready: boolean;
  prefetched: boolean;
};

export type VoiceEngineState = {
  mode: VoiceMode;
  listening: boolean;
  heard: string;
  error: string;
  waiting: boolean;
  /** 0–1: how finished the current sentence sounds. */
  complete: number;
  /** The answer was drafted while the owner spoke. */
  ready: boolean;
  sessionId: string;
};

let sessionCounter = 0;

/** The one engine's state, so any panel can show it without opening a second microphone. */
const IDLE: VoiceEngineState = {
  mode: "off", listening: false, heard: "", error: "", waiting: false, complete: 0, ready: false, sessionId: "",
};
let shared: VoiceEngineState = IDLE;
const stateListeners = new Set<(state: VoiceEngineState) => void>();

function publishState(state: VoiceEngineState): void {
  shared = state;
  stateListeners.forEach((listener) => {
    try { listener(state); } catch { /* ignore */ }
  });
}

/** Read what the engine is doing. The engine itself is mounted once, in App. */
export function useVoiceState(): VoiceEngineState {
  const [state, setState] = useState(shared);
  useEffect(() => {
    stateListeners.add(setState);
    setState(shared);
    return () => { stateListeners.delete(setState); };
  }, []);
  return state;
}

export function useVoiceEngine({ mode, busy, chatId, onSend, onCommand }: {
  mode: VoiceMode;
  busy: boolean;
  chatId: string;
  onSend: (text: string, sessionId: string) => void;
  /** A spoken command Proto Voice handled; the words never become a message. */
  onCommand?: (said: string) => void;
}): VoiceEngineState {
  const [listening, setListening] = useState(false);
  const [heard, setHeard] = useState("");
  const [error, setError] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [complete, setComplete] = useState(0);
  const [ready, setReady] = useState(false);

  const sessionId = useMemo(() => {
    sessionCounter += 1;
    return `voice-${Date.now().toString(36)}-${sessionCounter}`;
  }, []);
  const utteranceId = useRef("");
  const finalText = useRef("");
  const interimText = useRef("");
  const waitMs = useRef(DEFAULT_WAIT_MS);
  const lastHeardAt = useRef(0);
  const lastThinkAt = useRef(0);
  const thinking = useRef(false);
  const pending = useRef("");
  const speakingNow = useRef(false);
  const intentTimer = useRef(0);
  const doneKeys = useRef(new Set<string>());
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const chatRef = useRef(chatId);
  chatRef.current = chatId;
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const onSendRef = useRef(onSend);
  onSendRef.current = onSend;
  const onCommandRef = useRef(onCommand);
  onCommandRef.current = onCommand;

  const newUtterance = useCallback(() => {
    utteranceId.current = `u${Date.now().toString(36)}`;
    doneKeys.current.clear();
    setComplete(0);
    setReady(false);
  }, []);

  /** Ask the engine what it makes of the words so far. */
  const think = useCallback(async (text: string, final: boolean) => {
    if (!text.trim()) return;
    if (thinking.current && !final) return;
    thinking.current = true;
    try {
      const result = await api.post<ThinkReply>("/api/voice/think", {
        session_id: sessionId,
        text,
        final,
        chat_id: chatRef.current === "default" ? "" : chatRef.current,
        utterance_id: utteranceId.current,
      });
      if (result.ok) {
        waitMs.current = Math.max(250, Math.min(2500, result.data.wait_ms || DEFAULT_WAIT_MS));
        setComplete(result.data.complete ?? 0);
        setReady(Boolean(result.data.draft_ready));
      }
    } catch {
      /* the pause falls back to the default wait */
    } finally {
      thinking.current = false;
    }
  }, [sessionId]);

  /** Send what was said. */
  const flush = useCallback(async () => {
    const text = `${finalText.current} ${interimText.current}`.trim();
    finalText.current = "";
    interimText.current = "";
    setHeard("");
    window.clearTimeout(intentTimer.current);
    if (!text) return;
    emitVoice({ type: "final", text, utteranceId: utteranceId.current });
    void think(text, true);

    if (kahunaAllOn()) {
      // A spoken command ("open Gmail and write an email to…") is carried out by
      // Big Kahuna instead of becoming a chat message.
      const intent = await readIntent(text, true);
      const actions = intent?.actions ?? [];
      if (actions.length) {
        let said = "";
        for (const action of actions) {
          if (doneKeys.current.has(action.key)) continue;
          doneKeys.current.add(action.key);
          said = await runAction(action);
        }
        const earlyOnly = actions.every((a) => a.early);
        const commandOnly = actions.some((a) => a.kind === "compose_email") || text.split(/\s+/).length <= 8 || !earlyOnly;
        doneKeys.current.clear();
        if (commandOnly) {
          const reply = said || "Done.";
          void speakText(reply, { role: "reply" }).catch(() => undefined);
          onCommandRef.current?.(reply);
          newUtterance();
          return;
        }
      }
      doneKeys.current.clear();
    }

    // Proto Voice: the computer and the app first. Only words that are not a
    // command for this PC carry on into the chat.
    if (modeRef.current === "proto") {
      const acted = await api.post<{ said: string; to_chat: boolean; needs_confirm: boolean; kind: string }>(
        "/api/proto-voice/act", { text, session_id: sessionId, chat_id: chatRef.current === "default" ? "" : chatRef.current },
      );
      if (acted.ok && !acted.data.to_chat) {
        onCommandRef.current?.(acted.data.said);
        newUtterance();
        return;
      }
    }

    if (text.split(/\s+/).filter(Boolean).length < MIN_WORDS) { newUtterance(); return; }
    if (busyRef.current) {
      pending.current = pending.current ? `${pending.current} ${text}` : text;   // it goes when this answer ends
      setWaiting(true);
      newUtterance();
      return;
    }
    stopSpeaking();
    onSendRef.current(text, sessionId);
    newUtterance();
  }, [sessionId, think, newUtterance]);

  // Anything said while Nyx was answering goes as soon as it finishes.
  useEffect(() => {
    if (busy || !pending.current) return;
    const text = pending.current;
    pending.current = "";
    setWaiting(false);
    const wait = window.setTimeout(() => onSendRef.current(text, sessionId), 250);
    return () => window.clearTimeout(wait);
  }, [busy, sessionId]);

  // --- the microphone -------------------------------------------------------------

  useEffect(() => {
    if (mode === "off") {
      setListening(false);
      setHeard("");
      finalText.current = "";
      interimText.current = "";
      stopVad();
      return;
    }
    const Speech = speechRecognition();
    if (!Speech) { setError("This browser cannot listen. Chrome or Edge can."); return; }
    void startVad();                       // for pause timing and real barge-in
    // A local model that has gone cold takes minutes to answer, so wake it while
    // the owner is still reaching for the first word (Big Kahuna's warm-up).
    void api.post("/api/identity0/warm", { keep_minutes: 20 }).catch(() => undefined);
    let stopped = false;
    let engine: Recognition | null = null;
    newUtterance();

    const start = () => {
      if (stopped) return;
      const recognition = new Speech();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = navigator.language || "en-US";
      recognition.onresult = (event) => {
        let finals = "", interim = "";
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const result = event.results[i];
          if (result.isFinal) finals += result[0].transcript;
          else interim += result[0].transcript;
        }
        const fresh = `${finals}${interim}`.trim();
        if (!fresh) return;

        // Nyx's own voice coming back through the microphone is never a message.
        if (speakingNow.current && isEcho(fresh)) return;
        if (speakingNow.current) {
          // Real words over the top: with the echo-cancelled microphone quiet,
          // this is still the speaker, so wait for the words to stand on their own.
          const vad = vadState();
          if (!vadRunning() || vad.speaking || fresh.split(/\s+/).length >= 3) {
            stopSpeaking();
            emitVoice({ type: "bargein" });
          } else {
            return;
          }
        }

        if (finals) finalText.current = `${finalText.current} ${finals}`.trim();
        interimText.current = interim;
        const sofar = `${finalText.current} ${interim}`.trim();
        setHeard(sofar);
        lastHeardAt.current = Date.now();
        emitVoice({ type: "partial", text: sofar, utteranceId: utteranceId.current });

        if (kahunaAllOn()) {
          // Read the words while they are still being said: safe actions happen now.
          window.clearTimeout(intentTimer.current);
          intentTimer.current = window.setTimeout(() => {
            void readIntent(sofar, false).then((intent) => {
              for (const action of intent?.actions ?? []) {
                if (!action.early || doneKeys.current.has(action.key)) continue;
                doneKeys.current.add(action.key);
                void runAction(action);
              }
            });
          }, 250);
        }

        const now = Date.now();
        if (now - lastThinkAt.current >= THINK_EVERY_MS) {
          lastThinkAt.current = now;
          void think(sofar, false);
        }
      };
      recognition.onerror = (event) => {
        if (event?.error === "not-allowed") { setError("The microphone is blocked for this page."); stopped = true; }
        else if (event?.error === "no-speech") setError("");
      };
      recognition.onend = () => {
        setListening(false);
        if (!stopped) window.setTimeout(start, 300);        // Chrome ends the session every so often
      };
      engine = recognition;
      try {
        recognition.start();
        setListening(true);
        setError("");
        emitVoice({ type: "start", mode });
      } catch {
        /* already running */
      }
    };
    start();

    // The pause itself: the microphone says when it went quiet, and the engine
    // says how long a pause has to be for *this* sentence.
    const check = window.setInterval(() => {
      if (!finalText.current && !interimText.current) return;
      if (busyRef.current && pending.current) return;
      const quietFor = vadRunning() ? vadState().silenceMs : Date.now() - lastHeardAt.current;
      const heardFor = Date.now() - lastHeardAt.current;
      if (quietFor >= waitMs.current && heardFor >= 350) void flush();
    }, 90);

    return () => {
      stopped = true;
      window.clearInterval(check);
      window.clearTimeout(intentTimer.current);
      engine?.stop();
      engine = null;
      setListening(false);
      stopVad();
      emitVoice({ type: "stop", mode });
    };
  }, [mode, flush, think, newUtterance]);

  const speakingText = useSpeakingText();
  speakingNow.current = Boolean(speakingText);

  const state = useMemo(
    () => ({ mode, listening, heard, error, waiting, complete, ready, sessionId }),
    [mode, listening, heard, error, waiting, complete, ready, sessionId],
  );
  // Everything else reads the engine through `useVoiceState`, so the chat bar and
  // the Proto Voice dock show one microphone instead of opening their own.
  useEffect(() => { publishState(state); }, [state]);
  return state;
}

/** The line Nyx is speaking right now, or null. */
export function useSpeakingText(): string | null {
  const [text, setText] = useState<string | null>(speaking());
  useEffect(() => onVoice((event) => { if (event.type === "speaking") setText(event.text); }), []);
  return text;
}
