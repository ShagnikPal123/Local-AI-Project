/** The custom background behind the whole app: a picture, GIF or video, with motion (Request G8).
 *
 * Content layer only — controls stay solid and monochrome above it. A dimming
 * scrim keeps text readable (the owner sets how much), and Reduced Motion turns
 * every preset into a still and pauses videos.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { onWorkspaceEvent } from "../state/workspaceEvents";
import { useReducedMotion } from "../useReducedMotion";

export interface BackgroundItem {
  id: string;
  url: string;
  name: string;
  kind: "image" | "gif" | "video";
  animation: "still" | "drift" | "breathe" | "parallax" | "embers" | "time";
  dim: number;
  blur: number;
  prompt?: string;
  source?: string;
}

export function useBackgrounds() {
  const [data, setData] = useState<{ active: BackgroundItem | null; items: BackgroundItem[]; animations: string[] } | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => void api.get<typeof data>("/api/backgrounds").then((r) => { if (alive && r.ok) setData(r.data); });
    load();
    const off = onWorkspaceEvent((event) => { if (event.type === "background.changed") load(); });
    const onLocal = () => load();
    window.addEventListener("nyx:background", onLocal);
    return () => { alive = false; off(); window.removeEventListener("nyx:background", onLocal); };
  }, []);
  return data;
}

function Embers() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let frame = 0;
    const dots = Array.from({ length: 70 }, () => ({ x: Math.random(), y: Math.random(), r: 0.6 + Math.random() * 1.8, v: 0.0004 + Math.random() * 0.0012, w: Math.random() * Math.PI * 2 }));
    const draw = () => {
      frame = requestAnimationFrame(draw);
      if (document.hidden) return;
      const w = (canvas.width = canvas.clientWidth), h = (canvas.height = canvas.clientHeight);
      ctx.clearRect(0, 0, w, h);
      for (const d of dots) {
        d.y -= d.v; d.w += 0.02;
        if (d.y < -0.02) { d.y = 1.02; d.x = Math.random(); }
        const x = (d.x + Math.sin(d.w) * 0.004) * w, y = d.y * h;
        const g = ctx.createRadialGradient(x, y, 0, x, y, d.r * 5);
        g.addColorStop(0, "rgba(255,190,110,0.9)"); g.addColorStop(1, "rgba(255,120,40,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, d.r * 5, 0, Math.PI * 2); ctx.fill();
      }
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, []);
  return <canvas ref={ref} className="bg-layer__overlay" aria-hidden="true" />;
}

function TimeRings() {
  const ticks = Array.from({ length: 60 }, (_, i) => i);
  return (
    <svg className="bg-layer__overlay bg-layer__time" viewBox="-500 -500 1000 1000" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <g className="bg-time__ring bg-time__ring--a">
        <circle r="420" fill="none" stroke="rgba(214,190,90,0.28)" strokeWidth="2" />
        {ticks.map((i) => (
          <line key={i} x1="0" y1={-420} x2="0" y2={i % 5 === 0 ? -392 : -406} stroke="rgba(230,205,110,0.45)" strokeWidth={i % 5 === 0 ? 3 : 1.4}
            transform={`rotate(${i * 6})`} />
        ))}
      </g>
      <g className="bg-time__ring bg-time__ring--b">
        <circle r="300" fill="none" stroke="rgba(120,220,170,0.22)" strokeWidth="1.5" strokeDasharray="4 14" />
        {Array.from({ length: 12 }, (_, i) => (
          <circle key={i} r="5" cx="0" cy="-300" fill="rgba(140,235,180,0.5)" transform={`rotate(${i * 30})`} />
        ))}
      </g>
      <g className="bg-time__ring bg-time__ring--c">
        <circle r="190" fill="none" stroke="rgba(214,190,90,0.2)" strokeWidth="1" />
        <line x1="0" y1="0" x2="0" y2="-170" stroke="rgba(230,205,110,0.5)" strokeWidth="2.5" strokeLinecap="round" />
      </g>
    </svg>
  );
}

export function BackgroundLayer() {
  const data = useBackgrounds();
  const reduced = useReducedMotion();
  const active = data?.active ?? null;
  const [pointer, setPointer] = useState({ x: 0, y: 0 });

  useEffect(() => {
    document.documentElement.classList.toggle("has-custom-bg", Boolean(active));
    return () => document.documentElement.classList.remove("has-custom-bg");
  }, [active]);

  useEffect(() => {
    if (!active || active.animation !== "parallax" || reduced) return;
    const onMove = (e: PointerEvent) => setPointer({ x: e.clientX / window.innerWidth - 0.5, y: e.clientY / window.innerHeight - 0.5 });
    window.addEventListener("pointermove", onMove);
    return () => window.removeEventListener("pointermove", onMove);
  }, [active, reduced]);

  if (!active) return null;
  const motion = reduced ? "still" : active.animation;
  const style: React.CSSProperties = {
    filter: active.blur ? `blur(${active.blur}px)` : undefined,
    transform: motion === "parallax" ? `scale(1.08) translate(${pointer.x * -24}px, ${pointer.y * -16}px)` : undefined,
  };

  return (
    <div className="bg-layer" aria-hidden="true">
      {active.kind === "video" ? (
        <video key={active.url} className={`bg-layer__media is-${motion}`} src={active.url} style={style}
          autoPlay={!reduced} loop muted playsInline />
      ) : (
        <img key={active.url} className={`bg-layer__media is-${motion}`} src={active.url} alt="" style={style} />
      )}
      {motion === "embers" && <Embers />}
      {motion === "time" && <TimeRings />}
      <div className="bg-layer__scrim" style={{ background: `rgba(0,0,0,${active.dim})` }} />
    </div>
  );
}
