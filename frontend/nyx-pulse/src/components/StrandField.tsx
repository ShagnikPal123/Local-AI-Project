/** The Strands field — a drifting 3D point cloud drawn on a 2D canvas.
 *
 * Depth is a real perspective divide, not a drop shadow: every point carries a z,
 * is tilted by a FIXED viewing angle, and is projected with `FOCAL / (FOCAL + z)`.
 * Near points are larger and brighter, which is what makes the cloud read as a
 * volume rather than a scatter plot.
 *
 * **It expands, it never turns.** An earlier version advanced a Y/X rotation every
 * frame; that made a moving target of every node and was not what was wanted. The
 * only motion now is radial: while Nyx speaks, each point's own vector is scaled so
 * it travels straight out from the centre and eases back as speech ends. Angles are
 * never touched, so nothing appears to spin or orbit.
 *
 * Canvas rather than DOM/CSS 3D because the node count grows without bound as the
 * user talks (that is the whole point of the tab), and a few hundred absolutely
 * positioned elements with `translateZ` costs a layout pass per frame. It is also
 * why the animation loop reads its inputs from refs and callbacks: React never
 * re-renders during motion.
 *
 * Nothing is imported for this on purpose — the app is offline-first and
 * CSP-constrained, so a CDN three.js is not an option.
 */

import { useCallback, useEffect, useRef } from "react";

export interface FieldNode {
  id: string;
  label: string;
  kind: string;
  detail: string;
}

export interface FieldLink {
  source: string;
  target: string;
  weight: number;
}

export interface StrandFieldHandle {
  resetView: () => void;
  zoomBy: (factor: number) => void;
}

export interface StrandFieldProps {
  nodes: FieldNode[];
  links: FieldLink[];
  /** Colour per node kind, supplied by the panel so the legend cannot drift. */
  kindColor: (kind: string) => string;
  selectedId?: string | null;
  onSelect: (node: FieldNode | null) => void;
  /**
   * 0..1, sampled once per frame. The panel owns what this number means
   * (microphone amplitude, or a synthesised envelope) and labels it for the
   * user; the field only knows "move this much".
   */
  sampleEnergy?: (seconds: number) => number;
  /** Honour prefers-reduced-motion: no drift, no rotation, one frame per change. */
  reduced: boolean;
  /** Rendered height of the canvas box. */
  height: number | string;
  handleRef?: React.MutableRefObject<StrandFieldHandle | null>;
}

/** Perspective distance. Larger flattens the cloud; smaller exaggerates it. */
const FOCAL = 760;
/** World radius the node shell fills. */
const SHELL = 250;
const DUST_COUNT = 140;

interface Placed {
  node: FieldNode;
  /** Base position; each frame adds drift on top. */
  x: number;
  y: number;
  z: number;
  phase: number;
  /** performance.now() when this node first appeared, for the arrival flare. */
  born: number;
}

interface Dust {
  x: number;
  y: number;
  z: number;
  phase: number;
  speed: number;
  size: number;
}

interface Projected {
  id: string;
  sx: number;
  sy: number;
  depth: number;
  r: number;
}

/** Stable 0..1 from a string.
 *
 * Placement is hashed from the node id rather than taken from array order, so a
 * node appearing mid-list does not shove every other point somewhere new. The
 * map has to look like it is growing, not reshuffling.
 */
function hash01(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967296;
}

function place(node: FieldNode, born: number): Placed {
  const u = hash01(node.id);
  const v = hash01(node.id + ":v");
  const w = hash01(node.id + ":w");
  const theta = u * Math.PI * 2;
  const phi = Math.acos(2 * v - 1);
  const r = SHELL * (0.44 + 0.56 * w);
  return {
    node,
    x: r * Math.sin(phi) * Math.cos(theta),
    y: r * Math.sin(phi) * Math.sin(theta) * 0.72,
    z: r * Math.cos(phi),
    phase: u * Math.PI * 2,
    born,
  };
}

function makeDust(): Dust[] {
  const out: Dust[] = [];
  for (let i = 0; i < DUST_COUNT; i += 1) {
    const u = hash01("dust:" + i);
    const v = hash01("dust:" + i + ":v");
    const w = hash01("dust:" + i + ":w");
    const theta = u * Math.PI * 2;
    const phi = Math.acos(2 * v - 1);
    const r = SHELL * (0.2 + 1.5 * w);
    out.push({
      x: r * Math.sin(phi) * Math.cos(theta),
      y: r * Math.sin(phi) * Math.sin(theta) * 0.8,
      z: r * Math.cos(phi),
      phase: u * Math.PI * 2,
      speed: 0.18 + v * 0.5,
      size: 0.6 + w * 1.3,
    });
  }
  return out;
}

