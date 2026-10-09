/** One world, live.
 *
 * The snapshot is fetched once and kept current by ``world.event`` messages on the workspace stream — a building
 * going up, a bot falling asleep, a law enforced, a contest settled, the clock moving. Each event carries the whole
 * record that changed, so applying one is an upsert, and a dropped event heals on the next quiet re-fetch (every
 * 15 seconds, and whenever the window gets focus back). The world keeps running whether or not this tab is open.
 */

import { useCallback, useEffect, useState } from "react";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { worldApi } from "./worldApi";
import type {
  CensusStep, WorldBot, WorldBuilding, WorldGrave, WorldHead, WorldLaw, WorldProject, WorldSector, WorldSnapshot,
  WorldStartup, WorldTech, WorldWar,
} from "./types";

const HEAL_MS = 15_000;
/** Events that change what the planet draws (the rest only change the side panels). */
const SCENE_KINDS = new Set(["world", "sector", "bot", "grave", "building", "building.gone", "war", "startup", "era", "sky"]);
const READ_KINDS = new Set(["project", "war", "startup", "grave", "era", "tech"]);

export interface WorldLive {
  snapshot: WorldSnapshot | null;
  error: string;
  reload: () => Promise<void>;
  apply: (snapshot: WorldSnapshot) => void;
  /** Bumps every time something on the planet changes, so the scene knows to look again. */
  version: number;
}

function upsert<T>(rows: T[], row: T, key: (r: T) => string | number): T[] {
  const id = key(row);
  const index = rows.findIndex((r) => key(r) === id);
  if (index === -1) return [...rows, row];
  const copy = rows.slice();
  copy[index] = { ...copy[index], ...row };
  return copy;
}

export function useWorld(worldId: string): WorldLive {
  const [snapshot, setSnapshot] = useState<WorldSnapshot | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);

  const reload = useCallback(async () => {
    if (!worldId) return;
    const result = await worldApi.snapshot(worldId);
    if (result.ok) {
      setSnapshot(result.data);
      setVersion((v) => v + 1);
      setError("");
    } else {
      setError(result.error);
    }
  }, [worldId]);

  useEffect(() => {
    setSnapshot(null);
    void reload();
  }, [reload]);

  useEffect(() => {
    if (!worldId) return undefined;
    const timer = window.setInterval(() => void reload(), HEAL_MS);
    const onFocus = () => void reload();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [worldId, reload]);

  useEffect(() => {
    if (!worldId) return undefined;
    return onWorkspaceEvent((event) => {
      if (event.type !== "world.event" || event.world_id !== worldId) return;
      const kind = String(event.kind ?? "");
      setSnapshot((current) => {
        if (!current) return current;
        switch (kind) {
          case "world":
            return { ...current, world: { ...current.world, ...(event.world as Partial<WorldHead>) } };
          case "clock": {
            const population = event.population as WorldHead["population"] | undefined;
            return {
              ...current,
              world: {
                ...current.world,
                game_days: Number(event.game_days ?? current.world.game_days),
                game_date: String(event.game_date ?? current.world.game_date),
                spent: Number(event.spent ?? current.world.spent),
                real_seconds: Number(event.real_seconds ?? current.world.real_seconds),
                tech_points: Number(event.tech_points ?? current.world.tech_points),
                population: population ? { ...current.world.population, ...population } : current.world.population,
                time_left: current.world.duration
                  ? Math.max(0, current.world.duration - Number(event.spent ?? current.world.spent)) : null,
              },
            };
          }
          case "sector":
            return { ...current, sectors: upsert(current.sectors, event.sector as WorldSector, (s) => s.sid) };
          case "bot":
            return { ...current, bots: upsert(current.bots, event.bot as WorldBot, (b) => b.aid) };
          case "grave": {
            const grave = event.grave as WorldGrave;
            return {
              ...current,
              graves: upsert(current.graves, grave, (g) => g.gid),
              bots: current.bots.filter((b) => b.aid !== String(event.aid ?? grave.aid)),
            };
          }
          case "building":
            return { ...current, buildings: upsert(current.buildings, event.building as WorldBuilding, (b) => b.bid) };
          case "building.gone":
            return { ...current, buildings: current.buildings.filter((b) => b.bid !== Number(event.bid)) };
          case "law":
            return { ...current, laws: upsert(current.laws, event.law as WorldLaw, (l) => l.lid) };
          case "war":
            return { ...current, wars: upsert(current.wars, event.war as WorldWar, (w) => w.wid) };
          case "startup":
            return { ...current, startups: upsert(current.startups, event.startup as WorldStartup, (s) => s.suid) };
          case "project":
            return { ...current, projects: upsert(current.projects, event.project as WorldProject, (p) => p.n) };
          case "census":
            return { ...current, world: { ...current.world, census: (event.census as CensusStep | null) ?? null } };
          case "era":
            return { ...current, world: { ...current.world, era: Number(event.era), era_name: String(event.era_name) } };
          case "tech":
            return { ...current, world: { ...current.world, techs: [...current.world.techs, event.tech as WorldTech].slice(-8) } };
          case "sky":
            return { ...current, world: { ...current.world, stations: Number(event.stations), planets: Number(event.planets) } };
          case "stall":
            return { ...current, world: { ...current.world, stalled: String(event.stalled ?? "") } };
          default:
            return current;
        }
      });
      if (SCENE_KINDS.has(kind)) setVersion((v) => v + 1);
      // Timeline entries and anything not carried whole by the event come back with the next heal; ask for it now
      // when the change is one the owner will want to read about.
      if (READ_KINDS.has(kind)) window.setTimeout(() => void reload(), 400);
    });
  }, [worldId, reload]);

  const apply = useCallback((next: WorldSnapshot) => {
    setSnapshot(next);
    setVersion((v) => v + 1);
  }, []);

  return { snapshot, error, reload, apply, version };
}
