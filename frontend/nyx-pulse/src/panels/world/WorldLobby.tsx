/** The worlds you have, a new one, and upscaling an office into one (U34: *"when the user wants basically a super
 * large scale project they can press upscale for the office"*). */

import { useState } from "react";
import { gameDate, span, STATUS_WORDS, when } from "./format";
import type { SpeedId, WorldOverview } from "./types";
import { worldApi } from "./worldApi";

const RUN_TIMES = [
  { value: "until done", label: "Until the goal is met" },
  { value: "1 hour", label: "1 hour" },
  { value: "8 hours", label: "8 hours" },
  { value: "1 day", label: "1 day" },
  { value: "5 days", label: "5 days" },
  { value: "2 weeks", label: "2 weeks" },
  { value: "1 month", label: "1 month" },
];

export function WorldLobby({ overview, onOpen, onChanged, onError }: {
  overview: WorldOverview;
  onOpen: (id: string) => void;
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [duration, setDuration] = useState("until done");
  const [speed, setSpeed] = useState<SpeedId>("steady");
  const [making, setMaking] = useState(false);
  const [upscaling, setUpscaling] = useState("");
  const limits = overview.limits;

  const found = async () => {
    setMaking(true);
    const result = await worldApi.create({ name, goal, duration, speed });
    setMaking(false);
    if (!result.ok) {
      onError(result.error);
      return;
    }
    onChanged();
    onOpen(result.data.world.id);
  };

  const upscale = async (officeId: string) => {
    setUpscaling(officeId);
    const result = await worldApi.upscale(officeId, { speed });
    setUpscaling("");
    if (!result.ok) {
      onError(result.error);
      return;
    }
    onChanged();
    onOpen(result.data.world.id);
  };

  return (
    <div className="wld-lobby">
      <header className="wld-lobby__head">
        <p className="wld-card__eyebrow">AI Environment</p>
        <h1>Worlds</h1>
        <p className="wld-lobby__lede">
          A planet for projects too big for one office: it starts as bare rock, and grows as its AIs deliver — sectors with
          their own governments, laws, contests of ideas, start-ups, and in time space stations. The work is real; the
          planet is how you watch it.
        </p>
        <p className="ofc-muted">{limits.reason}</p>
      </header>

      <div className="wld-lobby__grid">
        <section className="wld-new" aria-labelledby="wld-new-title">
          <h2 id="wld-new-title">Found a world</h2>
          <label htmlFor="wld-goal">What should it work toward?</label>
          <textarea id="wld-goal" rows={4} value={goal} onChange={(e) => setGoal(e.currentTarget.value)}
                    placeholder="A recipe site with a weekly meal planner, a shopping list and a guide to using it" />
          <div className="wld-new__row">
            <label>
              <span>Name</span>
              <input value={name} onChange={(e) => setName(e.currentTarget.value)} placeholder="Taken from the goal" />
            </label>
            <label>
              <span>Run for</span>
              <select value={duration} onChange={(e) => setDuration(e.currentTarget.value)}>
                {RUN_TIMES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </label>
          </div>
          <fieldset className="wld-new__speed">
            <legend>Speed</legend>
            {limits.speeds.map((option) => (
              <label key={option.id} className={!option.allowed ? "is-off" : ""}
                     title={option.allowed ? option.what : `Not on this ${limits.machine} machine.`}>
                <input type="radio" name="wld-speed" value={option.id} checked={speed === option.id} disabled={!option.allowed}
                       onChange={() => setSpeed(option.id)} />
                <span>{option.label}</span>
              </label>
            ))}
            <p className="ofc-muted">{limits.speeds.find((s) => s.id === speed)?.what}</p>
          </fieldset>
          <p className="ofc-muted">While a world runs, the rest of Nyx's background work pauses, and starts again by itself
            when the world stops.</p>
          <button type="button" className="ofc-btn ofc-btn--primary" onClick={() => void found()} disabled={making}>
            {making ? "Founding…" : "Found the world"}
          </button>
        </section>

        <section className="wld-upscale" aria-labelledby="wld-up-title">
          <h2 id="wld-up-title">Upscale an office</h2>
          <p className="ofc-muted">Its team become the planet's first citizens; its sections become sectors.</p>
          <ul className="wld-rows">
            {overview.offices.length === 0 && <li className="ofc-muted">No offices yet — make one in Office Space.</li>}
            {overview.offices.map((office) => {
              const world = overview.worlds.find((w) => w.office_id === office.id);
              return (
                <li key={office.id} className="wld-officerow">
                  <div>
                    <b>{office.name}</b>
                    <span className="ofc-muted">{office.agents} agent{office.agents === 1 ? "" : "s"}{office.goal ? ` · ${office.goal}` : ""}</span>
                  </div>
                  {world ? (
                    <button type="button" className="ofc-btn ofc-btn--small" onClick={() => onOpen(world.id)}>Open its world</button>
                  ) : (
                    <button type="button" className="ofc-btn ofc-btn--small" disabled={upscaling === office.id}
                            onClick={() => void upscale(office.id)}>{upscaling === office.id ? "Upscaling…" : "Upscale"}</button>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      </div>

      <section aria-labelledby="wld-list-title" className="wld-worlds">
        <h2 id="wld-list-title">Your worlds</h2>
        {overview.worlds.length === 0 ? <p className="ofc-muted">None yet. Each world is one small file on this computer.</p> : (
          <ul className="wld-worldcards">
            {overview.worlds.map((world) => (
              <li key={world.id}>
                <button type="button" className="wld-worldcard" onClick={() => onOpen(world.id)}>
                  <span className={`wld-orb is-era-${world.era}`} aria-hidden="true" />
                  <span className="wld-worldcard__body">
                    <b>{world.name}</b>
                    <span>{world.goal || "No goal yet"}</span>
                    <small>
                      {STATUS_WORDS[world.status] ?? world.status} · {world.era_name} · {world.population} AIs ·
                      {" "}{world.buildings} buildings · {gameDate(world.game_days)}
                      {world.real_seconds ? ` · ran ${span(world.real_seconds)}` : ""} · {when(world.updated_at)}
                      {` · ${Math.max(1, Math.round(world.size / 1024))} KB`}
                    </small>
                  </span>
                  {overview.running === world.id && <span className="ofc-pill is-running"><i />running</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
