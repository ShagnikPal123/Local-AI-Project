/** Second Brain → Core: Nyx at work, as one living screen (owner request, 2026-09-16).
 *
 * "Make a third tab in second brain and add usage gauges for each process, all agents, api, and such being used.
 * Show sub agents and a way to run them from there and a way to … drop into a single project or press a plus to
 * add them. … In third tab add what the image looks like that I attached. This should be clean and aesthetic."
 *
 * The reference: a white-blue core glowing inside a sparse particle field on deep navy, a light strip arcing
 * across the top, and quiet glass panels at the edges — ring gauges top-right, a markets list on the left, a
 * voice channel waveform at the bottom and one monospace status line. Here every panel is real data from
 * `/api/core/overview` (polled while visible):
 *   • gauges — machine CPU / memory / GPU and this engine's own CPU;
 *   • APIs — each provider's calls, success, latency, limits and key health; markets from the Trading watchlist;
 *   • Sub-agents — drag one into the project dock (drag again for a second copy), Run, or + to make a new one;
 *   • Processes — everything running in the background, found rather than listed (`feature_catalog`, U31): jobs
 *     with their progress first, then the loops that are always on, folded away; a row opens the tab that shows it;
 *   • the core itself breathes with activity: brighter while Nyx thinks, pulsing while it speaks.
 * Reduced motion draws one still frame.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../../api";
import { useReducedMotion } from "../../useReducedMotion";
import { useStore } from "../../state/store";
import { turnsStore } from "../../state/turnStore";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { onSpeakingChange } from "../../voice/voicePlayer";
import { pushToast } from "../../state/toastStore";
import { BoxEditor, DispatchCard, newBox, runBoxes, useRoster, type BoxItem, type DispatchView } from "../agents/AgentBoxes";
import "./core.css";

interface Provider {
  name: string; calls: number; failures: number; last_hour: number; avg_latency: number | null; success_rate: number | null;
  tokens: number; configured: boolean; models: Record<string, number>; last_error: string;
  limit?: { window: string; kind: string; limit: number; remaining: number | null };
  keys?: { total: number; working: number; failed: number };
}
interface CoreAgent {
  name: string; emoji: string; role: string; goal: string; made_by: string; builtin: boolean; provider: string; model: string;
  status: string; copies_working: number; step: string; tasks_done: number; command: string;
}
interface Process {
  kind: string; id: string; label: string; detail: string; status: string; seconds?: number; progress?: number | null; chat_id?: string;
  /** "job" ends; "service" is a loop that is always on (the scheduler, the brain writer). */
  group?: "job" | "service";
  /** The tab that shows this work, or "" when none does. */
  tab?: string;
  source?: string;
}
interface Overview {
  at: number;
  machine: { cpu_percent?: number; memory_percent?: number; memory_used_gb?: number; memory_total_gb?: number; gpu_percent?: number | null; gpu_name?: string };
  engine: { cpu_percent?: number; memory_mb?: number; threads?: number; uptime_seconds?: number };
  providers: Provider[]; agents: CoreAgent[]; processes: Process[];
  today: { turns: number; ok?: number; median_latency_s?: number | null; agents_used?: number; tools_used?: number };
}
interface Signal { symbol: string; change_pct?: number | null; sparkline?: number[]; indicators?: { price: number }; error?: string }
interface Project { value: string; name: string; path?: string; kind: "code" | "build" }

const PROVIDER_LABEL: Record<string, string> = {
  nvidia: "NVIDIA", gemini: "Gemini", groq: "Groq", openai: "OpenAI", claude: "Claude", deepseek: "DeepSeek", kimi: "Kimi",
  aws: "AWS Bedrock", ollama: "Ollama", pollinations: "Pollinations", perplexity: "Perplexity",
};
const label = (name: string) => PROVIDER_LABEL[name] ?? name.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

