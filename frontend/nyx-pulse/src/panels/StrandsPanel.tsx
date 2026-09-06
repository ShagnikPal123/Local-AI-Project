/** Strands — the HUD tab (ROADMAP DD1-DD5, DD10, DD12).
 *
 * A radial map of how the system's ideas actually connect, with a speech core
 * at the centre and live panels around it.
 *
 * The reference Shagnik supplied is a mockup and every reading in it is invented.
 * Everything here is wired to a real endpoint, and where there is no data the
 * panel says so. A HUD that displays plausible-looking fiction is worse than an
 * empty one, because it looks authoritative.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";

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

const EVENT_COLOR: Record<SystemEvent["level"], string> = {
  info: "var(--color-neutral-500)",
  ok: "var(--color-ok)",
  warn: "var(--color-warn)",
  error: "var(--color-danger)",
};

const KIND_COLOR: Record<StrandNode["kind"], string> = {
  memory: "#5ad6e0",
  agent: "#9184d9",
  chat: "#5ac08a",
  knowledge: "#e0b45a",
};

const CENTRE = 200;
const RING_RADIUS = 132;

/** Lay nodes out on a circle. Deterministic, so the map does not jump on refresh. */
function layout(nodes: StrandNode[]): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const count = Math.max(nodes.length, 1);
  nodes.forEach((node, i) => {
    const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
    positions.set(node.id, {
      x: CENTRE + Math.cos(angle) * RING_RADIUS,
      y: CENTRE + Math.sin(angle) * RING_RADIUS,
    });
  });
  return positions;
}

function StrandMap({ graph, onSelect }: {
  graph: StrandGraph;
  onSelect: (node: StrandNode) => void;
}) {
  const positions = useMemo(() => layout(graph.nodes), [graph.nodes]);

  return (
    <svg viewBox="0 0 400 400" style={{ width: "100%", maxWidth: 460, aspectRatio: "1" }}>
      {/* Static rings — decoration, and clearly not data */}
      {[168, 132, 96].map((r) => (
        <circle key={r} cx={CENTRE} cy={CENTRE} r={r} fill="none"
          stroke="var(--color-accent)" strokeOpacity="0.1" strokeWidth="1"
          strokeDasharray={r === 168 ? "3 7" : undefined} />
      ))}

      {/* Strands */}
      {graph.links.map((link, i) => {
        const a = positions.get(link.source);
        const b = positions.get(link.target);
        if (!a || !b) return null;
        return (
          <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
            stroke="var(--color-accent)"
            strokeOpacity={Math.min(0.15 + link.weight * 0.12, 0.6)}
            strokeWidth={Math.min(1 + link.weight * 0.4, 3)}>
            <title>{link.shared.join(", ")}</title>
          </line>
        );
      })}

      {/* Core */}
      <circle cx={CENTRE} cy={CENTRE} r="42" fill="none"
        stroke="var(--color-accent)" strokeOpacity="0.35" strokeWidth="1" />
      <circle cx={CENTRE} cy={CENTRE} r="30" fill="var(--color-accent)" fillOpacity="0.07" />
      <text x={CENTRE} y={CENTRE - 4} textAnchor="middle"
        style={{ fill: "var(--color-accent)", fontSize: 11, letterSpacing: "0.14em" }}>
        STRANDS
      </text>
      <text x={CENTRE} y={CENTRE + 12} textAnchor="middle"
        style={{ fill: "var(--color-neutral-500)", fontSize: 9, fontFamily: "var(--font-mono)" }}>
        {graph.counts.nodes} · {graph.counts.links} links
      </text>

      {/* Nodes */}
      {graph.nodes.map((node) => {
        const pos = positions.get(node.id);
        if (!pos) return null;
        const color = KIND_COLOR[node.kind] ?? "var(--color-accent)";
        return (
          <g key={node.id} onClick={() => onSelect(node)} style={{ cursor: "pointer" }}>
            <circle cx={pos.x} cy={pos.y} r="6" fill={color} fillOpacity="0.85" />
            <circle cx={pos.x} cy={pos.y} r="11" fill="none" stroke={color} strokeOpacity="0.25" />
            <text x={pos.x} y={pos.y - 16} textAnchor="middle"
              style={{ fill: "var(--color-neutral-400)", fontSize: 9 }}>
              {node.label.length > 18 ? `${node.label.slice(0, 17)}…` : node.label}
            </text>
            <title>{node.detail}</title>
          </g>
        );
      })}
    </svg>
  );
}

