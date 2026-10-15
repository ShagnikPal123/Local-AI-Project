/** The Ichos tour (owner, 2026-10-15: "add a tutorial to how to use Ichos since it has so many tabs").
 *
 * A short guided walk through the app: each step opens the tab it talks about (through the same `nyx:open-tab` event
 * the app and Nyx already use), lights up what to look at when it is on screen, and says in two lines what the tab is
 * for and one thing to try. A card in the corner carries Back / Next / Skip, so the tab underneath stays usable.
 *
 * It offers itself once (a small "Take the tour" card on first start) and can be started again any time from the
 * "Tour" button in the top bar or by sending `nyx:tour`. Nothing is sent anywhere; whether it was seen is kept in this
 * browser only. */

import { useCallback, useEffect, useState } from "react";
import "./tour.css";

interface Step {
  /** Tab or section id to open (anything `nyx:open-tab` accepts). */
  tab?: string;
  /** What to light up, when it is on screen. */
  spot?: string;
  title: string;
  body: string;
  tryIt?: string;
}

export const TOUR: Step[] = [
  { tab: "nyx", title: "Welcome to Ichos", body: "Ichos is your local AI. It runs on this PC, works with or without the internet, and can use Claude, ChatGPT, Gemini, Perplexity and local models.",
    tryIt: "This tour takes about two minutes. Each step opens the tab it talks about." },
  { tab: "nyx", spot: ".composer-box", title: "Chat is home", body: "Almost everything starts here. Ask in plain words: Ichos answers, uses tools, opens windows beside the chat, and splits bigger jobs into threads.",
    tryIt: "Type / in the box to see every command." },
  { tab: "nyx", spot: ".lp-btn", title: "Pick who answers", body: "Under the box: the model and how hard it works. Pico is light, Monolith (Argon to Xenon) is general, Crescendo is for heavy work, Zencode is for code. Auto lets Ichos choose.",
    tryIt: "Leave it on Auto until you want something specific." },
  { tab: "nyx", spot: ".mode-slider", title: "How a chat works", body: "Normal answers and acts. Co-work checks in as it goes. Plan writes a plan first and asks before doing it. Swarm splits work across helpers. Auto picks for you." },
  { tab: "nyx", spot: ".cb-zone.is-bottom", title: "Bars you can move", body: "Context, usage, environment, connectors, remote access and team are small bars. Drag one by its ⠿ to the top or back, or hide it with its ⋮." },
  { tab: "nyx", spot: ".chat-rail__mode, .code-switch, .composer-box", title: "Code in a folder", body: "Chat or Code sits at the top of your chat list. Code works in a folder on this PC; the + beside the box does the same in any chat." },
  { tab: "nyx", spot: ".ov-panel, .ov-toggle", title: "Overview", body: "The panel on the right shows every chat that needs you or is working, a usage graph, your Library of files and artifacts, and what Ichos touched.",
    tryIt: "The Overview button at the top of the chat opens and closes it." },
  { tab: "nyx", spot: ".pj-rail", title: "Projects", body: "A project keeps chats, files, instructions and helpers together, like Claude Projects. Open one and its home shows the folder, instructions, knowledge and threads.",
    tryIt: "Press + next to Projects to make one." },
  { tab: "projects", title: "Constellations", body: "Every project and artifact sorted for you (each opens in the chat), plus Quasars (things Ichos made), Orbits (tasks on a repeat), the Calendar and Fractal design templates.",
    tryIt: "In Calendar, click a time to schedule something there." },
  { tab: "avatars", title: "Avatars", body: "Helpers that keep working for you: on call, all day or all year. Each has its own persona, memory, schedule and Allow / Ask rules." },
  { tab: "agents", title: "Agents", body: "The specialist team Ichos hands work to (coder, researcher, designer and more), sub-agents, and Big Kahuna, the strongest mind." },
  { tab: "research", title: "Research Lab", body: "Deep research with sources, predictions, and Data Absorption for learning from your own files." },
  { tab: "code", title: "Code", body: "A full code workspace: open a folder, read and edit files, run commands, and review changes before they are applied." },
  { tab: "office", title: "Office & World", body: "A visual office where you can watch your agents and avatars at work, and a world view of what they are doing." },
  { tab: "improve", title: "Improve", body: "Ichos suggests ways to get better and learns from use. Every change waits for your review before it ships." },
  { tab: "equalize", title: "Equalize", body: "Your daily briefing, Claude Code sessions by state, and the assistant that also lives in the notch at the top of the screen." },
  { tab: "computer", title: "Computer", body: "Ichos's own desktop and screen share. It only touches your computer with the access you grant." },
  { tab: "connectors", title: "Connections", body: "Connect Gmail, Drive, Calendar, Slack, GitHub and more, add API keys and models, and add new capabilities.",
    tryIt: "Connect Google once and Gmail, Drive and Calendar all work." },
  { tab: "nyx", title: "You're set", body: "Ask Ichos anything, from any tab. The Tour button at the top brings this back whenever you want it." },
];

