/** Proto Voice on screen: what it heard, what it did, and what it will not do.
 *
 * It floats above every tab, because Proto Voice is not a tab — the owner turns
 * it on once and then walks around the app (or away from it). Three states:
 *
 *   • not allowed yet → the consent card, once, like Free Will's.
 *   • listening      → the live line, and the last few things it did.
 *   • asking         → one question with Yes and No, which expires by itself.
 *
 * The two things it cannot do are written on the card rather than discovered by
 * asking: unlocking Windows (a separate secure desktop, and Nyx keeps no
 * password) and switching the PC on (nothing is listening while it is off).
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { onVoice, onVoiceMode, setVoiceMode, voiceMode } from "../../voice/voiceBus";
import "./voice.css";

type Settings = {
  allowed: boolean;
  standby: boolean;
  wake_words: string[];
  speak_actions: boolean;
  confirm_power: boolean;
  agents: boolean;
};

type State = { settings: Settings; asking: string; token: string; can_act: boolean };

const CAN = [
  "Open apps, folders, files and websites",
  "Move around Nyx: \"open the finance tab\"",
  "Volume, mute and the media keys",
  "Lock, sleep, restart — after you say yes",
  "Bring sub-agents into the chat and give them work",
  "Run a simulation: what it would do, doing none of it",
];
const CANNOT = [
  "Unlock Windows. The lock screen is its own secure desktop that nothing running as you can type into, and Nyx never keeps your password. Windows Hello does this properly.",
  "Turn the PC on. Nothing on it can hear while it is off; it does start itself with Windows.",
  "Send mail, spend money, or delete your files by voice. It drafts and you press send.",
];

export function ProtoVoiceDock() {
  const [mode, setMode] = useState(voiceMode());
  const [state, setState] = useState<State | null>(null);
  const [heard, setHeard] = useState("");
  const [log, setLog] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => onVoiceMode(setMode), []);

  const load = useCallback(async () => {
    const result = await api.get<State>("/api/proto-voice");
    if (result.ok) setState(result.data);
  }, []);

  useEffect(() => { if (mode === "proto") void load(); }, [mode, load]);

  useEffect(() => onVoice((event) => {
    if (event.type === "partial" || event.type === "final") setHeard(event.text);
  }), []);

  // What it did, from the engine, so the dock is honest even when Nyx acted on
  // something said while another tab was open.
  useEffect(() => onWorkspaceEvent((event) => {
    const e = event as { type: string; did?: string; said?: string; asking?: string; token?: string; standby?: boolean };
    if (e.type !== "voice.proto") return;
    if (e.asking) { setState((s) => (s ? { ...s, asking: e.asking ?? "", token: e.token ?? "" } : s)); return; }
    if (typeof e.standby === "boolean") { void load(); return; }
    if (e.did) {
      setLog((current) => [`${e.said || e.did}`, ...current].slice(0, 6));
      setState((s) => (s ? { ...s, asking: "", token: "" } : s));
    }
  }), [load]);

  const save = useCallback(async (changes: Partial<Settings>) => {
    setBusy(true);
    const result = await api.put<{ settings: Settings }>("/api/proto-voice", changes);
    if (result.ok) setState((s) => (s ? { ...s, settings: result.data.settings } : s));
    setBusy(false);
  }, []);

  const answer = useCallback(async (yes: boolean) => {
    if (!state?.token) return;
    await api.post("/api/proto-voice/confirm", { token: state.token, yes });
    setState((s) => (s ? { ...s, asking: "", token: "" } : s));
  }, [state?.token]);

  if (mode !== "proto") return null;

  if (state && !state.settings.allowed) {
    return (
      <div className="proto proto--consent" role="dialog" aria-label="Allow Proto Voice">
        <h2 className="proto__title">Let Nyx listen all the time?</h2>
        <p className="proto__lead">
          Proto Voice keeps the microphone open and acts on what you say. Nothing is recorded or stored —
          the words become an action or a message and are gone.
        </p>
        <div className="proto__cols">
          <div>
            <h3>It can</h3>
            <ul>{CAN.map((line) => <li key={line}>{line}</li>)}</ul>
          </div>
          <div>
            <h3>It cannot</h3>
            <ul>{CANNOT.map((line) => <li key={line}>{line}</li>)}</ul>
          </div>
        </div>
        <div className="proto__row">
          <button className="btn btn-primary" disabled={busy} onClick={() => void save({ allowed: true })}>
            Allow Proto Voice
          </button>
          <button className="btn btn-secondary" onClick={() => setVoiceMode("talk")}>Just active talk</button>
          <button className="btn btn-plain" onClick={() => setVoiceMode("off")}>Turn voice off</button>
        </div>
      </div>
    );
  }

  const standby = Boolean(state?.settings.standby);
  return (
    <div className={`proto${open ? " is-open" : ""}`} role="status" aria-live="polite">
      <div className="proto__bar">
        <span className={`proto__dot${standby ? " is-standby" : ""}`} aria-hidden="true" />
        <span className="proto__label">{standby ? "Standby — say “Nyx”" : "Proto Voice"}</span>
        <span className="proto__heard">{state?.asking || heard}</span>
        {state?.asking && (
          <>
            <button className="btn btn-primary proto__yes" onClick={() => void answer(true)}>Yes</button>
            <button className="btn btn-secondary" onClick={() => void answer(false)}>No</button>
          </>
        )}
        <button className="proto__more" aria-expanded={open} onClick={() => setOpen((v) => !v)}
                title="Proto Voice settings">⋯</button>
        <button className="chat-inline" onClick={() => setVoiceMode("off")}>Stop</button>
      </div>
      {open && state && (
        <div className="proto__panel">
          <label className="proto__check">
            <input type="checkbox" checked={state.settings.speak_actions} disabled={busy}
                   onChange={(e) => void save({ speak_actions: e.target.checked })} />
            Say what it is doing
          </label>
          <label className="proto__check">
            <input type="checkbox" checked={state.settings.confirm_power} disabled={busy}
                   onChange={(e) => void save({ confirm_power: e.target.checked })} />
            Ask before sleep, restart and shutdown
          </label>
          <label className="proto__check">
            <input type="checkbox" checked={state.settings.agents} disabled={busy}
                   onChange={(e) => void save({ agents: e.target.checked })} />
            May bring sub-agents into the chat
          </label>
          <label className="proto__field">
            <span>It answers to</span>
            <input type="text" defaultValue={state.settings.wake_words.join(", ")} disabled={busy}
                   onBlur={(e) => void save({ wake_words: e.target.value.split(",").map((w) => w.trim()).filter(Boolean) })} />
          </label>
          <div className="proto__row">
            <button className="btn btn-secondary" disabled={busy}
                    onClick={() => void save({ standby: !standby })}>
              {standby ? "Start listening" : "Go quiet until I say Nyx"}
            </button>
          </div>
          {log.length > 0 && (
            <ul className="proto__log">{log.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}</ul>
          )}
          <p className="proto__fine">
            It will not unlock Windows or type a password — the lock screen is a separate secure desktop, and
            Windows Hello is the way to do that.
          </p>
        </div>
      )}
    </div>
  );
}
