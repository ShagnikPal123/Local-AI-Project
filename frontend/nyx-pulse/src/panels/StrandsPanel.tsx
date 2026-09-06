/** Strands — the centrepiece tab (ROADMAP DD1-DD5, DD10, DD12).
 *
 * A drifting 3D field of everything the system currently knows about, which grows
 * as you talk to it: every memory, agent goal and open chat is a point, and the
 * strands between them are shared vocabulary the backend actually computed.
 *
 * Three rules this file is built around.
 *
 * 1. **Nothing decorative pretends to be data.** The reference Shagnik supplied is
 *    a mockup and every reading in it was invented. Points and links come from
 *    `/api/strands`; the ambient dust is drawn in a different colour and is never
 *    counted, clickable, or labelled.
 * 2. **The motion says what is true about it.** Shagnik could not tell whether the
 *    voice strand was real. So the field states its energy source in words at all
 *    times: the microphone when you switch it on, and otherwise a synthesised
 *    envelope derived from request timing and reply length — which is said out
 *    loud rather than dressed up as a waveform.
 * 3. **You can tell when it is thinking.** The old panel gave no signal at all.
 *    Now the shell's own AvatarState drives a labelled chip and the speed of the
 *    field, so "working" is visible from across the room.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type ChatResponse } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";
import { NyxAvatar, type AvatarState } from "../components/NyxAvatar";
import { StrandField, type FieldNode, type StrandFieldHandle } from "../components/StrandField";
import { useReducedMotion } from "../useReducedMotion";

interface StrandNode {
  id: string;
  label: string;
  kind: "memory" | "agent" | "chat" | "knowledge";
  detail: string;
  target: string;
}

interface StrandLink {
  source: string;
  target: string;
  weight: number;
  shared: string[];
}

interface StrandGraph {
  nodes: StrandNode[];
  links: StrandLink[];
  counts: { nodes: number; links: number; by_source: Record<string, number> };
  empty: boolean;
}

interface TeamSnapshot {
  agents: { name: string; status: string; current_step: string }[];
  working: number;
  total: number;
  resource_pressure: {
    gpu_temp_c?: number;
    gpu_utilization?: number;
    vram_used_mb?: number;
    vram_total_mb?: number;
    telemetry_available?: boolean;
    throttled?: boolean;
  };
}

interface WidgetDef {
  id: string;
  type: string;
  title: string;
  config: Record<string, string>;
  position: number;
}

interface WidgetTypeDef {
  type: string;
  description: string;
  needs_target: boolean;
}

interface SystemEvent {
  time: string;
  level: "info" | "ok" | "warn" | "error";
  source: string;
  message: string;
}

/** What `/api/voice/status` reports about the machine's actual voice hardware. */
interface VoiceStatus {
  enrolled: boolean;
  voice: string;
  voices: { name: string; culture?: string; gender?: string }[];
  mic: string | null;
  capabilities: { tts: boolean; stt: boolean; voice_id: boolean };
}

const EVENT_COLOR: Record<SystemEvent["level"], string> = {
  info: "var(--color-neutral-500)",
  ok: "var(--color-ok)",
  warn: "var(--color-warn)",
  error: "var(--color-danger)",
};

const KIND_COLOR: Record<string, string> = {
  memory: "#5ad6e0",
  agent: "#9184d9",
  chat: "#5ac08a",
  knowledge: "#e0b45a",
};

const kindColor = (kind: string) => KIND_COLOR[kind] ?? "#9184d9";

/** Where the field's motion is coming from right now. Rendered as words. */
type EnergySource = "mic" | "thinking" | "delivering" | "idle";

const SOURCE_LABEL: Record<EnergySource, string> = {
  mic: "Live microphone",
  thinking: "Synthesised — request in flight",
  delivering: "Synthesised — reply cadence",
  idle: "Still — no signal",
};

const SOURCE_TONE: Record<EnergySource, string> = {
  mic: "var(--color-ok)",
  thinking: "var(--color-accent-400)",
  delivering: "var(--color-accent-2)",
  idle: "var(--color-neutral-600)",
};

const METER_BARS = 32;

/** The voice meter.
 *
 * With the microphone on, each bar is one real frequency bin. With it off, the
 * bars are drawn from the synthesised envelope — the same number the field moves
 * to — and the badge above says so. It deliberately does not imitate a
 * microphone trace when there is no microphone.
 */
