/** The equalize page (from the Jarvis projects the owner pointed at, 2026-10-09; rebuilt for Nyx, no code taken).
 *
 * One screen to talk to Nyx and see what is waiting: a particle orb that listens, thinks and speaks; an Ask box that
 * can answer out loud; "Needs you" — every approval Nyx is waiting on, trades to approve, and Claude Code sessions
 * that stopped for the owner; and every recent Claude Code session on this PC by state. */

import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../../api";
import { onVoice, setVoiceMode, voiceMode, onVoiceMode } from "../../voice/voiceBus";
import { stopSpeaking } from "../../voice/voicePlayer";
import { useSpeakingText } from "../../voice/voiceEngine";
import { useTurns } from "../../hooks/useTurns";
import { useActiveTalk } from "../../components/chat/ActiveTalk";
import { useStore } from "../../state/store";
import { turnsStore } from "../../state/turnStore";
import { DigestCard } from "./DigestCard";
import "./equalize.css";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";
interface Need { kind: "approval" | "trade" | "claude"; id: string; title: string; detail: string; where: string; since: number }
interface Session { id: string; project: string; cwd: string; title: string; last: number; state: string; why: string }

export const STATE_WORDS: Record<OrbState, string> = { idle: "Ready", listening: "Listening", thinking: "Thinking", speaking: "Speaking" };
const SESSION_WORDS: Record<string, string> = { needs_you: "Needs you", working: "Working", your_turn: "Your turn", idle: "Idle" };

