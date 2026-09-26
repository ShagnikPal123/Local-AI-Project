/** The office floor: rooms you can see, desks you can watch, and lines when one agent talks to another.
 *
 * The owner asked to *"watch as they work"*, so the floor is the tab's centre of gravity: each section is a room
 * in its own colour, each agent is a desk whose head colour and symbol say what kind of agent it is, a working
 * agent's monitor is lit, and a message between two agents draws a line for a few seconds.
 *
 * It is one SVG with one transform for pan and zoom — hundreds of desks stay smooth because nothing re-lays out
 * when the view moves, and each desk is memoised so one agent's step changing repaints one desk.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "../../useReducedMotion";
import { layout, talkPath } from "./floorLayout";
import type { OfficeAgent, OfficeRole, OfficeSection, Talk } from "./types";

interface FloorProps {
  sections: OfficeSection[];
  agents: OfficeAgent[];
  roles: Record<string, OfficeRole>;
  talks: Talk[];
  selectedSections: string[];
  selectedAgents: string[];
  gatekeeperId: string;
  onPickAgent: (agentId: string, additive: boolean) => void;
  onOpenSection: (sectionId: string) => void;
  onToggleSection: (sectionId: string, additive: boolean) => void;
}

const STATUS_COLOR: Record<string, string> = {
  working: "var(--ofc-live)",
  waiting: "var(--ofc-wait)",
  paused: "var(--ofc-warn)",
  error: "var(--ofc-risk)",
  idle: "transparent",
};

export function Floor(props: FloorProps) {
  const { sections, agents, roles, talks, selectedSections, selectedAgents, gatekeeperId } = props;
  const reduced = useReducedMotion();
  const holder = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState({ x: 24, y: 24, k: 1 });
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const plan = useMemo(() => layout(sections, agents), [sections, agents]);
  const fitted = useRef("");

  /** Keep the office on screen.
   *
   * Without this, one fling of the mouse (or a couple of scroll-wheel notches) slid the whole floor past the
   * edge and left a black rectangle with no way back except the Fit button — which is exactly what it looked
   * like: a broken tab. Panning is now bounded so a slice of the rooms always stays in view.
   */
  const clamp = useCallback((next: { x: number; y: number; k: number }) => {
    const box = holder.current?.getBoundingClientRect();
    if (!box || !plan.rooms.length) return next;
    const edge = Math.min(180, box.width / 3);
    const contentW = plan.width * next.k;
    const contentH = plan.height * next.k;
    const x = contentW + 2 * edge <= box.width
      ? Math.min(Math.max(next.x, 0), box.width - contentW)      // it fits: keep it inside
      : Math.min(Math.max(next.x, box.width - contentW - edge), edge);
    const y = contentH + 2 * edge <= box.height
      ? Math.min(Math.max(next.y, 0), box.height - contentH)
      : Math.min(Math.max(next.y, box.height - contentH - edge), edge);
    return { ...next, x, y };
  }, [plan]);

  const fit = useCallback(() => {
    const box = holder.current?.getBoundingClientRect();
    if (!box || !plan.rooms.length) return;
    const k = Math.min((box.width - 32) / plan.width, (box.height - 32) / plan.height, 1);
    const scale = Math.max(0.25, Math.min(1, k));
    setView(clamp({ k: scale, x: (box.width - plan.width * scale) / 2,
                    y: Math.max(16, (box.height - plan.height * scale) / 2) }));
  }, [plan, clamp]);

  // The pane changing width (the sidebar opening, the window resizing) must not leave the floor off-screen.
  useEffect(() => {
    const element = holder.current;
    if (!element || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => setView((current) => clamp(current)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [clamp]);

  // Fit once per office shape change (a new room appearing should not yank the view the owner set).
  useEffect(() => {
    const shape = `${plan.rooms.length}:${Math.round(plan.width)}x${Math.round(plan.height)}`;
    if (fitted.current === shape || !plan.rooms.length) return;
    const first = fitted.current === "";
    fitted.current = shape;
    if (first || plan.width * view.k > (holder.current?.clientWidth ?? 0)) fit();
  }, [plan, fit, view.k]);

  const onWheel = useCallback((event: React.WheelEvent) => {
    if (event.ctrlKey) return;              // pinch-zoom on a trackpad is the browser's
    event.preventDefault();
    const box = holder.current?.getBoundingClientRect();
    if (!box) return;
    const px = event.clientX - box.left;
    const py = event.clientY - box.top;
    setView((current) => {
      const k = Math.max(0.25, Math.min(2.2, current.k * (event.deltaY < 0 ? 1.12 : 0.89)));
      const ratio = k / current.k;
      return clamp({ k, x: px - (px - current.x) * ratio, y: py - (py - current.y) * ratio });
    });
  }, [clamp]);

  const onPointerDown = (event: React.PointerEvent) => {
    if ((event.target as Element).closest("[data-desk],[data-room-head]")) return;
    drag.current = { x: event.clientX, y: event.clientY, ox: view.x, oy: view.y };
    setDragging(true);
    (event.currentTarget as Element).setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: React.PointerEvent) => {
    if (!drag.current) return;
    setView((current) => clamp({
      ...current,
      x: drag.current!.ox + (event.clientX - drag.current!.x),
      y: drag.current!.oy + (event.clientY - drag.current!.y),
    }));
  };
  const endDrag = () => {
    drag.current = null;
    setDragging(false);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const step = event.shiftKey ? 120 : 40;
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step],
    };
    if (moves[event.key]) {
      event.preventDefault();
      setView((c) => clamp({ ...c, x: c.x + moves[event.key][0], y: c.y + moves[event.key][1] }));
    }
    if (event.key === "+" || event.key === "=") setView((c) => clamp({ ...c, k: Math.min(2.2, c.k * 1.15) }));
    if (event.key === "-") setView((c) => clamp({ ...c, k: Math.max(0.25, c.k / 1.15) }));
    if (event.key.toLowerCase() === "f") fit();
  };

  const selectedSectionSet = new Set(selectedSections);
  const selectedAgentSet = new Set(selectedAgents);
  const now = Date.now();

  return (
    <div className={`ofc-floor${view.k < 0.7 ? " ofc-floor--far" : ""}${dragging ? " is-dragging" : ""}`}
         ref={holder} onWheel={onWheel} onPointerDown={onPointerDown} onPointerMove={onPointerMove}
         onPointerUp={endDrag} onPointerCancel={endDrag} onKeyDown={onKeyDown} tabIndex={0}
         aria-label={`Office floor: ${sections.length} sections, ${agents.length} agents`} role="group">
      {/* No SVG filters anywhere in here on purpose: a blur filter inside a transformed group made Chromium
          drop the whole layer to black mid-drag. A lit monitor is drawn as a second translucent rectangle. */}
      <svg className="ofc-floor__svg" width="100%" height="100%">
        <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
          {plan.rooms.map((room) => (
            <g key={room.section.id} className={`ofc-room${selectedSectionSet.has(room.section.id) ? " is-picked" : ""}`}
               style={{ ["--room" as string]: room.section.color }}>
              <rect className="ofc-room__floor" x={room.x} y={room.y} width={room.width} height={room.height} rx={16} />
              <g data-room-head="1" className="ofc-room__head" role="button" tabIndex={-1}
                 onClick={(event) => props.onToggleSection(room.section.id, event.shiftKey || event.metaKey || event.ctrlKey)}
                 onDoubleClick={() => props.onOpenSection(room.section.id)}>
                <rect x={room.x} y={room.y} width={room.width} height={30} rx={16} className="ofc-room__band" />
                <text x={room.x + 14} y={room.y + 20} className="ofc-room__name">{room.section.name}</text>
                <text x={room.x + room.width - 12} y={room.y + 20} className="ofc-room__count" textAnchor="end">
                  {room.desks.length}
                </text>
                <title>{room.section.purpose || room.section.name} — click to select, double-click to open</title>
              </g>
              {room.section.status !== "active" && (
                <text x={room.x + 14} y={room.y + room.height - 8} className="ofc-room__paused">
                  {room.section.status === "paused" ? "paused" : "halted"}
                </text>
              )}
              {room.desks.map((desk) => (
                <Desk key={desk.agent.id} agent={desk.agent} x={desk.x} y={desk.y}
                      role={roles[desk.agent.role]} sectionColor={room.section.color}
                      picked={selectedAgentSet.has(desk.agent.id)}
                      board={desk.agent.id === gatekeeperId} reduced={reduced}
                      onPick={props.onPickAgent} />
              ))}
            </g>
          ))}
          <g className="ofc-talks">
            {talks.flatMap((talk) => {
              const from = plan.byAgent[talk.from];
              if (!from) return [];
              return talk.to.slice(0, 4).map((toId) => {
                const to = plan.byAgent[toId];
                if (!to) return null;
                const age = (now - talk.at) / 1000;
                return (
                  <g key={`${talk.id}-${toId}`} className="ofc-talk" style={{ opacity: Math.max(0, 1 - age / 4) }}>
                    <path d={talkPath(from, to)} className="ofc-talk__line" />
                    {!reduced && (
                      <circle r={3.2} className="ofc-talk__dot">
                        <animateMotion dur="1.1s" repeatCount="3" path={talkPath(from, to)} />
                      </circle>
                    )}
                  </g>
                );
              });
            })}
          </g>
        </g>
      </svg>
      <div className="ofc-floor__tools">
        <button className="ofc-icon" onClick={fit} title="Fit the whole office (F)">⤢</button>
        <button className="ofc-icon" onClick={() => setView((c) => clamp({ ...c, k: Math.min(2.2, c.k * 1.15) }))}
                title="Zoom in (+)">＋</button>
        <button className="ofc-icon" onClick={() => setView((c) => clamp({ ...c, k: Math.max(0.25, c.k / 1.15) }))}
                title="Zoom out (−)">−</button>
        <span className="ofc-floor__zoom">{Math.round(view.k * 100)}%</span>
      </div>
    </div>
  );
}