function VoiceMeter({ sampleBands, reduced, source }: {
  sampleBands: (seconds: number) => number[];
  reduced: boolean;
  source: EnergySource;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sampleRef = useRef(sampleBands);
  sampleRef.current = sampleBands;

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas ? canvas.getContext("2d") : null;
    if (!canvas || !ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));

    const paint = (timeMs: number) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const bands = sampleRef.current(reduced ? 0 : timeMs / 1000);
      const gap = 2;
      const barW = Math.max(1, (w - gap * (METER_BARS - 1)) / METER_BARS);
      for (let i = 0; i < METER_BARS; i += 1) {
        const v = Math.max(0, Math.min(1, bands[i] ?? 0));
        const barH = Math.max(2, v * h);
        ctx.fillStyle = source === "mic"
          ? "rgba(90,192,138," + (0.35 + v * 0.6).toFixed(2) + ")"
          : "rgba(145,132,217," + (0.28 + v * 0.6).toFixed(2) + ")";
        ctx.fillRect(i * (barW + gap), (h - barH) / 2, barW, barH);
      }
    };

    if (reduced) {
      paint(0);
      return;
    }
    let raf = 0;
    const tick = (now: number) => {
      paint(now);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [reduced, source]);

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={"Voice meter. Source: " + SOURCE_LABEL[source]}
      style={{ display: "block", width: "100%", height: 30 }}
    />
  );
}

