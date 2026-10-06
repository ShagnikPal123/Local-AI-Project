/** Tutorials: a walkthrough of the build (each step lights one thing in 3D) and a tour of the studio itself. */

import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import type { Project, Tutorial } from "./types";

/** A walkthrough made from the build itself, so the highlighting tour works with no model and no key. */
export function localTutorial(project: Project): Tutorial {
  const parts = new Map(project.parts.map((p) => [p.id, p]));
  const order = (kind: string) => ({ enclosure: 0, mechanical: 1, fastener: 2, electronic: 3, material: 4 }[kind] ?? 5);
  const pieces = [...project.placements].sort((a, b) => order(parts.get(a.part_id)?.kind ?? "") - order(parts.get(b.part_id)?.kind ?? "") || a.at[1] - b.at[1]);

  const steps: Tutorial["steps"] = pieces.map((placement, index) => {
    const part = parts.get(placement.part_id)!;
    const notes = part.features.map((f) => f.note).filter(Boolean).slice(0, 2);
    const pins = part.pins.filter((p) => p.required).map((p) => p.name);
    return {
      id: `local-${placement.id}`,
      title: `${index + 1}. ${placement.name || part.name}`,
      body: [part.summary.replace(/ Nominal published dimensions.*$/, ""), notes.join(" ")].filter(Boolean).join(" ") || `A ${part.kind} part.`,
      focus: { kind: "placement", id: placement.id, part_id: part.id },
      tips: [
        part.material ? `Made from ${part.material}.` : "",
        pins.length ? `Needs ${pins.slice(0, 4).join(", ")} connected.` : "",
      ].filter(Boolean),
      warning: /mains|lipo|relay/i.test(`${part.name} ${part.summary}`) ? "Handle with care: read the note above before wiring this." : "",
    };
  });
  for (const net of project.nets) {
    steps.push({
      id: `local-${net.id}`,
      title: `Wire: ${net.name}`,
      body: `A ${net.kind} connection${net.voltage ? ` at ${net.voltage} V` : ""} joining ${net.points.length} pins.`,
      focus: { kind: "net", id: net.id },
      tips: [],
      warning: "",
    });
  }
  return { title: `How ${project.name} goes together`, intro: "", steps, source: "owner", model: "" };
}

export interface TutorialCardProps {
  tutorial: Tutorial;
  index: number;
  onIndex: (index: number) => void;
  onExit: () => void;
}

export function TutorialCard({ tutorial, index, onIndex, onExit }: TutorialCardProps) {
  const step = tutorial.steps[index];
  const last = tutorial.steps.length - 1;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.closest("input, textarea, select")) return;
      if (event.key === "ArrowRight") onIndex(Math.min(last, index + 1));
      if (event.key === "ArrowLeft") onIndex(Math.max(0, index - 1));
      if (event.key === "Escape") onExit();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, last, onIndex, onExit]);

  if (!step) return null;
  return (
    <div className="bs-tutorial" role="dialog" aria-label={tutorial.title} aria-live="polite">
      <div className="bs-tutorial__top">
        <span className="bs-tutorial__count">Step {index + 1} of {tutorial.steps.length}</span>
        <div className="bs-tutorial__dots" role="tablist">
          {tutorial.steps.map((s, i) => (
            <button key={s.id} role="tab" aria-selected={i === index} aria-label={`Step ${i + 1}: ${s.title}`} className={i === index ? "is-on" : i < index ? "is-done" : ""} onClick={() => onIndex(i)} />
          ))}
        </div>
        <button className="bs-icon" onClick={onExit} aria-label="End the walkthrough">×</button>
      </div>
      <h3>{step.title}</h3>
      <p>{step.body}</p>
      {step.tips.length > 0 && <ul className="bs-tutorial__tips">{step.tips.map((tip) => <li key={tip}>{tip}</li>)}</ul>}
      {step.warning && <p className="bs-tutorial__warning">{step.warning}</p>}
      <div className="bs-tutorial__nav">
        <button className="btn btn-secondary btn-sm" disabled={index === 0} onClick={() => onIndex(index - 1)}>← Back</button>
        {index < last
          ? <button className="btn btn-primary btn-sm" onClick={() => onIndex(index + 1)}>Next →</button>
          : <button className="btn btn-primary btn-sm" onClick={onExit}>Done</button>}
        {tutorial.model && <span className="bs-model">{tutorial.model}</span>}
      </div>
    </div>
  );
}

