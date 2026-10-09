/** The details card (U39): *"the person can interact with each bot, government to the low office workers …
 * basically a details tab … how many bots, what they are doing, main goals and such"*.
 *
 * One card for whatever was clicked. A bot's mood is asked from its own model when you press the button and shown
 * here only — it is never saved (the owner's rule). A contest can be heard and decided here; a start-up approved; a
 * grave's AI brought back; a law enforced or repealed.
 */

import { useMemo, useState } from "react";
import type { OfficeAgent, OfficeRole, OfficeSection, OfficeTask } from "../office/types";
import { ERAS, KIND_LABELS, gameDate, span } from "./format";
import type { Pick, WorldSnapshot } from "./types";
import { worldApi } from "./worldApi";

interface Props {
  pick: Pick;
  snapshot: WorldSnapshot;
  agents: Record<string, OfficeAgent>;
  sections: Record<string, OfficeSection>;
  roles: Record<string, OfficeRole>;
  tasks: OfficeTask[];
  onPick: (pick: Pick | null) => void;
  onClose: () => void;
  onChanged: () => void;
  onError: (message: string) => void;
}

export function Inspector(props: Props) {
  const { pick } = props;
  return (
    <aside className="wld-card" aria-label="Details" aria-live="polite">
      <button type="button" className="ofc-x wld-card__close" onClick={props.onClose} aria-label="Close the details">✕</button>
      {pick.kind === "world" && <WorldCard {...props} />}
      {pick.kind === "sector" && <SectorCard {...props} id={pick.id} />}
      {pick.kind === "building" && <BuildingCard {...props} id={pick.id} />}
      {pick.kind === "bot" && <BotCard {...props} id={pick.id} />}
      {pick.kind === "war" && <WarCard {...props} id={pick.id} />}
      {pick.kind === "startup" && <StartupCard {...props} id={pick.id} />}
      {pick.kind === "grave" && <GraveCard {...props} id={pick.id} />}
      {pick.kind === "law" && <LawCard {...props} id={pick.id} />}
      {pick.kind === "station" && <StationCard {...props} id={pick.id} />}
    </aside>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="wld-row"><span>{label}</span><b>{children}</b></div>;
}

function Gone({ what }: { what: string }) {
  return <p className="ofc-muted">That {what} is gone from the world.</p>;
}

function WorldCard({ snapshot }: Props) {
  const world = snapshot.world;
  const tech = world.techs[world.techs.length - 1];
  return (
    <>
      <p className="wld-card__eyebrow">The world</p>
      <h3>{world.name}</h3>
      <p className="wld-card__lead">{world.goal || "No goal yet."}</p>
      <Row label="Led by">{world.leader.kahuna ? "Big Kahuna (Identity 0)" : world.leader.name}</Row>
      <Row label="Era">{world.era_name}{world.next_era_at ? ` · ${world.tech_points}/${world.next_era_at} tech` : ""}</Row>
      {tech && <Row label="Technology">{tech.tech}</Row>}
      <Row label="Population">{world.population.ais} AIs · {world.population.common} common bots</Row>
      <Row label="Buildings">{snapshot.buildings.filter((b) => b.state !== "demolishing").length}</Row>
      <Row label="In orbit">{world.stations} stations · {world.planets} artificial planets</Row>
      <Row label="Laws in force">{snapshot.laws.filter((l) => l.status === "enforced").length}</Row>
      {tech?.about && <p className="ofc-muted">{tech.about}</p>}
    </>
  );
}

function SectorCard({ snapshot, id, agents, sections, tasks, roles, onPick }: Props & { id: string }) {
  const sector = snapshot.sectors.find((s) => s.sid === id);
  const people = useMemo(() => snapshot.bots.filter((b) => b.sector === id), [snapshot.bots, id]);
  if (!sector) return <Gone what="sector" />;
  const section = sections[id];
  const manager = section ? agents[section.manager_id] : undefined;
  const working = people.filter((b) => agents[b.aid]?.status === "working");
  const asleep = people.filter((b) => b.state === "asleep");
  const open = tasks.filter((t) => t.section_id === id && ["queued", "working", "review"].includes(t.status));
  const laws = snapshot.laws.filter((l) => l.sector === id && ["enforced", "testing"].includes(l.status));
  const commons = snapshot.common[id] ?? 0;
  const byRole = new Map<string, number>();
  for (const bot of people) byRole.set(bot.role, (byRole.get(bot.role) ?? 0) + 1);
  return (
    <>
      <p className="wld-card__eyebrow">{sector.important ? "The capital" : sector.startup ? "Start-up sector" : "Sector"}</p>
      <h3>{sector.name}</h3>
      <p className="wld-card__lead">{section?.purpose || "No stated purpose."}</p>
      <Row label="Government">{sector.gov}</Row>
      <Row label="Led by">{manager ? <button type="button" className="ofc-link" onClick={() => onPick({ kind: "bot", id: manager.id })}>{manager.name}</button> : "—"}</Row>
      <Row label="Works as">{KIND_LABELS[sector.kind] ?? sector.kind}</Row>
      <Row label="AIs">{people.length} · {working.length} working · {asleep.length} asleep</Row>
      <Row label="Common bots">{commons}</Row>
      <Row label="Influence">{sector.influence}</Row>
      {sector.full && <p className="wld-warn">Every plot is built on — it grows again in the next era.</p>}
      {byRole.size > 0 && (
        <div className="wld-chips" aria-label="Who lives here">
          {Array.from(byRole.entries()).map(([role, count]) => {
            const color = Object.values(roles).find((r) => r.title === role)?.color;
            return <span key={role} className="wld-chip" style={{ ["--chip" as string]: color ?? "#a594ff" }}>{count} × {role}</span>;
          })}
        </div>
      )}
      <h4>What they are doing</h4>
      {open.length === 0 ? <p className="ofc-muted">Nothing open right now.</p> : (
        <ul className="wld-list">
          {open.slice(0, 8).map((task) => (
            <li key={task.id}><span className={`wld-dot is-${task.status}`} />{task.title}
              {task.agent_id && agents[task.agent_id] ? <em> — {agents[task.agent_id].name}</em> : null}</li>
          ))}
        </ul>
      )}
      {laws.length > 0 && (<><h4>Its laws</h4><ul className="wld-list">{laws.map((law) => <li key={law.lid}>{law.text}</li>)}</ul></>)}
    </>
  );
}

function BuildingCard({ snapshot, id, agents, onPick }: Props & { id: number }) {
  const building = snapshot.buildings.find((b) => b.bid === id);
  if (!building) return <Gone what="building" />;
  const sector = snapshot.sectors.find((s) => s.sid === building.sector);
  const inside = snapshot.bots.filter((b) => b.sector === building.sector && agents[b.aid]?.status === "working");
  return (
    <>
      <p className="wld-card__eyebrow">{sector?.name ?? "Workplace"}</p>
      <h3>{KIND_LABELS[building.kind] ?? building.kind}</h3>
      <Row label="Floors">{building.floors}</Row>
      <Row label="Built in">{ERAS[building.era] ?? building.era} era · {gameDate(building.built_day)}</Row>
      <Row label="State">{building.state === "constructing" ? `Being built · ${Math.round(building.progress * 100)}%`
        : building.state === "demolishing" ? "Coming down" : "Standing"}</Row>
      {building.why && <p className="wld-card__lead">{building.why}</p>}
      <h4>Working here now</h4>
      {inside.length === 0 ? <p className="ofc-muted">Nobody at the moment.</p> : (
        <ul className="wld-list">
          {inside.slice(0, 10).map((bot) => (
            <li key={bot.aid}><button type="button" className="ofc-link" onClick={() => onPick({ kind: "bot", id: bot.aid })}>{bot.name}</button>
              <em> — {agents[bot.aid]?.step || "working"}</em></li>
          ))}
        </ul>
      )}
      {sector && <button type="button" className="ofc-link" onClick={() => onPick({ kind: "sector", id: sector.sid })}>Open {sector.name}</button>}
    </>
  );
}

function BotCard({ snapshot, id, agents, tasks, onPick, onError }: Props & { id: string }) {
  const [mood, setMood] = useState<{ text: string; live: boolean; note: string } | null>(null);
  const [asking, setAsking] = useState(false);
  const bot = snapshot.bots.find((b) => b.aid === id);
  if (!bot) return <Gone what="AI" />;
  const agent = agents[id];
  const task = agent?.task_id ? tasks.find((t) => t.id === agent.task_id) : undefined;
  const parents = bot.parents.map((p) => snapshot.bots.find((b) => b.aid === p)?.name
    ?? snapshot.graves.find((g) => g.aid === p)?.name ?? "an AI that is gone");
  const sector = snapshot.sectors.find((s) => s.sid === bot.sector);
  const ask = async () => {
    setAsking(true);
    const result = await worldApi.mood(snapshot.world.id, id);
    setAsking(false);
    if (result.ok) setMood({ text: result.data.mood, live: result.data.live, note: result.data.note });
    else onError(result.error);
  };
  return (
    <>
      <p className="wld-card__eyebrow">{sector?.name ?? "AI"}{bot.generation ? ` · generation ${bot.generation}` : ""}</p>
      <h3>{bot.name}</h3>
      <p className="wld-card__lead">{bot.role}{agent?.employment === "part_time" ? " · part time" : ""}</p>
      <Row label="Now">{bot.state === "asleep" && agent?.status !== "working" ? "Asleep" : agent?.status === "working"
        ? (agent.step || "Working") : "Awake, between tasks"}</Row>
      {task && <Row label="Task">{task.title}</Row>}
      <Row label="Tasks done">{agent?.tasks_done ?? 0}</Row>
      <Row label="Thinks with">{agent?.member || "—"}</Row>
      <Row label="Born">{gameDate(bot.born_day)}</Row>
      {parents.length > 0 && <Row label="Parents">{parents.join(" + ")}</Row>}
      <div className="wld-code" title="Its genetic code: generation · role · rank · full or part time · model · skills">
        <span>Genetic code</span><code>{bot.pretty}</code>
      </div>
      <div className="wld-chips">{bot.skills.map((skill) => <span key={skill} className="wld-chip">{skill}</span>)}</div>
      <div className="wld-mood">
        <button type="button" className="ofc-btn ofc-btn--small" onClick={() => void ask()} disabled={asking}>
          {asking ? "Asking…" : "Ask how it’s doing"}
        </button>
        {mood && (
          <blockquote>
            <p>“{mood.text}”</p>
            <footer>{mood.note}</footer>
          </blockquote>
        )}
      </div>
      {sector && <button type="button" className="ofc-link" onClick={() => onPick({ kind: "sector", id: sector.sid })}>Open {sector.name}</button>}
    </>
  );
}

function WarCard({ snapshot, id, onChanged, onError }: Props & { id: string }) {
  const [own, setOwn] = useState("");
  const [busy, setBusy] = useState(false);
  const war = snapshot.wars.find((w) => w.wid === id);
  if (!war) return <Gone what="contest" />;
  const a = snapshot.sectors.find((s) => s.sid === war.a);
  const b = snapshot.sectors.find((s) => s.sid === war.b);
  const left = war.deadline ? war.deadline - Date.now() / 1000 : 0;
  const run = async (call: () => Promise<{ ok: boolean; error?: string }>) => {
    setBusy(true);
    const result = await call();
    setBusy(false);
    if (!result.ok) onError(result.error ?? "That did not work.");
    onChanged();
  };
  const sides = [
    { key: "a" as const, sector: a, stance: war.a_stance, case: war.cases.a },
    { key: "b" as const, sector: b, stance: war.b_stance, case: war.cases.b },
  ];
  return (
    <>
      <p className="wld-card__eyebrow">A contest of ideas</p>
      <h3>{a?.name ?? "?"} vs {b?.name ?? "?"}</h3>
      <p className="wld-card__lead"><b>Why they disagree:</b> {war.reason}</p>
      <div className="wld-factions">
        {sides.map((side) => (
          <div key={side.key} className={`wld-faction${war.winner === side.key ? " is-winner" : ""}`}>
            <b>{side.sector?.name ?? "?"}</b>
            <p>{side.stance}</p>
            {side.case && <blockquote><p>{side.case}</p></blockquote>}
            {war.status === "awaiting" && (
              <button type="button" className="ofc-btn ofc-btn--small" disabled={busy}
                      onClick={() => void run(() => worldApi.decide(snapshot.world.id, war.wid, side.key))}>
                Side with {side.sector?.name ?? side.key.toUpperCase()}
              </button>
            )}
          </div>
        ))}
      </div>
      {war.status === "open" && (
        <>
          <p className="ofc-muted">{snapshot.world.status !== "running"
            ? "The government settles it once the world is running — unless you open a resolution first."
            : left > 0 ? `The government settles it in ${span(left)} unless you open a resolution.`
              : "The government is settling it now."}</p>
          <button type="button" className="ofc-btn ofc-btn--primary" disabled={busy}
                  onClick={() => void run(() => worldApi.hearing(snapshot.world.id, war.wid))}>
            Open a resolution
          </button>
        </>
      )}
      {war.status === "hearing" && <p className="ofc-muted wld-thinking"><i aria-hidden="true" />Each side is preparing its case…</p>}
      {war.status === "awaiting" && (
        <div className="wld-own">
          <label htmlFor={`own-${war.wid}`}>Or decide your own way</label>
          <textarea id={`own-${war.wid}`} rows={2} value={own} onChange={(e) => setOwn(e.currentTarget.value)}
                    placeholder="What you want instead…" />
          <button type="button" className="ofc-btn ofc-btn--small" disabled={busy || own.trim().length < 4}
                  onClick={() => void run(() => worldApi.decide(snapshot.world.id, war.wid, "own", own))}>
            Decide this way
          </button>
        </div>
      )}
      {war.status === "resolved" && (
        <>
          <Row label="Settled by">{war.by === "owner" ? "You" : "The government"}</Row>
          <p className="wld-card__lead"><b>Decision:</b> {war.decision}</p>
          {war.why && <p className="ofc-muted">{war.why}</p>}
        </>
      )}
    </>
  );
}

function StartupCard({ snapshot, id, agents, onChanged, onError, onPick }: Props & { id: string }) {
  const [busy, setBusy] = useState(false);
  const startup = snapshot.startups.find((s) => s.suid === id);
  if (!startup) return <Gone what="start-up" />;
  const act = async (action: "approve" | "decline") => {
    setBusy(true);
    const result = await worldApi.startup(snapshot.world.id, id, action);
    setBusy(false);
    if (!result.ok) onError(result.error);
    onChanged();
  };
  return (
    <>
      <p className="wld-card__eyebrow">Start-up · {startup.status}</p>
      <h3>{startup.name}</h3>
      <p className="wld-card__lead">{startup.idea}</p>
      {startup.why && <p className="ofc-muted">{startup.why}</p>}
      <Row label="Proposed by">{startup.by || "—"}</Row>
      <Row label="Founders">{startup.founders.map((f) => agents[f]?.name ?? "an AI").join(", ") || "—"}</Row>
      {startup.status === "proposed" && (
        <div className="wld-actions">
          <button type="button" className="ofc-btn ofc-btn--primary" disabled={busy} onClick={() => void act("approve")}>Approve</button>
          <button type="button" className="ofc-btn" disabled={busy} onClick={() => void act("decline")}>Decline</button>
        </div>
      )}
      {startup.status === "approved" && <p className="ofc-muted">Approved — waiting for room in the world.</p>}
      {startup.sector && <button type="button" className="ofc-link" onClick={() => onPick({ kind: "sector", id: startup.sector })}>Open its sector</button>}
    </>
  );
}

function GraveCard({ snapshot, id, onChanged, onError }: Props & { id: number }) {
  const [busy, setBusy] = useState(false);
  const grave = snapshot.graves.find((g) => g.gid === id);
  if (!grave) return <Gone what="grave" />;
  const bringBack = async () => {
    setBusy(true);
    const result = await worldApi.rejoin(snapshot.world.id, id);
    setBusy(false);
    if (!result.ok) onError(result.error);
    onChanged();
  };
  return (
    <>
      <p className="wld-card__eyebrow">Here lies</p>
      <h3>{grave.name}</h3>
      <p className="wld-card__lead">{grave.role}{grave.sector ? ` of ${grave.sector}` : ""}</p>
      <Row label="Lived">{gameDate(grave.born_day)} → {gameDate(grave.died_day)}</Row>
      <p className="wld-epitaph">“{grave.epitaph}”</p>
      {grave.rejoined ? <p className="ofc-muted">Came back to work.</p> : (
        <button type="button" className="ofc-btn ofc-btn--small" disabled={busy} onClick={() => void bringBack()}>
          {busy ? "Bringing back…" : "Bring back to work"}
        </button>
      )}
    </>
  );
}

function LawCard({ snapshot, id, onChanged, onError }: Props & { id: number }) {
  const law = snapshot.laws.find((l) => l.lid === id);
  if (!law) return <Gone what="law" />;
  const act = async (action: "enforce" | "repeal") => {
    const result = await worldApi.law(snapshot.world.id, id, action);
    if (!result.ok) onError(result.error);
    onChanged();
  };
  const where = law.scope === "world" ? "The whole world" : snapshot.sectors.find((s) => s.sid === law.sector)?.name ?? "A sector";
  return (
    <>
      <p className="wld-card__eyebrow">Law · {law.status}</p>
      <h3>{law.text}</h3>
      <Row label="Applies to">{where}</Row>
      <Row label="Made by">{law.by || "—"}</Row>
      <Row label="On">{gameDate(law.day)}</Row>
      {law.note && <p className="ofc-muted">{law.note}</p>}
      <div className="wld-actions">
        {law.status !== "enforced" && law.status !== "rejected" &&
          <button type="button" className="ofc-btn ofc-btn--small" onClick={() => void act("enforce")}>Enforce</button>}
        {(law.status === "enforced" || law.status === "testing") &&
          <button type="button" className="ofc-btn ofc-btn--small ofc-btn--risk" onClick={() => void act("repeal")}>Repeal</button>}
      </div>
    </>
  );
}

function StationCard({ snapshot, id }: Props & { id: number }) {
  const planet = id >= 100;
  return (
    <>
      <p className="wld-card__eyebrow">In orbit</p>
      <h3>{planet ? `Artificial planet ${id - 99}` : `Space station ${id + 1}`}</h3>
      <p className="wld-card__lead">
        {planet ? "Built in the Stellar era, when the stations were not enough." :
          "Built when the planet ran out of room — where the world's more advanced agents work."}
      </p>
      <Row label="Era">{snapshot.world.era_name}</Row>
    </>
  );
}