function Widget({ title, children, onRemove }: {
  title: string;
  children: React.ReactNode;
  onRemove?: () => void;
}) {
  return (
    <div className="card" style={{ padding: "12px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
        <span className="label">{title}</span>
        {onRemove && (
          <button className="btn" onClick={onRemove}
            style={{ marginLeft: "auto", fontSize: 11, color: "var(--color-neutral-600)", padding: 0 }}>
            remove
          </button>
        )}
      </div>
      {children}
    </div>
  );
}

interface WidgetData {
  hw: TeamSnapshot["resource_pressure"];
  team: TeamSnapshot | null;
  graph: StrandGraph;
  events: SystemEvent[];
  blind: boolean;
}

/** Render one widget by type. Unknown types say so rather than rendering blank. */
function renderWidget(widget: WidgetDef, data: WidgetData): React.ReactNode {
  const { hw, team, graph, events, blind } = data;

  switch (widget.type) {
    case "system":
      return blind ? (
        <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
          No hardware telemetry on this machine.
        </div>
      ) : (
        <>
          <Reading label="GPU temp" value={`${hw.gpu_temp_c ?? 0}°C`}
            tone={(hw.gpu_temp_c ?? 0) >= 82 ? "var(--color-danger)" : "var(--color-ok)"} />
          <Reading label="GPU load" value={`${hw.gpu_utilization ?? 0}%`} />
          <Reading label="VRAM"
            value={`${Math.round(hw.vram_used_mb ?? 0)} / ${Math.round(hw.vram_total_mb ?? 0)} MB`} />
          <Reading label="Throttling" value={hw.throttled ? "yes" : "no"}
            tone={hw.throttled ? "var(--color-warn)" : "var(--color-ok)"} />
        </>
      );

    case "agents":
      if (!team || team.agents.length === 0) {
        return <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>No agents running.</div>;
      }
      return team.agents.map((a, i) => (
        <div key={i} style={{ padding: "4px 0", fontSize: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <span>{a.name}</span>
            <span style={{
              fontFamily: "var(--font-mono)", fontSize: 11,
              color: a.status === "working" ? "var(--color-accent)" : "var(--color-neutral-600)",
            }}>
              {a.status}
            </span>
          </div>
          {a.current_step && (
            <div style={{ fontSize: 11, color: "var(--color-neutral-600)" }}>-&gt; {a.current_step}</div>
          )}
        </div>
      ));

    case "events":
      if (events.length === 0) {
        return <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>Nothing logged yet.</div>;
      }
      return (
        <div style={{ maxHeight: 180, overflowY: "auto", fontFamily: "var(--font-mono)", fontSize: 11 }}>
          {events.map((e, i) => (
            <div key={i} style={{ display: "flex", gap: 6, padding: "2px 0", lineHeight: 1.5 }}>
              <span style={{ color: "var(--color-neutral-700)" }}>{e.time}</span>
              <span style={{ color: EVENT_COLOR[e.level], flex: 1, wordBreak: "break-word" }}>
                {e.message}
              </span>
            </div>
          ))}
        </div>
      );

    case "sources":
      return Object.entries(graph.counts.by_source).map(([source, n]) => (
        <Reading key={source} label={source} value={String(n)} />
      ));

    case "tab":
      return (
        <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
          Bound to the <strong>{widget.config.target}</strong> tab. Live embedding is not built
          yet, so open that tab directly for now.
        </div>
      );

    case "prompt":
      return (
        <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
          Saved prompt: {widget.config.target}. Running saved prompts on a schedule is not
          built yet.
        </div>
      );

    case "finance":
      return (
        <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
          Market data is not wired to this widget yet.
        </div>
      );

    default:
      return (
        <div style={{ fontSize: 12, color: "var(--color-warn)" }}>
          Unknown widget type: {widget.type}
        </div>
      );
  }
}

function Reading({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: 12 }}>
      <span style={{ color: "var(--color-neutral-500)" }}>{label}</span>
      <span style={{ fontFamily: "var(--font-mono)", color: tone ?? "var(--color-text)" }}>{value}</span>
    </div>
  );
}

interface Turn {
  role: "user" | "assistant" | "error";
  text: string;
  provider?: string;
}

export function StrandsPanel({ state, onActivity }: {
  /** The shell's current agent state, so this panel shows the same truth the avatar does. */
  state?: AvatarState;
  onActivity?: (s: AvatarState) => void;
}) {
  const reduced = useReducedMotion();

  const [graph, setGraph] = useState<StrandGraph | null>(null);
  const [team, setTeam] = useState<TeamSnapshot | null>(null);
  const [selected, setSelected] = useState<FieldNode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [widgets, setWidgets] = useState<WidgetDef[]>([]);
  const [available, setAvailable] = useState<WidgetTypeDef[]>([]);
  const [events, setEvents] = useState<SystemEvent[]>([]);
  const [adding, setAdding] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const dragFrom = useRef<number | null>(null);
  const fieldRef = useRef<StrandFieldHandle | null>(null);

  // Growth. The point of this tab is that it gets bigger as you talk, so the
  // count when you arrived is kept and the difference is shown.
  const baselineRef = useRef<number | null>(null);
  const [grown, setGrown] = useState(0);

  // --- conversation ---------------------------------------------------------
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const turnsRef = useRef<HTMLDivElement>(null);

  // --- energy ---------------------------------------------------------------
  const [micOn, setMicOn] = useState(false);
  const [micDenied, setMicDenied] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);
  const [delivering, setDelivering] = useState(false);
  const micLevelRef = useRef(0);
  const micBandsRef = useRef<Uint8Array | null>(null);
  const micCleanup = useRef<(() => void) | null>(null);
  const deliverUntilRef = useRef(0);

  const thinking = busy || state === "thinking";
  const thinkingRef = useRef(thinking);
  thinkingRef.current = thinking;
  const micOnRef = useRef(micOn);
  micOnRef.current = micOn;

  const source: EnergySource = micOn
    ? "mic"
    : thinking
      ? "thinking"
      : delivering
        ? "delivering"
        : "idle";

  /** 0..1 for the field, once per frame. Stable identity: it reads only refs. */
  const sampleEnergy = useCallback((t: number) => {
    if (micOnRef.current) return micLevelRef.current;
    if (thinkingRef.current) return 0.34 + 0.12 * Math.sin(t * 2.6);
    if (performance.now() < deliverUntilRef.current) {
      // A speech-shaped envelope: a syllable rate under a slower phrase rate.
      // Synthesised, not measured — the badge beside the meter says exactly that.
      const syllable = Math.abs(Math.sin(t * 11));
      const phrase = 0.5 + 0.5 * Math.sin(t * 2.3 + 0.7);
      return 0.26 + 0.55 * syllable * (0.45 + 0.55 * phrase);
    }
    return 0.06;
  }, []);

  /** Per-bar values for the meter: real FFT bins with the mic on, else the envelope. */
  const sampleBands = useCallback((t: number) => {
    const bins = micBandsRef.current;
    if (micOnRef.current && bins) {
      const out: number[] = [];
      const step = Math.max(1, Math.floor(bins.length / METER_BARS));
      for (let i = 0; i < METER_BARS; i += 1) {
        let peak = 0;
        for (let k = 0; k < step; k += 1) peak = Math.max(peak, bins[i * step + k] ?? 0);
        out.push(peak / 255);
      }
      return out;
    }
    const energy = sampleEnergy(t);
    const out: number[] = [];
    for (let i = 0; i < METER_BARS; i += 1) {
      const centre = 1 - Math.abs(i - METER_BARS / 2) / (METER_BARS / 2);
      const ripple = 0.55 + 0.45 * Math.sin(t * 6 + i * 0.55);
      out.push(energy * (0.25 + centre * 0.9) * ripple);
    }
    return out;
  }, [sampleEnergy]);

  // --- loading --------------------------------------------------------------
  const refresh = useCallback(async () => {
    const [g, t, w, e] = await Promise.all([
      api.get<StrandGraph>("/api/strands"),
      api.get<TeamSnapshot>("/api/agents"),
      api.get<{ widgets: WidgetDef[]; available: WidgetTypeDef[] }>("/api/widgets"),
      api.get<{ events: SystemEvent[] }>("/api/events"),
    ]);
    if (g.ok) {
      setGraph(g.data);
      setError(null);
      if (baselineRef.current === null) baselineRef.current = g.data.counts.nodes;
      setGrown(Math.max(0, g.data.counts.nodes - (baselineRef.current ?? 0)));
    } else {
      setError(g.error);
    }
    if (t.ok) setTeam(t.data);
    if (w.ok) { setWidgets(w.data.widgets); setAvailable(w.data.available); }
    if (e.ok) setEvents(e.data.events);
  }, []);

  useEffect(() => {
    let alive = true;
    const load = () => { if (alive) void refresh(); };
    load();
    // Frequent enough that a point appears while the reply is still on screen.
    const timer = setInterval(load, 4000);
    return () => { alive = false; clearInterval(timer); };
  }, [refresh]);

  useEffect(() => {
    void api.get<VoiceStatus>("/api/voice/status").then((r) => {
      if (r.ok) setVoiceStatus(r.data);
    });
  }, []);

  useEffect(() => () => micCleanup.current?.(), []);

  // --- microphone -----------------------------------------------------------
  async function toggleMic() {
    if (micOn) {
      micCleanup.current?.();
      micCleanup.current = null;
      micBandsRef.current = null;
      micLevelRef.current = 0;
      setMicOn(false);
      onActivity?.("idle");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      const wave = new Uint8Array(analyser.fftSize);
      const spectrum = new Uint8Array(analyser.frequencyBinCount);
      let raf = 0;
      const tick = () => {
        analyser.getByteTimeDomainData(wave);
        analyser.getByteFrequencyData(spectrum);
        let peak = 0;
        for (const v of wave) peak = Math.max(peak, Math.abs(v - 128));
        micLevelRef.current = Math.min(peak / 64, 1);
        micBandsRef.current = spectrum;
        raf = requestAnimationFrame(tick);
      };
      tick();
      micCleanup.current = () => {
        cancelAnimationFrame(raf);
        stream.getTracks().forEach((track) => track.stop());
        void ctx.close();
      };
      setMicOn(true);
      setMicDenied(false);
      onActivity?.("listening");
    } catch {
      setMicDenied(true);
    }
  }

  // --- talking to it from here ---------------------------------------------
  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setTurns((t) => [...t.slice(-9), { role: "user", text }]);
    setDraft("");
    setBusy(true);
    onActivity?.("thinking");

    const result = await api.post<ChatResponse>("/api/chat", { message: text });
    setBusy(false);

    if (result.ok) {
      // The field is `reply`. Reading `response` here returned undefined and
      // rendered an empty bubble on an HTTP 200 — the bug that made the app look
      // broken with nothing in the console.
      const reply = result.data.reply ?? "";
      setTurns((t) => [...t.slice(-9), { role: "assistant", text: reply, provider: result.data.provider }]);
      // Delivery envelope, scaled to how much there is to say. Derived from the
      // reply's own length; it is not audio and the badge does not claim it is.
      const words = reply.split(/\s+/).filter(Boolean).length;
      const ms = Math.min(9000, Math.max(1200, words * 260));
      deliverUntilRef.current = performance.now() + ms;
      setDelivering(true);
      window.setTimeout(() => setDelivering(false), ms);
      onActivity?.("idle");
    } else {
      setTurns((t) => [...t.slice(-9), { role: "error", text: result.error }]);
      onActivity?.("error");
    }
    // New chat and new memories become new points; pull them straight away
    // rather than waiting out the poll.
    void refresh();
    queueMicrotask(() => turnsRef.current?.scrollTo({ top: turnsRef.current.scrollHeight }));
  }

  // --- widgets --------------------------------------------------------------
  async function addWidget(type: WidgetTypeDef) {
    let config: Record<string, string> = {};
    if (type.needs_target) {
      const target = window.prompt(
        type.type === "tab"
          ? "Which tab should this widget show? (e.g. models, agents)"
          : "Which saved prompt should this widget show?",
      );
      if (!target || !target.trim()) return;
      config = { target: target.trim() };
    }
    const result = await api.post<{ widgets: WidgetDef[] }>("/api/widgets", {
      type: type.type, config,
    });
    if (result.ok) { setWidgets(result.data.widgets); setAdding(false); }
    else setError(result.error);
  }

  async function removeWidget(id: string) {
    const result = await api.del<{ widgets: WidgetDef[] }>(`/api/widgets/${id}`);
    if (result.ok) setWidgets(result.data.widgets);
    else setError(result.error);
  }

  async function dropWidget(toIndex: number) {
    const from = dragFrom.current;
    dragFrom.current = null;
    if (from === null || from === toIndex) return;
    const next = [...widgets];
    const [moved] = next.splice(from, 1);
    next.splice(toIndex, 0, moved);
    setWidgets(next);  // optimistic; the server confirms the order below
    const result = await api.post<{ widgets: WidgetDef[] }>("/api/widgets/order", {
      order: next.map((w) => w.id),
    });
    if (result.ok) setWidgets(result.data.widgets);
  }

  async function resetWidgets() {
    const result = await api.post<{ widgets: WidgetDef[] }>("/api/widgets/reset");
    if (result.ok) setWidgets(result.data.widgets);
  }

  // Referential stability matters here: a new array every render would re-run the
  // field's placement reconciliation and re-fire every arrival flare.
  const fieldNodes = useMemo(
    () => (graph?.nodes ?? []).map((n) => ({ id: n.id, label: n.label, kind: n.kind, detail: n.detail })),
    [graph?.nodes],
  );
  const fieldLinks = useMemo(
    () => (graph?.links ?? []).map((l) => ({ source: l.source, target: l.target, weight: l.weight })),
    [graph?.links],
  );

  if (error && !graph) return <PanelShell title="Strands"><ErrorState error={error} /></PanelShell>;
  if (!graph) return <PanelShell title="Strands"><Loading what="Tracing strands" /></PanelShell>;

  const hw = team?.resource_pressure ?? {};
  const blind = hw.telemetry_available === false;
  const canvasHeight = expanded ? "calc(100vh - 300px)" : "clamp(320px, 46vh, 560px)";

  const stateLabel = micOn
    ? "Listening"
    : thinking
      ? "Nyx is thinking…"
      : delivering
        ? "Replying"
        : "Idle";
  const avatarState: AvatarState = micOn ? "listening" : thinking ? "thinking" : (state ?? "idle");

  return (
    <PanelShell
      title="Strands"
      subtitle={
        `${graph.counts.nodes} nodes · ${graph.counts.links} connections` +
        (grown > 0 ? ` · +${grown} since you opened this tab` : "")
      }
      actions={
        <button className="btn btn-secondary" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show widgets" : "Expand field"}
        </button>
      }
    >
      <div className="strands-grid" data-expanded={expanded ? "true" : "false"}>
        {/* --- the field ---------------------------------------------------- */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
          <div style={{ position: "relative" }}>
            <StrandField
              nodes={fieldNodes}
              links={fieldLinks}
              kindColor={kindColor}
              selectedId={selected?.id ?? null}
              onSelect={setSelected}
              sampleEnergy={sampleEnergy}
              reduced={reduced}
              height={canvasHeight}
              handleRef={fieldRef}
            />

            {/* State chip. The one thing the old panel could not tell you. */}
            <div
              style={{
                position: "absolute", top: 10, left: 10, display: "flex", alignItems: "center",
                gap: 8, padding: "6px 10px", borderRadius: 999,
                background: "rgba(18,20,31,.82)", boxShadow: "inset 0 0 0 1px var(--color-divider)",
                pointerEvents: "none",
              }}
            >
              <NyxAvatar state={avatarState} size={18} />
              <span style={{ fontSize: 12, color: thinking ? "var(--color-accent-300)" : "var(--color-neutral-400)" }}>
                {stateLabel}
              </span>
            </div>

            {/* View controls */}
            <div style={{ position: "absolute", top: 10, right: 10, display: "flex", gap: 4 }}>
              <button className="btn btn-secondary" title="Zoom out"
                onClick={() => fieldRef.current?.zoomBy(1 / 1.25)}
                style={{ padding: "4px 10px", fontSize: 13 }}>−</button>
              <button className="btn btn-secondary" title="Zoom in"
                onClick={() => fieldRef.current?.zoomBy(1.25)}
                style={{ padding: "4px 10px", fontSize: 13 }}>+</button>
              <button className="btn btn-secondary" title="Recentre"
                onClick={() => fieldRef.current?.resetView()}
                style={{ padding: "4px 10px", fontSize: 12 }}>Reset</button>
            </div>

            {/* Legend and hint */}
            <div
              style={{
                position: "absolute", bottom: 10, left: 10, display: "flex", flexWrap: "wrap",
                alignItems: "center", gap: 10, fontSize: 11, color: "var(--color-neutral-500)",
                pointerEvents: "none",
              }}
            >
              {Object.entries(KIND_COLOR).map(([kind, color]) => (
                <span key={kind} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: color }} />
                  {kind}
                </span>
              ))}
              <span style={{ color: "var(--color-neutral-700)" }}>
                hover to slow it · drag to pan · ctrl+scroll or +/− to zoom · click a point
              </span>
            </div>

            {graph.empty && (
              <div
                style={{
                  position: "absolute", inset: 0, display: "grid", placeItems: "center",
                  padding: 30, textAlign: "center", pointerEvents: "none",
                }}
              >
                <div style={{ maxWidth: 380, fontSize: 13, color: "var(--color-neutral-400)", lineHeight: 1.7 }}>
                  No strands yet. Every point here is a real memory, agent goal, or open
                  chat — talk to Nyx below and the field fills in.
                  <br /><br />
                  <span style={{ color: "var(--color-neutral-600)" }}>
                    The faint drifting specks are depth, not data, and are never counted.
                  </span>
                </div>
              </div>
            )}
          </div>

          {selected && (
            <div className="card" style={{ borderLeft: `3px solid ${kindColor(selected.kind)}` }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 5 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{selected.label}</span>
                <span style={{ fontSize: 10, textTransform: "uppercase", color: kindColor(selected.kind) }}>
                  {selected.kind}
                </span>
                <button className="btn" style={{ marginLeft: "auto", fontSize: 11, color: "var(--color-neutral-500)" }}
                  onClick={() => setSelected(null)}>close</button>
              </div>
              <div style={{ fontSize: 12, color: "var(--color-neutral-400)", lineHeight: 1.6 }}>
                {selected.detail}
              </div>
            </div>
          )}

          {/* --- voice: what is actually driving the motion ------------------ */}
          <div className="card" style={{ padding: "12px 14px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <span className="label">Voice</span>
              <span
                style={{
                  marginLeft: "auto", fontSize: 11, color: SOURCE_TONE[source],
                  display: "inline-flex", alignItems: "center", gap: 6,
                }}
              >
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: SOURCE_TONE[source] }} />
                {SOURCE_LABEL[source]}
              </span>
            </div>

            <VoiceMeter sampleBands={sampleBands} reduced={reduced} source={source} />

            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
              <button className="btn btn-secondary" onClick={() => void toggleMic()}>
                {micOn ? "Stop listening" : "Speak"}
              </button>
              <span style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
                Click Speak to talk, or type in the box below.
              </span>
            </div>

            {micDenied && (
              <div style={{ fontSize: 11, color: "var(--color-warn)", marginTop: 8 }}>
                The browser refused microphone access, so the meter stays on the synthesised
                source rather than faking a trace.
              </div>
            )}

            <div style={{ fontSize: 11, color: "var(--color-neutral-600)", lineHeight: 1.6, marginTop: 10 }}>
              {micOn
                ? "Every bar is one frequency bin from your microphone, live."
                : "With the microphone off, the bars and the field are a synthesised envelope built from request timing and reply length. It is motion, not measured audio."}
            </div>

            {voiceStatus && (
              <div style={{ fontSize: 11, color: "var(--color-neutral-600)", lineHeight: 1.6, marginTop: 6 }}>
                Backend voice engine: microphone {voiceStatus.mic ? voiceStatus.mic : "not detected"} ·{" "}
                {voiceStatus.voices.length} speech voice{voiceStatus.voices.length === 1 ? "" : "s"}
                {voiceStatus.voice ? ` (${voiceStatus.voice})` : ""} ·{" "}
                voice ID {voiceStatus.enrolled ? "enrolled" : "not enrolled"}. Nyx does not speak
                aloud from this tab, so nothing here is driven by that engine.
              </div>
            )}
          </div>

          {/* --- talk to it from here ---------------------------------------- */}
          <div className="card" style={{ padding: "12px 14px" }}>
            <div className="label" style={{ marginBottom: 8 }}>Talk to Nyx</div>

            {turns.length > 0 && (
              <div
                ref={turnsRef}
                style={{
                  maxHeight: 190, overflowY: "auto", display: "flex", flexDirection: "column",
                  gap: 8, marginBottom: 10,
                }}
              >
                {turns.map((turn, i) => (
                  <div
                    key={i}
                    style={{
                      alignSelf: turn.role === "user" ? "flex-end" : "flex-start",
                      maxWidth: "86%",
                      padding: "8px 11px",
                      borderRadius: "var(--radius)",
                      fontSize: 13,
                      lineHeight: 1.6,
                      whiteSpace: "pre-wrap",
                      background: turn.role === "user" ? "var(--color-accent-900)" : "var(--color-nav)",
                      borderLeft: turn.role === "error" ? "3px solid var(--color-danger)" : undefined,
                    }}
                  >
                    {turn.text}
                    {turn.provider && (
                      <div style={{ marginTop: 6, fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--color-neutral-600)" }}>
                        {turn.provider}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: "flex", gap: 8 }}>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                rows={2}
                placeholder="Say something and watch the field grow…  (Enter to send)"
                style={{
                  flex: 1, resize: "none", background: "var(--color-nav)", color: "var(--color-text)",
                  border: "none", borderRadius: "var(--radius)", padding: "10px 12px",
                  font: "inherit", fontSize: 14, boxShadow: "inset 0 0 0 1px var(--color-divider)",
                }}
              />
              <button
                className="btn btn-primary"
                onClick={() => void send()}
                disabled={busy || !draft.trim()}
                style={{ opacity: busy || !draft.trim() ? 0.5 : 1, alignSelf: "stretch", padding: "0 18px" }}
              >
                {busy ? "…" : "Send"}
              </button>
            </div>
          </div>
        </div>

        {/* --- widgets: user-configurable, drag to reorder ------------------- */}
        {!expanded && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span className="label">Widgets</span>
              <button className="btn" style={{ marginLeft: "auto", fontSize: 11, color: "var(--color-neutral-500)" }}
                onClick={() => setAdding((v) => !v)}>
                {adding ? "cancel" : "+ add"}
              </button>
              <button className="btn" style={{ fontSize: 11, color: "var(--color-neutral-600)" }}
                onClick={() => void resetWidgets()}>reset</button>
            </div>

            {adding && (
              <div className="card" style={{ padding: "10px 12px" }}>
                {available.map((a) => (
                  <button key={a.type} onClick={() => void addWidget(a)}
                    style={{
                      display: "block", width: "100%", textAlign: "left", padding: "7px 9px",
                      marginBottom: 5, borderRadius: 6, background: "var(--color-nav)", fontSize: 12,
                    }}>
                    <div style={{ fontWeight: 500 }}>
                      {a.type}
                      {a.needs_target && (
                        <span style={{ color: "var(--color-neutral-600)", fontWeight: 400 }}> · asks for a target</span>
                      )}
                    </div>
                    <div style={{ color: "var(--color-neutral-500)", fontSize: 11, lineHeight: 1.5 }}>
                      {a.description}
                    </div>
                  </button>
                ))}
              </div>
            )}

            {widgets.map((w, index) => (
              <div
                key={w.id}
                draggable
                onDragStart={() => (dragFrom.current = index)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => void dropWidget(index)}
                style={{ cursor: "grab" }}
              >
                <Widget title={w.title} onRemove={() => void removeWidget(w.id)}>
                  {renderWidget(w, { hw, team, graph, events, blind })}
                </Widget>
              </div>
            ))}
          </div>
        )}
      </div>
    </PanelShell>
  );
}
