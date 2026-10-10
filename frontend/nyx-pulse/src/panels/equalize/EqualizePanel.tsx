/** The Jarvis page (from the Jarvis projects the owner pointed at, 2026-10-09; rebuilt for Nyx, no code taken).
 *
 * One screen to talk to Nyx and see what is waiting: a particle orb that listens, thinks and speaks; an Ask box that
 * can answer out loud; "Needs you" — every approval Nyx is waiting on, trades to approve, and Claude Code sessions
 * that stopped for the owner; and every recent Claude Code session on this PC by state. */

import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../../api";
import { onVoice, setVoiceMode, voiceMode, onVoiceMode } from "../../voice/voiceBus";
import { speakText } from "../../voice/voicePlayer";
import { DigestCard } from "./DigestCard";
import "./jarvis.css";

type OrbState = "idle" | "listening" | "thinking" | "speaking";
interface Need { kind: "approval" | "trade" | "claude"; id: string; title: string; detail: string; where: string; since: number }
interface Session { id: string; project: string; cwd: string; title: string; last: number; state: string; why: string }

const STATE_WORDS: Record<OrbState, string> = { idle: "Ready", listening: "Listening", thinking: "Thinking", speaking: "Speaking" };
const SESSION_WORDS: Record<string, string> = { needs_you: "Needs you", working: "Working", your_turn: "Your turn", idle: "Idle" };

function ago(seconds: number): string {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/** A sphere of points that breathes when idle, ripples while listening, swirls while thinking and pulses with speech. */
function Orb({ state }: { state: OrbState }) {
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

export function JarvisPanel() {
  const [orb, setOrb] = useState<OrbState>("idle");
  const [mode, setMode] = useState(voiceMode());
  const [heard, setHeard] = useState("");
  const [ask, setAsk] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [speak, setSpeak] = useState(() => localStorage.getItem("nyx.jarvis.speak") !== "0");
  const [needs, setNeeds] = useState<Need[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState("");

  useEffect(() => onVoiceMode(setMode), []);
  useEffect(() => onVoice((event) => {
    if (event.type === "partial" || event.type === "final") { setHeard(event.text); setOrb("listening"); }
    else if (event.type === "start") setOrb("listening");
    else if (event.type === "stop") setOrb((s) => (s === "listening" ? "idle" : s));
    else if (event.type === "speaking") setOrb(event.text ? "speaking" : "idle");
  }), []);

  const load = useCallback(async () => {
    const [n, s] = await Promise.all([api.get<{ items: Need[] }>("/api/jarvis/needs-you"), api.get<{ sessions: Session[] }>("/api/jarvis/sessions")]);
    if (n.ok) setNeeds(n.data.items); else setError(n.error);
    if (s.ok) setSessions(s.data.sessions);
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  const send = async () => {
    const text = ask.trim();
    if (!text) return;
    setBusy(true); setOrb("thinking"); setReply("");
    const result = await api.post<{ reply: string }>("/api/chat", { message: text }, 180000);
    setBusy(false);
    if (!result.ok) { setReply(result.error); setOrb("idle"); return; }
    setReply(result.data.reply);
    setAsk("");
    if (speak) {
      setOrb("speaking");
      try { await speakText(result.data.reply.slice(0, 900)); } catch { /* no voice: the text is on screen */ }
    }
    setOrb("idle");
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
      <section className="jv-hero" aria-label="Talk to Nyx">
        <Orb state={busy ? "thinking" : orb} />
        <div className="jv-hero__side">
          <p className="jv-state" aria-live="polite">{STATE_WORDS[busy ? "thinking" : orb]}{heard && orb === "listening" ? ` — “${heard}”` : ""}</p>
          <form className="jv-ask" onSubmit={(e) => { e.preventDefault(); void send(); }}>
            <input value={ask} onChange={(e) => setAsk(e.target.value)} placeholder="Ask Nyx anything…" aria-label="Ask Nyx" />
            <button className="btn btn-primary" disabled={busy || !ask.trim()}>{busy ? "Thinking…" : "Ask"}</button>
          </form>
          <div className="jv-row">
            <button className="btn btn-secondary" onClick={() => setVoiceMode(mode === "talk" ? "off" : "talk")} aria-pressed={mode === "talk"}>
              {mode === "talk" ? "Stop Listening" : "Talk"}
            </button>
            <label className="jv-check">
              <input type="checkbox" checked={speak} onChange={(e) => { setSpeak(e.target.checked); try { localStorage.setItem("nyx.jarvis.speak", e.target.checked ? "1" : "0"); } catch { /* not kept */ } }} />
              Speak answers
            </label>
          </div>
          {reply && <div className="jv-reply">{reply}</div>}
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
