/** The week calendar (Orbits › Calendar): when Orbits will run, plus Google Calendar when it is connected.
 *
 * It draws whatever `/api/scheduled/calendar/week` returns and obeys the saved look (a small checked spec), so the AI can
 * restyle it by changing that spec ("make the calendar compact", "hide weekends") without any UI code being written.
 * The look is re-read every few seconds so such a change shows without a reload.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { Loading } from "../../components/Panel";
import "./calendar.css";

interface Look {
  view: "week" | "agenda"; density: "compact" | "comfortable" | "roomy"; start_hour: number; end_hour: number;
  show_weekend: boolean; week_starts: "mon" | "sun"; colour_by: "avatar" | "repeat" | "source"; accent: string; show_google: boolean;
}
interface Item {
  id: string; title: string; avatar: string; repeat: string; at: number; time: string; day: number; all_day: boolean;
  enabled: boolean; runs: boolean; source: "orbit" | "google";
}
interface Day { date: string; label: string; number: number; today: boolean }
interface Week { start: string; days: Day[]; items: Item[]; look: Look; google: { connected: boolean; error: string } }

const DENSITY_PX = { compact: 30, comfortable: 44, roomy: 62 } as const;

/** A stable colour from a word, so the same avatar is always the same hue. */
function hue(word: string): string {
  let h = 0;
  for (const ch of word) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h} 62% 58%)`;
}

export function colourOf(item: Item, by: Look["colour_by"]): string {
  if (by === "avatar") return item.avatar ? hue(item.avatar) : "var(--color-neutral-500)";
  if (by === "repeat") return item.repeat ? hue(item.repeat) : "var(--color-info, #5aa9ff)";
  return item.source === "google" ? "var(--color-info, #5aa9ff)" : "var(--cal-accent)";
}

/** Items that start close together share the row side by side instead of hiding each other. */
export function lanes(items: Item[]): Map<Item, { lane: number; of: number }> {
  const out = new Map<Item, { lane: number; of: number }>();
  const sorted = [...items].sort((a, b) => a.at - b.at);
  let group: Item[] = [];
  let groupEnd = 0;
  const flush = () => { group.forEach((item, i) => out.set(item, { lane: i, of: group.length })); group = []; };
  for (const item of sorted) {
    if (group.length && item.at >= groupEnd) flush();
    group.push(item);
    groupEnd = Math.max(groupEnd, item.at + 30 * 60);
  }
  flush();
  return out;
}

function minutes(item: Item): number {
  const d = new Date(item.at * 1000);
  return d.getHours() * 60 + d.getMinutes();
}

function Chip({ item, look }: { item: Item; look: Look }) {
  const note = `${item.time} · ${item.title}${item.source === "orbit" ? (item.runs ? "" : " (nobody assigned, never runs)") + (item.enabled ? "" : " (paused)") : " (Google Calendar)"}`;
  return (
    <span className={`cal-chip${item.enabled ? "" : " is-paused"}${item.runs || item.source === "google" ? "" : " is-idle"}`}
      style={{ ["--cal-colour" as string]: colourOf(item, look.colour_by) }} title={note}>
      <b>{item.time}</b> {item.title}
    </span>
  );
}

function WeekGrid({ week }: { week: Week }) {
  const { look } = week;
  const days = week.days.filter((_, i) => look.show_weekend || ![5, 6].includes(look.week_starts === "sun" ? (i + 6) % 7 : i));
  const rowPx = DENSITY_PX[look.density];
  const hours = Array.from({ length: look.end_hour - look.start_hour }, (_, i) => look.start_hour + i);
  const indexOf = (d: Day) => week.days.indexOf(d);
  return (
    <div className="cal-grid" style={{ ["--cal-cols" as string]: days.length, ["--cal-row" as string]: `${rowPx}px` }}>
      <div className="cal-corner" />
      {days.map((d) => (
        <div key={d.date} className={`cal-dayhead${d.today ? " is-today" : ""}`}><small>{d.label}</small><b>{d.number}</b></div>
      ))}
      <div className="cal-allday-label"><small>all day</small></div>
      {days.map((d) => {
        const own = week.items.filter((it) => it.day === indexOf(d));
        const outside = own.filter((it) => !it.all_day && (minutes(it) < look.start_hour * 60 || minutes(it) >= look.end_hour * 60));
        return (
          <div key={d.date} className="cal-allday">
            {own.filter((it) => it.all_day).concat(outside).map((it, i) => <Chip key={`${it.id}${i}`} item={it} look={look} />)}
          </div>
        );
      })}
      <div className="cal-hours" style={{ height: hours.length * rowPx }}>
        {hours.map((h) => <span key={h} style={{ height: rowPx }}>{String(h).padStart(2, "0")}:00</span>)}
      </div>
      {days.map((d) => {
        const timed = week.items.filter((it) => it.day === indexOf(d) && !it.all_day
          && minutes(it) >= look.start_hour * 60 && minutes(it) < look.end_hour * 60);
        const placed = lanes(timed);
        return (
          <div key={d.date} className={`cal-col${d.today ? " is-today" : ""}`} style={{ height: hours.length * rowPx }}>
            {timed.map((it, i) => {
              const spot = placed.get(it) ?? { lane: 0, of: 1 };
              const top = ((minutes(it) - look.start_hour * 60) / 60) * rowPx;
              return (
                <span key={`${it.id}${i}`} className={`cal-event${it.enabled ? "" : " is-paused"}${it.runs || it.source === "google" ? "" : " is-idle"}`}
                  style={{ top, left: `${(spot.lane / spot.of) * 100}%`, width: `${100 / spot.of}%`, ["--cal-colour" as string]: colourOf(it, look.colour_by) }}
                  title={`${it.time} · ${it.title}`}>
                  <b>{it.time}</b> {it.title}
                </span>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

function Agenda({ week }: { week: Week }) {
  const { look } = week;
  return (
    <div className="cal-agenda">
      {week.days.filter((d) => look.show_weekend || ![5, 6].includes(look.week_starts === "sun" ? (week.days.indexOf(d) + 6) % 7 : week.days.indexOf(d))).map((d) => {
        const own = week.items.filter((it) => it.day === week.days.indexOf(d));
        return (
          <section key={d.date} className={`cal-agenda__day${d.today ? " is-today" : ""}`}>
            <h3>{d.label} <b>{d.number}</b></h3>
            {own.length === 0 ? <p className="cal-muted">Nothing.</p> : own.map((it, i) => <Chip key={`${it.id}${i}`} item={it} look={look} />)}
          </section>
        );
      })}
    </div>
  );
}

const LOOK_CHOICES: { key: keyof Look; label: string; options: string[] }[] = [
  { key: "view", label: "View", options: ["week", "agenda"] },
  { key: "density", label: "Row size", options: ["compact", "comfortable", "roomy"] },
  { key: "colour_by", label: "Colour by", options: ["source", "avatar", "repeat"] },
];

export function CalendarPanel() {
  const [anchor, setAnchor] = useState<string>("");
  const [week, setWeek] = useState<Week | null>(null);
  const [error, setError] = useState("");
  const [styling, setStyling] = useState(false);

  const load = useCallback(async () => {
    const result = await api.get<Week>(`/api/scheduled/calendar/week${anchor ? `?day=${anchor}` : ""}`);
    if (result.ok) { setWeek(result.data); setError(""); } else setError(result.error);
  }, [anchor]);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  const shift = (days: number) => {
    const base = new Date(`${week?.start ?? new Date().toISOString().slice(0, 10)}T12:00:00`);
    base.setDate(base.getDate() + days);
    setAnchor(base.toISOString().slice(0, 10));
  };
  async function change(patch: Partial<Look>) {
    const result = await api.put<{ look: Look }>("/api/scheduled/calendar/look", patch);
    if (result.ok) void load(); else setError(result.error);
  }

  const range = useMemo(() => {
    if (!week) return "";
    const first = new Date(`${week.days[0].date}T12:00:00`);
    const last = new Date(`${week.days[6].date}T12:00:00`);
    const f = (d: Date) => d.toLocaleDateString([], { month: "short", day: "numeric" });
    return `${f(first)} to ${f(last)}`;
  }, [week]);

  if (!week) return error ? <p className="cal-error" role="alert">{error}</p> : <Loading what="Loading the calendar" />;
  const { look } = week;
  return (
    <div className="cal" data-density={look.density} style={look.accent ? { ["--cal-accent" as string]: look.accent } : undefined}>
      <header className="cal-bar">
        <button type="button" className="btn btn-secondary" onClick={() => shift(-7)} aria-label="Previous week">‹</button>
        <button type="button" className="btn btn-secondary" onClick={() => setAnchor("")}>Today</button>
        <button type="button" className="btn btn-secondary" onClick={() => shift(7)} aria-label="Next week">›</button>
        <h2 className="cal-range">{range}</h2>
        <span className="cal-spacer" />
        <button type="button" className="btn btn-secondary" aria-expanded={styling} onClick={() => setStyling((v) => !v)}>Look</button>
      </header>
      {styling && (
        <div className="cal-look" role="group" aria-label="Calendar look">
          {LOOK_CHOICES.map((c) => (
            <label key={c.key}>{c.label}
              <select value={String(look[c.key])} onChange={(e) => void change({ [c.key]: e.target.value } as Partial<Look>)}>
                {c.options.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </label>
          ))}
          <label>From <input type="number" min={0} max={22} value={look.start_hour} onChange={(e) => void change({ start_hour: Number(e.target.value) })} /></label>
          <label>To <input type="number" min={2} max={24} value={look.end_hour} onChange={(e) => void change({ end_hour: Number(e.target.value) })} /></label>
          <label className="cal-check"><input type="checkbox" checked={look.show_weekend} onChange={(e) => void change({ show_weekend: e.target.checked })} />Weekends</label>
          <label className="cal-check"><input type="checkbox" checked={look.show_google} onChange={(e) => void change({ show_google: e.target.checked })} />Google Calendar</label>
          <label>Accent <input type="color" value={look.accent || "#ff7a2e"} onChange={(e) => void change({ accent: e.target.value })} /></label>
          <button type="button" className="btn btn-secondary" onClick={() => void change({ accent: "" })}>Default accent</button>
          <p className="cal-muted">You can also just ask: "make the calendar compact" or "hide weekends".</p>
        </div>
      )}
      {error && <p className="cal-error" role="alert">{error}</p>}
      {look.show_google && !week.google.connected && (
        <p className="cal-muted">{week.google.error ? `Google Calendar could not be read (${week.google.error}). ` : "Google Calendar is not connected. "}Showing Orbits only.</p>
      )}
      {look.view === "agenda" ? <Agenda week={week} /> : <WeekGrid week={week} />}
      {week.items.length === 0 && <p className="cal-muted">Nothing is scheduled this week. Add an Orbit and it shows up here.</p>}
    </div>
  );
}
