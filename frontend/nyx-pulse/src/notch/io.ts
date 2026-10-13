/** Io — the character who lives in the Equalize notch.
 *
 * The owner wanted Coucou's notch with "a different character that more resembles our current way the AI talks".
 * Ichos talks through an equalizer (the voice globe), so Io is a small moon (Io is one of Jupiter's) made of soft
 * lavender glass whose face *is* the voice: two capsule eyes that follow the pointer, which become equalizer bars
 * while Ichos speaks, rings that pulse with the microphone while it listens, and a little moon that orbits it while
 * it thinks or works. Drawn in code on a canvas — no images, no borrowed artwork.
 *
 * One engine draws every size: the big Io in the notch and the mini ones that stand for other agents (tinted with
 * the agent's colour). It pauses itself when its canvas is hidden.
 */

export type IoState =
  | "idle" | "working" | "thinking" | "searching" | "listening" | "speaking"
  | "approval" | "question" | "error" | "finished" | "sleeping" | "dizzy";
export type IoEmote = "love" | "surprised" | "proud" | "wink" | "annoyed" | "happy" | null;

/** State colour, how strongly it tints the body, and the badge shown on the shoulder. */
export const IO_STATES: Record<IoState, { color: string; tint: number; badge: "" | "dots" | "!" | "?" | "dot" }> = {
  idle: { color: "#E6E9EE", tint: 0, badge: "" },
  working: { color: "#3B9EFF", tint: 0.55, badge: "dots" },
  thinking: { color: "#8B5CF6", tint: 0.55, badge: "dots" },
  searching: { color: "#6366F1", tint: 0.55, badge: "dots" },
  listening: { color: "#22D3EE", tint: 0.45, badge: "" },
  speaking: { color: "#A594FF", tint: 0.4, badge: "" },
  approval: { color: "#F5A524", tint: 0.6, badge: "!" },
  question: { color: "#22D3EE", tint: 0.55, badge: "?" },
  error: { color: "#F4505E", tint: 0.6, badge: "dot" },
  finished: { color: "#34D399", tint: 0.3, badge: "dot" },
  sleeping: { color: "#94A3B8", tint: 0.25, badge: "" },
  dizzy: { color: "#F472B6", tint: 0.5, badge: "" },
};

export interface IoOptions {
  /** Body tint for a mini agent (its colour); empty for Io itself. */
  tint?: string;
  /** Draw shoulder badges and particles (off for the tiniest minis). */
  details?: boolean;
  /** A picture the owner dropped in as the avatar: drawn inside the body instead of the glass. */
  image?: HTMLImageElement | null;
  /** 0..1 levels of Ichos's own voice, for the equalizer eyes. */
  levels?: () => number[];
  /** 0..1 microphone level, for the listening rings. */
  mic?: () => number;
}

type Particle = { x: number; y: number; vx: number; vy: number; life: number; kind: "spark" | "heart" | "z" | "star" };

