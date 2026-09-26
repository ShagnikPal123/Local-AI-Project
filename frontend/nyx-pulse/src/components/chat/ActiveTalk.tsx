/** Talking to Nyx in the chat: the bar, and the speaking half of a spoken turn.
 *
 * The listening half lives in `src/voice/voiceEngine.ts` (Project Null N90).
 * What is here is what the owner hears and sees:
 *
 *  • Each sentence is read out **as it is written**, not after the whole answer
 *    lands, so the reply starts about as soon as the first line exists.
 *  • While it works it says what it is doing, sparingly — a spoken "searching
 *    the web" is useful once, not four times.
 *  • The bar under the messages says what it heard, whether it already has the
 *    answer ready, and how to stop.
 *
 * `useActiveTalk` keeps the name and shape the chat panel already used, so the
 * panel only had to gain the voice mode, not change how it talks to this.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { stopSpeaking, speakText } from "../../voice/voicePlayer";
import { useVoiceState, voiceSupported, useSpeakingText } from "../../voice/voiceEngine";
import { setVoiceMode, type VoiceMode } from "../../voice/voiceBus";
import type { AssistantTurn } from "./types";

/** A step is spoken at most this often, and only a few times a turn. */
const PROGRESS_GAP_MS = 5000;
const MAX_PROGRESS = 4;
/** How much of one answer is read aloud before the rest is left on screen. */
const SPEAK_LIMIT = 900;

export function activeTalkSupported(): boolean {
  return voiceSupported();
}

/** The first couple of sentences of an answer, without markdown, for reading aloud. */
export function speakable(text: string, limit = 700): string {
  const plain = plainSpeech(text);
  if (plain.length <= limit) return plain;
  const cut = plain.slice(0, limit);
  const stop = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("! "), cut.lastIndexOf("? "));
  return (stop > 120 ? cut.slice(0, stop + 1) : cut) + " …the rest is on screen.";
}