export function StrandField({
  nodes,
  links,
  kindColor,
  selectedId,
  onSelect,
  sampleEnergy,
  reduced,
  height,
  handleRef,
}: StrandFieldProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Everything the frame loop reads lives in a ref, so panning, zooming and new
  // data never restart the animation or force a React render mid-motion.
  const placedRef = useRef<Map<string, Placed>>(new Map());
  const linksRef = useRef<FieldLink[]>(links);
  const dustRef = useRef<Dust[]>(makeDust());
  const viewRef = useRef({ panX: 0, panY: 0, zoom: 1 });
  const energyRef = useRef(0);
  const projectedRef = useRef<Projected[]>([]);
  const selectedRef = useRef<string | null>(selectedId ?? null);
  const sampleRef = useRef(sampleEnergy);
  const colorRef = useRef(kindColor);
  const sizeRef = useRef({ w: 0, h: 0, dpr: 1 });
  // A virtual clock rather than wall time. Hovering eases it towards a crawl so
  // a point can actually be clicked; scaling wall time directly would jump the
  // rotation by however far the clock had already run.
  const flowRef = useRef(0);
  const flowSpeedRef = useRef(1);
  const lastTsRef = useRef(0);
  const hoverRef = useRef(false);

  sampleRef.current = sampleEnergy;
  colorRef.current = kindColor;
  selectedRef.current = selectedId ?? null;
  linksRef.current = links;

  // Reconcile placement with the current node list, keeping the birth time of
  // nodes we already had so the arrival flare fires exactly once per node.
  useEffect(() => {
    const now = performance.now();
    const next = new Map<string, Placed>();
    for (const node of nodes) {
      const existing = placedRef.current.get(node.id);
      next.set(node.id, existing ? { ...existing, node } : place(node, now));
    }
    placedRef.current = next;
  }, [nodes]);

  const draw = useCallback((timeMs: number) => {
    const canvas = canvasRef.current;
    const ctx = canvas ? canvas.getContext("2d") : null;
    if (!canvas || !ctx) return;

    const { w, h, dpr } = sizeRef.current;
    if (w === 0 || h === 0) return;

    // Advance the virtual clock. dt is clamped so a backgrounded tab does not
    // resume with one enormous jump.
    const dt = lastTsRef.current === 0 ? 0 : Math.min(0.05, (timeMs - lastTsRef.current) / 1000);
    lastTsRef.current = timeMs;
    const speedTarget = hoverRef.current ? 0.12 : 1;
    flowSpeedRef.current += (speedTarget - flowSpeedRef.current) * 0.08;
    if (!reduced) flowRef.current += dt * flowSpeedRef.current;
    const t = reduced ? 0 : flowRef.current;

    // Ease towards the requested energy so a burst of speech does not snap.
    const requested = sampleRef.current ? sampleRef.current(t) : 0;
    const target = Math.max(0, Math.min(1, requested));
    energyRef.current += (target - energyRef.current) * (reduced ? 1 : 0.09);
    const energy = energyRef.current;

    const view = viewRef.current;
    const cx = w / 2 + view.panX;
    const cy = h / 2 + view.panY;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // The field EXPANDS while Nyx speaks; it never turns.
    //
    // A fixed viewing angle is applied once so the cloud still reads as a
    // volume, but it does not advance with time - an earlier version rotated
    // about Y and X every frame, which made a moving target of every point and
    // was explicitly not wanted. Motion now comes only from `expansion`, which
    // pushes each point radially outward from the centre and lets it settle
    // back as speech ends.
    const VIEW_Y = 0.42;
    const VIEW_X = 0.16;
    const cosY = Math.cos(VIEW_Y);
    const sinY = Math.sin(VIEW_Y);
    const cosX = Math.cos(VIEW_X);
    const sinX = Math.sin(VIEW_X);
    const zoom = view.zoom;

    // 1.0 at rest. Speech drives it outward; the small idle term is a breath so
    // the field is not perfectly frozen when nothing is happening.
    const expansion = reduced
      ? 1
      : 1 + energy * 0.55 + Math.sin(t * 1.6) * 0.02 * (1 + energy * 3);

    const project = (px: number, py: number, pz: number) => {
      // Scale the point's own vector: direction is untouched, only distance
      // from the centre changes. This is what makes it expand rather than spin.
      const ex = px * expansion;
      const ey = py * expansion;
      const ez = pz * expansion;
      const x1 = ex * cosY - ez * sinY;
      const z1 = ex * sinY + ez * cosY;
      const y1 = ey * cosX - z1 * sinX;
      const z2 = ey * sinX + z1 * cosX;
      const depth = FOCAL / (FOCAL + z2 + SHELL * 1.2);
      return { sx: cx + x1 * depth * zoom, sy: cy + y1 * depth * zoom, depth };
    };

    // --- ambient dust: the sense of a volume the nodes hang inside -----------
    for (const d of dustRef.current) {
      const bob = reduced ? 0 : Math.sin(t * d.speed + d.phase) * 26;
      const sway = reduced ? 0 : Math.cos(t * d.speed * 0.7 + d.phase) * 18;
      const p = project(d.x + sway, d.y + bob, d.z);
      const alpha = Math.max(0, (p.depth - 0.4) * 0.85) * (0.6 + energy * 0.4);
      if (alpha <= 0.004) continue;
      ctx.beginPath();
      ctx.arc(p.sx, p.sy, Math.max(0.5, d.size * 1.25 * p.depth * zoom), 0, Math.PI * 2);
      ctx.fillStyle = "rgba(181,171,252," + alpha.toFixed(3) + ")";
      ctx.fill();
    }

    // --- nodes ---------------------------------------------------------------
    const screen = new Map<string, Projected & { placed: Placed }>();
    placedRef.current.forEach((item) => {
      const bob = reduced ? 0 : Math.sin(t * 0.55 + item.phase) * (7 + energy * 16);
      const sway = reduced ? 0 : Math.cos(t * 0.4 + item.phase) * (5 + energy * 10);
      const p = project(item.x + sway, item.y + bob, item.z);
      screen.set(item.node.id, {
        id: item.node.id,
        sx: p.sx,
        sy: p.sy,
        depth: p.depth,
        r: Math.max(1.6, 4.4 * p.depth * zoom),
        placed: item,
      });
    });

    // Strands first, so nodes sit on top of their own connections.
    ctx.lineCap = "round";
    for (const link of linksRef.current) {
      const a = screen.get(link.source);
      const b = screen.get(link.target);
      if (!a || !b) continue;
      const depth = (a.depth + b.depth) / 2;
      const alpha = Math.min(0.5, (0.08 + link.weight * 0.06) * depth * (0.7 + energy * 0.8));
      ctx.beginPath();
      ctx.moveTo(a.sx, a.sy);
      ctx.lineTo(b.sx, b.sy);
      ctx.strokeStyle = "rgba(145,132,217," + alpha.toFixed(3) + ")";
      ctx.lineWidth = Math.max(0.5, Math.min(2.4, link.weight * 0.5) * depth * zoom);
      ctx.stroke();
    }

    // --- core ----------------------------------------------------------------
    const corePulse = 1 + energy * 0.35 + (reduced ? 0 : Math.sin(t * 2.2) * 0.04);
    const coreR = 26 * zoom * corePulse;
    const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR * 3.4);
    glow.addColorStop(0, "rgba(181,171,252," + (0.3 + energy * 0.42).toFixed(3) + ")");
    glow.addColorStop(1, "rgba(181,171,252,0)");
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(cx, cy, coreR * 3.4, 0, Math.PI * 2);
    ctx.fill();
    for (const ring of [1, 1.7, 2.5]) {
      ctx.beginPath();
      ctx.arc(cx, cy, coreR * ring, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(145,132,217," + (0.3 / ring + energy * 0.14).toFixed(3) + ")";
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // Far points first so near ones overlap them, which is the depth cue.
    const ordered = Array.from(screen.values()).sort((a, b) => a.depth - b.depth);
    projectedRef.current = ordered.map((p) => ({
      id: p.id, sx: p.sx, sy: p.sy, depth: p.depth, r: p.r,
    }));

    ctx.textAlign = "center";
    for (const p of ordered) {
      const color = colorRef.current(p.placed.node.kind);
      const alpha = Math.max(0.16, Math.min(1, (p.depth - 0.35) * 1.9));
      const selected = selectedRef.current === p.id;

      // Arrival flare: a ring that expands once, so a node created by the
      // conversation you just had is visibly new rather than silently present.
      const age = (timeMs - p.placed.born) / 1000;
      if (age < 1.8 && !reduced) {
        const k = age / 1.8;
        ctx.beginPath();
        ctx.arc(p.sx, p.sy, p.r + k * 34, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.globalAlpha = (1 - k) * 0.6;
        ctx.lineWidth = 1.4;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      ctx.globalAlpha = alpha;
      ctx.beginPath();
      ctx.arc(p.sx, p.sy, p.r, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(p.sx, p.sy, p.r * (selected ? 3.2 : 2.1), 0, Math.PI * 2);
      ctx.strokeStyle = color;
      ctx.globalAlpha = alpha * (selected ? 0.9 : 0.28);
      ctx.lineWidth = selected ? 1.6 : 1;
      ctx.stroke();

      // Labels only where they are legible; a wall of overlapping 6px text is
      // less readable than none at all.
      if (p.depth * zoom > 0.62) {
        ctx.globalAlpha = Math.min(0.95, alpha);
        ctx.fillStyle = "#cfd3e5";
        ctx.font = Math.round(Math.min(13, 9 + p.depth * zoom * 3)) + "px Inter, system-ui, sans-serif";
        const raw = p.placed.node.label;
        ctx.fillText(raw.length > 22 ? raw.slice(0, 21) + "…" : raw, p.sx, p.sy - p.r - 7);
      }
      ctx.globalAlpha = 1;
    }
  }, [reduced]);

  // Size the backing store to the device pixel ratio, or the whole thing is soft.
  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      sizeRef.current = { w: rect.width, h: rect.height, dpr };
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      canvas.style.width = rect.width + "px";
      canvas.style.height = rect.height + "px";
      draw(performance.now());
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [draw]);

  // The loop. Under prefers-reduced-motion there is no loop at all — the field is
  // drawn once and redrawn only when the data or the view changes.
  useEffect(() => {
    if (reduced) {
      draw(performance.now());
      return;
    }
    let raf = 0;
    const tick = (now: number) => {
      draw(now);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [draw, reduced]);

  useEffect(() => {
    if (reduced) draw(performance.now());
  }, [draw, reduced, nodes, links, selectedId]);

  // --- pan, zoom, select ----------------------------------------------------
  const dragRef = useRef<{ x: number; y: number; moved: number } | null>(null);

  const redrawIfStill = useCallback(() => {
    if (reduced) draw(performance.now());
  }, [draw, reduced]);

  const applyZoom = useCallback((factor: number) => {
    const view = viewRef.current;
    view.zoom = Math.max(0.35, Math.min(4, view.zoom * factor));
    redrawIfStill();
  }, [redrawIfStill]);

  useEffect(() => {
    if (!handleRef) return;
    handleRef.current = {
      resetView: () => {
        viewRef.current = { panX: 0, panY: 0, zoom: 1 };
        redrawIfStill();
      },
      zoomBy: applyZoom,
    };
    return () => { handleRef.current = null; };
  }, [handleRef, applyZoom, redrawIfStill]);

  // Wheel zooms only with ctrl/cmd held. Swallowing a plain wheel over a canvas
  // this tall would trap the page scroll: the field fills most of the panel, and
  // a user reaching the widgets below it would find the page frozen. Ctrl+wheel
  // is the same bargain an embedded map makes, and the +/- buttons cover the rest.
  //
  // Attached by hand rather than via onWheel because React registers that
  // listener passive, and a passive listener cannot preventDefault.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      applyZoom(event.deltaY < 0 ? 1.12 : 1 / 1.12);
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [applyZoom]);

  return (
    <div
      ref={wrapRef}
      style={{
        position: "relative",
        height,
        minHeight: 260,
        borderRadius: "var(--radius)",
        overflow: "hidden",
        background: "radial-gradient(circle at 50% 45%, #1b1f36 0%, #141623 55%, #101220 100%)",
        boxShadow: "inset 0 0 0 1px var(--color-divider)",
      }}
    >
      <canvas
        ref={canvasRef}
        aria-label="Strand field. Drag to pan, ctrl and scroll to zoom, click a point for its detail."
        style={{ display: "block", touchAction: "none", cursor: "grab" }}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          dragRef.current = { x: e.clientX, y: e.clientY, moved: 0 };
        }}
        onPointerMove={(e) => {
          const drag = dragRef.current;
          if (!drag) return;
          const dx = e.clientX - drag.x;
          const dy = e.clientY - drag.y;
          drag.x = e.clientX;
          drag.y = e.clientY;
          drag.moved += Math.abs(dx) + Math.abs(dy);
          viewRef.current.panX += dx;
          viewRef.current.panY += dy;
          redrawIfStill();
        }}
        onPointerUp={(e) => {
          const drag = dragRef.current;
          dragRef.current = null;
          if (!drag || drag.moved > 5) return;
          // A click, not a drag: pick the nearest projected point.
          const rect = e.currentTarget.getBoundingClientRect();
          const px = e.clientX - rect.left;
          const py = e.clientY - rect.top;
          let best: Projected | null = null;
          let bestDist = Infinity;
          for (const p of projectedRef.current) {
            const d = Math.hypot(p.sx - px, p.sy - py);
            if (d < Math.max(20, p.r * 4) && d < bestDist) {
              best = p;
              bestDist = d;
            }
          }
          const found = best ? placedRef.current.get(best.id) : undefined;
          onSelect(found ? found.node : null);
        }}
        onPointerEnter={() => { hoverRef.current = true; }}
        onPointerLeave={() => { hoverRef.current = false; dragRef.current = null; }}
        onPointerCancel={() => { dragRef.current = null; }}
      />
    </div>
  );
}
