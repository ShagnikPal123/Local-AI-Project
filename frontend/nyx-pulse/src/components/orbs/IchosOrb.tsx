/** IchosOrb — the dotted thought-orbs from `thinking-orbs`, painted in Ichos's colours.
 *
 * The library's own <ThinkingOrb> is strictly grey. We take its geometry engine
 * (`thinking-orbs/engine`: per-frame, z-sorted dots and lines) and paint it
 * ourselves, so depth runs from a dim far tint to the bright accent and the orb
 * belongs to the theme instead of sitting on it. Colours are read from the CSS
 * tokens, and re-read when the root's style or theme changes.
 *
 * Two tuned presets ship (20 and 64 px). Any other size draws the nearer preset
 * scaled, so a 14 px row icon and a 160 px hero are both crisp.
 *
 * Like the original: one shared clock keeps every orb in phase, it stops while
 * offscreen or the tab is hidden, and reduced motion gets one still frame.
 */

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { MODE_FRAMES, resolvePreset } from "thinking-orbs/engine";
import { useReducedMotion } from "../../useReducedMotion";
import { ORB_MEANING, type OrbState } from "./orbState";
import "./orbs.css";

export type OrbTone = "accent" | "ok" | "danger" | "mono";

interface Props {
  state?: OrbState;
  size?: number;
  tone?: OrbTone;
  speed?: number;
  paused?: boolean;
  /** Soft halo behind the orb; on by default from 48 px. */
  glow?: boolean;
  label?: string;
  /** Decorative: hidden from screen readers (the text beside it says it). */
  decorative?: boolean;
  className?: string;
  style?: CSSProperties;
}

const TONE_VARS: Record<OrbTone, [string, string]> = {
  accent: ["--color-accent", "--color-accent-2"],
  ok: ["--color-ok", "--color-ok"],
  danger: ["--color-danger", "--color-danger"],
  mono: ["--color-neutral-600", "--color-neutral-400"],
};

type RGB = [number, number, number];

function parseColor(value: string, fallback: RGB): RGB {
  const v = value.trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(v);
  if (hex) {
    const h = hex[1].length === 3 ? hex[1].split("").map((c) => c + c).join("") : hex[1];
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  const rgb = /rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)/i.exec(v);
  return rgb ? [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])] : fallback;
}

const mix = (a: RGB, b: RGB, t: number): RGB => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

interface Palette { far: RGB; mid: RGB; near: RGB }

function readPalette(el: Element, tone: OrbTone): Palette {
  const css = getComputedStyle(el);
  const [baseVar, hiVar] = TONE_VARS[tone];
  const base = parseColor(css.getPropertyValue(baseVar), [165, 148, 255]);
  const hi = parseColor(css.getPropertyValue(hiVar), base);
  const bg = parseColor(css.getPropertyValue("--color-bg"), [18, 19, 25]);
  const dark = 0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2] < 128;
  // Far dots sink toward the page; the nearest lift toward white on dark pages
  // (toward ink on light ones), which is what reads as depth.
  const lift: RGB = dark ? [255, 255, 255] : [20, 18, 40];
  return { far: mix(base, bg, 0.62), mid: base, near: mix(hi, lift, 0.35) };
}

function colorAt(p: Palette, depth: number, alpha: number): string {
  const d = Math.min(1, Math.max(0, depth));
  const c = d < 0.6 ? mix(p.far, p.mid, d / 0.6) : mix(p.mid, p.near, (d - 0.6) / 0.4);
  return `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${alpha})`;
}

/** Re-render when the root theme changes (Appearance can recolour the accent live). */
function useThemeEpoch(): number {
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    const bump = () => setEpoch((n) => n + 1);
    const mo = new MutationObserver(bump);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["style", "class", "data-theme"] });
    mo.observe(document.body, { attributes: true, attributeFilter: ["style", "class", "data-theme"] });
    return () => mo.disconnect();
  }, []);
  return epoch;
}

export function IchosOrb({
  state = "breathing",
  size = 20,
  tone = "accent",
  speed = 1,
  paused = false,
  glow,
  label,
  decorative,
  className,
  style,
}: Props) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const reduced = useReducedMotion();
  const epoch = useThemeEpoch();

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const preset = size >= 40 ? 64 : 20;
    const scale = size / preset;
    const { mode, speed: baseSpeed, opts } = resolvePreset(state, preset);
    const frameFn = MODE_FRAMES[mode];
    const palette = readPalette(canvas, tone);
    const effSpeed = baseSpeed * speed;

    const draw = (t: number) => {
      ctx.setTransform(dpr * scale, 0, 0, dpr * scale, 0, 0);
      ctx.clearRect(0, 0, preset, preset);
      const { dots, lines } = frameFn(preset, t, opts);
      if (lines) {
        ctx.lineCap = "round";
        for (const l of lines) {
          ctx.strokeStyle = colorAt(palette, 1 - l.white, l.a ?? 1);
          ctx.lineWidth = l.w;
          ctx.beginPath();
          ctx.moveTo(l.x1, l.y1);
          ctx.lineTo(l.x2, l.y2);
          ctx.stroke();
        }
      }
      for (const d of dots) {
        ctx.fillStyle = colorAt(palette, 1 - d.white, d.a ?? 1);
        ctx.beginPath();
        ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    if (reduced) {
      draw(0.6);
      return;
    }

    let raf = 0;
    let running = false;
    const loop = () => {
      draw((performance.now() / 1000) * effSpeed);
      if (running) raf = requestAnimationFrame(loop);
    };
    const start = () => {
      if (running || paused) return;
      running = true;
      raf = requestAnimationFrame(loop);
    };
    const stop = () => {
      running = false;
      cancelAnimationFrame(raf);
    };

    draw((performance.now() / 1000) * effSpeed);

    let visible = true;
    const io = typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver(([entry]) => {
          visible = entry.isIntersecting;
          if (visible && document.visibilityState !== "hidden") start();
          else stop();
        })
      : null;
    io?.observe(canvas);
    const onVis = () => {
      if (document.visibilityState === "hidden") stop();
      else if (visible) start();
    };
    document.addEventListener("visibilitychange", onVis);
    if (!io) start();

    return () => {
      stop();
      io?.disconnect();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [state, size, tone, speed, paused, reduced, epoch]);

  const withGlow = glow ?? size >= 48;
  const a11y = decorative
    ? { "aria-hidden": true as const }
    : { role: "img" as const, "aria-label": label ?? `Ichos is ${ORB_MEANING[state]}`, title: label ?? `Ichos is ${ORB_MEANING[state]}` };

  return (
    <span
      className={["ichos-orb", className].filter(Boolean).join(" ")}
      data-state={state}
      data-tone={tone}
      data-glow={withGlow ? "true" : undefined}
      style={{ ["--orb-size" as string]: `${size}px`, ...style }}
      {...a11y}
    >
      <canvas ref={ref} className="ichos-orb__canvas" />
    </span>
  );
}
