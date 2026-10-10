/** Nyx — the brain, the chat and the voice on one screen.
 *
 * The owner asked to combine the brain and chat tabs ("chat, voice, and the second
 * brain should be shown") on a black canvas like his reference: a living memory
 * field with labelled source clusters and a quiet monospace HUD. So:
 *
 *   content layer   — BrainField: every point is a real memory, concept or source;
 *   functional layer — a few glass surfaces only (liquid-glass.md › Restraint):
 *                      the chat sheet, the network status card, the sources legend.
 *
 * The one orchestrated moment: sending a message asks Nyx Core which domain it
 * belongs to and that cluster pulses; while Nyx works, the clusters for the tools
 * it is using pulse, and new memories bloom in live. Reduced motion keeps the
 * field still (motion.md › Make motion optional).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { BrainField, type BrainCluster, type BrainFieldHandle, type BrainNodeInfo, type BrainStats } from "../components/brain/BrainField";
import { CoreView } from "../components/brain/CoreView";
import { AgentProperties } from "../components/AgentProperties";
import type { AvatarState } from "../components/NyxAvatar";
import { ChatPanel } from "./ChatPanel";
import { useReducedMotion } from "../useReducedMotion";
import { useStore } from "../state/store";
import { turnsStore } from "../state/turnStore";
import { onWorkspaceEvent } from "../state/workspaceEvents";
import { onSpeakingChange, speakText, stopSpeaking } from "../voice/voicePlayer";
import { onVoiceMode, voiceMode } from "../voice/voiceBus";

interface BrainSummary {
  nodes: number;
  memories: number;
  concepts: number;
  edges: number;
  added_24h: number;
  memories_24h: number;
  impulses_per_min: number;
  clusters: BrainCluster[];
  seeding: { running: boolean; current: string; added: number };
}

interface CoreSummary {
  level: number;
  name: string;
  like: string;
  parameters: number;
  progress: number;
  next_name: string | null;
  independence: number;
  domain_accuracy: number | null;
  widths: number[];
  examples: number;
}

const DOMAIN_CLUSTER: Record<string, number> = {
  chat: 0, web: 1, files: 2, code: 3, knowledge: 4, agents: 5, "self-study": 6, email: 7, design: 8, system: 9, models: 10, voice: 11,
};

function clusterForTool(name: string): number {
  const n = name.toLowerCase();
  if (/web|search|fetch|browse|news|url|weather|stock/.test(n)) return 1;
  if (/email|mail/.test(n)) return 7;
  if (/file|folder|document|obsidian|drive/.test(n)) return 2;
  if (/command|python|code|shell/.test(n)) return 3;
  if (/brain|recall|remember|knowledge/.test(n)) return 4;
  if (/agent|delegate|skill/.test(n)) return 5;
  if (/improve|self/.test(n)) return 6;
  if (/ui_|tab|theme|design|image/.test(n)) return 8;
  if (/mouse|keyboard|screen|window|process|volume|system|open_/.test(n)) return 9;
  if (/speak|voice/.test(n)) return 11;
  return 0;
}

const fmt = (n: number) => n.toLocaleString();

/** The Second Brain as a window beside the chat (redesign 2026-10-10): the field and the core, no chat sheet over it. */
export function SecondBrainWindow() {
  return <NyxPanel windowed provider="" onProvider={() => {}} onOpenTab={(tab) => window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab } }))} />;
}

