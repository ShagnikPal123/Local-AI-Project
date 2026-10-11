/** Motion across the app (owner, 2026-10-10: "use these tools implemented into the general design … react-bits, lenis,
 * gsap"; "I would also love more moving parts").
 *
 *  - Lenis (MIT) — smooth, inertial scrolling on each page; any inner area that scrolls on its own keeps native
 *    scrolling, so lists, chats and editors never fight it.
 *  - GSAP — a page settles in when you open a tab, and its cards rise in one after another.
 *  - React Bits–style touches, written here (not copied): a spark burst where you click a primary button, and a
 *    spotlight that follows the pointer across cards.
 * All of it is off under prefers-reduced-motion. Started once from main.tsx; it watches <main> for page changes.
 */

import gsap from "gsap";
import Lenis from "lenis";

const reduced = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

let lenis: Lenis | null = null;
let frame = 0;

function scrollsItself(node: HTMLElement | null, root: HTMLElement): boolean {
  for (let el = node; el && el !== root; el = el.parentElement) {
    const style = getComputedStyle(el);
    if (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 2) return true;
    if (el.matches("textarea, canvas, [data-lenis-prevent]")) return true;
  }
  return false;
}

function smoothScroll(root: HTMLElement): void {
  lenis?.destroy();
  lenis = null;
  if (reduced() || root.scrollHeight <= root.clientHeight + 4) return;
  const content = root.firstElementChild as HTMLElement | null;
  if (!content) return;
  lenis = new Lenis({ wrapper: root, content, duration: 0.9, smoothWheel: true,
    prevent: (node: HTMLElement) => scrollsItself(node, root) });
  cancelAnimationFrame(frame);
  const loop = (time: number) => { lenis?.raf(time); frame = requestAnimationFrame(loop); };
  frame = requestAnimationFrame(loop);
}

function settle(root: HTMLElement): void {
  if (reduced()) return;
  gsap.fromTo(root, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.32, ease: "power2.out", clearProps: "transform,opacity" });
  const cards = root.querySelectorAll(".card, .model-tile, .pd-scale, .study__choice, .ability-box");
  if (cards.length) {
    gsap.fromTo(Array.from(cards).slice(0, 16), { opacity: 0, y: 14 },
      { opacity: 1, y: 0, duration: 0.4, ease: "power3.out", stagger: 0.035, delay: 0.05, clearProps: "transform,opacity" });
  }
}

function spark(x: number, y: number, color: string): void {
  const layer = document.createElement("div");
  layer.className = "click-spark";
  layer.style.left = `${x}px`;
  layer.style.top = `${y}px`;
  document.body.appendChild(layer);
  const bits = Array.from({ length: 8 }, (_, i) => {
    const bit = document.createElement("i");
    bit.style.background = color;
    layer.appendChild(bit);
    const angle = (Math.PI * 2 * i) / 8;
    return { bit, dx: Math.cos(angle) * 22, dy: Math.sin(angle) * 22 };
  });
  bits.forEach(({ bit, dx, dy }) => gsap.fromTo(bit, { x: 0, y: 0, scale: 1, opacity: 1 },
    { x: dx, y: dy, scale: 0.2, opacity: 0, duration: 0.45, ease: "power2.out" }));
  window.setTimeout(() => layer.remove(), 520);
}

let started = false;

export function startMotion(): void {
  if (started) return;
  started = true;
  // Page changes: the first child of <main> is the open page.
  let current: Element | null = null;
  const watch = () => {
    const main = document.querySelector("main");
    const root = main?.firstElementChild as HTMLElement | null;
    if (!root || root === current) return;
    current = root;
    settle(root);
    window.setTimeout(() => smoothScroll(root), 400);
  };
  new MutationObserver(watch).observe(document.body, { childList: true, subtree: true });
  window.setTimeout(watch, 600);

  document.addEventListener("click", (e) => {
    const target = (e.target as HTMLElement | null)?.closest(".btn-primary, .ability-box__open, .plus-menu__button");
    if (!target || reduced()) return;
    spark(e.clientX, e.clientY, getComputedStyle(document.documentElement).getPropertyValue("--color-accent").trim() || "#a594ff");
  });

  // Spotlight on cards: the light follows the pointer (CSS reads --mx/--my).
  document.addEventListener("pointermove", (e) => {
    const card = (e.target as HTMLElement | null)?.closest(".card, .model-tile, .pd-scale") as HTMLElement | null;
    if (!card) return;
    const box = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${e.clientX - box.left}px`);
    card.style.setProperty("--my", `${e.clientY - box.top}px`);
  }, { passive: true });
}
