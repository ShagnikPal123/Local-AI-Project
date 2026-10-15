/** Code glyphs that drift behind the chat once the owner has not typed for a while (Drive doc 2, item 2.2).
 *
 * The owner: "if the user is idle for 10 or more seconds it has a field where code glyphs appear and is
 * interactable until the user starts typing". Idle means no key pressed: moving the mouse is how you play with
 * the field, so it must not count as activity. The canvas never takes pointer events itself; the chat's wrapper
 * forwards moves and clicks, so bubbles, links and buttons above it keep working exactly as before.
 * Reduced motion keeps it off, and a hidden window stops the animation loop.
 */

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useReducedMotion } from "../../useReducedMotion";

export const IDLE_MS = 10_000;
const CHARS = "{}[]()<>/=;:+*&|!?#$%01λ→=>".split("");
const COUNT = 64;

export interface IdleGlyphsHandle {
  pointer: (x: number, y: number) => void;
  burst: (x: number, y: number) => void;
}

interface Glyph { x: number; y: number; vx: number; vy: number; ch: string; size: number; alpha: number }

export const IdleGlyphs = forwardRef<IdleGlyphsHandle>(function IdleGlyphs(_props, ref) {
  const reduced = useReducedMotion();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [idle, setIdle] = useState(false);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const glyphs = useRef<Glyph[]>([]);

  // Any key pressed anywhere in the app counts as typing: the field goes at once and the clock starts again.
  useEffect(() => {
    if (reduced) return;
    let timer = window.setTimeout(() => setIdle(true), IDLE_MS);
    const typed = () => {
      setIdle(false);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setIdle(true), IDLE_MS);
    };
    window.addEventListener("keydown", typed, true);
    return () => { window.clearTimeout(timer); window.removeEventListener("keydown", typed, true); };
  }, [reduced]);

  useImperativeHandle(ref, () => ({
    pointer: (x, y) => { pointer.current = { x, y }; },
    burst: (x, y) => {
      for (const g of glyphs.current) {
        const dx = g.x - x, dy = g.y - y, d = Math.hypot(dx, dy) || 1;
        if (d < 160) {
          g.vx += (dx / d) * (160 - d) * 0.06;
          g.vy += (dy / d) * (160 - d) * 0.06;
          g.ch = CHARS[Math.floor(Math.random() * CHARS.length)];
        }
      }
    },
  }), []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!idle || reduced || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const fit = () => {
      const { width, height } = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, width * dpr);
      canvas.height = Math.max(1, height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { width, height };
    };
    let box = fit();
    glyphs.current = Array.from({ length: COUNT }, () => ({
      x: Math.random() * box.width, y: Math.random() * box.height,
      vx: (Math.random() - 0.5) * 0.2, vy: -0.15 - Math.random() * 0.35,
      ch: CHARS[Math.floor(Math.random() * CHARS.length)], size: 11 + Math.random() * 9, alpha: 0.12 + Math.random() * 0.22,
    }));
    const color = getComputedStyle(canvas).getPropertyValue("--color-accent-300").trim() || "#9aa7ff";
    const onResize = () => { box = fit(); };
    window.addEventListener("resize", onResize);
    let frame = 0;
    const step = () => {
      frame = window.requestAnimationFrame(step);
      if (document.hidden) return;
      ctx.clearRect(0, 0, box.width, box.height);
      ctx.fillStyle = color;
      const p = pointer.current;
      for (const g of glyphs.current) {
        if (p) {
          const dx = g.x - p.x, dy = g.y - p.y, d = Math.hypot(dx, dy) || 1;
          if (d < 90) { g.vx += (dx / d) * 0.35; g.vy += (dy / d) * 0.35; }
        }
        g.vx *= 0.94;
        g.vy = g.vy * 0.94 + (-0.25 - g.vy) * 0.02;
        g.x += g.vx;
        g.y += g.vy;
        if (g.y < -20) { g.y = box.height + 10; g.x = Math.random() * box.width; }
        if (g.x < -20) g.x = box.width + 10;
        if (g.x > box.width + 20) g.x = -10;
        ctx.globalAlpha = g.alpha;
        ctx.font = `${g.size}px ui-monospace, Consolas, monospace`;
        ctx.fillText(g.ch, g.x, g.y);
      }
    };
    step();
    return () => { window.cancelAnimationFrame(frame); window.removeEventListener("resize", onResize); };
  }, [idle, reduced]);

  if (reduced) return null;
  return <canvas ref={canvasRef} className={`idle-glyphs ${idle ? "on" : ""}`} aria-hidden="true" />;
});