/** Speech core. Amplitude comes from the mic when granted, and it is honest when not. */
function SpeechCore() {
  const [level, setLevel] = useState(0);
  const [listening, setListening] = useState(false);
  const [denied, setDenied] = useState(false);
  const cleanup = useRef<(() => void) | null>(null);

  async function toggle() {
    if (listening) {
      cleanup.current?.();
      cleanup.current = null;
      setListening(false);
      setLevel(0);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext();
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      let raf = 0;
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
        setLevel(Math.min(peak / 64, 1));
        raf = requestAnimationFrame(tick);
      };
      tick();
      cleanup.current = () => {
        cancelAnimationFrame(raf);
        stream.getTracks().forEach((t) => t.stop());
        void ctx.close();
      };
      setListening(true);
      setDenied(false);
    } catch {
      setDenied(true);
    }
  }

  useEffect(() => () => cleanup.current?.(), []);

  const bars = 28;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 2, height: 34 }}>
        {Array.from({ length: bars }, (_, i) => {
          const centreBias = 1 - Math.abs(i - bars / 2) / (bars / 2);
          const h = listening
            ? 3 + level * 30 * (0.35 + centreBias * 0.9) * (0.6 + Math.random() * 0.4)
            : 3;
          return (
            <span key={i} style={{
              width: 2, height: `${h}px`, background: "var(--color-accent)",
              opacity: listening ? 0.45 + centreBias * 0.55 : 0.2,
              transition: "height 70ms linear",
            }} />
          );
        })}
      </div>
      <button className="btn btn-secondary" onClick={() => void toggle()}>
        {listening ? "Stop listening" : "Awaiting command…"}
      </button>
      {denied && (
        <div style={{ fontSize: 11, color: "var(--color-warn)" }}>
          Microphone access denied — the waveform stays flat rather than faking motion.
        </div>
      )}
    </div>
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

export function StrandsPanel() {
  const [graph, setGraph] = useState<StrandGraph | null>(null);
  const [team, setTeam] = useState<TeamSnapshot | null>(null);
  const [selected, setSelected] = useState<StrandNode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [widgets, setWidgets] = useState<WidgetDef[]>([]);
  const [available, setAvailable] = useState<WidgetTypeDef[]>([]);
  const [events, setEvents] = useState<SystemEvent[]>([]);
  const [adding, setAdding] = useState(false);
  const dragFrom = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const [g, t, w, e] = await Promise.all([
        api.get<StrandGraph>("/api/strands"),
        api.get<TeamSnapshot>("/api/agents"),
        api.get<{ widgets: WidgetDef[]; available: WidgetTypeDef[] }>("/api/widgets"),
        api.get<{ events: SystemEvent[] }>("/api/events"),
      ]);
      if (!alive) return;
      if (g.ok) { setGraph(g.data); setError(null); } else setError(g.error);
      if (t.ok) setTeam(t.data);
      if (w.ok) { setWidgets(w.data.widgets); setAvailable(w.data.available); }
      if (e.ok) setEvents(e.data.events);
    };
    void load();
    const timer = setInterval(load, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

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

  if (error && !graph) return <PanelShell title="Strands"><ErrorState error={error} /></PanelShell>;
  if (!graph) return <PanelShell title="Strands"><Loading what="Tracing strands" /></PanelShell>;

  const hw = team?.resource_pressure ?? {};
  const blind = hw.telemetry_available === false;

  return (
    <PanelShell
      title="Strands"
      subtitle={`${graph.counts.nodes} nodes · ${graph.counts.links} connections`}
    >
      <div style={{
        display: "grid", gap: 14, alignItems: "start",
        gridTemplateColumns: "minmax(0, 1fr) minmax(220px, 300px)",
      }}>
        {/* Centre */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16, minWidth: 0 }}>
          {graph.empty ? (
            <div className="card" style={{ width: "100%", textAlign: "center", padding: 40 }}>
              <div style={{ fontSize: 13, color: "var(--color-neutral-500)", lineHeight: 1.7 }}>
                No strands yet. This map is built from real memories, agent goals, and open
                chats — as those appear, the connections between them are drawn here.
                <br /><br />
                Nothing is shown rather than a decorative graph, because a map of invented
                data would be worse than an empty one.
              </div>
            </div>
          ) : (
            <StrandMap graph={graph} onSelect={setSelected} />
          )}

          <SpeechCore />

          {selected && (
            <div className="card" style={{ width: "100%", borderLeft: `3px solid ${KIND_COLOR[selected.kind]}` }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 5 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{selected.label}</span>
                <span style={{ fontSize: 10, textTransform: "uppercase", color: KIND_COLOR[selected.kind] }}>
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
        </div>

        {/* Widgets — user-configurable, drag to reorder */}
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
      </div>
    </PanelShell>
  );
}