function ago(seconds: number): string {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/** A sphere of points that breathes when idle, ripples while listening, swirls while thinking and pulses with speech. */
export function Orb({ state }: { state: OrbState }) {
  const host = useRef<HTMLDivElement>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.z = 3.2;
    const count = 2400;
    const base = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {               // Fibonacci sphere: even spacing, no seams
      const y = 1 - (i / (count - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const t = i * Math.PI * (3 - Math.sqrt(5));
      base.set([Math.cos(t) * r, y, Math.sin(t) * r], i * 3);
    }
    const positions = base.slice();
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const material = new THREE.PointsMaterial({ size: 0.022, color: 0xa594ff, transparent: true, opacity: 0.9 });
    const points = new THREE.Points(geometry, material);
    scene.add(points);
    const colours: Record<OrbState, THREE.Color> = {
      idle: new THREE.Color(0xa594ff), listening: new THREE.Color(0x64d2ff),
      thinking: new THREE.Color(0xffd60a), speaking: new THREE.Color(0x7bd3a8),
    };
    const resize = () => {
      const size = Math.max(160, Math.min(el.clientWidth, 420));
      renderer.setSize(size, size);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    let frame = 0;
    const start = performance.now();
    const draw = () => {
      const t = (performance.now() - start) / 1000;
      const now = stateRef.current;
      material.color.lerp(colours[now], 0.08);
      const amp = now === "speaking" ? 0.12 + 0.06 * Math.sin(t * 9) : now === "listening" ? 0.07 : now === "thinking" ? 0.05 : 0.025;
      for (let i = 0; i < count; i++) {
        const x = base[i * 3], y = base[i * 3 + 1], z = base[i * 3 + 2];
        const wave = Math.sin(t * (now === "listening" ? 5 : 1.6) + y * 6 + x * 3) * amp;
        const k = 1 + wave;
        positions[i * 3] = x * k; positions[i * 3 + 1] = y * k; positions[i * 3 + 2] = z * k;
      }
      geometry.attributes.position.needsUpdate = true;
      points.rotation.y += now === "thinking" ? 0.02 : 0.004;
      points.rotation.x = Math.sin(t * 0.3) * 0.15;
      renderer.render(scene, camera);
      if (!reduced) frame = requestAnimationFrame(draw);
    };
    draw();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      geometry.dispose();
      material.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={host} className="jv-orb" role="img" aria-label={`Nyx is ${STATE_WORDS[state].toLowerCase()}`} />;
}

/** The chat Equalize talks in: the one the owner was last in, so the conversation continues in the Chat tab. */
function activeChat(): string {
  try { return localStorage.getItem("nyx.chat.active") || "default"; } catch { return "default"; }
}

export function EqualizePanel() {
  // Fixed 2026-10-10 (owner: "it simply doesn't work well"). Two real bugs: what you said on this tab went to the
  // chat panel — which is not on screen here — so speech vanished or yanked you to Chat; and Ask used a slow,
  // blocking /api/chat call that never streamed. Now both go through the chat's own live turns (useTurns) in your
  // current chat, answers stream onto this page, and useActiveTalk speaks them sentence by sentence as they are written.
  const chatId = activeChat();
  const { runningTurn, send } = useTurns(chatId);
  const [mode, setMode] = useState(voiceMode());
  const [heard, setHeard] = useState("");
  const [listening, setListening] = useState(false);
  const [ask, setAsk] = useState("");
  const [speak, setSpeak] = useState(() => localStorage.getItem("nyx.equalize.speak") !== "0");
  const [needs, setNeeds] = useState<Need[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState("");
  const [log, setLog] = useState<{ you: string; turnId?: string }[]>([]);
  const turns = useStore(turnsStore, (s) => s.turns);
  const speakingNow = useSpeakingText();
  const talkOn = mode !== "off";
  useActiveTalk({ enabled: talkOn || speak, turn: runningTurn });

  // The quickest model for spoken answers, as the chat picks it (local first, then a fast online one).
  const [voiceProvider, setVoiceProvider] = useState("");
  useEffect(() => {
    let alive = true;
    void api.get<{ service?: { router_status?: Record<string, boolean> } }>("/api/status").then((r) => {
      if (!alive || !r.ok) return;
      const router = r.data.service?.router_status ?? {};
      setVoiceProvider(["identity0", "ollama", "groq", "nvidia", "gemini"].find((n) => router[`${n}_available`]) ?? "");
    });
    return () => { alive = false; };
  }, []);

  // The desktop notch (notch.py): Ichos's voice as a pill on top of the screen, outside the browser.
  const [notchOn, setNotchOn] = useState(false);
  useEffect(() => { void api.get<{ running: boolean }>("/api/notch").then((r) => { if (r.ok) setNotchOn(r.data.running); }); }, []);
  const toggleNotch = async () => {
    const r = await api.post<{ running: boolean }>(notchOn ? "/api/notch/stop" : "/api/notch/start", {});
    if (r.ok) setNotchOn(!notchOn); else setError(r.error);
  };

  useEffect(() => onVoiceMode(setMode), []);
  useEffect(() => onVoice((event) => {
    if (event.type === "partial" || event.type === "final") { setHeard(event.text); setListening(event.type === "partial"); }
    else if (event.type === "start") setListening(true);
    else if (event.type === "stop") setListening(false);
  }), []);

  const say = useCallback(async (text: string, sessionId?: string, spoken = false) => {
    const message = text.trim();
    if (!message) return;
    setError("");
    setLog((l) => [...l.slice(-5), { you: message }]);
    await send({ message, chatId, voice: spoken || speak, voiceSession: sessionId,
                 provider: spoken ? voiceProvider || undefined : undefined });
  }, [send, chatId, speak, voiceProvider]);

  // What the one microphone heard arrives here while this page is open (the chat panel is not mounted).
  useEffect(() => {
    const onVoiceSend = (event: Event) => {
      const detail = (event as CustomEvent<{ text?: string; sessionId?: string }>).detail ?? {};
      if (detail.text) void say(detail.text, detail.sessionId, true);
    };
    window.addEventListener("nyx:voice-send", onVoiceSend);
    return () => window.removeEventListener("nyx:voice-send", onVoiceSend);
  }, [say]);

  // Tie each thing you said to the turn that answered it, so the page shows the conversation.
  const runningId = runningTurn?.turnId;
  useEffect(() => {
    if (!runningId) return;
    // The first id is a local placeholder; the real one replaces it when the server answers, so follow it.
    setLog((l) => {
      const last = l[l.length - 1];
      if (!last || (last.turnId && !last.turnId.startsWith("local-"))) return l;
      return [...l.slice(0, -1), { ...last, turnId: runningId }];
    });
  }, [runningId]);

  const busy = Boolean(runningTurn);
  const orb: OrbState = speakingNow ? "speaking" : busy ? "thinking" : listening ? "listening" : "idle";

  const load = useCallback(async () => {
    const [n, s] = await Promise.all([api.get<{ items: Need[] }>("/api/equalize/needs-you"), api.get<{ sessions: Session[] }>("/api/equalize/sessions")]);
    if (n.ok) setNeeds(n.data.items); else setError(n.error);
    if (s.ok) setSessions(s.data.sessions);
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  const sendTyped = async () => {
    const text = ask;
    setAsk("");
    await say(text);
  };

  const answer = async (need: Need, approve: boolean) => {
    const path = need.kind === "trade" ? `/api/trading/approvals/${need.id}` : `/api/approvals/${encodeURIComponent(need.id)}`;
    const result = await api.post(path, { approve }, 60000);
    if (!result.ok) setError(result.error);
    void load();
  };

  const groups = ["needs_you", "working", "your_turn", "idle"].map((state) => ({ state, items: sessions.filter((s) => s.state === state) }))
    .filter((g) => g.items.length);

  return (
    <div className="jv">
      <section className="jv-hero" aria-label="Talk to Ichos">
        <Orb state={orb} />
        <div className="jv-hero__side">
          <p className="jv-state" aria-live="polite">{STATE_WORDS[orb]}{heard && listening ? ` — “${heard}”` : ""}</p>
          <form className="jv-ask" onSubmit={(e) => { e.preventDefault(); void sendTyped(); }}>
            <input value={ask} onChange={(e) => setAsk(e.target.value)} placeholder={talkOn ? "Talk, or type here…" : "Ask Ichos anything…"} aria-label="Ask Ichos" />
            <button className="btn btn-primary" disabled={busy || !ask.trim()}>{busy ? "Answering…" : "Ask"}</button>
          </form>
          <div className="jv-row">
            <button className={`btn ${talkOn ? "btn-primary" : "btn-secondary"}`} onClick={() => setVoiceMode(talkOn ? "off" : "talk")} aria-pressed={talkOn}>
              {talkOn ? "Stop listening" : "Talk"}
            </button>
            {speakingNow && <button className="btn btn-secondary" onClick={() => stopSpeaking()}>Stop speaking</button>}
            <label className="jv-check">
              <input type="checkbox" checked={speak} onChange={(e) => { setSpeak(e.target.checked); try { localStorage.setItem("nyx.equalize.speak", e.target.checked ? "1" : "0"); } catch { /* not kept */ } }} />
              Speak answers
            </label>
            <button className="btn btn-secondary" onClick={() => void toggleNotch()} aria-pressed={notchOn}
              title="A pill at the top of your screen that shows when Ichos listens, thinks and speaks — even with Ichos behind other apps">
              {notchOn ? "Hide the notch" : "Show the notch on screen"}
            </button>
          </div>
          {log.length > 0 && (
            <ol className="jv-convo" aria-label="This conversation">
              {log.map((entry, i) => {
                const turn = entry.turnId ? turns[entry.turnId] : undefined;
                return (
                  <li key={i}>
                    <p className="jv-you">{entry.you}</p>
                    <p className="jv-reply">{turn?.answer || (turn ? turn.status || "Thinking…" : "Sending…")}</p>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </section>

      {error && <p className="jv-error" role="alert">{error}</p>}

      <div className="jv-grid">
        <section className="jv-card" aria-labelledby="jv-needs">
          <h2 id="jv-needs">Needs you <span>{needs.length || ""}</span></h2>
          {needs.length === 0 && <p className="jv-muted">Nothing is waiting on you.</p>}
          <ul className="jv-list">
            {needs.map((need) => (
              <li key={`${need.kind}-${need.id}`} className={`jv-need is-${need.kind}`}>
                <div>
                  <b>{need.title}</b>
                  {need.detail && <span className="jv-muted">{need.detail}</span>}
                  <span className="jv-muted">{ago(need.since)}</span>
                </div>
                {need.kind !== "claude" && (
                  <span className="jv-actions">
                    <button className="btn btn-primary" onClick={() => void answer(need, true)}>Approve</button>
                    <button className="btn btn-secondary" onClick={() => void answer(need, false)}>Decline</button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>

        <DigestCard />

        <section className="jv-card jv-card--wide" aria-labelledby="jv-sessions">
          <h2 id="jv-sessions">Claude Code on this PC <span>{sessions.length || ""}</span></h2>
          {sessions.length === 0 && <p className="jv-muted">No Claude Code sessions in the last week.</p>}
          {groups.map((group) => (
            <div key={group.state} className="jv-group">
              <h3 className={`is-${group.state}`}>{SESSION_WORDS[group.state]} · {group.items.length}</h3>
              <ul className="jv-list">
                {group.items.map((s) => (
                  <li key={s.id} className="jv-session" title={s.cwd}>
                    <span className={`jv-dot is-${s.state}`} aria-hidden="true" />
                    <div><b>{s.title}</b><span className="jv-muted">{s.project} · {ago(s.last)} · {s.why}</span></div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
