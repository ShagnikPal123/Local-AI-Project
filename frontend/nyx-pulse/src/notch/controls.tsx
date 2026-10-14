/** The notch's controls row and home cards (Fixer Upper S30; reference image p05: system icons left of the camera,
 * the owner's apps right of it, then music · weather · calendar · timer cards underneath).
 *
 * Nothing here decides what runs on the PC: a button sends a control id or a launcher id, and notch_controls.py
 * looks it up in its closed set or the owner's saved launchers.
 */

import { useCallback, useEffect, useState } from "react";
import { controlsApi, type DayPlan, type HomeViewId, type Launcher, type NotchControls, type Playing, type Timer, type Weather } from "./notchApi";

const svg = (d: React.ReactNode, size = 15, fill = false) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill ? "currentColor" : "none"} stroke={fill ? "none" : "currentColor"}
    strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);

/** One icon per system control (notch_controls.SYSTEM's icon names). */
export const ControlIcon: Record<string, () => React.ReactElement> = {
  gear: () => svg(<><circle cx="12" cy="12" r="3.2" /><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6" /></>),
  sliders: () => svg(<path d="M4 7h10M18 7h2M4 17h4M12 17h8M14 4.5v5M8 14.5v5" />),
  sound: () => svg(<><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor" /><path d="M15.5 9a4 4 0 0 1 0 6M18.3 6.5a7.5 7.5 0 0 1 0 11" /></>),
  sun: () => svg(<><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" /></>),
  contrast: () => svg(<><circle cx="12" cy="12" r="8.5" /><path d="M12 3.5v17a8.5 8.5 0 0 0 0-17z" fill="currentColor" /></>),
  folder: () => svg(<path d="M3.5 6.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2V17.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" />),
  terminal: () => svg(<><rect x="3" y="4.5" width="18" height="15" rx="2.5" /><path d="m7 9.5 3 2.5-3 2.5M12.5 15h4.5" /></>),
  pulse: () => svg(<path d="M3 12h4l2.5-6 4 12 2.5-6H21" />),
  volume_down: () => svg(<><path d="M5 9.5h3.5L13 5.5v13l-4.5-4H5z" fill="currentColor" /><path d="M16.5 12h4" /></>),
  volume_up: () => svg(<><path d="M5 9.5h3.5L13 5.5v13l-4.5-4H5z" fill="currentColor" /><path d="M16.5 12h4M18.5 10v4" /></>),
  mute: () => svg(<><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor" /><path d="m16 9.5 5 5M21 9.5l-5 5" /></>),
  play: () => svg(<path d="M7 5v14l11-7z" />, 14, true),
  next: () => svg(<path d="M5 6v12l8.5-6zM14 6v12l6.5-6z" />, 14, true),
  previous: () => svg(<path d="M19 6v12l-8.5-6zM10 6v12L3.5 12z" />, 14, true),
};

const KIND_ICON: Record<Launcher["kind"], React.ReactNode> = {
  app: svg(<><rect x="4" y="4" width="7" height="7" rx="2" /><rect x="13" y="4" width="7" height="7" rx="2" /><rect x="4" y="13" width="7" height="7" rx="2" /><rect x="13" y="13" width="7" height="7" rx="2" /></>, 13),
  site: svg(<><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.5 2.6 2.5 14.4 0 17M12 3.5c-2.5 2.6-2.5 14.4 0 17" /></>, 13),
  folder: svg(<path d="M3.5 6.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2V17.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" />, 13),
  command: svg(<path d="m6 8 4 4-4 4M12 16h6" />, 13),
};

/** The controls and launchers, loaded once and refreshed when the setup page saves. */
export function useControls(): { controls: NotchControls | null; reload: () => void } {
  const [controls, setControls] = useState<NotchControls | null>(null);
  const reload = useCallback(() => {
    void controlsApi.get().then((r) => { if (r.ok) setControls(r.data); });
  }, []);
  useEffect(() => {
    reload();
    const id = window.setInterval(reload, 15_000);
    return () => window.clearInterval(id);
  }, [reload]);
  return { controls, reload };
}

/** The p05 strip: system icons on the left of the camera gap, the owner's launchers on the right. */
export function ControlsStrip({ controls, onSaid }: { controls: NotchControls; onSaid: (text: string, ok: boolean) => void }) {
  const labels = Object.fromEntries(controls.available.map((c) => [c.id, c]));
  const run = async (id: string, kind: "system" | "launcher") => {
    const result = await controlsApi.run(id, kind);
    onSaid(result.ok ? result.data.said : result.error, result.ok && result.data.ok);
  };
  return (
    <div className="nx-strip">
      <div className="side">
        {controls.system.map((id) => {
          const c = labels[id];
          if (!c) return null;
          return <button key={id} className="nx-ctl" title={c.label} aria-label={c.label} onClick={() => void run(id, "system")}>
            {(ControlIcon[c.icon] ?? ControlIcon.gear)()}</button>;
        })}
      </div>
      <span className="gap" />
      <div className="side right">
        {controls.launchers.slice(0, 7).map((l) => (
          <button key={l.id} className="nx-launch" title={l.kind === "command" ? `${l.name} — ${l.command}` : l.name}
            aria-label={l.name} style={{ ["--lc" as string]: l.color }} onClick={() => void run(l.id, "launcher")}>
            <span className="glyph">{l.name.slice(0, 1).toUpperCase()}</span>
            <span className="kind">{KIND_ICON[l.kind]}</span>
          </button>
        ))}
        {!controls.launchers.length && <span className="nx-sub hint">Add apps in Equalize › Notch controls</span>}
      </div>
    </div>
  );
}

// ── The cards ───────────────────────────────────────────────────────────────

function usePoll<T>(load: () => Promise<{ ok: true; data: T } | { ok: false; error: string }>, every: number): T | null {
  const [value, setValue] = useState<T | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await load();
      if (alive && r.ok) setValue(r.data);
    };
    void tick();
    const id = window.setInterval(tick, every);
    return () => { alive = false; window.clearInterval(id); };
  }, [load, every]);
  return value;
}

const SKY: Record<string, React.ReactNode> = {
  sun: svg(<><circle cx="12" cy="12" r="4.5" /><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" /></>, 34),
  partly: svg(<><circle cx="9" cy="9" r="3.5" /><path d="M8 19h9a3.5 3.5 0 0 0 0-7 5 5 0 0 0-9.5 1.5A3 3 0 0 0 8 19z" /></>, 34),
  cloud: svg(<path d="M7 18.5h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.4 1.6A3.3 3.3 0 0 0 7 18.5z" />, 34),
  rain: svg(<><path d="M7 14.5h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.4 1.6A3.3 3.3 0 0 0 7 14.5z" /><path d="m9 17.5-1 2.5M13 17.5l-1 2.5M17 17.5l-1 2.5" /></>, 34),
  snow: svg(<><path d="M7 14.5h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.4 1.6A3.3 3.3 0 0 0 7 14.5z" /><path d="M9 18.5h.01M13 19.5h.01M17 18.5h.01" /></>, 34),
  storm: svg(<><path d="M7 14.5h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.4 1.6A3.3 3.3 0 0 0 7 14.5z" /><path d="m12.5 15-2 3.5h3l-2 3.5" /></>, 34),
  fog: svg(<path d="M4 9h16M6 13h12M4 17h16" />, 34),
};

export function NowPlayingCard({ wide = false }: { wide?: boolean }) {
  const playing = usePoll<Playing>(controlsApi.playing, 3000);
  const media = (op: string) => void controlsApi.run(op, "system");
  const has = playing?.ok && playing.title;
  return (
    <div className={`nx-card nx-wcard music ${wide ? "wide" : ""}`}>
      <div className="art" aria-hidden="true"><span /></div>
      <div className="nx-grow">
        <div className="nx-title nx-ellipsis">{has ? playing!.title : "Nothing playing"}</div>
        <div className="nx-sub nx-ellipsis">{has ? playing!.artist || prettyApp(playing!.app) : playing?.ok === false ? playing.why : "Spotify, YouTube, any player"}</div>
        <div className="nx-row transport">
          <button className="nx-ctl" aria-label="Previous" onClick={() => media("previous")}>{ControlIcon.previous()}</button>
          <button className="nx-ctl" aria-label="Play or pause" onClick={() => media("play_pause")}>{playing?.playing
            ? svg(<path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" />, 14, true) : ControlIcon.play()}</button>
          <button className="nx-ctl" aria-label="Next" onClick={() => media("next")}>{ControlIcon.next()}</button>
        </div>
      </div>
    </div>
  );
}

function prettyApp(id = ""): string {
  const name = id.split(/[\\!/]/).pop()?.replace(/\.exe$/i, "") ?? "";
  return name.charAt(0).toUpperCase() + name.slice(1);
}

export function WeatherCard() {
  const weather = usePoll<Weather>(controlsApi.weather, 10 * 60_000);
  if (!weather) return <div className="nx-card nx-wcard"><div className="nx-sub">Weather…</div></div>;
  if (!weather.ok) return <div className="nx-card nx-wcard"><div className="nx-sub">{weather.why}</div></div>;
  return (
    <div className="nx-card nx-wcard weather">
      <div className="nx-grow">
        <div className="nx-big">{Math.round(weather.now ?? 0)}°</div>
        <div className="nx-sub nx-ellipsis">{weather.city}{weather.stale ? " · earlier" : ""}</div>
        <div className="nx-sub small">H {Math.round(weather.high ?? 0)}° · L {Math.round(weather.low ?? 0)}°</div>
      </div>
      <span className="sky">{SKY[weather.sky ?? "cloud"] ?? SKY.cloud}</span>
    </div>
  );
}

export function CalendarCard() {
  const day = usePoll<DayPlan>(controlsApi.day, 5 * 60_000);
  const today = new Date();
  const next = day?.events.find((e) => e.all_day || !e.end || e.end >= today.toTimeString().slice(0, 5));
  return (
    <div className="nx-card nx-wcard day">
      <div className="date">
        <span className="dow">{today.toLocaleDateString([], { weekday: "short" }).toUpperCase()}</span>
        <span className="num">{today.getDate()}</span>
      </div>
      <div className="nx-grow">
        {next ? <>
          <div className="nx-title nx-ellipsis">{next.title}</div>
          <div className="nx-sub">{next.all_day ? "All day" : `${next.start}${next.end ? ` – ${next.end}` : ""}`}</div>
        </> : <div className="nx-sub">{day?.ok === false ? day.why : "Nothing else today."}</div>}
      </div>
    </div>
  );
}

export function TimerCard({ timers, now, onOpen }: { timers: Timer[]; now: number; onOpen: () => void }) {
  const left = timers[0] ? Math.max(0, timers[0].ends * 1000 - now) : 25 * 60_000;
  const m = Math.floor(left / 60_000), s = Math.floor((left % 60_000) / 1000);
  return (
    <button className="nx-card nx-wcard timer" onClick={onOpen} aria-label="Timers">
      <div className="nx-big">{m}:{String(s).padStart(2, "0")}</div>
      <span className="nx-round">{svg(<path d="M8 5v14l11-7z" />, 12, true)}</span>
    </button>
  );
}

/** Which card a home view shows on its own. */
export const SINGLE: Partial<Record<HomeViewId, () => React.ReactElement>> = {
  now_playing: () => <NowPlayingCard wide />,
  weather: () => <WeatherCard />,
  calendar: () => <CalendarCard />,
};

export const VIEW_LABEL: Record<HomeViewId, string> = {
  apps: "Apps", now_playing: "Now playing", weather: "Weather", calendar: "Calendar", timer: "Timer", agents: "Agents",
};

/** The dashboard (p05): the strip, then the owner's chosen cards side by side. */
export function AppsView({ controls, timers, now, onTimers, onSaid }: {
  controls: NotchControls; timers: Timer[]; now: number; onTimers: () => void; onSaid: (text: string, ok: boolean) => void;
}) {
  const cards = controls.home.views.filter((v) => v !== "apps" && v !== "agents");
  return (
    <div className="nx-dash">
      <ControlsStrip controls={controls} onSaid={onSaid} />
      <div className="nx-cards">
        {(cards.length ? cards : ["now_playing", "weather", "calendar"] as HomeViewId[]).map((v) => (
          v === "timer" ? <TimerCard key={v} timers={timers} now={now} onOpen={onTimers} />
            : <div key={v} className={`slot ${v}`}>{SINGLE[v]?.()}</div>
        ))}
      </div>
    </div>
  );
}

/** One home view by itself, under the same strip. */
export function SingleView({ view, controls, onSaid }: { view: HomeViewId; controls: NotchControls; onSaid: (text: string, ok: boolean) => void }) {
  return (
    <div className="nx-dash">
      <ControlsStrip controls={controls} onSaid={onSaid} />
      <div className="nx-cards one">{SINGLE[view]?.()}</div>
    </div>
  );
}