/** Markdown makes no sound: strip it before anything is spoken. */
function plainSpeech(text: string): string {
  return (text || "")
    .replace(/```[\s\S]*?```/g, " (there is code in the chat) ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " (a picture) ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_#>`|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Complete sentences at the start of `text`, and where they end. */
function sentencesIn(text: string): { said: string; upto: number } {
  const match = /^[\s\S]*?[.!?](?=\s|$)/.exec(text);
  if (!match) return { said: "", upto: 0 };
  let upto = 0;
  const sentences: string[] = [];
  const re = /[^.!?]*[.!?](?=\s|$)/g;
  let found: RegExpExecArray | null;
  while ((found = re.exec(text)) !== null) {
    sentences.push(found[0].trim());
    upto = found.index + found[0].length;
  }
  return { said: sentences.join(" ").trim(), upto };
}

export interface ActiveTalkState {
  on: boolean;
  mode: VoiceMode;
  listening: boolean;
  heard: string;
  speaking: string | null;
  error: string;
  waiting: boolean;
  /** 0–1: how finished what it is hearing sounds. */
  complete: number;
  /** The answer was written while the owner was still talking. */
  ready: boolean;
}

export function useActiveTalk({ enabled, turn }: {
  enabled: boolean;
  turn: AssistantTurn | undefined;
}): ActiveTalkState {
  // The microphone itself is `VoiceListener`, mounted once at the top of the app
  // so Proto Voice keeps listening on every tab. This reads it.
  const engine = useVoiceState();
  const speaking = useSpeakingText();

  // --- what Nyx says while it works, and the answer as it is written ---------
  const spokenSteps = useRef(new Set<string>());
  const lastProgress = useRef(0);
  const progressCount = useRef(0);
  const spokenTurn = useRef("");
  const spokenUpto = useRef(0);
  const spokenChars = useRef(0);

  const say = useCallback((text: string, role: string) => {
    const plain = plainSpeech(text);
    if (!plain) return;
    void speakText(plain, { role }).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!enabled || !turn) return;
    if (spokenTurn.current !== turn.turnId) {
      spokenTurn.current = turn.turnId;
      spokenUpto.current = 0;
      spokenChars.current = 0;
      spokenSteps.current.clear();
      progressCount.current = 0;
    }

    // Sentences that are finished get read while the rest is still being written.
    const answer = plainSpeech(turn.answer || "");
    if (answer.length > spokenUpto.current && spokenChars.current < SPEAK_LIMIT) {
      const rest = answer.slice(spokenUpto.current);
      const { said, upto } = turn.state === "done" ? { said: rest, upto: rest.length } : sentencesIn(rest);
      if (said && (said.length > 24 || turn.state === "done")) {
        spokenUpto.current += upto;
        spokenChars.current += said.length;
        say(spokenChars.current >= SPEAK_LIMIT ? `${said} …the rest is on screen.` : said, "reply");
      }
    }

    if (turn.state === "streaming" && !turn.answer) {
      const running = turn.steps?.filter((step) => step.status === "running") ?? [];
      const step = running[running.length - 1];
      const now = Date.now();
      if (step && !spokenSteps.current.has(step.callId ?? step.name) && now - lastProgress.current > PROGRESS_GAP_MS
          && progressCount.current < MAX_PROGRESS) {
        spokenSteps.current.add(step.callId ?? step.name);
        lastProgress.current = now;
        progressCount.current += 1;
        say(step.label || `${step.name.replace(/_/g, " ")}…`, "narrator");
      }
    }
  }, [enabled, turn?.state, turn?.turnId, turn?.steps?.length, turn?.answer, say]); // eslint-disable-line react-hooks/exhaustive-deps

  return useMemo(() => ({
    on: enabled,
    mode: engine.mode,
    listening: engine.listening,
    heard: engine.heard,
    speaking,
    error: engine.error,
    waiting: engine.waiting,
    complete: engine.complete,
    ready: engine.ready,
  }), [enabled, engine.mode, engine.listening, engine.heard, speaking, engine.error, engine.waiting,
       engine.complete, engine.ready]);
}

/** The strip under the messages while voice is on: what it heard, and how to stop. */
export function ActiveTalkBar({ state, onOff }: { state: ActiveTalkState; onOff: () => void }) {
  if (!state.on) return null;
  const line = state.error ? state.error
    : state.speaking ? "Nyx is speaking — just talk to interrupt"
    : state.waiting ? "Heard you — it goes as soon as this answer finishes"
    : state.heard ? state.heard
    : state.listening ? (state.mode === "proto" ? "Proto Voice is listening" : "Listening — stop talking for a moment and it sends by itself")
    : "Starting the microphone…";
  return (
    <div className={`talk${state.error ? " is-error" : ""}`} role="status" aria-live="polite">
      <span className={`talk__dot${state.listening && !state.speaking ? " is-live" : ""}${state.speaking ? " is-speaking" : ""}`} aria-hidden="true" />
      <span className="talk__text">{line}</span>
      {state.heard && !state.speaking && (
        <span className="talk__meter" title="How finished that sounded — a finished sentence is answered sooner">
          <span className="talk__meter-fill" style={{ width: `${Math.round(state.complete * 100)}%` }} />
        </span>
      )}
      {state.ready && !state.speaking && <span className="talk__ready">answer ready</span>}
      {state.speaking && <button className="chat-inline" onClick={() => stopSpeaking()}>Quiet</button>}
      <button className="chat-inline" onClick={onOff}>Turn off</button>
    </div>
  );
}

/** The switch in the chat bar: off → talk → proto. */
export function VoiceSwitch({ mode, onMode }: { mode: VoiceMode; onMode: (mode: VoiceMode) => void }) {
  const [open, setOpen] = useState(false);
  const label = mode === "proto" ? "Proto" : "Talk";
  const title = mode === "off" ? "Voice: speak instead of typing"
    : mode === "talk" ? "Active talk is on — speak and it sends by itself"
    : "Proto Voice is on — it always listens and can act on the computer";
  return (
    <span className="voice-switch">
      <button className={`chat-talk${mode !== "off" ? " is-on" : ""}`} role="switch" aria-checked={mode !== "off"}
        onClick={() => { const next: VoiceMode = mode === "off" ? "talk" : "off"; setVoiceMode(next); onMode(next); }}
        title={title}>
        <span className="chat-talk__dot" aria-hidden="true" />{label}
      </button>
      <button className="voice-switch__more" aria-label="Voice mode" aria-expanded={open}
              onClick={() => setOpen((v) => !v)} title="Choose how it listens">
        <svg width="9" height="9" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div className="voice-switch__menu" role="menu">
          {([
            ["off", "Off", "Nothing is listening"],
            ["talk", "Talk", "Speak, and it answers out loud"],
            ["proto", "Proto Voice", "Always listening, and allowed to act"],
          ] as [VoiceMode, string, string][]).map(([value, name, what]) => (
            <button key={value} role="menuitemradio" aria-checked={mode === value}
                    className={`voice-switch__item${mode === value ? " is-picked" : ""}`}
                    onClick={() => { setOpen(false); setVoiceMode(value); onMode(value); }}>
              <b>{name}</b><span>{what}</span>
            </button>
          ))}
        </div>
      )}
    </span>
  );
}