export function NyxPanel({ onActivity, provider, onProvider, onOpenTab, windowed = false }: {
  onActivity?: (s: AvatarState) => void;
  provider: string;
  onProvider: (provider: string) => void;
  onOpenTab?: (tab: string) => void;
  /** Shown as a chat window: always the brain, and the chat is the one beside it, not a sheet on top. */
  windowed?: boolean;
}) {
  const reduced = useReducedMotion();
  // Update 1, U48 — what the tab shows, chosen at its top: "chat" (chats down the left, like Claude) or "brain"
  // (the Second Brain with voice and the chat sheet, the main screen until now). Remembered.
  const [layoutRaw, setLayout] = useState<"chat" | "brain">(() => {
    try { return localStorage.getItem("nyx.layout") === "brain" ? "brain" : "chat"; } catch { return "chat"; }
  });
  const layout = windowed ? "brain" : layoutRaw;
  useEffect(() => { if (!windowed) try { localStorage.setItem("nyx.layout", layoutRaw); } catch { /* not kept */ } }, [layoutRaw, windowed]);
  const field = useRef<BrainFieldHandle>(null);
  const [summary, setSummary] = useState<BrainSummary | null>(null);
  const [core, setCore] = useState<CoreSummary | null>(null);
  const [stats, setStats] = useState<BrainStats>({ fps: 0, points: 0, edges: 0 });
  const [focus, setFocus] = useState<number | null>(null);
  const [selected, setSelected] = useState<BrainNodeInfo | null>(null);
  const [predicted, setPredicted] = useState<number[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ memories: { id: number; text: string; source: string; index: number | null }[] } | null>(null);
  const [chatOpen, setChatOpen] = useState(!windowed);
  // The chat sheet's width: drag its left edge or press Expand (Request G17). Remembered.
  const [sheetWidth, setSheetWidth] = useState(() => {
    try { return Number(localStorage.getItem("nyx.sheet.width")) || 440; } catch { return 440; }
  });
  const [expanded, setExpanded] = useState(() => { try { return localStorage.getItem("nyx.sheet.expanded") === "1"; } catch { return false; } });
  const [stageWidth, setStageWidth] = useState(1200);
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const observer = new ResizeObserver(() => setStageWidth(stage.clientWidth || 1200));
    observer.observe(stage);
    return () => observer.disconnect();
  }, [layout]);
  const maxSheet = Math.max(340, stageWidth - 24);
  // "when activating voice make the side panel a bit smaller" (Project Null N90):
  // hands-free means looking at the brain, not reading the sheet, so it steps back
  // while voice is on and returns to the owner's own width afterwards.
  const [voiceOn, setVoiceOn] = useState(() => voiceMode() !== "off");
  useEffect(() => onVoiceMode((mode) => setVoiceOn(mode !== "off")), []);
  const wanted = voiceOn && !expanded ? Math.max(340, Math.round(sheetWidth * 0.78)) : sheetWidth;
  const effectiveSheet = Math.round(Math.min(maxSheet, expanded ? Math.max(sheetWidth, stageWidth * 0.66) : wanted));
  const saveSheet = (width: number, isExpanded: boolean) => {
    try {
      localStorage.setItem("nyx.sheet.width", String(Math.round(width)));
      localStorage.setItem("nyx.sheet.expanded", isExpanded ? "1" : "0");
    } catch { /* not persisted in private browsing */ }
  };
  const resizeSheet = (width: number) => {
    const clamped = Math.min(maxSheet, Math.max(340, width));
    setSheetWidth(clamped);
    setExpanded(false);
    saveSheet(clamped, false);
  };
  const onGripDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const stage = stageRef.current;
    if (!stage) return;
    e.preventDefault();
    const grip = e.currentTarget;
    grip.setPointerCapture(e.pointerId);
    const right = stage.getBoundingClientRect().right - 12;
    const move = (ev: PointerEvent) => resizeSheet(right - ev.clientX);
    const up = () => { grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", up); };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", up);
  };
  const [autoSpeak, setAutoSpeak] = useState(() => { try { return localStorage.getItem("nyx.voice.autospeak") === "1"; } catch { return false; } });
  const [speaking, setSpeaking] = useState<string | null>(null);
  const tagRefs = useRef<Map<number, { tag: HTMLButtonElement | null; line: SVGLineElement | null }>>(new Map());
  const stageRef = useRef<HTMLDivElement>(null);

  const loadSummary = useCallback(async () => {
    const [brain, coreResult] = await Promise.all([
      api.get<BrainSummary>("/api/brain/summary"),
      api.get<CoreSummary>("/api/core"),
    ]);
    if (brain.ok) setSummary(brain.data);
    if (coreResult.ok) setCore(coreResult.data);
  }, []);

  useEffect(() => {
    void loadSummary();
    const timer = window.setInterval(() => { if (!document.hidden) void loadSummary(); }, 15000);
    return () => window.clearInterval(timer);
  }, [loadSummary]);

  useEffect(() => onWorkspaceEvent((event) => {
    if (event.type === "brain.seeded" || event.type === "core.grew") void loadSummary();
  }), [loadSummary]);

  useEffect(() => onSpeakingChange(setSpeaking), []);

  // Clusters Nyx is working in right now: the tools of every running turn.
  const working = useStore(turnsStore, (s) => s.turns);
  const activeClusters = useMemo(() => {
    const ids = new Set<number>(predicted);
    let running = false;
    for (const turn of Object.values(working)) {
      if (turn.state !== "streaming") continue;
      running = true;
      turn.steps.filter((step) => step.status === "running").forEach((step) => ids.add(clusterForTool(step.name)));
    }
    if (running && ids.size === 0) ids.add(0);
    return Array.from(ids);
  }, [working, predicted]);

  // Auto-speak: read each finished answer aloud in Nyx's voice.
  const spokenRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!autoSpeak) return;
    for (const turn of Object.values(working)) {
      if (turn.state === "done" && turn.answer && !spokenRef.current.has(turn.turnId) && Date.now() - turn.startedAt < 5 * 60_000) {
        spokenRef.current.add(turn.turnId);
        void speakText(turn.answer, { role: "reply" }).catch(() => undefined);
      }
    }
  }, [working, autoSpeak]);

  const toggleAutoSpeak = () => {
    setAutoSpeak((value) => {
      const next = !value;
      try { localStorage.setItem("nyx.voice.autospeak", next ? "1" : "0"); } catch { /* ignore */ }
      if (next) Object.values(working).forEach((t) => spokenRef.current.add(t.turnId)); // don't read old answers
      else stopSpeaking();
      return next;
    });
  };

  const onSent = useCallback((text: string) => {
    if (!text) return;
    void api.get<{ prediction: { domain: string; domain_p: number } }>(`/api/core/predict?text=${encodeURIComponent(text.slice(0, 500))}`)
      .then((result) => {
        if (!result.ok) return;
        const id = DOMAIN_CLUSTER[result.data.prediction.domain];
        if (id === undefined) return;
        setPredicted([id]);
        window.setTimeout(() => setPredicted([]), 4000);
      });
  }, []);

  const runSearch = async (q: string) => {
    if (!q.trim()) { setResults(null); return; }
    const result = await api.get<{ memories: { id: number; text: string; source: string; index: number | null }[] }>(`/api/brain/search?q=${encodeURIComponent(q)}`);
    if (result.ok) setResults(result.data);
  };
  const highlight = useMemo(() => (results?.memories ?? []).map((m) => m.index).filter((i): i is number => typeof i === "number"), [results]);

  // Cluster tags: positioned straight from the render loop (no React re-render per frame).
  const clusters = summary?.clusters ?? [];
  const onProject = useCallback((anchors: { id: number; x: number; y: number; visible: boolean }[]) => {
    const stage = stageRef.current;
    if (!stage) return;
    const w = stage.clientWidth, h = stage.clientHeight;
    const sheet = chatOpen && w > 900 ? Math.min(effectiveSheet, w - 24) : 0;
    const cx = (w - sheet) / 2, cy = h / 2;
    const rx = Math.max(160, (w - sheet) * 0.42), ry = Math.max(120, h * 0.38);
    for (const anchor of anchors) {
      const refs = tagRefs.current.get(anchor.id);
      if (!refs?.tag || !refs.line) continue;
      const dx = anchor.x - cx, dy = anchor.y - cy;
      const angle = Math.atan2(dy / ry, dx / rx);
      const tx = cx + Math.cos(angle) * rx, ty = cy + Math.sin(angle) * ry;
      const visible = anchor.visible && anchor.x > -200 && anchor.x < w + 200;
      refs.tag.style.transform = `translate(${Math.round(tx)}px, ${Math.round(ty)}px) translate(${Math.cos(angle) < 0 ? "-100%" : "0"}, -50%)`;
      refs.tag.style.opacity = visible ? "1" : "0";
      refs.line.setAttribute("x1", String(anchor.x));
      refs.line.setAttribute("y1", String(anchor.y));
      refs.line.setAttribute("x2", String(tx));
      refs.line.setAttribute("y2", String(ty));
      refs.line.style.opacity = visible ? "1" : "0";
    }
  }, [chatOpen, effectiveSheet]);

  const toggleFocus = (id: number) => {
    const next = focus === id ? null : id;
    setFocus(next);
    field.current?.focusCluster(next);
  };

  const total = summary?.memories ?? 0;
  const seeding = summary?.seeding?.running;
  // Two ways to see what Nyx is: the memory field and the core at work. Agent City went in Update 1 (U13, owner:
  // "remove Agent city since it was basically what office would look like") — Office Space shows the team as a
  // place, and an agent still opens from the Core view and the Agents tab. A saved "city" falls back to the field.
  const [view, setView] = useState<"field" | "core">(() => {
    try { return localStorage.getItem("nyx.stage.view") === "core" ? "core" : "field"; } catch { return "field"; }
  });
  const [openAgent, setOpenAgent] = useState<string | null>(null);
  useEffect(() => { try { localStorage.setItem("nyx.stage.view", view); } catch { /* not kept in private windows */ } }, [view]);
  // U15, "some tabs on memory field ... are obstructive": the cards fold to one line, and remember how the owner left them.
  const [legendOpen, setLegendOpen] = useState(() => {
    try { return localStorage.getItem("nyx.field.legend") === "1"; } catch { return false; }
  });
  const [statusOpen, setStatusOpen] = useState(() => {
    try { return localStorage.getItem("nyx.field.status") === "1"; } catch { return false; }
  });
  useEffect(() => { try { localStorage.setItem("nyx.field.legend", legendOpen ? "1" : "0"); } catch { /* not kept */ } }, [legendOpen]);
  useEffect(() => { try { localStorage.setItem("nyx.field.status", statusOpen ? "1" : "0"); } catch { /* not kept */ } }, [statusOpen]);

  const layoutBar = windowed ? null : (
    <div className="nyx-tab__bar">
      <div className="segmented" role="group" aria-label="What the Nyx tab shows">
        <button type="button" aria-pressed={layout === "chat"} onClick={() => setLayout("chat")}>Chat</button>
        <button type="button" aria-pressed={layout === "brain"} onClick={() => setLayout("brain")}>Second Brain</button>
      </div>
      <span className="nyx-tab__hint">
        {layout === "chat" ? "Your chats are on the left — the memory field and voice are one click away."
          : "The memory field, voice and a chat beside them."}
      </span>
    </div>
  );

  if (layout === "chat") {
    return (
      <div className="nyx-tab">
        {layoutBar}
        <ChatPanel variant="home" onActivity={onActivity} provider={provider} onProvider={onProvider} onSent={onSent}
          brain={summary ? { memories: summary.memories, today: summary.memories_24h } : null}
          onOpenBrain={() => setLayout("brain")} />
      </div>
    );
  }

  return (
    <div className="nyx-tab">
    {layoutBar}
    <div ref={stageRef} className={`nyx-stage${chatOpen ? " has-chat" : ""}${view === "core" ? " is-core" : ""}`} style={{ ["--sheet-w" as string]: `${effectiveSheet}px` }}>
      {view === "core" && (
        <CoreView shiftX={chatOpen && stageWidth > 900 ? Math.round(effectiveSheet / 2) : 0} onOpenAgent={setOpenAgent} onOpenTab={onOpenTab} />
      )}
      {openAgent && <AgentProperties name={openAgent} onClose={() => setOpenAgent(null)} onRenamed={setOpenAgent} />}
      {view === "field" && <BrainField
        ref={field}
        clusters={clusters}
        reduced={reduced}
        active={activeClusters}
        highlight={highlight}
        onStats={setStats}
        onSelect={setSelected}
        onProject={onProject}
        shiftX={chatOpen ? Math.round(effectiveSheet / 2) : 0}
      />}

      {/* Radial threads from each cluster to its label, like the reference. */}
      <svg className="nyx-threads" aria-hidden="true">
        <defs>
          {clusters.map((c) => (
            <linearGradient key={c.id} id={`thread-${c.id}`} gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor={c.color} stopOpacity="0.9" />
              <stop offset="1" stopColor={c.color} stopOpacity="0.15" />
            </linearGradient>
          ))}
        </defs>
        {clusters.filter((c) => c.count > 0).map((c) => (
          <line key={c.id} ref={(el) => { const r = tagRefs.current.get(c.id) ?? { tag: null, line: null }; r.line = el; tagRefs.current.set(c.id, r); }}
            stroke={c.color} strokeOpacity={activeClusters.includes(c.id) ? 0.85 : 0.35} strokeWidth={activeClusters.includes(c.id) ? 1.4 : 0.8} />
        ))}
      </svg>
      <div className="nyx-tags">
        {clusters.filter((c) => c.count > 0).map((c) => (
          <button
            key={c.id}
            ref={(el) => { const r = tagRefs.current.get(c.id) ?? { tag: null, line: null }; r.tag = el; tagRefs.current.set(c.id, r); }}
            className={`nyx-tag${focus === c.id ? " is-focused" : ""}${activeClusters.includes(c.id) ? " is-active" : ""}`}
            onClick={() => toggleFocus(c.id)}
            aria-pressed={focus === c.id}
            title={`${c.label}: ${fmt(c.count)} nodes — click to fly there`}
          >
            <span className="nyx-tag__dot" style={{ background: c.color }} />
            <span className="nyx-tag__name">{c.label}</span>
            <span className="nyx-tag__sub">{c.top.slice(0, 2).join(" · ") || `${fmt(c.count)} nodes`}</span>
          </button>
        ))}
      </div>

      {/* Identity, the view switch, and the sources legend — one column, so nothing sits on top of anything else. */}
      <div className="nyx-hud nyx-hud--left">
        <div className="nyx-brand">
          <span className="nyx-brand__mark" aria-hidden="true">◐</span>
          <div>
            <div className="nyx-brand__name">NYX ICHOS</div>
            <div className="hud-caption">{view === "core" ? "core" : "memory field"}</div>
          </div>
        </div>
        <div className="nyx-stage__views segmented" role="group" aria-label="What this stage shows">
          <button type="button" aria-pressed={view === "field"} onClick={() => setView("field")}>Memory field</button>
          <button type="button" aria-pressed={view === "core"} onClick={() => setView("core")}>Core</button>
        </div>
        <div className={`nyx-legend glass${legendOpen ? " is-open" : ""}`}>
          <button type="button" className="nyx-fold" aria-expanded={legendOpen} onClick={() => setLegendOpen(!legendOpen)}>
            <span className="hud-caption">Memory sources</span>
            <span className="hud-value">{fmt(clusters.reduce((sum, c) => sum + (c.count || 0), 0))}</span>
          </button>
          {legendOpen && <ul>
            {clusters.map((c) => (
              <li key={c.id}>
                <button onClick={() => toggleFocus(c.id)} aria-pressed={focus === c.id} disabled={!c.count}>
                  <span className="nyx-tag__dot" style={{ background: c.color }} />
                  <span>{c.label}</span>
                  <span className="hud-value">{c.count ? fmt(c.count) : "—"}</span>
                </button>
              </li>
            ))}
          </ul>}
          <form className="nyx-search" onSubmit={(e) => { e.preventDefault(); void runSearch(query); }}>
            <input value={query} onChange={(e) => { setQuery(e.target.value); if (!e.target.value) setResults(null); }}
              placeholder="Search memories" aria-label="Search Nyx's memories" />
          </form>
          {results && (
            <div className="nyx-results" aria-live="polite">
              {results.memories.length === 0 ? <div className="muted">Nothing remembered about that yet.</div> :
                results.memories.slice(0, 5).map((m) => (
                  <div key={m.id} className="nyx-result"><span className="hud-caption">{m.source}</span>{m.text.slice(0, 160)}</div>
                ))}
            </div>
          )}
        </div>
      </div>

      {/* Network status: one line until asked for the numbers. */}
      <div className={`nyx-hud nyx-hud--status glass${statusOpen ? " is-open" : ""}`} aria-live="off">
        <button type="button" className="nyx-fold nyx-online" aria-expanded={statusOpen} onClick={() => setStatusOpen(!statusOpen)}
          title={statusOpen ? "Hide the numbers" : "Show the memory network's numbers"}>
          <span className="nyx-online__dot" />Online<span className="hud-value nyx-online__fps">{stats.fps} fps</span>
        </button>
        {statusOpen && <dl>
          <div><dt>Live system</dt><dd className="hud-value">{stats.fps} fps</dd></div>
          <div><dt>Nodes drawn</dt><dd className="hud-value">{fmt(stats.points)}</dd></div>
          <div><dt>Links</dt><dd className="hud-value">{fmt(summary?.edges ?? 0)}</dd></div>
          <div><dt>Impulses</dt><dd className="hud-value">{fmt(summary?.impulses_per_min ?? 0)}/min</dd></div>
          {core && <div><dt>Nyx Core</dt><dd className="hud-value">L{core.level} {core.name}</dd></div>}
        </dl>}
        {seeding && <div className="hud-caption nyx-seeding">Growing from {summary?.seeding.current}…</div>}
      </div>

      {/* Title */}
      <div className="nyx-title">
        <div className="hud-caption">Super brain · live memory map</div>
        <h1>Second Brain</h1>
        <div className="nyx-title__count">
          <span className="hud-value">{fmt(total)}</span> memories in the field
          <span className="chip">+{fmt(summary?.memories_24h ?? 0)} / 24h</span>
        </div>
        {core && (
          <button className="nyx-core-pill" onClick={() => onOpenTab?.("learn")} title="Open the Learn tab">
            <span className="nyx-core-pill__ring" style={{ ["--p" as string]: `${Math.round(core.progress * 100)}%` }} />
            Nyx Core · {fmt(core.parameters)} learned parameters · {Math.round(core.independence * 100)}% on its own
          </button>
        )}
      </div>

      <div className="nyx-hints hud-caption" aria-hidden="true">Drag rotate · Shift-drag pan · Scroll zoom · F full screen</div>

      {selected && (
        <div className="nyx-node glass" role="dialog" aria-label="Memory details">
          <div className="nyx-node__head">
            <span className="nyx-tag__dot" style={{ background: clusters[selected.cluster]?.color }} />
            <span className="hud-caption">{selected.kind} · {clusters[selected.cluster]?.label} · seen {selected.hits}×</span>
            <button className="btn btn-secondary" onClick={() => setSelected(null)} aria-label="Close">✕</button>
          </div>
          <div className="nyx-node__text">{selected.memory?.text ?? selected.label}</div>
          {selected.neighbours.length > 0 && (
            <div className="nyx-node__links">
              {selected.neighbours.slice(0, 10).map((n) => <span key={n.id} className="chip">{n.label.slice(0, 32)}</span>)}
            </div>
          )}
        </div>
      )}

      {/* Chat + voice sheet */}
      {!windowed && <aside className={`nyx-sheet glass${chatOpen ? "" : " is-closed"}`} aria-label="Chat with Nyx">
        <div
          className="nyx-sheet__grip"
          role="separator"
          aria-orientation="vertical"
          aria-label="Chat width — drag, or use the arrow keys"
          aria-valuemin={340}
          aria-valuemax={maxSheet}
          aria-valuenow={effectiveSheet}
          tabIndex={0}
          title="Drag to resize · double-click to reset"
          onPointerDown={onGripDown}
          onDoubleClick={() => resizeSheet(440)}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft") { e.preventDefault(); resizeSheet(effectiveSheet + 32); }
            if (e.key === "ArrowRight") { e.preventDefault(); resizeSheet(effectiveSheet - 32); }
          }}
        />
        <div className="nyx-sheet__head">
          <div className={`nyx-voice-orb${speaking ? " is-speaking" : ""}`} aria-hidden="true" />
          <div className="nyx-sheet__title">Nyx</div>
          <button className="nyx-voice-toggle" role="switch" aria-checked={autoSpeak} onClick={toggleAutoSpeak}
            title="Read every answer aloud in Nyx's voice">
            <span className="switch" aria-checked={autoSpeak} />
            <span>Voice</span>
          </button>
          {speaking && <button className="btn btn-secondary" onClick={() => stopSpeaking()}>Stop voice</button>}
          <button
            className="btn btn-secondary nyx-sheet__expand"
            onClick={() => { const next = !expanded; setExpanded(next); saveSheet(sheetWidth, next); }}
            aria-pressed={expanded}
            title={expanded ? "Back to your chosen width" : "Make the chat wide"}
          >
            {expanded ? "Shrink" : "Expand"}
          </button>
          <button className="btn btn-secondary" onClick={() => setChatOpen(false)} aria-label="Hide chat" title="Hide chat — see the whole brain">Hide</button>
        </div>
        {chatOpen && <ChatPanel variant="sheet" onActivity={onActivity} provider={provider} onProvider={onProvider} onSent={onSent} />}
      </aside>}
      {!chatOpen && !windowed && (
        <button className="nyx-sheet-open btn btn-plain" onClick={() => setChatOpen(true)}>Chat with Nyx</button>
      )}
    </div>
    </div>
  );
}
