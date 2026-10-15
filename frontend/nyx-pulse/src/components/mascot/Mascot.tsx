/** Io, the pixel octopus (Fixer Upper S1/S3, reference p41): a small mascot that sits on the chat box and shows the
 * work going on, one arm per running task.
 *
 *  - Each agent that is working lights one arm, coloured by what it is doing: green coding, amber writing,
 *    blue searching, pink design, grey anything else. Up to eight arms; more than that shows "+N".
 *  - A stuck agent (blocked or error) makes its arm wiggle, like Io scratching its head.
 *  - While Ichos is answering, Io bobs. When nothing runs it sits still and blinks now and then.
 *  - Hover (or focus) lists the tasks. Settings › Appearance › "Show Io on the chat box" hides it.
 * Drawn as SVG squares from the grid below, so it stays crisp at any size. Motion is off under reduced motion.
 */

import { useEffect, useState } from "react";
import type { TeamAgentView } from "../chat/types";
import "./mascot.css";

// Helmet and face, 16 x 10. o outline · r helmet · R helmet shine · v visor · g eye · p skin · m mic
const HEAD = [
  "....oooooooo....",
  "..oorrrrrrrroo..",
  ".orrRrrrrrrRrro.",
  ".orrrrrrrrrrrro.",
  "orrvvvvvvvvvvrro",
  "orvvgvvvvvvgvvro",
  "orvvgvvvvvvgvvro",
  "orrvvvvvvvvvvrro",
  ".orppppmmppppro.",
  "..oppppppppppo..",
];
const COLOR: Record<string, string> = {
  o: "#1b1030", r: "#c0392b", R: "#e8574a", v: "#2b2742", g: "#3ef07a", p: "#8e44ad", m: "#4a4a4a",
};
// Eight arms under the head: the squares of each, top to bottom.
const ARMS: [number, number][][] = [
  [[2, 10], [1, 11], [0, 12], [0, 13], [1, 14]],
  [[4, 10], [3, 11], [3, 12], [2, 13], [2, 14]],
  [[5, 10], [5, 11], [4, 12], [4, 13], [5, 14]],
  [[7, 10], [7, 11], [6, 12], [6, 13], [7, 14]],
  [[8, 10], [8, 11], [9, 12], [9, 13], [8, 14]],
  [[10, 10], [10, 11], [11, 12], [11, 13], [10, 14]],
  [[11, 10], [12, 11], [12, 12], [13, 13], [13, 14]],
  [[13, 10], [14, 11], [15, 12], [15, 13], [14, 14]],
];
// Arms light from the middle out, so one task reads as "one arm up front".
const ORDER = [3, 4, 2, 5, 1, 6, 0, 7];

export type TaskKind = "code" | "write" | "search" | "design" | "other";
const KIND_COLOR: Record<TaskKind, string> = {
  code: "#4ade80", write: "#fbbf24", search: "#60a5fa", design: "#f472b6", other: "#cbd5e1",
};
const KIND_WORD: Record<TaskKind, string> = { code: "coding", write: "writing", search: "searching", design: "designing", other: "working" };

/** What an agent is doing, read from its step and goal. */
export function kindOf(text = ""): TaskKind {
  const t = text.toLowerCase();
  if (/(code|coding|test|build|compile|debug|fix|commit|refactor|script|python|patch)/.test(t)) return "code";
  if (/(search|look up|lookup|research|read|browse|find|fetch|crawl)/.test(t)) return "search";
  if (/(design|draw|style|layout|image|icon|colou?r|mock)/.test(t)) return "design";
  if (/(writ|draft|email|summar|note|doc|reply|essay|translate)/.test(t)) return "write";
  return "other";
}

export interface ArmTask { name: string; kind: TaskKind; stuck: boolean; step?: string }

/** The agents worth an arm: working ones, and stuck ones so the owner sees them. */
export function armTasks(agents: TeamAgentView[]): ArmTask[] {
  return agents
    .filter((a) => a.status === "working" || a.status === "blocked" || a.status === "error")
    .map((a) => ({ name: a.name, kind: kindOf(`${a.step ?? ""} ${a.goal ?? ""}`), stuck: a.status !== "working", step: a.step }));
}

const MASCOT_KEY = "ichos.mascot.show";
export function mascotShown(): boolean {
  try { return localStorage.getItem(MASCOT_KEY) !== "0"; } catch { return true; }
}
export function setMascotShown(on: boolean): void {
  try { localStorage.setItem(MASCOT_KEY, on ? "1" : "0"); } catch { /* private window */ }
  window.dispatchEvent(new Event("ichos:mascot"));
}

export function Mascot({ agents, busy, scale = 3 }: { agents: TeamAgentView[]; busy: boolean; scale?: number }) {
  const [shown, setShown] = useState(mascotShown);
  const [blink, setBlink] = useState(false);
  useEffect(() => {
    const on = () => setShown(mascotShown());
    window.addEventListener("ichos:mascot", on);
    return () => window.removeEventListener("ichos:mascot", on);
  }, []);
  useEffect(() => {
    let t = 0;
    const next = () => { t = window.setTimeout(() => { setBlink(true); window.setTimeout(() => setBlink(false), 140); next(); }, 2600 + Math.random() * 3200); };
    next();
    return () => window.clearTimeout(t);
  }, []);
  if (!shown) return null;

  const tasks = armTasks(agents);
  const lit = new Map<number, ArmTask>();
  tasks.slice(0, 8).forEach((task, i) => lit.set(ORDER[i], task));
  const extra = Math.max(0, tasks.length - 8);
  const label = tasks.length
    ? `Io: ${tasks.map((t) => `${t.name} ${t.stuck ? "is stuck" : KIND_WORD[t.kind]}`).join(", ")}`
    : busy ? "Io: Ichos is answering" : "Io: nothing running";

  return (
    <div className={`io-mascot${busy ? " is-busy" : ""}${tasks.length ? " is-working" : ""}`} tabIndex={0} role="img" aria-label={label}>
      <svg width={16 * scale} height={15 * scale} viewBox="0 0 16 15" shapeRendering="crispEdges">
        {HEAD.flatMap((row, y) => row.split("").map((ch, x) => {
          if (ch === ".") return null;
          const fill = ch === "g" && blink ? COLOR.v : COLOR[ch];
          return <rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill={fill} />;
        }))}
        {ARMS.map((arm, i) => {
          const task = lit.get(i);
          const fill = task ? KIND_COLOR[task.kind] : i % 2 ? "#7d3c98" : COLOR.p;
          return (
            <g key={i} className={`io-arm${task ? " is-lit" : ""}${task?.stuck ? " is-stuck" : ""}`}
              style={{ transformOrigin: `${arm[0][0] + 0.5}px ${arm[0][1]}px` }}>
              {arm.map(([x, y]) => <rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill={fill} />)}
            </g>
          );
        })}
      </svg>
      {extra > 0 && <span className="io-mascot__more">+{extra}</span>}
      <div className="io-mascot__tip" role="tooltip">
        {tasks.length ? tasks.map((t, i) => (
          <div key={i} className="io-mascot__row">
            <i style={{ background: t.stuck ? "var(--color-danger, #ef4444)" : KIND_COLOR[t.kind] }} />
            <b>{t.name}</b><span>{t.stuck ? "stuck, needs a look" : t.step || KIND_WORD[t.kind]}</span>
          </div>
        )) : <span>{busy ? "Ichos is answering…" : "Nothing running. Each task lights an arm."}</span>}
      </div>
    </div>
  );
}