// --- the studio tour --------------------------------------------------------------------

const TOUR = [
  { target: "rail", title: "Parts come from here", body: "Real boards and components with true sizes and pinouts, parts you have saved, and parts you draw yourself. Press Add and it drops into the space." },
  { target: "viewport", title: "The single shared space", body: "Every part lives here together. Drag to orbit, scroll to zoom, click to select, Shift-click several to combine them into one part." },
  { target: "modes", title: "Three ways to work", body: "Space arranges pieces. Part edits one part shape by shape — every shape lights up as you select it. Circuit shows every pin so you can wire them." },
  { target: "tools", title: "Move and rotate", body: "With a piece selected, Move and Rotate give you handles in 3D. Numbers in the panel on the right are exact to the millimetre." },
  { target: "panel", title: "Details, checks and Nyx", body: "Inspect what you selected, see problems the moment they happen, the parts list and print weights, and ask Nyx to draw, wire, review or design." },
  { target: "walkthrough", title: "Walk through any build", body: "Step through a build one piece at a time. Each step lights that piece and fades the rest, like this tour." },
];

const TOUR_KEY = "nyx.build.tour.v1";

export function useStudioTour() {
  const [step, setStep] = useState<number | null>(null);
  useEffect(() => {
    try {
      if (!localStorage.getItem(TOUR_KEY)) setStep(0);
    } catch {
      /* storage blocked: skip the automatic tour, the ? button still works */
    }
  }, []);
  const finish = useCallback(() => {
    setStep(null);
    try { localStorage.setItem(TOUR_KEY, "done"); } catch { /* nothing to remember it in */ }
  }, []);
  return { step, setStep, finish, total: TOUR.length };
}

export function StudioTour({ step, onStep, onFinish }: { step: number; onStep: (step: number) => void; onFinish: () => void }) {
  const item = TOUR[step];
  const [rect, setRect] = useState<DOMRect | null>(null);

  useLayoutEffect(() => {
    const measure = () => {
      const el = document.querySelector(`[data-tour="${item.target}"]`);
      setRect(el ? el.getBoundingClientRect() : null);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [item.target]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onFinish();
      if (event.key === "ArrowRight" || event.key === "Enter") step < TOUR.length - 1 ? onStep(step + 1) : onFinish();
      if (event.key === "ArrowLeft" && step > 0) onStep(step - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, onStep, onFinish]);

  const pad = 8;
  const hole = rect ? { left: rect.left - pad, top: rect.top - pad, width: rect.width + pad * 2, height: rect.height + pad * 2 } : null;
  const cardWidth = 320;
  let left = hole ? hole.left + hole.width + 16 : window.innerWidth / 2 - cardWidth / 2;
  let top = hole ? hole.top : window.innerHeight / 2 - 100;
  if (hole && left + cardWidth > window.innerWidth - 16) left = hole.left - cardWidth - 16;
  if (left < 16) left = Math.max(16, Math.min(window.innerWidth - cardWidth - 16, (hole?.left ?? 0) + 24));
  if (hole && hole.width > window.innerWidth * 0.5) top = Math.min(hole.top + 24, window.innerHeight - 240);
  top = Math.max(16, Math.min(window.innerHeight - 240, top));

  return (
    <div className="bs-tour" role="dialog" aria-modal="true" aria-label={`Studio tour: ${item.title}`}>
      {hole && <div className="bs-tour__hole" style={hole} />}
      <div className="bs-tour__card" style={{ left, top, width: cardWidth }}>
        <div className="bs-tutorial__count">Tour · {step + 1} of {TOUR.length}</div>
        <h3>{item.title}</h3>
        <p>{item.body}</p>
        <div className="bs-tutorial__nav">
          <button className="btn btn-ghost btn-sm" onClick={onFinish}>Skip</button>
          {step > 0 && <button className="btn btn-secondary btn-sm" onClick={() => onStep(step - 1)}>Back</button>}
          <button className="btn btn-primary btn-sm" autoFocus onClick={() => (step < TOUR.length - 1 ? onStep(step + 1) : onFinish())}>{step < TOUR.length - 1 ? "Next" : "Start building"}</button>
        </div>
      </div>
    </div>
  );
}