const SEEN_KEY = "nyx.tour.seen";

function seen(): boolean {
  try { return localStorage.getItem(SEEN_KEY) === "1"; } catch { return true; }
}
function markSeen(): void {
  try { localStorage.setItem(SEEN_KEY, "1"); } catch { /* private window: it offers itself again, which is fine */ }
}

/** Start the tour from anywhere (a button, a slash command, Nyx itself). */
export function startTour(): void {
  window.dispatchEvent(new CustomEvent("nyx:tour"));
}

function useSpot(selector: string | undefined, step: number): DOMRect | null {
  const [rect, setRect] = useState<DOMRect | null>(null);
  useEffect(() => {
    setRect(null);
    if (!selector) return;
    let frame = 0;
    const find = () => {
      const el = document.querySelector(selector);
      const box = el?.getBoundingClientRect();
      setRect(box && box.width > 0 && box.height > 0 ? box : null);
    };
    // The tab opens lazily: look again for a moment while it renders.
    const timers = [60, 300, 800].map((ms) => window.setTimeout(find, ms));
    const onResize = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(find); };
    window.addEventListener("resize", onResize);
    return () => { timers.forEach(window.clearTimeout); window.removeEventListener("resize", onResize); cancelAnimationFrame(frame); };
  }, [selector, step]);
  return rect;
}

export function IchosTour() {
  const [step, setStep] = useState<number | null>(null);
  const [offer, setOffer] = useState(() => !seen());

  const go = useCallback((index: number) => {
    const next = TOUR[index];
    if (next?.tab) window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: next.tab } }));
    setStep(index);
  }, []);
  const close = useCallback(() => { setStep(null); setOffer(false); markSeen(); }, []);

  useEffect(() => {
    const onTour = () => { setOffer(false); go(0); };
    window.addEventListener("nyx:tour", onTour);
    return () => window.removeEventListener("nyx:tour", onTour);
  }, [go]);
  useEffect(() => {
    if (step === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight" && step < TOUR.length - 1) go(step + 1);
      else if (e.key === "ArrowLeft" && step > 0) go(step - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, go, close]);

  const current = step === null ? null : TOUR[step];
  const rect = useSpot(current?.spot, step ?? -1);

  if (step === null || !current) {
    if (!offer) return null;
    return (
      <div className="tour-offer" role="dialog" aria-label="Take the tour">
        <b>New to Ichos?</b>
        <span>A two-minute walk through the tabs.</span>
        <span className="tour-offer__acts">
          <button type="button" className="btn btn-primary" onClick={() => { setOffer(false); go(0); }}>Take the tour</button>
          <button type="button" className="btn btn-secondary" onClick={close}>Not now</button>
        </span>
      </div>
    );
  }

  const last = step === TOUR.length - 1;
  return (
    <>
      {rect && (
        <div className="tour-spot" aria-hidden="true"
          style={{ top: rect.top - 6, left: rect.left - 6, width: rect.width + 12, height: rect.height + 12 }} />
      )}
      <div className="tour-card" role="dialog" aria-modal="false" aria-labelledby="tour-title">
        <div className="tour-card__count">Step {step + 1} of {TOUR.length}</div>
        <h2 id="tour-title">{current.title}</h2>
        <p>{current.body}</p>
        {current.tryIt && <p className="tour-card__try"><span aria-hidden="true">→</span> {current.tryIt}</p>}
        <div className="tour-card__dots" aria-hidden="true">
          {TOUR.map((_, i) => <i key={i} className={i === step ? "is-on" : i < step ? "is-done" : ""} />)}
        </div>
        <div className="tour-card__acts">
          <button type="button" className="btn" onClick={close}>{last ? "Close" : "Skip"}</button>
          <span className="tour-card__spacer" />
          {step > 0 && <button type="button" className="btn btn-secondary" onClick={() => go(step - 1)}>Back</button>}
          <button type="button" className="btn btn-primary" autoFocus onClick={() => (last ? close() : go(step + 1))}>{last ? "Done" : "Next"}</button>
        </div>
      </div>
    </>
  );
}
