/** Progress: how the owner's idea is growing (owner, 2026-10-10: "Tech should be able to get super advanced, from
 * trains to hover vehicles, it shows the user their idea is growing"). The growth chart, the transport ladder from
 * footpaths to star lanes, the economy, and the whole technology tree with the research focus the owner can set. */

import { useState } from "react";
import type { WorldSnapshot } from "./types";
import { worldApi } from "./worldApi";

const SERIES = [
  { index: 1, label: "Tech", color: "var(--color-accent, #ff7a2e)" },
  { index: 3, label: "Floors", color: "#64d2ff" },
  { index: 4, label: "AIs", color: "#30d158" },
];

function GrowthChart({ growth }: { growth: number[][] }) {
  if (growth.length < 2) {
    return <p className="ofc-muted">The chart fills in while the world runs — a point every few seconds.</p>;
  }
  const width = 320;
  const height = 110;
  const days = growth.map((r) => r[0]);
  const x0 = Math.min(...days);
  const x1 = Math.max(...days, x0 + 1);
  return (
    <figure className="wld-growth" aria-label="How the world grew">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-hidden="true" preserveAspectRatio="none">
        {SERIES.map((series) => {
          const top = Math.max(1, ...growth.map((r) => r[series.index]));
          const points = growth.map((r) => `${((r[0] - x0) / (x1 - x0)) * width},${height - 4 - (r[series.index] / top) * (height - 10)}`);
          return <polyline key={series.label} points={points.join(" ")} fill="none" stroke={series.color} strokeWidth={2}
                           vectorEffect="non-scaling-stroke" strokeLinejoin="round" />;
        })}
      </svg>
      <figcaption>
        {SERIES.map((series) => (
          <span key={series.label}><i style={{ background: series.color }} />{series.label}{" "}
            <b>{growth[growth.length - 1][series.index].toLocaleString()}</b></span>
        ))}
        <span className="ofc-muted">each line on its own scale · day {Math.round(x0)}–{Math.round(x1)}</span>
      </figcaption>
    </figure>
  );
}

export function ProgressPanel({ snapshot, onChanged, onError }: {
  snapshot: WorldSnapshot;
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const tech = snapshot.tech;
  if (!tech) return <p className="ofc-muted">Open the world again to see its progress.</p>;
  const world = snapshot.world;
  const standing = snapshot.buildings.filter((b) => b.state === "standing");
  const tallest = standing.reduce((max, b) => Math.max(max, b.floors), 0);
  const building = snapshot.buildings.filter((b) => b.state === "constructing");
  const waiting = building.filter((b) => b.why.startsWith("Waiting for materials")).length;
  const branches = Object.entries(tech.branches);

  const setFocus = async (branch: string) => {
    setBusy(true);
    const result = await worldApi.focus(world.id, branch);
    setBusy(false);
    if (!result.ok) onError(result.error);
    else onChanged();
  };

  return (
    <div className="wld-panel">
      <section aria-labelledby="wld-growth">
        <h3 id="wld-growth">Growth</h3>
        <GrowthChart growth={snapshot.growth ?? []} />
        <div className="wld-stats" role="list">
          <div role="listitem"><b>{tech.researched}/{tech.total}</b><span>technologies</span></div>
          <div role="listitem"><b>{standing.length}</b><span>buildings</span></div>
          <div role="listitem"><b>{tallest}</b><span>tallest (floors)</span></div>
          <div role="listitem"><b>{Math.round(snapshot.stock?.materials ?? 0).toLocaleString()}</b><span>materials</span></div>
          <div role="listitem"><b>{Math.round(snapshot.stock?.energy ?? 0).toLocaleString()}</b><span>energy</span></div>
          <div role="listitem"><b>{Math.round(snapshot.stock?.compute ?? 0).toLocaleString()}</b><span>compute</span></div>
        </div>
        {building.length > 0 && (
          <p className="ofc-muted">{building.length} under construction{waiting ? ` — ${waiting} waiting for materials` : ""}.</p>
        )}
      </section>

      <section aria-labelledby="wld-transport">
        <h3 id="wld-transport">How the world moves</h3>
        <ol className="wld-ladder">
          {tech.transport_levels.map((label, index) => (
            <li key={label} className={index < tech.transport ? "is-done" : index === tech.transport ? "is-now" : ""}
                aria-current={index === tech.transport ? "step" : undefined}>
              <i aria-hidden="true" />{label}
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="wld-tree">
        <h3 id="wld-tree">Technology</h3>
        <p className="ofc-muted">
          {world.tech_points.toLocaleString()} tech points.
          {tech.next ? <> Next: <b>{tech.next.name}</b> at {tech.next.cost}.</> : " Everything is discovered."}
          {" "}Labs and data centres research on their own while the world runs (×{tech.research_bonus}).
        </p>
        <div className="wld-focus" role="radiogroup" aria-label="Research focus — that branch costs a quarter less">
          <span>Focus</span>
          {branches.map(([key, label]) => (
            <button key={key} type="button" role="radio" aria-checked={tech.focus === key} disabled={busy}
                    className={tech.focus === key ? "is-on" : ""} onClick={() => void setFocus(key)}>{label}</button>
          ))}
        </div>
        {branches.map(([key, label]) => (
          <div key={key} className="wld-branchrow">
            <h4>{label}</h4>
            <ul>
              {tech.tree.filter((t) => t.branch === key).map((t) => (
                <li key={t.id} className={`is-${t.state}`} title={t.about}>
                  <span>{t.name}</span>
                  <small>{t.state === "done" ? "✓" : t.cost}</small>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}