const TAU = Math.PI * 2;
const ease = (from: number, to: number, k: number) => from + (to - from) * k;

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h.slice(0, 6), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const rgba = (hex: string, a: number) => {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r},${g},${b},${a})`;
};

/** A superellipse ("squircle") path — Io's body. Exponent 3.4: rounder than a box, flatter than a pebble. */
function squircle(ctx: CanvasRenderingContext2D, cx: number, cy: number, rx: number, ry: number, n = 3.4) {
  ctx.beginPath();
  const steps = 72;
  for (let i = 0; i <= steps; i++) {
    const t = (i / steps) * TAU;
    const c = Math.cos(t), s = Math.sin(t);
    const x = cx + rx * Math.sign(c) * Math.pow(Math.abs(c), 2 / n);
    const y = cy + ry * Math.sign(s) * Math.pow(Math.abs(s), 2 / n);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
}

export class Io {
  private ctx: CanvasRenderingContext2D;
  private raf = 0;
  private running = false;
  private state: IoState = "idle";
  private emote: IoEmote = null;
  private emoteUntil = 0;
  private stateSince = performance.now();
  private look = { x: 0, y: 0, tx: 0, ty: 0 };
  private blink = 0;
  private nextBlink = performance.now() + 2500;
  private squash = 0;
  private roll = 0;
  private particles: Particle[] = [];
  private eqBars = [0, 0, 0, 0, 0, 0];
  private observer: IntersectionObserver | null = null;
  private visible = true;
  opts: IoOptions;

  constructor(private canvas: HTMLCanvasElement, private size: number, opts: IoOptions = {}) {
    this.ctx = canvas.getContext("2d")!;
    this.opts = { details: true, ...opts };
    this.resize(size);
    if (typeof IntersectionObserver !== "undefined") {
      this.observer = new IntersectionObserver((entries) => {
        this.visible = entries.some((e) => e.isIntersecting);
        if (this.visible && this.running && !this.raf) this.loop();
      });
      this.observer.observe(canvas);
    }
  }

  resize(size: number) {
    this.size = size;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    this.canvas.width = Math.round(size * dpr);
    this.canvas.height = Math.round(size * dpr);
    this.canvas.style.width = `${size}px`;
    this.canvas.style.height = `${size}px`;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  setState(state: IoState) {
    if (state === this.state) return;
    this.state = state;
    this.stateSince = performance.now();
    if (state === "finished") {
      this.roll = 1;
      this.burst("spark", 10);
    }
    if (state === "error") this.squash = 0.9;
    if (state === "dizzy") this.roll = 2;
  }

  setEmote(emote: IoEmote, ms = 1600) {
    this.emote = emote;
    this.emoteUntil = performance.now() + ms;
    if (emote === "love") this.burst("heart", 5);
    if (emote === "proud") this.burst("star", 6);
    if (emote === "surprised" || emote === "annoyed") this.squash = 1;
  }

  /** Where the pointer is, relative to Io's centre, in CSS pixels. Io looks there. */
  lookAt(dx: number, dy: number) {
    this.look.tx = Math.tanh(dx / 260);
    this.look.ty = Math.tanh(dy / 200);
  }

  poke() {
    this.squash = 1;
    this.blink = 1;
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.loop();
  }

  stop() {
    this.running = false;
    cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  destroy() {
    this.stop();
    this.observer?.disconnect();
  }

  private burst(kind: Particle["kind"], count: number) {
    if (!this.opts.details) return;
    for (let i = 0; i < count; i++) {
      const a = Math.random() * TAU;
      this.particles.push({ x: 0, y: -0.2, vx: Math.cos(a) * (0.4 + Math.random() * 0.6), vy: -0.6 - Math.random() * 0.8,
        life: 1, kind });
    }
  }

  private loop = () => {
    this.raf = 0;
    if (!this.running || !this.visible) return;
    this.draw(performance.now());
    this.raf = requestAnimationFrame(this.loop);
  };

  /** Draw one frame. Public so tests and a paused canvas can render a still. */
  draw(now: number) {
    const { ctx, size } = this;
    const R = size * 0.3;
    const cx = size / 2, cy = size / 2 + R * 0.06;
    const st = IO_STATES[this.state];
    const t = now / 1000;
    if (this.emote && now > this.emoteUntil) this.emote = null;

    // Motion: breathing, the approval hop, the error shake, squash and roll decay.
    this.look.x = ease(this.look.x, this.state === "thinking" ? 0.55 : this.state === "searching" ? Math.sin(t * 2.4) * 0.8 : this.look.tx, 0.12);
    this.look.y = ease(this.look.y, this.state === "thinking" ? -0.5 : this.look.ty, 0.12);
    this.squash = Math.max(0, this.squash - 0.06);
    this.roll = Math.max(0, this.roll - 0.022);
    const breathe = Math.sin(t * (this.state === "sleeping" ? 1.2 : 2.1)) * (this.state === "sleeping" ? 0.035 : 0.018);
    const hop = this.state === "approval" ? Math.abs(Math.sin(t * 5)) * R * 0.12 : 0;
    const since = (now - this.stateSince) / 1000;
    const shake = this.state === "error" && since < 0.5 ? Math.sin(since * 60) * R * 0.08 * (1 - since * 2) : 0;
    const sq = Math.sin(this.squash * Math.PI) * 0.16;
    const sx = 1 + sq + breathe * 0.5, sy = 1 - sq + breathe;
    const tilt = this.state === "question" ? -0.17 : this.emote === "wink" ? 0.1 : Math.sin(t * 0.7) * 0.02;

    // Blink.
    if (now > this.nextBlink) {
      this.blink = 1;
      this.nextBlink = now + 2200 + Math.random() * 3200;
      if (Math.random() < 0.22) setTimeout(() => (this.blink = 1), 180);
    }
    this.blink = Math.max(0, this.blink - 0.14);

    ctx.clearRect(0, 0, size, size);

    // Halo behind the body, in the state colour.
    if (this.opts.details) {
      const glow = this.state === "idle" ? 0.22 : 0.42 + Math.sin(t * 3) * 0.08;
      const halo = ctx.createRadialGradient(cx, cy, R * 0.4, cx, cy, R * 1.6);
      halo.addColorStop(0, rgba(this.emote === "annoyed" ? "#A855F7" : st.color, glow));
      halo.addColorStop(1, rgba(st.color, 0));
      ctx.fillStyle = halo;
      ctx.fillRect(0, 0, size, size);
    }

    // The orbit: a little moon circles Io while it works or thinks.
    const orbiting = ["working", "thinking", "searching"].includes(this.state);
    const orbitAngle = t * (this.state === "thinking" ? 1.6 : 2.6);
    const moonBehind = Math.sin(orbitAngle) < 0;
    const drawMoon = () => {
      if (!orbiting || !this.opts.details) return;
      const mx = cx + Math.cos(orbitAngle) * R * 1.45;
      const my = cy - R * 0.1 + Math.sin(orbitAngle) * R * 0.38;
      ctx.beginPath();
      ctx.ellipse(cx, cy - R * 0.1, R * 1.45, R * 0.38, 0, 0, TAU);
      ctx.strokeStyle = rgba(st.color, 0.22);
      ctx.lineWidth = Math.max(0.6, R * 0.03);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(mx, my, R * (moonBehind ? 0.1 : 0.13), 0, TAU);
      ctx.fillStyle = rgba(st.color, moonBehind ? 0.55 : 1);
      ctx.fill();
    };
    if (moonBehind) drawMoon();

    ctx.save();
    ctx.translate(cx + shake, cy - hop);
    ctx.rotate(tilt);
    ctx.scale(sx, sy);
    const rx = R * 1.18, ry = R * 0.86;

    // Body.
    squircle(ctx, 0, 0, rx, ry);
    if (this.opts.image && this.opts.image.complete && this.opts.image.naturalWidth) {
      ctx.save();
      ctx.clip();
      const img = this.opts.image;
      const scale = Math.max((rx * 2) / img.naturalWidth, (ry * 2) / img.naturalHeight);
      ctx.drawImage(img, -img.naturalWidth * scale / 2, -img.naturalHeight * scale / 2, img.naturalWidth * scale, img.naturalHeight * scale);
      ctx.restore();
    } else {
      const base = this.opts.tint || "";
      const body = ctx.createLinearGradient(rx * 0.6, -ry, -rx * 0.6, ry);
      if (base) {
        body.addColorStop(0, rgba(base, 1));
        body.addColorStop(1, rgba(base, 0.72));
      } else {
        body.addColorStop(0, "#F6F4FF");
        body.addColorStop(0.55, "#DCD6FF");
        body.addColorStop(1, "#B6ACEF");
      }
      ctx.fillStyle = body;
      ctx.fill();
      // Craters: faint, so it reads as a small moon up close and as a soft pebble when tiny.
      if (!base && this.opts.details) {
        ctx.fillStyle = "rgba(120,104,210,0.10)";
        for (const [x, y, r] of [[-0.62, -0.42, 0.13], [0.7, 0.38, 0.1], [-0.35, 0.55, 0.07]]) {
          ctx.beginPath();
          ctx.arc(x * rx, y * ry, r * R, 0, TAU);
          ctx.fill();
        }
      }
    }
    // State tint rising from the bottom, then shading and the glassy highlight.
    if (st.tint > 0) {
      squircle(ctx, 0, 0, rx, ry);
      const tintGrad = ctx.createLinearGradient(0, ry, 0, -ry * 0.25);
      tintGrad.addColorStop(0, rgba(st.color, 0.85 * st.tint));
      tintGrad.addColorStop(1, rgba(st.color, 0));
      ctx.fillStyle = tintGrad;
      ctx.fill();
    }
    squircle(ctx, 0, 0, rx, ry);
    const shade = ctx.createRadialGradient(-rx * 0.1, -ry * 0.2, R * 0.3, 0, 0, rx * 1.1);
    shade.addColorStop(0, "rgba(0,0,0,0)");
    shade.addColorStop(1, "rgba(20,10,60,0.22)");
    ctx.fillStyle = shade;
    ctx.fill();
    const shine = ctx.createRadialGradient(rx * 0.42, -ry * 0.55, 0, rx * 0.42, -ry * 0.55, R * 0.7);
    shine.addColorStop(0, "rgba(255,255,255,0.6)");
    shine.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = shine;
    ctx.fill();

    // Face.
    this.drawEyes(R, t);
    ctx.restore();

    if (!moonBehind) drawMoon();

    // Shoulder badge.
    if (this.opts.details && st.badge) this.drawBadge(cx - rx * 0.92, cy - ry * 0.95 - hop, R, st.color, st.badge, t);

    // Sleeping z's and particles.
    if (this.state === "sleeping" && this.opts.details && Math.random() < 0.02) this.burst("z", 1);
    this.drawParticles(cx, cy, R);
  }

  private drawEyes(R: number, t: number) {
    const { ctx } = this;
    const ink = "#16123A";
    const gap = R * 0.42;
    const ex = this.look.x * R * 0.32, ey = this.look.y * R * 0.22;
    const eyeW = R * 0.25, eyeH = R * 0.34;
    const emote = this.emote;
    const pos = [-gap + ex, gap + ex];

    ctx.fillStyle = ink;
    ctx.strokeStyle = ink;
    ctx.lineCap = "round";

    if (this.state === "speaking") {
      // The equalizer: Ichos's own voice moves the bars.
      const levels = this.opts.levels?.() ?? [];
      for (let i = 0; i < 6; i++) {
        const target = levels.length ? levels[Math.floor((i / 6) * levels.length)] ?? 0 : 0.35 + Math.sin(t * 9 + i) * 0.3;
        this.eqBars[i] = ease(this.eqBars[i], Math.max(0.12, Math.min(1, target)), 0.35);
      }
      pos.forEach((x, side) => {
        for (let b = 0; b < 3; b++) {
          const h = eyeH * (0.35 + this.eqBars[side * 3 + b] * 1.0);
          const bx = x + (b - 1) * eyeW * 0.42;
          ctx.beginPath();
          ctx.roundRect(bx - eyeW * 0.14, ey - h / 2, eyeW * 0.28, h, eyeW * 0.14);
          ctx.fill();
        }
      });
      return;
    }
    if (this.state === "listening") {
      const level = Math.min(1, this.opts.mic?.() ?? (0.3 + Math.sin(t * 4) * 0.2));
      pos.forEach((x) => {
        ctx.lineWidth = R * 0.07;
        ctx.beginPath();
        ctx.arc(x, ey, eyeW * (0.42 + level * 0.32), 0, TAU);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(x, ey, eyeW * 0.16, 0, TAU);
        ctx.fill();
      });
      return;
    }
    if (emote === "love") {
      ctx.fillStyle = "#FF4D6D";
      pos.forEach((x) => heart(ctx, x, ey, eyeW * 1.1));
      return;
    }
    if (emote === "proud") {
      ctx.fillStyle = "#F7B32B";
      pos.forEach((x) => star(ctx, x, ey, eyeW * 0.75));
      return;
    }
    if (this.state === "dizzy") {
      ctx.lineWidth = R * 0.05;
      pos.forEach((x, i) => spiral(ctx, x, ey, eyeW * 0.7, t * (i ? -6 : 6)));
      return;
    }
    if (this.state === "finished" || emote === "happy") {
      ctx.lineWidth = R * 0.08;
      pos.forEach((x) => {
        ctx.beginPath();
        ctx.arc(x, ey + eyeH * 0.15, eyeW * 0.55, Math.PI * 1.15, Math.PI * 1.85);
        ctx.stroke();
      });
      return;
    }
    if (this.state === "sleeping") {
      ctx.lineWidth = R * 0.06;
      pos.forEach((x) => {
        ctx.beginPath();
        ctx.moveTo(x - eyeW * 0.5, ey);
        ctx.lineTo(x + eyeW * 0.5, ey);
        ctx.stroke();
      });
      return;
    }
    if (emote === "annoyed" || this.state === "error") {
      ctx.lineWidth = R * 0.08;
      pos.forEach((x, i) => {
        ctx.beginPath();
        ctx.moveTo(x - eyeW * 0.55, ey + (i ? 1 : -1) * eyeH * 0.12 - eyeH * 0.05);
        ctx.lineTo(x + eyeW * 0.55, ey + (i ? -1 : 1) * eyeH * 0.12 - eyeH * 0.05);
        ctx.stroke();
      });
      return;
    }
    const open = Math.max(0.08, 1 - this.blink * 1.6);
    const big = this.state === "approval" || emote === "surprised" ? 1.25 : 1;
    pos.forEach((x, i) => {
      const h = eyeH * open * big * (emote === "wink" && i === 1 ? 0.12 : 1);
      ctx.beginPath();
      ctx.roundRect(x - (eyeW * big) / 2, ey - h / 2, eyeW * big, h, (eyeW * big) / 2);
      ctx.fill();
      if (open > 0.6 && h > eyeH * 0.5) {
        ctx.fillStyle = "rgba(255,255,255,0.85)";
        ctx.beginPath();
        ctx.arc(x + eyeW * 0.16, ey - h * 0.22, eyeW * 0.13, 0, TAU);
        ctx.fill();
        ctx.fillStyle = ink;
      }
    });
  }

  private drawBadge(x: number, y: number, R: number, color: string, kind: string, t: number) {
    const { ctx } = this;
    const r = R * 0.34;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, TAU);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.lineWidth = R * 0.06;
    ctx.strokeStyle = "#0B0C0E";
    ctx.stroke();
    ctx.fillStyle = "#fff";
    if (kind === "dots") {
      for (let i = 0; i < 3; i++) {
        const lift = Math.max(0, Math.sin(t * 6 - i * 0.8)) * r * 0.25;
        ctx.beginPath();
        ctx.arc(x + (i - 1) * r * 0.48, y - lift, r * 0.16, 0, TAU);
        ctx.fill();
      }
    } else if (kind === "!" || kind === "?") {
      ctx.font = `700 ${r * 1.3}px system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(kind, x, y + r * 0.06);
    }
  }

  private drawParticles(cx: number, cy: number, R: number) {
    const { ctx } = this;
    this.particles = this.particles.filter((p) => p.life > 0);
    for (const p of this.particles) {
      p.x += p.vx * 0.02;
      p.y += p.vy * 0.02;
      p.vy += 0.01;
      p.life -= 0.018;
      const x = cx + p.x * R * 1.6, y = cy + p.y * R * 1.6;
      ctx.globalAlpha = Math.max(0, p.life);
      if (p.kind === "heart") {
        ctx.fillStyle = "#FF4D6D";
        heart(ctx, x, y, R * 0.2);
      } else if (p.kind === "star") {
        ctx.fillStyle = "#F7B32B";
        star(ctx, x, y, R * 0.12);
      } else if (p.kind === "z") {
        ctx.fillStyle = "#C9CDD4";
        ctx.font = `600 ${R * 0.32}px system-ui, sans-serif`;
        ctx.fillText("z", x + R * 0.6, y - R * 0.6);
      } else {
        ctx.fillStyle = "#34D399";
        ctx.beginPath();
        ctx.arc(x, y, R * 0.05, 0, TAU);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }
  }
}

function heart(ctx: CanvasRenderingContext2D, x: number, y: number, s: number) {
  ctx.beginPath();
  ctx.moveTo(x, y + s * 0.35);
  ctx.bezierCurveTo(x - s * 0.6, y - s * 0.1, x - s * 0.3, y - s * 0.55, x, y - s * 0.2);
  ctx.bezierCurveTo(x + s * 0.3, y - s * 0.55, x + s * 0.6, y - s * 0.1, x, y + s * 0.35);
  ctx.fill();
}

function star(ctx: CanvasRenderingContext2D, x: number, y: number, r: number) {
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const a = (i / 10) * TAU - Math.PI / 2;
    const rr = i % 2 ? r * 0.45 : r;
    ctx.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr);
  }
  ctx.closePath();
  ctx.fill();
}

function spiral(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, turn: number) {
  ctx.beginPath();
  for (let i = 0; i < 40; i++) {
    const a = turn + (i / 40) * TAU * 2;
    const rr = (i / 40) * r;
    ctx.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr);
  }
  ctx.stroke();
}