interface DeskProps {
  agent: OfficeAgent;
  x: number;
  y: number;
  role?: OfficeRole;
  sectionColor: string;
  picked: boolean;
  board: boolean;
  reduced: boolean;
  onPick: (agentId: string, additive: boolean) => void;
}

const Desk = memo(function Desk({ agent, x, y, role, sectionColor, picked, board, reduced, onPick }: DeskProps) {
  const head = role?.color ?? "#9397ab";
  const working = agent.status === "working";
  const ring = STATUS_COLOR[agent.status] ?? "transparent";
  return (
    <g data-desk={agent.id} className={`ofc-desk is-${agent.status}${picked ? " is-picked" : ""}${board ? " is-board" : ""}`}
       transform={`translate(${x} ${y})`} role="button" tabIndex={-1}
       onClick={(event) => onPick(agent.id, event.shiftKey || event.metaKey || event.ctrlKey)}>
      <title>{`${agent.name} — ${role?.title ?? agent.role}\n${agent.step || agent.status}${
        agent.member ? `\nmodel: ${agent.member}` : ""}`}</title>
      <rect className="ofc-desk__surface" x={-27} y={2} width={54} height={16} rx={5}
            style={{ stroke: sectionColor }} />
      {working && <rect className="ofc-desk__halo" x={-17} y={-12} width={34} height={21} rx={6}
                        style={{ fill: head }} />}
      <rect className={`ofc-desk__screen${working ? " is-on" : ""}`} x={-13} y={-8} width={26} height={13} rx={3}
            style={working ? { fill: head } : undefined} />
      <circle className="ofc-desk__head" cx={0} cy={-20} r={9} style={{ fill: head }} />
      <text className="ofc-desk__glyph" x={0} y={-16.5} textAnchor="middle">{role?.glyph ?? "●"}</text>
      {ring !== "transparent" && (
        <circle className={`ofc-desk__ring${working && !reduced ? " is-pulsing" : ""}`} cx={0} cy={-20} r={12.5}
                style={{ stroke: ring }} />
      )}
      {picked && <circle className="ofc-desk__picked" cx={0} cy={-20} r={15.5} />}
      <text className="ofc-desk__name" x={0} y={30} textAnchor="middle">{agent.name}</text>
    </g>
  );
});
