/** One world, open: the planet, the controls, the details card, the side panels and the timeline. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { OutputBox } from "../office/OutputBox";
import { useOffice } from "../office/useOffice";
import { SpeedControl, TimelineStrip } from "./Controls";
import { KIND_LABELS, STATUS_WORDS, span } from "./format";
import { Inspector } from "./Inspector";
import { PlanetScene, type AgentLook, type PlanetHandle } from "./planet/PlanetScene";
import { GovernmentPanel, PeoplePanel, TimelinePanel } from "./SidePanels";
import type { Pick, SpeedId } from "./types";
import { useWorld } from "./useWorld";
import { WorldChat } from "./WorldChat";
import { worldApi } from "./worldApi";

type Side = "talk" | "government" | "people" | "timeline";

const RUN_TIMES = [
  { value: "until done", label: "Until the goal is met" },
  { value: "1 hour", label: "1 hour" },
  { value: "8 hours", label: "8 hours" },
  { value: "1 day", label: "1 day" },
  { value: "5 days", label: "5 days" },
  { value: "2 weeks", label: "2 weeks" },
  { value: "1 month", label: "1 month" },
];

export function WorldView({ worldId, onLobby, onError }: {
  worldId: string;
  onLobby: () => void;
  onError: (message: string) => void;
}) {
  const live = useWorld(worldId);
  const snapshot = live.snapshot;
  const office = useOffice(snapshot?.world.office_id ?? "");
  const planet = useRef<PlanetHandle | null>(null);
  const [pick, setPick] = useState<Pick | null>(null);
  const [side, setSide] = useState<Side>("talk");
  const [sending, setSending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState("");
  const [menu, setMenu] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState("");

  const choose = useCallback((next: Pick | null) => {
    setPick(next);
    planet.current?.focus(next);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !(event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement)) {
        setPick(null);
        planet.current?.reset();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const agents = office.agentsById;
  const looks = useMemo<Record<string, AgentLook>>(() => Object.fromEntries(
    Object.values(agents).map((a) => [a.id, { status: a.status, role: a.role, employment: a.employment, step: a.step }])),
  [agents]);
  const roleColors = useMemo(() => Object.fromEntries(Object.values(office.rolesById).map((r) => [r.id, r.color])),
    [office.rolesById]);
  const sectionColors = useMemo(() => Object.fromEntries(Object.values(office.sectionsById).map((s) => [s.id, s.color])),
    [office.sectionsById]);
  const working = useMemo(() => new Set(Object.values(agents).filter((a) => a.status === "working").map((a) => a.id)),
    [agents]);

  if (!snapshot) {
    return (
      <div className="wld-message">
        {live.error ? <><p className="ofc-error">{live.error}</p><button className="ofc-btn" onClick={onLobby}>All worlds</button></>
          : <p className="ofc-muted">Opening the world…</p>}
      </div>
    );
  }
  const world = snapshot.world;

  const control = async (action: "start" | "pause" | "resume" | "stop", haltOffice = false) => {
    setBusy(true);
    const result = await worldApi.control(world.id, action, haltOffice);
    setBusy(false);
    if (result.ok) {
      live.apply(result.data);
      setBlocked("");
    } else if (/office .* is working/i.test(result.error)) {
      setBlocked(result.error);
    } else {
      onError(result.error);
    }
  };

  const say = async (text: string) => {
    setSending(true);
    const result = await worldApi.say(world.id, text);
    setSending(false);
    if (result.ok) {
      live.apply(result.data.snapshot);
      void office.reload();
    } else if (/office .* is working/i.test(result.error)) {
      setBlocked(result.error);
    } else {
      onError(result.error);
    }
  };

  const setSpeed = async (speed: SpeedId) => {
    const result = await worldApi.speed(world.id, speed);
    if (result.ok) live.apply(result.data);
    else onError(result.error);
  };

  const patch = async (changes: { name?: string; duration?: string; settings?: Record<string, unknown> }) => {
    const result = await worldApi.patch(world.id, changes);
    if (result.ok) live.apply(result.data);
    else onError(result.error);
  };

  const trash = async () => {
    if (!window.confirm(`Move “${world.name}” to the trash? Its office and the files its AIs made stay in Office Space.`)) return;
    const result = await worldApi.trash(world.id);
    if (result.ok) onLobby();
    else onError(result.error);
  };

  const crumbs: { label: string; pick: Pick | null }[] = [{ label: world.name, pick: null }];
  if (pick) {
    const sectorId = pick.kind === "sector" ? pick.id
      : pick.kind === "building" ? snapshot.buildings.find((b) => b.bid === pick.id)?.sector
        : pick.kind === "bot" ? snapshot.bots.find((b) => b.aid === pick.id)?.sector : undefined;
    const sector = snapshot.sectors.find((s) => s.sid === sectorId);
    if (sector) crumbs.push({ label: sector.name, pick: { kind: "sector", id: sector.sid } });
    if (pick.kind === "building") {
      const building = snapshot.buildings.find((b) => b.bid === pick.id);
      if (building) crumbs.push({ label: KIND_LABELS[building.kind] ?? building.kind, pick });
    }
    if (pick.kind === "bot") {
      const bot = snapshot.bots.find((b) => b.aid === pick.id);
      if (bot) crumbs.push({ label: bot.name, pick });
    }
  }

  const running = world.status === "running";
  const paused = world.status === "paused";
  const leaderWord = world.leader.kahuna ? "Big Kahuna" : world.leader.name;
  const government = snapshot.sectors.find((s) => s.important)?.gov ?? "World Government";

  return (
    <div className="wld-view">
      <header className="wld-top">
        <button type="button" className="ofc-link" onClick={onLobby}>All worlds</button>
        {renaming ? (
          <input className="wld-rename" autoFocus value={name} aria-label="World name"
                 onChange={(e) => setName(e.currentTarget.value)}
                 onBlur={() => setRenaming(false)}
                 onKeyDown={(e) => {
                   if (e.key === "Enter" && name.trim()) { void patch({ name: name.trim() }); setRenaming(false); }
                   if (e.key === "Escape") setRenaming(false);
                 }} />
        ) : (
          <h1 title="Rename" onDoubleClick={() => { setName(world.name); setRenaming(true); }}>{world.name}</h1>
        )}
        <span className={`ofc-pill is-${running ? "running" : paused ? "paused" : world.status === "stopped" ? "halted" : "idle"}`}>
          <i />{STATUS_WORDS[world.status] ?? world.status}
        </span>
        <span className="wld-era" title={world.next_era_at ? `${world.tech_points} of ${world.next_era_at} tech points to the next era` : "The last era"}>
          {world.era_name}
          {world.next_era_at && <span className="wld-era__bar" style={{ ["--p" as string]: Math.min(1, world.tech_points / world.next_era_at) }} />}
        </span>
        <span className="wld-top__facts">
          {world.population.ais} AIs · {world.population.awake} awake · {world.population.common} common bots
          {world.leader.name ? <> · led by <b>{leaderWord}</b></> : null}
        </span>
        <div className="wld-top__actions">
          <SpeedControl speed={world.speed} limits={snapshot.limits} onChange={(s) => void setSpeed(s)} />
          {(world.status === "idle" || world.status === "complete" || world.status === "stopped") && (
            <button type="button" className="ofc-btn ofc-btn--primary" disabled={busy || (!world.goal && !snapshot.commands.length)}
                    title={world.goal ? "Start the world: everything else on this computer pauses until it stops" : "Give it a goal in the world chat first"}
                    onClick={() => void control("start")}>
              {world.status === "idle" ? "Start" : "Run again"}
            </button>
          )}
          {running && <button type="button" className="ofc-btn ofc-btn--small" disabled={busy} onClick={() => void control("pause")}>Pause</button>}
          {paused && <button type="button" className="ofc-btn ofc-btn--primary" disabled={busy} onClick={() => void control("resume")}>Resume</button>}
          {(running || paused) && <button type="button" className="ofc-btn ofc-btn--small ofc-btn--risk" disabled={busy} onClick={() => void control("stop")}>Stop</button>}
          <div className="wld-menu">
            <button type="button" className="ofc-icon" aria-haspopup="menu" aria-expanded={menu} aria-label="More"
                    onClick={() => setMenu((open) => !open)}>⋯</button>
            {menu && (
              <div className="wld-menu__list" role="menu" onMouseLeave={() => setMenu(false)}>
                <label role="menuitem">
                  <span>Run for</span>
                  <select value="" onChange={(e) => { if (e.currentTarget.value) void patch({ duration: e.currentTarget.value }); setMenu(false); }}>
                    <option value="">{world.duration ? span(world.duration) : "Until the goal is met"}</option>
                    {RUN_TIMES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                  </select>
                </label>
                <label role="menuitemcheckbox" aria-checked={Boolean(world.settings.share_machine)}>
                  <input type="checkbox" checked={Boolean(world.settings.share_machine)}
                         onChange={(e) => void patch({ settings: { share_machine: e.currentTarget.checked } })} />
                  <span>Let the rest of Nyx keep running</span>
                </label>
                <button type="button" role="menuitem" onClick={() => { setName(world.name); setRenaming(true); setMenu(false); }}>Rename</button>
                <button type="button" role="menuitem" onClick={() => window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "office" } }))}>
                  Open its office
                </button>
                <button type="button" role="menuitem" className="is-risk" onClick={() => void trash()}>Move to trash</button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="wld-body">
        <div className="wld-stage">
          <PlanetScene ref={planet} snapshot={snapshot} version={live.version} agents={looks} roleColors={roleColors}
                       sectionColors={sectionColors} talks={office.talks} selected={pick} onPick={choose}
                       inset={pick ? 384 : 0} />

          <nav className="wld-crumbs" aria-label="Where you are">
            {crumbs.map((crumb, index) => (
              <button key={index} type="button" className={index === crumbs.length - 1 ? "is-here" : ""}
                      onClick={() => (crumb.pick ? choose(crumb.pick) : (setPick(null), planet.current?.reset()))}>
                {crumb.label}
              </button>
            ))}
          </nav>
          <div className="wld-zoom">
            <button type="button" aria-label="Zoom in" onClick={() => planet.current?.zoom(0.75)}>+</button>
            <button type="button" aria-label="Zoom out" onClick={() => planet.current?.zoom(1.35)}>−</button>
            <button type="button" aria-label="The whole planet" title="The whole planet (Esc)"
                    onClick={() => { setPick(null); planet.current?.reset(); }}>◎</button>
            <button type="button" aria-label="About the world" title="About the world" onClick={() => setPick({ kind: "world" })}>i</button>
          </div>

          <div className="wld-banners">
            {blocked && (
              <div className="wld-banner is-warn" role="alert">
                <p>{blocked}</p>
                <button type="button" className="ofc-btn ofc-btn--small ofc-btn--risk" onClick={() => void control("start", true)}>
                  Halt that office and start the world
                </button>
                <button type="button" className="ofc-link" onClick={() => setBlocked("")}>Not now</button>
              </div>
            )}
            {world.census && (
              <div className="wld-banner" role="status">
                <b>Census</b> {world.census.index}/{world.census.total} — {world.census.sector_name}: the {world.census.level}
                <span className="wld-banner__bar" style={{ ["--p" as string]: world.census.index / world.census.total }} />
              </div>
            )}
            {world.stalled && <div className="wld-banner is-warn" role="status">{world.stalled}</div>}
            {world.note && !running && <div className="wld-banner" role="status">{world.note}</div>}
            {world.project && running && (
              <div className="wld-banner is-project" role="status">
                <b>Project {world.project.n}</b> {world.project.title}
              </div>
            )}
            {!world.goal && world.status === "idle" && (
              <div className="wld-banner" role="status">An empty planet. Tell it what to work toward in the world chat.</div>
            )}
          </div>

          {pick && (
            <Inspector pick={pick} snapshot={snapshot} agents={agents} sections={office.sectionsById}
                       roles={office.rolesById} tasks={office.snapshot?.tasks ?? []} onPick={choose}
                       onClose={() => setPick(null)} onChanged={() => void live.reload()} onError={onError} />
          )}
        </div>

        <aside className="wld-side" aria-label="The world's panels">
          <div className="wld-tabs" role="tablist">
            {(["talk", "government", "people", "timeline"] as Side[]).map((id) => (
              <button key={id} type="button" role="tab" aria-selected={side === id} className={side === id ? "is-on" : ""}
                      onClick={() => setSide(id)}>
                {id === "talk" ? "Talk & output" : id === "government" ? "Government" : id === "people" ? "People" : "Timeline"}
                {id === "government" && snapshot.wars.some((w) => w.status === "awaiting") ? <i className="wld-dotnote" /> : null}
                {id === "government" && snapshot.startups.some((s) => s.status === "proposed") ? <i className="wld-dotnote" /> : null}
              </button>
            ))}
          </div>
          <div className="wld-side__body">
            {side === "talk" && (
              <>
                <WorldChat messages={office.snapshot?.chat ?? []} government={government} queued={snapshot.commands}
                           running={running} thinking={world.thinking} onSend={say} sending={sending} />
                <OutputBox officeId={world.office_id} outputs={office.snapshot?.outputs ?? []} onError={onError} />
              </>
            )}
            {side === "government" && (
              <GovernmentPanel snapshot={snapshot} onPick={choose} onChanged={() => void live.reload()} onError={onError} />
            )}
            {side === "people" && <PeoplePanel snapshot={snapshot} working={working} onPick={choose} />}
            {side === "timeline" && <TimelinePanel snapshot={snapshot} />}
          </div>
        </aside>
      </div>

      <TimelineStrip snapshot={snapshot} />
    </div>
  );
}
