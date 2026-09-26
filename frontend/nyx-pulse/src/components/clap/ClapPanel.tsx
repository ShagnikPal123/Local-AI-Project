/** Clap — teach Nyx a sound and say what it should do (Project Null N86).
 *
 * Settings → Clap. Two built-in sounds are recognised without teaching (two
 * claps, a whistle); anything else is taught by making it three times, which is
 * enough for the shape to average out without turning this into a chore.
 *
 * Every row says plainly when Nyx is listening for it, because a microphone that
 * is open at times you cannot predict is not something to leave implicit.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { pushToast } from "../../state/toastStore";
import { averageTemplates, startClapListening, startTeaching, stopClapListening, stopTeaching, clapListening } from "../../voice/clapDetector";
import "./clap.css";

interface Gesture {
  id: string; name: string; kind: string; enabled: boolean; when: string[];
  action: string; say: string; text: string; template: number[][]; heard?: number;
}
interface ClapState {
  enabled: boolean;
  sensitivity: number;
  greeting: { enabled: boolean; text: string; when: string };
  gestures: Gesture[];
}

const WHEN_WORDS: Record<string, string> = {
  away: "when you are away",
  offline: "when there is no internet",
  proto: "while the background voice is on",
  talk: "while we are talking",
  always: "always",
};

const ACTION_WORDS: Record<string, string> = {
  say: "say something back",
  listen: "start listening for what I say",
  status: "tell me what is going on",
  command: "do something I set",
};

const TAKES = 3;

export function ClapPanel() {
  const [state, setState] = useState<ClapState | null>(null);
  const [teaching, setTeaching] = useState<{ name: string; takes: number[][][]; recording: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const wasListening = useRef(false);

  const load = useCallback(async () => {
    const result = await api.get<ClapState>("/api/voice/gestures");
    if (result.ok) setState(result.data);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const changed = () => { window.dispatchEvent(new CustomEvent("nyx:clap-changed")); void load(); };

  async function saveSettings(changes: Partial<ClapState>) {
    const result = await api.put<ClapState>("/api/voice/gestures/settings", changes);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setState(result.data);
    changed();
  }

  async function patch(id: string, changes: Partial<Gesture>) {
    const result = await api.patch<{ gesture: Gesture }>(`/api/voice/gestures/${id}`, changes);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    changed();
  }

  async function remove(id: string, name: string) {
    if (!window.confirm(`Stop listening for “${name}”?`)) return;
    const result = await api.del(`/api/voice/gestures/${id}`);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    changed();
  }

  async function record() {
    if (!teaching) return;
    wasListening.current = clapListening();
    const ok = await startClapListening();
    if (!ok) { pushToast("Nyx could not open the microphone. Allow it in the browser and try again.", "warn"); return; }
    startTeaching();
    setTeaching({ ...teaching, recording: true });
  }

  function stopRecording() {
    if (!teaching) return;
    const take = stopTeaching();
    if (!wasListening.current) stopClapListening();
    if (take.length < 3) {
      pushToast("That was too short to learn — hold the sound a moment longer.", "warn");
      setTeaching({ ...teaching, recording: false });
      return;
    }
    setTeaching({ ...teaching, takes: [...teaching.takes, take], recording: false });
  }

  async function saveTaught() {
    if (!teaching || teaching.takes.length === 0) return;
    setSaving(true);
    const template = averageTemplates(teaching.takes);
    const result = await api.post<{ gesture: Gesture }>("/api/voice/gestures", {
      name: teaching.name.trim() || "My sound",
      kind: "taught",
      when: ["away", "offline", "proto"],
      action: "listen",
      say: "I'm here — what do you need?",
      template,
    });
    setSaving(false);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setTeaching(null);
    pushToast(`Nyx will answer to “${result.data.gesture.name}”.`, "ok");
    changed();
  }

  if (!state) return <p className="clap__loading">Loading…</p>;

  return (
    <div className="clap">
      <label className="clap__switch">
        <input type="checkbox" checked={state.enabled} onChange={(e) => void saveSettings({ enabled: e.target.checked })} />
        <span><b>Answer to sounds</b> — clap, whistle or anything you teach it, without touching the keyboard.</span>
      </label>

      <p className="clap__note">
        The microphone only opens for the times each sound lists below. Nothing is recorded: a sound becomes a short list
        of numbers describing its shape, and Nyx goes deaf while it is speaking so it never answers itself.
      </p>

      <div className="clap__rows" role="list">
        {state.gestures.map((gesture) => (
          <div key={gesture.id} role="listitem" className={`clap__row${gesture.enabled ? " is-on" : ""}`}>
            <div className="clap__row-head">
              <label className="clap__row-name">
                <input type="checkbox" checked={gesture.enabled} onChange={(e) => void patch(gesture.id, { enabled: e.target.checked })} />
                <b>{gesture.name}</b>
                <span className="clap__kind">{gesture.kind === "taught" ? "taught sound" : gesture.kind.replace("_", " ")}</span>
              </label>
              {gesture.heard ? <span className="clap__heard">heard {gesture.heard}×</span> : null}
              {gesture.kind === "taught" && (
                <button className="btn btn-secondary" onClick={() => void remove(gesture.id, gesture.name)}>Remove</button>
              )}
            </div>
            <div className="clap__row-body">
              <label>
                <span>Then Nyx will</span>
                <select value={gesture.action} onChange={(e) => void patch(gesture.id, { action: e.target.value })}>
                  {Object.entries(ACTION_WORDS).map(([value, words]) => <option key={value} value={value}>{words}</option>)}
                </select>
              </label>
              <label>
                <span>{gesture.action === "command" ? "Saying this to itself" : "Saying"}</span>
                <input
                  defaultValue={gesture.action === "command" ? gesture.text : gesture.say}
                  placeholder={gesture.action === "command" ? "e.g. read me my unread email" : "e.g. I'm here — what do you need?"}
                  onBlur={(e) => void patch(gesture.id, gesture.action === "command" ? { text: e.target.value } : { say: e.target.value })}
                />
              </label>
              <div className="clap__when">
                {Object.entries(WHEN_WORDS).map(([value, words]) => (
                  <button
                    key={value}
                    type="button"
                    className={`clap__when-chip${gesture.when.includes(value) ? " is-on" : ""}`}
                    aria-pressed={gesture.when.includes(value)}
                    onClick={() => void patch(gesture.id, {
                      when: gesture.when.includes(value) ? gesture.when.filter((w) => w !== value) : [...gesture.when, value],
                    })}
                  >
                    {words}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {teaching ? (
        <div className="clap__teach">
          <label>
            <span>What is this sound called?</span>
            <input autoFocus value={teaching.name} onChange={(e) => setTeaching({ ...teaching, name: e.target.value })}
                   placeholder="e.g. Two knocks, or “hey Nyx”" />
          </label>
          <p className="clap__note">
            Make the sound {TAKES} times — hold the button, make it, let go. Claps, a whistled tune, a knock on the desk
            or a short phrase all work.
          </p>
          <div className="clap__takes">
            {Array.from({ length: TAKES }).map((_, index) => (
              <span key={index} className={`clap__take${index < teaching.takes.length ? " is-done" : ""}`}>{index + 1}</span>
            ))}
            <button
              className={`btn ${teaching.recording ? "btn-primary is-live" : "btn-secondary"}`}
              onMouseDown={() => void record()}
              onMouseUp={stopRecording}
              onTouchStart={() => void record()}
              onTouchEnd={stopRecording}
            >
              {teaching.recording ? "Listening… let go when done" : teaching.takes.length >= TAKES ? "Make it again (optional)" : "Hold and make the sound"}
            </button>
          </div>
          <div className="clap__teach-actions">
            <button className="btn btn-primary" disabled={teaching.takes.length === 0 || saving} onClick={() => void saveTaught()}>
              {saving ? "Saving…" : `Teach it (${teaching.takes.length} of ${TAKES})`}
            </button>
            <button className="btn btn-secondary" onClick={() => { stopTeaching(); if (!wasListening.current) stopClapListening(); setTeaching(null); }}>Cancel</button>
          </div>
        </div>
      ) : (
        <button className="btn btn-secondary clap__add" onClick={() => setTeaching({ name: "", takes: [], recording: false })}>
          Teach Nyx a new sound
        </button>
      )}

      <div className="clap__tuning">
        <label>
          <span>How easily it hears things</span>
          <input type="range" min="0.2" max="0.95" step="0.05" defaultValue={state.sensitivity}
                 onChange={(e) => void saveSettings({ sensitivity: Number(e.target.value) })} />
          <small>Higher means it answers more readily — and mistakes the odd noise for you.</small>
        </label>
      </div>

      <div className="clap__greeting">
        <b>When the voice starts</b>
        <label className="clap__switch">
          <input type="checkbox" checked={state.greeting.enabled}
                 onChange={(e) => void saveSettings({ greeting: { ...state.greeting, enabled: e.target.checked } })} />
          <span>Say a line so you know it is listening</span>
        </label>
        <label>
          <span>What it says</span>
          <input defaultValue={state.greeting.text} placeholder="Nyx here. Listening."
                 onBlur={(e) => void saveSettings({ greeting: { ...state.greeting, text: e.target.value } })} />
        </label>
        <label>
          <span>How often</span>
          <select value={state.greeting.when} onChange={(e) => void saveSettings({ greeting: { ...state.greeting, when: e.target.value } })}>
            <option value="every">every time the voice is switched on</option>
            <option value="first">the first time each day</option>
            <option value="off">never</option>
          </select>
        </label>
      </div>
    </div>
  );
}
