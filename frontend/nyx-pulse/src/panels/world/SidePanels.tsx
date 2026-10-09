/** The world's side panels: Government (laws, contests, start-ups), People (who is awake, asleep, born, buried)
 * and Timeline (the world's own history, in game time and real time). Every row opens its details card. */

import { useState } from "react";
import { gameDate, gameDateShort, when } from "./format";
import type { Pick, WorldSnapshot } from "./types";
import { worldApi } from "./worldApi";

const LAW_ORDER = ["testing", "enforced", "proposed", "repealed", "rejected"];

export function GovernmentPanel({ snapshot, onPick, onChanged, onError }: {
  snapshot: WorldSnapshot;
  onPick: (pick: Pick) => void;
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [text, setText] = useState("");
  const [scope, setScope] = useState("");
  const [busy, setBusy] = useState(false);
  const sectorName = (sid: string) => snapshot.sectors.find((s) => s.sid === sid)?.name ?? "?";
  const laws = [...snapshot.laws].sort((a, b) =>
    LAW_ORDER.indexOf(a.status) - LAW_ORDER.indexOf(b.status) || b.lid - a.lid);
  const wars = [...snapshot.wars].reverse();
  const startups = [...snapshot.startups].reverse();

  const propose = async () => {
    const body = text.trim();
    if (!body) return;
    setBusy(true);
    const result = await worldApi.newLaw(snapshot.world.id, body, scope ? "sector" : "world", scope);
    setBusy(false);
    if (!result.ok) {
      onError(result.error);
      return;
    }
    setText("");
    if (result.data.status === "rejected") onError(result.data.note);
    onChanged();
  };

  return (
    <div className="wld-panel">
      <section aria-labelledby="wld-laws">
        <h3 id="wld-laws">Laws</h3>
        <p className="ofc-muted">Each is checked against your rules, tried on one project, then enforced or repealed.</p>
        <ul className="wld-rows">
          {laws.length === 0 && <li className="ofc-muted">No laws yet — the governments propose them as they work.</li>}
          {laws.map((law) => (
            <li key={law.lid}>
              <button type="button" className="wld-rowbtn" onClick={() => onPick({ kind: "law", id: law.lid })}>
                <span className={`wld-badge is-${law.status}`}>{law.status === "testing" ? "on trial" : law.status}</span>
                <span className="wld-rowbtn__text">{law.text}</span>
                <span className="wld-rowbtn__meta">{law.scope === "world" ? "world" : sectorName(law.sector)}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="wld-newlaw">
          <input value={text} onChange={(e) => setText(e.currentTarget.value)} placeholder="Propose a law of your own…"
                 aria-label="A law of your own" onKeyDown={(e) => { if (e.key === "Enter") void propose(); }} />
          <select value={scope} onChange={(e) => setScope(e.currentTarget.value)} aria-label="Where it applies">
            <option value="">Whole world</option>
            {snapshot.sectors.map((s) => <option key={s.sid} value={s.sid}>{s.name}</option>)}
          </select>
          <button type="button" className="ofc-btn ofc-btn--small" onClick={() => void propose()} disabled={busy || !text.trim()}>
            Propose
          </button>
        </div>
      </section>

      <section aria-labelledby="wld-wars">
        <h3 id="wld-wars">Contests of ideas</h3>
        <ul className="wld-rows">
          {wars.length === 0 && <li className="ofc-muted">No contests. Sectors start one when they would honestly do the next step differently.</li>}
          {wars.map((war) => (
            <li key={war.wid}>
              <button type="button" className="wld-rowbtn" onClick={() => onPick({ kind: "war", id: war.wid })}>
                <span className={`wld-badge is-war-${war.status}`}>{war.status === "awaiting" ? "your call" : war.status}</span>
                <span className="wld-rowbtn__text">{sectorName(war.a)} vs {sectorName(war.b)} — {war.reason}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="wld-startups">
        <h3 id="wld-startups">Start-ups</h3>
        <ul className="wld-rows">
          {startups.length === 0 && <li className="ofc-muted">None yet. A losing idea or a new direction becomes a proposal here.</li>}
          {startups.map((startup) => (
            <li key={startup.suid}>
              <button type="button" className="wld-rowbtn" onClick={() => onPick({ kind: "startup", id: startup.suid })}>
                <span className={`wld-badge is-startup-${startup.status}`}>{startup.status}</span>
                <span className="wld-rowbtn__text">{startup.name} — {startup.idea}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export function PeoplePanel({ snapshot, working, onPick }: {
  snapshot: WorldSnapshot;
  working: Set<string>;
  onPick: (pick: Pick) => void;
}) {
  const world = snapshot.world;
  const born = snapshot.bots.filter((b) => b.parents.length > 0);
  const asleep = snapshot.bots.filter((b) => b.state === "asleep" && !working.has(b.aid));
  const busy = snapshot.bots.filter((b) => working.has(b.aid));
  const graves = [...snapshot.graves].reverse();
  const census = world.census;
  return (
    <div className="wld-panel">
      <div className="wld-stats" role="list">
        <div role="listitem"><b>{world.population.ais}</b><span>AIs</span></div>
        <div role="listitem"><b>{busy.length}</b><span>working</span></div>
        <div role="listitem"><b>{asleep.length}</b><span>asleep</span></div>
        <div role="listitem"><b>{world.population.common}</b><span>common bots</span></div>
        <div role="listitem"><b>{world.births}</b><span>born</span></div>
        <div role="listitem"><b>{world.deaths}</b><span>laid to rest</span></div>
      </div>
      <p className="ofc-muted">At most {snapshot.limits.population} AIs on this {snapshot.limits.machine} machine. Common bots
        build and keep things and use no model.</p>
      {census && (
        <div className="wld-census" role="status">
          <b>Census {census.index}/{census.total}</b> — {census.sector_name}: checking the {census.level}
          {census.checked ? ` (${census.checked})` : ""}
        </div>
      )}

      <section aria-labelledby="wld-born">
        <h3 id="wld-born">Born here</h3>
        <ul className="wld-rows">
          {born.length === 0 && <li className="ofc-muted">No children yet — two trades make one after a project they both delivered.</li>}
          {born.map((bot) => (
            <li key={bot.aid}>
              <button type="button" className="wld-rowbtn" onClick={() => onPick({ kind: "bot", id: bot.aid })}>
                <span className="wld-badge is-born">gen {bot.generation}</span>
                <span className="wld-rowbtn__text">{bot.name} — {bot.role}</span>
                <span className="wld-rowbtn__meta">{gameDateShort(bot.born_day)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="wld-asleep">
        <h3 id="wld-asleep">Asleep</h3>
        <ul className="wld-rows">
          {asleep.length === 0 && <li className="ofc-muted">Everyone is awake.</li>}
          {asleep.slice(0, 40).map((bot) => (
            <li key={bot.aid}>
              <button type="button" className="wld-rowbtn" onClick={() => onPick({ kind: "bot", id: bot.aid })}>
                <span className="wld-badge is-asleep">zz</span>
                <span className="wld-rowbtn__text">{bot.name} — {bot.role}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="wld-graves">
        <h3 id="wld-graves">Graves</h3>
        <ul className="wld-rows">
          {graves.length === 0 && <li className="ofc-muted">No one has been let go.</li>}
          {graves.slice(0, 60).map((grave) => (
            <li key={grave.gid}>
              <button type="button" className="wld-rowbtn" onClick={() => onPick({ kind: "grave", id: grave.gid })}>
                <span className="wld-badge is-grave">{grave.rejoined ? "back" : "†"}</span>
                <span className="wld-rowbtn__text">{grave.name} — {grave.epitaph}</span>
                <span className="wld-rowbtn__meta">{gameDateShort(grave.died_day)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

const EVENT_GLYPHS: Record<string, string> = {
  founded: "✦", project: "▶", done: "✓", era: "★", law: "§", war: "⚔", startup: "⚑", birth: "♥", death: "†",
  build: "▲", teardown: "▼", station: "◎", census: "≡", owner: "●", stall: "■", note: "·", retool: "↻", rejoin: "↺",
};

export function TimelinePanel({ snapshot }: { snapshot: WorldSnapshot }) {
  const events = [...snapshot.timeline].reverse();
  const projects = [...snapshot.projects].reverse();
  return (
    <div className="wld-panel">
      <section aria-labelledby="wld-projects">
        <h3 id="wld-projects">Projects</h3>
        <ul className="wld-rows">
          {projects.length === 0 && <li className="ofc-muted">No projects yet.</li>}
          {projects.map((project) => (
            <li key={project.n} className="wld-project">
              <span className={`wld-badge is-p-${project.status}`}>{project.status === "running" ? "now" : project.status}</span>
              <div>
                <b>{project.n}. {project.title}</b>
                {project.summary && <p>{project.summary}</p>}
                <small>{gameDate(project.day)} · {when(project.started_at)}</small>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="wld-history">
        <h3 id="wld-history">History</h3>
        <ol className="wld-history">
          {events.map((event, index) => (
            <li key={`${event.ts}-${index}`} className={`is-${event.kind}`}>
              <span className="wld-history__glyph" aria-hidden="true">{EVENT_GLYPHS[event.kind] ?? "·"}</span>
              <div>
                <p>{event.text}</p>
                <small>{gameDateShort(event.day)} · {when(event.ts)}</small>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