function duration(seconds?: number): string {
  if (!seconds && seconds !== 0) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** Where a row opens when the server did not say (rows from before `tab` existed). */
const LEGACY_TAB: Record<string, string> = { autopilot: "improve", review: "improve", analysis: "improve", turn: "nyx", dispatch: "nyx" };

/** One background process: what it is, what it is doing, for how long, and how far along — opens where it is shown. */
function ProcessRow({ p, onOpenTab, service = false }: { p: Process; onOpenTab?: (tab: string) => void; service?: boolean }) {
  const tab = p.tab || LEGACY_TAB[p.kind] || "";
  const body = (
    <>
      <span className="core__api-name"><b>{p.label}</b>{p.detail && <span>{p.detail}</span>}</span>
      {typeof p.seconds === "number" && <span className="core__proc-time">{duration(p.seconds)}</span>}
    </>
  );
  return (
    <li className={`core__proc${service ? " is-service" : ""}`}>
      {tab && onOpenTab ? (
        <button className="core__proc-main" onClick={() => onOpenTab(tab)} title={`Open ${tab}`}>{body}</button>
      ) : (
        <div className="core__proc-main is-static">{body}</div>
      )}
      {!service && (
        <span className={`core__progress${typeof p.progress === "number" ? "" : " is-indeterminate"}`}>
          <i style={{ width: typeof p.progress === "number" ? `${Math.max(3, p.progress * 100)}%` : undefined }} />
        </span>
      )}
    </li>
  );
}

// --- the scene ------------------------------------------------------------------------------------------

function glowTexture(stops: [number, string][], size = 256): THREE.Texture {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  stops.forEach(([at, color]) => gradient.addColorStop(at, color));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function streakTexture(): THREE.Texture {
  const canvas = document.createElement("canvas");
  canvas.width = 512; canvas.height = 32;
  const ctx = canvas.getContext("2d")!;
  const gradient = ctx.createLinearGradient(0, 0, 512, 0);
  gradient.addColorStop(0, "rgba(120,190,255,0)");
  gradient.addColorStop(0.42, "rgba(170,215,255,0.55)");
  gradient.addColorStop(0.5, "rgba(255,255,255,1)");
  gradient.addColorStop(0.58, "rgba(170,215,255,0.55)");
  gradient.addColorStop(1, "rgba(120,190,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 13, 512, 6);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function CoreScene({ energy, reduced, shiftX }: { energy: number; reduced: boolean; shiftX: number }) {
  const host = useRef<HTMLDivElement>(null);
  const energyRef = useRef(energy);
  const shiftRef = useRef(shiftX);
  energyRef.current = energy;
  shiftRef.current = shiftX;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      return; // no WebGL: the CSS glow behind the canvas still shows a core
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
    camera.position.set(0, 0, 7);

    // Particle field: dense near the core, sparse and wide outside, like dust lit by it.
    const count = 5200;
    const positions = new Float32Array(count * 3);
    const seeds = new Float32Array(count);
    const sizes = new Float32Array(count);
    for (let i = 0; i < count; i += 1) {
      const u = Math.random(), v = Math.random();
      const theta = 2 * Math.PI * u, phi = Math.acos(2 * v - 1);
      const r = 0.45 + 4.4 * Math.pow(Math.random(), 1.9);
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta) * 1.25;
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta) * 0.9;
      positions[i * 3 + 2] = r * Math.cos(phi);
      seeds[i] = Math.random();
      sizes[i] = r < 1.4 ? 1.1 + Math.random() * 1.4 : 0.6 + Math.random() * 1.6;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("seed", new THREE.BufferAttribute(seeds, 1));
    geometry.setAttribute("size", new THREE.BufferAttribute(sizes, 1));
    const material = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { time: { value: 0 }, energy: { value: 0.3 }, pixel: { value: renderer.getPixelRatio() } },
      vertexShader: `
        attribute float seed; attribute float size;
        uniform float time; uniform float energy; uniform float pixel;
        varying float vAlpha; varying float vWarm;
        void main() {
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          float dist = length(position);
          float twinkle = 0.55 + 0.45 * sin(time * (0.6 + seed * 1.8) + seed * 40.0);
          vAlpha = (0.25 + 0.75 * twinkle) * mix(0.35, 1.0, energy) * clamp(1.6 / (dist + 0.4), 0.18, 1.0);
          vWarm = seed;
          gl_PointSize = size * pixel * (26.0 / -mv.z) * (0.8 + energy * 0.5);
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: `
        varying float vAlpha; varying float vWarm;
        void main() {
          vec2 c = gl_PointCoord - 0.5;
          float d = length(c);
          float soft = smoothstep(0.5, 0.0, d);
          vec3 col = mix(vec3(0.42, 0.68, 1.0), vec3(0.85, 0.94, 1.0), vWarm * vWarm);
          gl_FragColor = vec4(col, soft * soft * vAlpha);
        }`,
    });
    const field = new THREE.Points(geometry, material);
    scene.add(field);

    const coreTexture = glowTexture([[0, "rgba(255,255,255,1)"], [0.12, "rgba(255,255,255,0.98)"], [0.22, "rgba(190,225,255,0.75)"],
      [0.45, "rgba(70,140,255,0.22)"], [1, "rgba(20,60,160,0)"]]);
    const haloTexture = glowTexture([[0, "rgba(90,160,255,0.45)"], [0.35, "rgba(40,100,230,0.16)"], [1, "rgba(10,30,90,0)"]]);
    const core = new THREE.Sprite(new THREE.SpriteMaterial({ map: coreTexture, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: haloTexture, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
    const streak = new THREE.Sprite(new THREE.SpriteMaterial({ map: streakTexture(), blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
    halo.scale.set(7, 7, 1);
    scene.add(halo, core, streak);

    let width = 1, height = 1;
    const resize = () => {
      width = el.clientWidth || 1; height = el.clientHeight || 1;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    resize();
    const observer = new ResizeObserver(() => { resize(); if (reduced) draw(0); });
    observer.observe(el);

    let pointerX = 0, pointerY = 0;
    const onPointer = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      pointerX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
      pointerY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
    };
    window.addEventListener("pointermove", onPointer);

    let shown = 0.3;
    const draw = (t: number) => {
      shown += (energyRef.current - shown) * 0.04;
      const pulse = reduced ? 0 : Math.sin(t * (1.2 + shown * 3)) * 0.05 * (0.4 + shown);
      material.uniforms.time.value = t;
      material.uniforms.energy.value = shown;
      // Keep the core in the middle of what is visible when the chat sheet covers the right side.
      const worldPerPixel = (2 * Math.tan((camera.fov * Math.PI) / 360) * camera.position.z) / height;
      const offset = -shiftRef.current * worldPerPixel;
      field.position.x = core.position.x = halo.position.x = streak.position.x = offset;
      if (!reduced) {
        field.rotation.y = t * 0.035 + pointerX * 0.08;
        field.rotation.x = Math.sin(t * 0.05) * 0.08 + pointerY * 0.05;
      }
      const coreSize = 1.55 + shown * 0.65 + pulse;
      core.scale.set(coreSize, coreSize, 1);
      halo.scale.set(6.4 + shown * 2.4, 6.4 + shown * 2.4, 1);
      (halo.material as THREE.SpriteMaterial).opacity = 0.55 + shown * 0.45;
      streak.scale.set(3.4 + shown * 1.6, 0.2, 1);
      (streak.material as THREE.SpriteMaterial).opacity = 0.55 + shown * 0.45;
      renderer.render(scene, camera);
    };
    let frame = 0;
    const started = performance.now();
    const tick = () => {
      if (!document.hidden) draw((performance.now() - started) / 1000);
      frame = requestAnimationFrame(tick);
    };
    if (reduced) draw(0); else frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("pointermove", onPointer);
      geometry.dispose(); material.dispose(); coreTexture.dispose(); haloTexture.dispose();
      [core, halo, streak].forEach((s) => { (s.material as THREE.SpriteMaterial).map?.dispose(); s.material.dispose(); });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [reduced]);

  return <div ref={host} className="core__scene" aria-hidden="true" />;
}

// --- small pieces ---------------------------------------------------------------------------------------

function Ring({ value, caption, detail }: { value: number | null | undefined; caption: string; detail?: string }) {
  const pct = typeof value === "number" ? Math.max(0, Math.min(100, value)) : null;
  const r = 19, c = 2 * Math.PI * r;
  return (
    <div className="core__ring" role="meter" aria-label={caption} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? undefined}
      title={detail ? `${caption}: ${detail}` : caption}>
      <svg viewBox="0 0 48 48" aria-hidden="true">
        <circle cx="24" cy="24" r={r} className="core__ring-track" />
        {pct !== null && <circle cx="24" cy="24" r={r} className={`core__ring-fill${pct > 85 ? " is-hot" : ""}`}
          strokeDasharray={`${(pct / 100) * c} ${c}`} transform="rotate(-90 24 24)" />}
      </svg>
      <span className="core__ring-value">{pct === null ? "—" : `${Math.round(pct)}%`}</span>
      <span className="core__ring-caption">{caption}</span>
    </div>
  );
}

function Spark({ values, className }: { values: number[]; className?: string }) {
  if (values.length < 2) return <svg className={`core__spark ${className ?? ""}`} viewBox="0 0 64 20" aria-hidden="true" />;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const points = values.map((v, i) => `${(i / (values.length - 1)) * 64},${18 - ((v - min) / span) * 16}`).join(" ");
  return (
    <svg className={`core__spark ${className ?? ""}`} viewBox="0 0 64 20" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={points} fill="none" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function Waveform({ active }: { active: boolean }) {
  const bars = useMemo(() => Array.from({ length: 56 }, (_, i) => 0.25 + 0.75 * Math.abs(Math.sin(i * 1.7) * Math.cos(i * 0.37))), []);
  return (
    <div className={`core__wave${active ? " is-active" : ""}`} aria-hidden="true">
      {bars.map((h, i) => <span key={i} style={{ ["--h" as string]: h.toFixed(2), animationDelay: `${(i % 14) * 70}ms` }} />)}
    </div>
  );
}

// --- the view ----------------------------------------------------------------------------------------------

export function CoreView({ shiftX = 0, onOpenAgent, onOpenTab }: {
  shiftX?: number;
  onOpenAgent?: (name: string) => void;
  onOpenTab?: (tab: string) => void;
}) {
  const reduced = useReducedMotion();
  const roster = useRoster();
  const [data, setData] = useState<Overview | null>(null);
  const [history, setHistory] = useState<Record<string, number[]>>({});
  const [speaking, setSpeaking] = useState(false);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState("");
  const [boxes, setBoxes] = useState<BoxItem[]>([]);
  const [dockOpen, setDockOpen] = useState(false);
  const [dispatches, setDispatches] = useState<DispatchView[]>([]);
  const [making, setMaking] = useState<{ name: string; goal: string } | null>(null);
  const [agentFilter, setAgentFilter] = useState<"all" | "made" | "working">("all");
  const [running, setRunning] = useState(false);
  const lastCalls = useRef<Record<string, number>>({});

  const load = useCallback(async () => {
    const result = await api.get<Overview>("/api/core/overview", 8000);
    if (!result.ok) return;
    setData(result.data);
    setHistory((current) => {
      const next = { ...current };
      const push = (key: string, value: number) => { next[key] = [...(next[key] ?? []), value].slice(-24); };
      push("cpu", result.data.machine.cpu_percent ?? 0);
      for (const p of result.data.providers) {
        const before = lastCalls.current[p.name];
        push(`api:${p.name}`, before === undefined ? 0 : Math.max(0, p.calls - before));
        lastCalls.current[p.name] = p.calls;
      }
      return next;
    });
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 4000);
    const off = onWorkspaceEvent((event) => {
      if (event.type === "agents.changed" || event.type === "agent.created") void load();
      if (event.type === "agents.dispatch") {
        const d = event.dispatch as DispatchView | undefined;
        if (d) setDispatches((current) => current.some((x) => x.dispatch_id === d.dispatch_id) ? current : [d, ...current].slice(0, 3));
      }
    });
    return () => { window.clearInterval(timer); off(); };
  }, [load]);

  useEffect(() => onSpeakingChange((id) => setSpeaking(Boolean(id))), []);

  useEffect(() => {
    let alive = true;
    const loadSignals = async () => {
      const result = await api.get<{ signals: Signal[] }>("/api/trading/signals", 20_000);
      if (alive && result.ok) setSignals(result.data.signals.filter((s) => !s.error && s.indicators).slice(0, 3));
    };
    void loadSignals();
    const timer = window.setInterval(() => { if (!document.hidden) void loadSignals(); }, 5 * 60_000);
    void Promise.all([
      api.get<{ workspaces: { id: string; name: string; path: string }[] }>("/api/code/workspaces"),
      api.get<{ projects: { id: string; name: string }[] }>("/api/build/projects"),
      api.get<{ dispatches: DispatchView[] }>("/api/dispatch?active=true"),
    ]).then(([code, build, active]) => {
      if (!alive) return;
      const list: Project[] = [];
      if (code.ok) list.push(...code.data.workspaces.map((w) => ({ value: `code:${w.id}`, name: w.name, path: w.path, kind: "code" as const })));
      if (build.ok) list.push(...(build.data.projects ?? []).map((b) => ({ value: `build:${b.id}`, name: b.name, kind: "build" as const })));
      setProjects(list);
      if (active.ok) setDispatches(active.data.dispatches.slice(0, 3));
    });
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  const turns = useStore(turnsStore, (s) => s.turns);
  const thinking = Object.values(turns).some((t) => t.state === "streaming");
  const agents = (data?.agents ?? []).filter((a) => a.role !== "master");
  const working = agents.reduce((n, a) => n + (a.copies_working || 0), 0);
  const allProcesses = data?.processes ?? [];
  // Always-on loops are not work: they must not keep the core lit or the count up.
  const processes = allProcesses.filter((p) => p.group !== "service");
  const services = allProcesses.filter((p) => p.group === "service");
  const energy = Math.min(1, 0.25 + (thinking ? 0.35 : 0) + (speaking ? 0.3 : 0) + Math.min(0.3, working * 0.08) + (processes.length ? 0.08 : 0));
  const state = speaking ? "SPEAKING" : thinking ? "THINKING" : working || processes.length ? "WORKING" : "IDLE";
  const activeProvider = data?.providers.find((p) => p.calls > 0);

  const shownAgents = agents.filter((a) => agentFilter === "all" || (agentFilter === "made" ? !a.builtin : a.copies_working > 0));

  const addBox = (agent: string) => {
    setBoxes((current) => [...current, newBox(agent)]);
    setDockOpen(true);
    window.setTimeout(() => {
      const areas = document.querySelectorAll<HTMLTextAreaElement>(".core__dock .box__task");
      areas[areas.length - 1]?.focus();
    }, 60);
  };

  async function runDock() {
    setRunning(true);
    const chosen = projects.find((p) => p.value === project);
    let chatId = "";
    try { chatId = localStorage.getItem("nyx.chat.active") || ""; } catch { /* not kept */ }
    const dispatch = await runBoxes(boxes, { chatId, project: chosen ? { name: chosen.name, path: chosen.path, kind: chosen.kind } as { name?: string; path?: string } : undefined });
    setRunning(false);
    if (!dispatch) return;
    setDispatches((current) => [dispatch, ...current.filter((d) => d.dispatch_id !== dispatch.dispatch_id)].slice(0, 3));
    setBoxes([]);
    pushToast(`${dispatch.instances.length} agent${dispatch.instances.length === 1 ? "" : "s"} started — results also go to your current chat.`, "ok");
  }

  async function makeAgent() {
    if (!making?.name.trim() || !making.goal.trim()) return;
    const result = await api.post<{ agent: { name: string } }>("/api/agents/subagents", { name: making.name, goal: making.goal, emoji: "🤖" }, 30_000);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast(`${result.data.agent.name} joined the team — it's /${result.data.agent.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")} too.`, "ok");
    setMaking(null);
    void load();
  }

  const machine = data?.machine ?? {};
  const engine = data?.engine ?? {};

  return (
    <div className="core" style={{ ["--core-shift" as string]: `${shiftX}px` }}>
      <div className="core__backdrop" aria-hidden="true" />
      <CoreScene energy={energy} reduced={reduced} shiftX={shiftX} />
      <svg className="core__arc" viewBox="0 0 1000 120" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="core-arc" x1="0" x2="1">
            <stop offset="0" stopColor="#bfe0ff" stopOpacity="0" />
            <stop offset="0.5" stopColor="#ffffff" stopOpacity="0.95" />
            <stop offset="1" stopColor="#bfe0ff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d="M 60 110 Q 500 -40 940 110" className="core__arc-glow" stroke="url(#core-arc)" />
        <path d="M 60 110 Q 500 -40 940 110" className="core__arc-leds" stroke="url(#core-arc)" />
      </svg>

      <div className="core__hud">
        {/* Top left: the day so far */}
        <section className="core__panel core__stat" aria-label="Today">
          <div className="core__caption"><span className="core__dot" /> Nyx core · today</div>
          <div className="core__big">{data?.today.turns ?? "—"}</div>
          <div className="core__sub">
            answers · {data?.today.median_latency_s ? `${data.today.median_latency_s}s median` : "no latency yet"} · up {duration(engine.uptime_seconds)}
          </div>
        </section>

        {/* Top right: gauges */}
        <section className="core__gauges" aria-label="Usage gauges">
          <Ring value={machine.cpu_percent} caption="CPU" />
          <Ring value={machine.memory_percent} caption="Memory" detail={machine.memory_used_gb ? `${machine.memory_used_gb} of ${machine.memory_total_gb} GB` : undefined} />
          <Ring value={machine.gpu_percent ?? null} caption="GPU" detail={machine.gpu_name} />
          <Ring value={engine.cpu_percent} caption="Nyx" detail={engine.memory_mb ? `${engine.memory_mb} MB · ${engine.threads} threads` : undefined} />
        </section>

        {/* Left: APIs and markets */}
        <div className="core__col core__col--left">
          <section className="core__panel core__apis" aria-label="APIs in use">
            <div className="core__caption">APIs <span>{data?.providers.reduce((n, p) => n + p.calls, 0) ?? 0} calls this session</span></div>
            <ul className="core__rows">
              {(data?.providers ?? []).slice(0, 7).map((p) => {
                const remaining = p.limit && p.limit.limit ? Math.max(0, Math.min(1, (p.limit.remaining ?? p.limit.limit) / p.limit.limit)) : null;
                return (
                  <li key={p.name} className={`core__api${p.calls === 0 ? " is-quiet" : ""}`} title={p.last_error || Object.keys(p.models).join(", ")}>
                    <span className="core__badge">{label(p.name).slice(0, 1)}</span>
                    <span className="core__api-name">
                      <b>{label(p.name)}</b>
                      <span>{p.calls ? `${p.success_rate !== null ? Math.round((p.success_rate ?? 0) * 100) : "—"}% ok · ${p.avg_latency ?? "—"}s` : p.configured ? "ready" : "no key"}
                        {p.keys && p.keys.total > 1 ? ` · ${p.keys.working}/${p.keys.total} keys` : ""}</span>
                    </span>
                    <Spark values={history[`api:${p.name}`] ?? []} className={p.failures ? "is-warn" : ""} />
                    <span className="core__api-num">
                      <b>{p.calls}</b>
                      {remaining !== null
                        ? <span className="core__limit" title={`${p.limit?.remaining} of ${p.limit?.limit} ${p.limit?.kind} left this ${p.limit?.window}`}><i style={{ width: `${remaining * 100}%` }} /></span>
                        : <span>{p.last_hour}/h</span>}
                    </span>
                  </li>
                );
              })}
              {data && data.providers.length === 0 && <li className="core__empty">No API calls yet.</li>}
            </ul>
          </section>
          {signals.length > 0 && (
            <section className="core__panel core__markets" aria-label="Markets">
              <div className="core__caption">Markets</div>
              <ul className="core__rows">
                {signals.map((s) => (
                  <li key={s.symbol} className="core__api">
                    <span className="core__badge is-market">{s.symbol.slice(0, 1)}</span>
                    <span className="core__api-name"><b>{s.symbol}</b><span>watchlist</span></span>
                    <Spark values={(s.sparkline ?? []).slice(-30)} className={(s.change_pct ?? 0) < 0 ? "is-down" : "is-up"} />
                    <span className="core__api-num">
                      <b>{s.indicators ? s.indicators.price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}</b>
                      <span className={(s.change_pct ?? 0) < 0 ? "is-down" : "is-up"}>{typeof s.change_pct === "number" ? `${s.change_pct > 0 ? "+" : ""}${s.change_pct.toFixed(2)}%` : ""}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        {/* Right: sub-agents and processes */}
        <div className="core__col core__col--right">
          <section className="core__panel core__agents" aria-label="Sub-agents">
            <div className="core__caption">
              Sub-agents <span>{working ? `${working} working` : `${agents.length} ready`}</span>
              <button className="core__plus" onClick={() => setMaking(making ? null : { name: "", goal: "" })} aria-expanded={Boolean(making)} aria-label="Make a sub-agent" title="Make a sub-agent">+</button>
            </div>
            {making && (
              <form className="core__make" onSubmit={(e) => { e.preventDefault(); void makeAgent(); }}>
                <input value={making.name} placeholder="Name, e.g. Price Scout" aria-label="Name" autoFocus maxLength={40}
                  onChange={(e) => setMaking({ ...making, name: e.target.value })} />
                <input value={making.goal} placeholder="What it's for" aria-label="Goal" maxLength={300}
                  onChange={(e) => setMaking({ ...making, goal: e.target.value })} />
                <div className="core__make-actions">
                  <button type="button" className="chat-inline" onClick={() => onOpenTab?.("subagents")}>More options…</button>
                  <button className="btn btn-primary" disabled={!making.name.trim() || !making.goal.trim()}>Make</button>
                </div>
              </form>
            )}
            <div className="core__filter" role="group" aria-label="Which agents">
              {(["all", "made", "working"] as const).map((f) => (
                <button key={f} aria-pressed={agentFilter === f} onClick={() => setAgentFilter(f)}>{f === "all" ? "All" : f === "made" ? "Made" : "Working"}</button>
              ))}
            </div>
            <ul className="core__rows core__agentlist">
              {shownAgents.map((a) => (
                <li key={a.name} className={`core__agent is-${a.copies_working ? "working" : a.status}`} draggable
                  onDragStart={(e) => { e.dataTransfer.setData("application/x-nyx-agent", a.name); e.dataTransfer.effectAllowed = "copy"; setDockOpen(true); }}
                  title={`${a.goal}\nDrag into the project dock — drag again for another copy.`}>
                  <span className="core__grip" aria-hidden="true">⋮⋮</span>
                  <button className="core__agent-main" onClick={() => onOpenAgent?.(a.name)}>
                    <span className="core__emoji" aria-hidden="true">{a.emoji || "🤖"}</span>
                    <span className="core__api-name">
                      <b>{a.name}{a.made_by === "nyx" && <em className="core__tag">by Nyx</em>}{a.made_by === "owner" && <em className="core__tag">yours</em>}</b>
                      <span>{a.copies_working ? `● ${a.copies_working > 1 ? `${a.copies_working} copies working` : a.step || "working"}` : `${a.tasks_done} done · ${a.command}`}</span>
                    </span>
                  </button>
                  <button className="core__run" onClick={() => addBox(a.name)} aria-label={`Run ${a.name}`}>Run</button>
                </li>
              ))}
            </ul>
          </section>
          <section className="core__panel core__procs" aria-label="Processes">
            <div className="core__caption">Processes <span>{processes.length || "none"} running{services.length ? ` · ${services.length} always on` : ""}</span></div>
            <ul className="core__rows">
              {processes.map((p) => <ProcessRow key={`${p.kind}-${p.id}`} p={p} onOpenTab={onOpenTab} />)}
              {processes.length === 0 && <li className="core__empty">Quiet. Nothing is working in the background.</li>}
            </ul>
            {services.length > 0 && (
              <details className="core__services">
                <summary>Always on · {services.length}</summary>
                <ul className="core__rows">
                  {services.map((p) => <ProcessRow key={`${p.kind}-${p.id}`} p={p} onOpenTab={onOpenTab} service />)}
                </ul>
              </details>
            )}
          </section>
        </div>

        {/* Bottom: project dock, voice channel, status line */}
        <div className="core__bottom">
          {dispatches.length > 0 && (
            <div className="core__dispatches">
              {dispatches.slice(0, 2).map((d) => (
                <DispatchCard key={d.dispatch_id} initial={d} roster={roster} compact
                  onClose={() => setDispatches((current) => current.filter((x) => x.dispatch_id !== d.dispatch_id))} />
              ))}
            </div>
          )}
          <section className={`core__panel core__dock${dockOpen ? " is-open" : ""}`} aria-label="Project dock"
            onDragOver={(e) => { if (!dockOpen && e.dataTransfer.types.includes("application/x-nyx-agent")) { e.preventDefault(); setDockOpen(true); } }}>
            <div className="core__caption">
              <button className="core__dock-toggle" onClick={() => setDockOpen((v) => !v)} aria-expanded={dockOpen}>
                {dockOpen ? "▾" : "▸"} Project dock
              </button>
              <span>{boxes.length ? `${boxes.length} box${boxes.length === 1 ? "" : "es"}` : "drag agents here"}</span>
              <button className="core__plus" onClick={() => { setDockOpen(true); if (roster[0]) addBox(roster[0].name); }} aria-label="Add an agent box" title="Add an agent box">+</button>
            </div>
            {dockOpen && (
              <div className="core__dock-body">
                <label className="core__project">
                  <span>Project</span>
                  <select value={project} onChange={(e) => setProject(e.target.value)}>
                    <option value="">No project — general</option>
                    {projects.some((p) => p.kind === "code") && <optgroup label="Code folders">
                      {projects.filter((p) => p.kind === "code").map((p) => <option key={p.value} value={p.value}>{p.name}</option>)}
                    </optgroup>}
                    {projects.some((p) => p.kind === "build") && <optgroup label="Build projects">
                      {projects.filter((p) => p.kind === "build").map((p) => <option key={p.value} value={p.value}>{p.name}</option>)}
                    </optgroup>}
                  </select>
                  <button type="button" className="chat-inline" onClick={() => onOpenTab?.("code")}>Open a folder…</button>
                </label>
                <BoxEditor items={boxes} onChange={setBoxes} roster={roster} compact onDropAgent={addBox} />
                <div className="core__dock-foot">
                  {boxes.length > 0 && <button className="btn btn-secondary" onClick={() => setBoxes([])}>Clear</button>}
                  <button className="btn btn-primary" disabled={boxes.length === 0 || running} onClick={() => void runDock()}>
                    {running ? "Starting…" : `Run ${boxes.length || ""} ${boxes.length === 1 ? "Agent" : "Agents"}`.replace("  ", " ")}
                  </button>
                </div>
              </div>
            )}
          </section>
          <section className="core__panel core__voice" aria-label="Voice channel">
            <div className="core__caption"><span className={`core__dot${speaking ? " is-live" : ""}`} /> Voice channel · Nyx <span>{speaking ? "Speaking" : thinking ? "Thinking" : "Standby"}</span></div>
            <Waveform active={speaking || (thinking && !reduced)} />
          </section>
          <div className="core__status" aria-live="off">
            CORE {state} · {activeProvider ? label(activeProvider.name).toUpperCase() : "NO CALLS YET"} · {working}/{agents.length} AGENTS · {processes.length} PROCESSES · LAT {data?.today.median_latency_s ?? "—"}S
          </div>
        </div>
      </div>
    </div>
  );
}
