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

/** Where a click lands in a day column, rounded to the half hour ("09:30"). */
function slotTime(offsetY: number, rowPx: number, startHour: number): string {
  const total = Math.max(0, Math.floor((offsetY / rowPx) * 2)) * 30 + startHour * 60;
  return `${String(Math.min(23, Math.floor(total / 60))).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function WeekGrid({ week, onSlot, onPick }: { week: Week; onSlot: (date: string, time: string) => void; onPick: (item: Item) => void }) {
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
          <div key={d.date} className={`cal-col${d.today ? " is-today" : ""}`} style={{ height: hours.length * rowPx }}
            title="Click to add something here"
            onClick={(e) => {
              if (e.target !== e.currentTarget) return;
              onSlot(d.date, slotTime(e.nativeEvent.offsetY, rowPx, look.start_hour));
            }}>
            {timed.map((it, i) => {
              const spot = placed.get(it) ?? { lane: 0, of: 1 };
              const top = ((minutes(it) - look.start_hour * 60) / 60) * rowPx;
              return (
                <button type="button" key={`${it.id}${i}`} className={`cal-event${it.enabled ? "" : " is-paused"}${it.runs || it.source === "google" ? "" : " is-idle"}`}
                  style={{ top, left: `${(spot.lane / spot.of) * 100}%`, width: `${100 / spot.of}%`, ["--cal-colour" as string]: colourOf(it, look.colour_by) }}
                  title={`${it.time} · ${it.title}`} onClick={() => onPick(it)}>
                  <b>{it.time}</b> {it.title}
                </button>
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
  // Click an empty slot to add an Orbit there; click an event to see it and run, pause or remove it.
  const [slot, setSlot] = useState<{ date: string; time: string } | null>(null);
  const [picked, setPicked] = useState<Item | null>(null);

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
        <button type="button" className="btn btn-primary" onClick={() => { setPicked(null); setSlot({ date: week.days.find((d) => d.today)?.date ?? week.days[0].date, time: "09:00" }); }}>+ Add</button>
        <button type="button" className="btn btn-secondary" aria-expanded={styling} onClick={() => setStyling((v) => !v)}>Look</button>
      </header>
      {slot && <AddForm slot={slot} onClose={() => setSlot(null)} onAdded={() => { setSlot(null); void load(); }} />}
      {picked && <ItemCard item={picked} onClose={() => setPicked(null)} onChanged={() => { setPicked(null); void load(); }} />}
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
        <p className="cal-muted">{week.google.error ? `Google Calendar could not be read (${week.google.error}). ` : "Google Calendar is not connected. "}Showing Orbits only.{" "}
          <button type="button" className="cal-link" onClick={() => window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "connectors" } }))}>
            Connect Google Calendar</button></p>
      )}
      {look.view === "agenda" ? <Agenda week={week} /> : <WeekGrid week={week} onSlot={(date, time) => { setPicked(null); setSlot({ date, time }); }} onPick={(it) => { setSlot(null); setPicked(it); }} />}
      {week.items.length === 0 && <p className="cal-muted">Nothing is scheduled this week. Click a time in the week, or + Add, to put something there.</p>}
    </div>
  );
}

// --- adding and changing, right on the calendar (owner, 2026-10-15: "calendar in Constellations doesn't work") -------

interface Avatar { id: string; name: string }
const REPEATS: [string, string][] = [["once", "Just this once"], ["daily", "Every day"], ["weekdays", "Weekdays"], ["weekly", "Every week on this day"]];

function AddForm({ slot, onClose, onAdded }: { slot: { date: string; time: string }; onClose: () => void; onAdded: () => void }) {
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [date, setDate] = useState(slot.date);
  const [time, setTime] = useState(slot.time);
  const [repeat, setRepeat] = useState("once");
  const [avatar, setAvatar] = useState("");
  const [avatars, setAvatars] = useState<Avatar[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { setDate(slot.date); setTime(slot.time); }, [slot]);
  useEffect(() => {
    void api.get<{ avatars: Avatar[] }>("/api/avatars").then((r) => {
      if (r.ok) { setAvatars(r.data.avatars); if (r.data.avatars[0]) setAvatar((v) => v || r.data.avatars[0].id); }
    });
  }, []);
  const when = new Date(`${date}T${time}:00`);
  const save = async () => {
    setError("");
    // Monday = 0, like the Orbits form.
    const weekday = (when.getDay() + 6) % 7;
    const r = await api.post("/api/scheduled", { title: title.trim(), prompt: prompt.trim() || title.trim(), repeat, time, avatar,
      days: [weekday], every_minutes: 60, calendar: false, at: repeat === "once" ? when.getTime() / 1000 : 0 });
    if (r.ok) onAdded(); else setError(r.error);
  };
  return (
    <form className="cal-form" onSubmit={(e) => { e.preventDefault(); void save(); }} aria-label="Add to the calendar">
      <div className="cal-form__row">
        <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What, e.g. Morning mail" aria-label="Title" />
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Day" />
        <input type="time" value={time} onChange={(e) => setTime(e.target.value)} aria-label="Time" />
        <select value={repeat} onChange={(e) => setRepeat(e.target.value)} aria-label="Repeat">
          {REPEATS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      <textarea rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)} aria-label="What Ichos should do then"
        placeholder="What should Ichos do then? (Leave empty for a plain reminder.)" />
      <div className="cal-form__row">
        <select value={avatar} onChange={(e) => setAvatar(e.target.value)} aria-label="Who does it">
          <option value="">Nobody (shows, never runs)</option>
          {avatars.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <span className="cal-spacer" />
        {error && <span className="cal-error" role="alert">{error}</span>}
        <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={!title.trim() || Number.isNaN(when.getTime())}>Add</button>
      </div>
    </form>
  );
}

function ItemCard({ item, onClose, onChanged }: { item: Item; onClose: () => void; onChanged: () => void }) {
  const [error, setError] = useState("");
  const act = async (call: () => Promise<{ ok: boolean; error?: string }>) => {
    const r = await call();
    if (r.ok) onChanged(); else setError(r.error || "That did not work.");
  };
  const day = new Date(item.at * 1000).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
  return (
    <div className="cal-form" role="dialog" aria-label={item.title}>
      <div className="cal-form__row">
        <b>{item.title}</b>
        <span className="cal-muted">{day} · {item.time}{item.source === "google" ? " · Google Calendar" : ""}
          {item.source === "orbit" && !item.runs ? " · nobody assigned, never runs" : ""}{item.enabled ? "" : " · paused"}</span>
        <span className="cal-spacer" />
        {item.source === "orbit" && <>
          <button type="button" className="btn btn-secondary" disabled={!item.runs} onClick={() => void act(() => api.post(`/api/scheduled/${item.id}/run`, {}))}>Run now</button>
          <button type="button" className="btn btn-secondary" onClick={() => void act(() => api.put(`/api/scheduled/${item.id}`, { enabled: !item.enabled }))}>{item.enabled ? "Pause" : "Resume"}</button>
          <button type="button" className="btn btn-secondary" onClick={() => void act(() => api.del(`/api/scheduled/${item.id}`))}>Remove</button>
        </>}
        <button type="button" className="btn btn-secondary" onClick={onClose}>Close</button>
      </div>
      {error && <p className="cal-error" role="alert">{error}</p>}
    </div>
  );
}
