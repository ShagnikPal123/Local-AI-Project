/** The "Particles" style: a slow field of points behind the app, in the pop palette. Cheap on purpose — 70 points,
 * 30 fps, paused while the window is hidden, absent under reduced motion or when the style is off. */

import { useEffect, useRef, useState } from "react";
import { currentMix, onMix } from "./styleMix";

const COLORS = ["165,148,255", "95,212,244", "243,155,214", "111,227,180"];

export function ParticleField() {
  const [on, setOn] = useState(() => currentMix().includes("particles"));
  useEffect(() => onMix((mix) => setOn(mix.includes("particles"))), []);
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!on || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const size = () => { canvas.width = innerWidth * dpr; canvas.height = innerHeight * dpr; };
    size();
    window.addEventListener("resize", size);
    const points = Array.from({ length: 70 }, (_, i) => ({
      x: Math.random(), y: Math.random(), r: 0.6 + Math.random() * 1.6,
      vx: (Math.random() - 0.5) * 0.00012, vy: (Math.random() - 0.5) * 0.00012, c: COLORS[i % COLORS.length],
    }));
    let frame = 0;
    let last = 0;
    const draw = (t: number) => {
      frame = requestAnimationFrame(draw);
      if (document.hidden || t - last < 33) return;
      last = t;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const p of points) {
        p.x = (p.x + p.vx + 1) % 1;
        p.y = (p.y + p.vy + 1) % 1;
        ctx.beginPath();
        ctx.fillStyle = `rgba(${p.c},0.55)`;
        ctx.arc(p.x * canvas.width, p.y * canvas.height, p.r * dpr, 0, Math.PI * 2);
        ctx.fill();
      }
    };
    frame = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("resize", size); };
  }, [on]);

  if (!on) return null;
  return <canvas ref={ref} className="particle-field" aria-hidden="true" />;
}

/** Split-flap numbers: each digit that changed flips (style "splitflap"); otherwise plain text. */
export function FlipNumber({ value }: { value: number | string }) {
  const text = typeof value === "number" ? value.toLocaleString() : value;
  const prev = useRef(text);
  const old = prev.current;
  useEffect(() => { prev.current = text; }, [text]);
  return (
    <span className="flip" aria-label={text}>
      {text.split("").map((ch, i) => (
        <span key={`${i}-${ch}`} aria-hidden="true" className={`flip-digit${old[i] !== ch ? " is-new" : ""}`}>{ch}</span>
      ))}
    </span>
  );
}
