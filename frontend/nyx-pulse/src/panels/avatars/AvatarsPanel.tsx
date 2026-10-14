/** Avatars (avatars.py): always-on helpers the owner shapes — main function, what it does, when it runs (on call, all
 *  day, all year), what it may use (Allow / Ask), goals, watches and taught tasks. Seven ship switched off; make more
 *  from blank or from any of them. From chat: "@Orbit …", /avatar, /team. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { startItemDrag } from "../../state/dragItems";
import "./avatars.css";

type Rule = "allow" | "ask";
interface Schedule { mode: string; every_minutes: number; start: string; end: string; days: number[] }
interface Goal { id: string; text: string; steps: { text: string; done: boolean }[]; status: string; progress: string }
interface Watch { id: string; what: string; every_minutes: number; phone: boolean; last_at: number; last: string }
interface Lesson { id: string; name: string; steps: string[]; repeat: string; last_at: number }
interface Activity { at: number; kind: string; input: string; reply: string; ok: boolean; seconds: number }
export interface Avatar {
  id: string; name: string; icon: string; main: string; main_custom: string; does: string; inspired_by: string;
  personality: string; personality_custom: string;
  enabled: boolean; model: string; max_runs_per_day: number; schedule: Schedule; functions: Record<string, Rule>;
  goals: Goal[]; watches: Watch[]; lessons: Lesson[]; notes: string[];
  builtin: boolean; edited: boolean; busy: boolean; runs_today: number; last_tick: number; chat_id: string; activity: Activity[];
}
interface FunctionInfo { label: string; about: string; default: Rule; locked: boolean; always_ask: boolean }
interface Catalog {
  functions: Record<string, FunctionInfo>; main: Record<string, string>; schedules: Record<string, string>;
  models: Record<string, string>; repeats: string[]; personalities: Record<string, string>;
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const EVERY = [15, 30, 60, 90, 120, 240, 480, 1440];

function hue(id: string): number {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

function ago(seconds: number): string {
  if (!seconds) return "never";
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function minutes(n: number): string {
  return n % 60 === 0 ? (n === 60 ? "hour" : n === 1440 ? "day" : `${n / 60} hours`) : `${n} min`;
}

/** Fields a record from an older engine may not have yet. */
function withDefaults(a: Avatar): Avatar {
  return { ...a, personality: a.personality ?? "", personality_custom: a.personality_custom ?? "",
    functions: a.functions ?? { talk: "allow" }, goals: a.goals ?? [], watches: a.watches ?? [], lessons: a.lessons ?? [],
    notes: a.notes ?? [], activity: a.activity ?? [],
    schedule: a.schedule ?? { mode: "on_call", every_minutes: 60, start: "08:00", end: "20:00", days: [0, 1, 2, 3, 4, 5, 6] } };
}

export function scheduleWords(s: Schedule): string {
  if (s.mode === "on_call") return "When called";
  const every = `every ${minutes(s.every_minutes)}`;
  return s.mode === "all_day" ? `${s.start}–${s.end}, ${every}` : `All year, ${every}`;
}

/** A small orbit emblem: the initial on a planet, ringed, coloured from the id. */
function Emblem({ avatar, size = 44 }: { avatar: Pick<Avatar, "id" | "name" | "enabled" | "busy">; size?: number }) {
  const h = hue(avatar.id);
  return (
    <svg className={`av-emblem${avatar.busy ? " is-busy" : ""}`} width={size} height={size} viewBox="0 0 44 44" aria-hidden="true">
      <circle cx="22" cy="22" r="14" fill={`hsl(${h} 62% ${avatar.enabled ? 58 : 34}%)`} />
      <ellipse className="av-ring" cx="22" cy="22" rx="20" ry="7" fill="none" stroke={`hsl(${(h + 40) % 360} 80% 74%)`}
        strokeWidth="1.6" transform="rotate(-24 22 22)" opacity={avatar.enabled ? 0.95 : 0.45} />
      <text x="22" y="27" textAnchor="middle" fontSize="14" fontWeight="700" fill="#0d0e14">{avatar.name.slice(0, 1).toUpperCase()}</text>
    </svg>
  );
}

export function AvatarsPanel() {
  const [list, setList] = useState<Avatar[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [error, setError] = useState("");
  const [teamOpen, setTeamOpen] = useState(false);

  const load = useCallback(async () => {
    const r = await api.get<{ avatars: Avatar[]; catalog: Catalog }>("/api/avatars");
    if (!r.ok) { setError(r.error); return; }
    // An engine older than this page leaves fields out; fill them so nothing reads an undefined list.
    const c = r.data.catalog ?? ({} as Partial<Catalog>);
    setCatalog({ functions: c.functions ?? {}, main: c.main ?? {}, schedules: c.schedules ?? { on_call: "Only when called" },
      models: c.models ?? { "": "Ichos's usual model" }, repeats: c.repeats ?? [""],
      personalities: c.personalities ?? {} });
    setList((r.data.avatars ?? []).map(withDefaults));
    setSelected((current) => current && r.data.avatars.some((a) => a.id === current) ? current : r.data.avatars[0]?.id ?? "");
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => onWorkspaceEvent((event) => { if (event.type === "avatar.update") void load(); }), [load]);

  const avatar = list.find((a) => a.id === selected) ?? null;
  const onCount = list.filter((a) => a.enabled).length;

  async function create(template = "") {
    const r = await api.post<Avatar>("/api/avatars", { avatar: { name: template ? "" : "New avatar", does: "" }, template });
    if (!r.ok) { setError(r.error); return; }
    await load();
    setSelected(r.data.id);
  }

  async function toggle(a: Avatar) {
    const r = await api.put<Avatar>(`/api/avatars/${a.id}`, { enabled: !a.enabled });
    if (!r.ok) setError(r.error); else await load();
  }

  return (
    <div className="av">
      <header className="av-head">
        <div>
          <h1>Avatars</h1>
          <p className="av-muted">Helpers that keep working for you — on call, all day or all year. {onCount ? `${onCount} on.` : "All off: nothing runs (or costs anything) until you switch one on."} In chat, write <code>@Name</code>, <code>/avatar</code> or <code>/team</code>.</p>
        </div>
        <div className="av-row">
          <button className="btn btn-secondary" onClick={() => setTeamOpen((v) => !v)} aria-expanded={teamOpen}>Team task</button>
          <button className="btn btn-primary" onClick={() => void create()}>New avatar</button>
        </div>
      </header>
      {error && <p className="av-error" role="alert">{error} <button className="btn btn-ghost" onClick={() => setError("")}>Dismiss</button></p>}
      {teamOpen && <TeamCard avatars={list} onDone={load} />}

      <div className="av-body">
        <ul className="av-list" aria-label="Avatars">
          {list.map((a) => (
            <li key={a.id}>
              <div className={`av-card${a.id === selected ? " is-selected" : ""}`} draggable
                title="Drag onto a tab to point the AI at this avatar"
                onDragStart={(e) => startItemDrag(e, { kind: "avatar", id: a.id, label: a.name })}>
                <button className="av-card__main" onClick={() => setSelected(a.id)} aria-pressed={a.id === selected}>
                  <Emblem avatar={a} />
                  <span className="av-card__text">
                    <b>{a.name}</b>
                    <span>{a.main === "custom" ? a.main_custom || "Custom" : catalog?.main[a.main] ?? ""}</span>
                    <span className="av-muted">{a.busy ? "Working…" : scheduleWords(a.schedule)}</span>
                  </span>
                </button>
                <label className="av-switch" title={a.enabled ? "On — runs on its schedule" : "Off"}>
                  <input type="checkbox" role="switch" checked={a.enabled} onChange={() => void toggle(a)} aria-label={`${a.name} on`} />
                  <span aria-hidden="true" />
                </label>
              </div>
            </li>
          ))}
          <li className="av-list__foot">
            <button className="btn btn-ghost" onClick={() => void api.post("/api/avatars/restore").then(load)}>Bring back hidden defaults</button>
          </li>
        </ul>
        {avatar && catalog ? <Editor key={avatar.id} avatar={avatar} catalog={catalog} reload={load} onError={setError}
          onCopy={() => void create(avatar.id)} onGone={() => setSelected("")} /> : <p className="av-muted">Pick an avatar.</p>}
      </div>
    </div>
  );
}

function Editor({ avatar, catalog, reload, onError, onCopy, onGone }: {
  avatar: Avatar; catalog: Catalog; reload: () => Promise<void>; onError: (e: string) => void; onCopy: () => void; onGone: () => void;
}) {
  const [draft, setDraft] = useState(avatar);
  const [saving, setSaving] = useState(false);
  const before = useRef(avatar);
  useEffect(() => {
    const previous = before.current;
    before.current = avatar;
    setDraft((d) => ({ ...avatar, ...unsaved(d, previous) }));
  }, [avatar]);
  const dirty = useMemo(() => JSON.stringify(core(draft)) !== JSON.stringify(core(avatar)), [draft, avatar]);

  const set = <K extends keyof Avatar>(key: K, value: Avatar[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const setSched = (changes: Partial<Schedule>) => setDraft((d) => ({ ...d, schedule: { ...d.schedule, ...changes } }));

  async function save() {
    setSaving(true);
    const r = await api.put<Avatar>(`/api/avatars/${avatar.id}`, core(draft));
    setSaving(false);
    if (!r.ok) onError(r.error); else await reload();
  }

  async function remove() {
    const words = avatar.builtin ? `Hide ${avatar.name}? "Bring back hidden defaults" restores it.` : `Delete ${avatar.name}? Its chat is kept.`;
    if (!window.confirm(words)) return;
    const r = await api.del(`/api/avatars/${avatar.id}`);
    if (!r.ok) onError(r.error); else { onGone(); await reload(); }
  }

  async function resetIt() {
    if (!window.confirm(`Put ${avatar.name} back the way it shipped? Goals, watches and lessons you added go too.`)) return;
    const r = await api.post(`/api/avatars/${avatar.id}/reset`);
    if (!r.ok) onError(r.error); else await reload();
  }

  const s = draft.schedule;
  return (
    <section className="av-editor" aria-label={`${avatar.name} settings`}>
      <div className="av-editor__head">
        <Emblem avatar={avatar} size={56} />
        <div className="av-editor__title">
          <input className="av-name" value={draft.name} maxLength={40} onChange={(e) => set("name", e.target.value)} aria-label="Name" />
          <span className="av-muted">
            {avatar.inspired_by ? `Like ${avatar.inspired_by} · ` : ""}{avatar.runs_today} run{avatar.runs_today === 1 ? "" : "s"} today · last check-in {ago(avatar.last_tick)}
          </span>
        </div>
        <div className="av-row">
          <button className="btn btn-primary" disabled={!dirty || saving} onClick={() => void save()}>{saving ? "Saving…" : dirty ? "Save" : "Saved"}</button>
          {dirty && <button className="btn btn-ghost" onClick={() => setDraft(avatar)}>Undo</button>}
        </div>
      </div>

      <Talk avatar={avatar} onError={onError} />

      <div className="av-grid">
        <fieldset className="av-box">
          <legend>Main function &amp; personality</legend>
          <div className="av-chips" role="radiogroup" aria-label="Main function">
            {Object.entries(catalog.main ?? {}).map(([key, label]) => (
              <button key={key} role="radio" aria-checked={draft.main === key} className={`av-chip${draft.main === key ? " is-on" : ""}`}
                onClick={() => set("main", key)}>{label}</button>
            ))}
          </div>
          {draft.main === "custom" && <input value={draft.main_custom} maxLength={80} placeholder="Its main function, in a few words"
            onChange={(e) => set("main_custom", e.target.value)} aria-label="Custom main function" />}
          <label className="av-field">What it does
            <textarea rows={4} maxLength={1200} value={draft.does} onChange={(e) => set("does", e.target.value)}
              placeholder="In your words: what it should do, how, and when to bother you." />
          </label>
          {Object.keys(catalog.personalities ?? {}).length > 0 && <label className="av-field">Personality
            <select value={draft.personality} onChange={(e) => set("personality", e.target.value)}>
              {Object.entries(catalog.personalities ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>}
          {draft.personality === "custom" && <textarea rows={2} maxLength={600} value={draft.personality_custom}
            onChange={(e) => set("personality_custom", e.target.value)} aria-label="Custom personality"
            placeholder="How it should sound, e.g. calm, dry humour, short sentences, calls me boss" />}
        </fieldset>

        <fieldset className="av-box">
          <legend>When it runs</legend>
          <div className="av-seg" role="radiogroup" aria-label="When it runs">
            {Object.entries(catalog.schedules ?? {}).map(([key, label]) => (
              <button key={key} role="radio" aria-checked={s.mode === key} className={s.mode === key ? "is-on" : ""}
                onClick={() => setSched({ mode: key })}>{label.split(" (")[0].replace(", around the clock", "")}</button>
            ))}
          </div>
          <p className="av-muted">{catalog.schedules[s.mode]}{s.mode !== "on_call" && !draft.enabled ? " — switch it on in the list to start." : ""}</p>
          {s.mode !== "on_call" && (
            <div className="av-inline">
              <label>Check in every
                <select value={s.every_minutes} onChange={(e) => setSched({ every_minutes: Number(e.target.value) })}>
                  {[...new Set([...EVERY, s.every_minutes])].sort((a, b) => a - b).map((n) => <option key={n} value={n}>{minutes(n)}</option>)}
                </select>
              </label>
              {s.mode === "all_day" && <>
                <label>from <input type="time" value={s.start} onChange={(e) => setSched({ start: e.target.value })} /></label>
                <label>to <input type="time" value={s.end} onChange={(e) => setSched({ end: e.target.value })} /></label>
              </>}
            </div>
          )}
          <div className="av-chips" aria-label="Days">
            {DAYS.map((d, i) => {
              const on = s.days.includes(i);
              return <button key={d} aria-pressed={on} className={`av-chip av-chip--day${on ? " is-on" : ""}`}
                onClick={() => setSched({ days: on ? s.days.filter((x) => x !== i) : [...s.days, i].sort() })}>{d}</button>;
            })}
          </div>
          <div className="av-inline">
            <label>At most <input type="number" min={1} max={96} value={draft.max_runs_per_day}
              onChange={(e) => set("max_runs_per_day", Number(e.target.value) || 1)} /> runs a day</label>
            <label>Model
              <select value={draft.model} onChange={(e) => set("model", e.target.value)}>
                {Object.entries(catalog.models ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
          </div>
        </fieldset>
      </div>

      <fieldset className="av-box">
        <legend>Functions — what it may use</legend>
        <ul className="av-fns">
          {Object.entries(catalog.functions ?? {}).map(([key, f]) => {
            const rule = draft.functions[key];
            const on = Boolean(rule);
            return (
              <li key={key} className={on ? "is-on" : ""}>
                <label className="av-check">
                  <input type="checkbox" checked={on} disabled={f.locked} onChange={() => {
                    const next = { ...draft.functions };
                    if (on) delete next[key]; else next[key] = f.default;
                    set("functions", next);
                  }} />
                  <span><b>{f.label}</b><span className="av-muted">{f.about}</span></span>
                </label>
                {on && !f.locked && (
                  <select value={rule} disabled={f.always_ask} aria-label={`${f.label}: allow or ask`}
                    onChange={(e) => set("functions", { ...draft.functions, [key]: e.target.value as Rule })}>
                    <option value="allow">Allow</option>
                    <option value="ask">Ask me first</option>
                  </select>
                )}
              </li>
            );
          })}
        </ul>
        <p className="av-muted">Never allowed for any avatar: deleting files, power and system settings, the clipboard, changing Ichos itself.</p>
      </fieldset>

      <div className="av-grid">
        <Goals avatar={avatar} onError={onError} reload={reload} />
        <Watches avatar={avatar} onError={onError} reload={reload} />
        <Lessons avatar={avatar} onError={onError} reload={reload} repeats={catalog.repeats} />
        <Memory avatar={avatar} onError={onError} reload={reload} />
      </div>

      <ActivityLog avatar={avatar} />

      <div className="av-row av-foot">
        <button className="btn btn-secondary" disabled={avatar.busy} onClick={() => void api.post(`/api/avatars/${avatar.id}/run`, { kind: "checkin" }).then((r) => { if (!r.ok) onError(r.error); })}>Check in now</button>
        <button className="btn btn-secondary" onClick={onCopy}>Duplicate</button>
        {avatar.builtin && avatar.edited && <button className="btn btn-ghost" onClick={() => void resetIt()}>Reset to default</button>}
        <button className="btn btn-ghost av-danger" onClick={() => void remove()}>{avatar.builtin ? "Hide" : "Delete"}</button>
      </div>
    </section>
  );
}

/** The fields the Save button owns; lists (goals, watches, lessons, notes) save as you add them. */
function core(a: Avatar) {
  return { name: a.name, main: a.main, main_custom: a.main_custom, does: a.does, personality: a.personality,
    personality_custom: a.personality_custom, model: a.model,
    max_runs_per_day: a.max_runs_per_day, schedule: a.schedule, functions: a.functions };
}

/** The owner's unsaved edits (fields that differ from what was loaded), kept when the avatar reloads underneath. */
function unsaved(draft: Avatar, loaded: Avatar): Partial<Avatar> {
  const out: Record<string, unknown> = {};
  const d = core(draft) as Record<string, unknown>;
  const l = core(loaded) as Record<string, unknown>;
  for (const key of Object.keys(d)) if (JSON.stringify(d[key]) !== JSON.stringify(l[key])) out[key] = d[key];
  return draft.id === loaded.id ? (out as Partial<Avatar>) : {};
}

function Talk({ avatar, onError }: { avatar: Avatar; onError: (e: string) => void }) {
  const [text, setText] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  async function send() {
    if (!text.trim()) return;
    setBusy(true); setReply("");
    const r = await api.post<Activity>(`/api/avatars/${avatar.id}/talk`, { text }, 600000);
    setBusy(false);
    if (!r.ok) { onError(r.error); return; }
    setReply(r.data.reply); setText("");
  }
  return (
    <div className="av-talk">
      <form className="av-row" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={`Tell ${avatar.name} something to do…`} aria-label={`Message ${avatar.name}`} />
        <button className="btn btn-primary" disabled={busy || !text.trim()}>{busy ? "Working…" : "Send"}</button>
      </form>
      {reply && <p className="av-reply">{reply}</p>}
    </div>
  );
}

function useList(avatar: Avatar, kind: "goals" | "watches" | "lessons", onError: (e: string) => void, reload: () => Promise<void>) {
  return {
    add: async (item: Record<string, unknown>) => {
      const r = await api.post(`/api/avatars/${avatar.id}/${kind}`, { item });
      if (!r.ok) { onError(r.error); return false; }
      await reload(); return true;
    },
    remove: async (id: string) => {
      const r = await api.del(`/api/avatars/${avatar.id}/${kind}/${id}`);
      if (!r.ok) onError(r.error); else await reload();
    },
    run: async (id: string, runKind: "watch" | "lesson") => {
      const r = await api.post(`/api/avatars/${avatar.id}/run`, { kind: runKind, item: id });
      if (!r.ok) onError(r.error);
    },
  };
}

function Goals({ avatar, onError, reload }: { avatar: Avatar; onError: (e: string) => void; reload: () => Promise<void> }) {
  const list = useList(avatar, "goals", onError, reload);
  const [text, setText] = useState("");
  const [steps, setSteps] = useState("");
  return (
    <fieldset className="av-box">
      <legend>Goals <span className="av-muted">it works on them at each check-in</span></legend>
      <ul className="av-items">
        {avatar.goals.map((g) => {
          const done = g.steps.filter((x) => x.done).length;
          return (
            <li key={g.id}>
              <div>
                <b>{g.text}</b>
                {g.steps.length > 0 && <progress max={g.steps.length} value={done} aria-label={`${done} of ${g.steps.length} steps`} />}
                <span className="av-muted">{g.status === "done" ? "Done" : g.progress || (g.steps.length ? `${done}/${g.steps.length} steps` : "Not started")}</span>
              </div>
              <button className="btn btn-ghost" onClick={() => void list.remove(g.id)} aria-label={`Remove goal ${g.text}`}>Remove</button>
            </li>
          );
        })}
      </ul>
      <form className="av-add" onSubmit={async (e) => { e.preventDefault(); if (await list.add({ text, steps: steps.split("\n").filter(Boolean).map((t) => ({ text: t })) })) { setText(""); setSteps(""); } }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="A goal, e.g. Launch the website by Friday" aria-label="New goal" />
        <textarea rows={2} value={steps} onChange={(e) => setSteps(e.target.value)} placeholder="Plan (optional), one step per line" aria-label="Goal steps" />
        <button className="btn btn-secondary" disabled={!text.trim()}>Add goal</button>
      </form>
    </fieldset>
  );
}

function Watches({ avatar, onError, reload }: { avatar: Avatar; onError: (e: string) => void; reload: () => Promise<void> }) {
  const list = useList(avatar, "watches", onError, reload);
  const [what, setWhat] = useState("");
  const [every, setEvery] = useState(60);
  const [phone, setPhone] = useState(false);
  return (
    <fieldset className="av-box">
      <legend>Watches <span className="av-muted">speaks up only when something changes</span></legend>
      <ul className="av-items">
        {avatar.watches.map((w) => (
          <li key={w.id}>
            <div>
              <b>{w.what}</b>
              <span className="av-muted">every {minutes(w.every_minutes)}{w.phone ? " · texts your phone" : ""} · checked {ago(w.last_at)}</span>
              {w.last && <span className="av-last">{w.last}</span>}
            </div>
            <span className="av-actions">
              <button className="btn btn-ghost" disabled={avatar.busy} onClick={() => void list.run(w.id, "watch")}>Check now</button>
              <button className="btn btn-ghost" onClick={() => void list.remove(w.id)}>Remove</button>
            </span>
          </li>
        ))}
      </ul>
      <form className="av-add" onSubmit={async (e) => { e.preventDefault(); if (await list.add({ what, every_minutes: every, phone })) setWhat(""); }}>
        <input value={what} onChange={(e) => setWhat(e.target.value)} placeholder="e.g. Rain in Austin tomorrow, or BTC below 90k" aria-label="What to watch" />
        <div className="av-inline">
          <label>every <select value={every} onChange={(e) => setEvery(Number(e.target.value))}>{EVERY.map((n) => <option key={n} value={n}>{minutes(n)}</option>)}</select></label>
          <label className="av-check"><input type="checkbox" checked={phone} onChange={(e) => setPhone(e.target.checked)} /> Text my phone too</label>
          <button className="btn btn-secondary" disabled={!what.trim()}>Add watch</button>
        </div>
      </form>
    </fieldset>
  );
}

function Lessons({ avatar, onError, reload, repeats }: { avatar: Avatar; onError: (e: string) => void; reload: () => Promise<void>; repeats: string[] }) {
  const list = useList(avatar, "lessons", onError, reload);
  const [name, setName] = useState("");
  const [steps, setSteps] = useState("");
  const [repeat, setRepeat] = useState("");
  return (
    <fieldset className="av-box">
      <legend>Taught tasks <span className="av-muted">show it once, it repeats</span></legend>
      <ul className="av-items">
        {avatar.lessons.map((l) => (
          <li key={l.id}>
            <div>
              <b>{l.name}</b>
              <span className="av-muted">{l.steps.length} steps · {l.repeat || "when asked"} · last {ago(l.last_at)}</span>
            </div>
            <span className="av-actions">
              <button className="btn btn-ghost" disabled={avatar.busy} onClick={() => void list.run(l.id, "lesson")}>Run</button>
              <button className="btn btn-ghost" onClick={() => void list.remove(l.id)}>Remove</button>
            </span>
          </li>
        ))}
      </ul>
      <form className="av-add" onSubmit={async (e) => { e.preventDefault(); if (await list.add({ name, steps: steps.split("\n").filter(Boolean), repeat })) { setName(""); setSteps(""); } }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Task name, e.g. Weekly expenses" aria-label="Task name" />
        <textarea rows={3} value={steps} onChange={(e) => setSteps(e.target.value)} placeholder={"The steps, one per line:\nOpen the receipts folder\nAdd them to the sheet"} aria-label="Task steps" />
        <div className="av-inline">
          <label>Repeat <select value={repeat} onChange={(e) => setRepeat(e.target.value)}>{repeats.map((r) => <option key={r} value={r}>{r || "when asked"}</option>)}</select></label>
          <button className="btn btn-secondary" disabled={!name.trim() || !steps.trim()}>Teach it</button>
        </div>
      </form>
    </fieldset>
  );
}

function Memory({ avatar, onError, reload }: { avatar: Avatar; onError: (e: string) => void; reload: () => Promise<void> }) {
  const [note, setNote] = useState("");
  const save = async (notes: string[]) => {
    const r = await api.put(`/api/avatars/${avatar.id}`, { notes });
    if (!r.ok) onError(r.error); else await reload();
  };
  return (
    <fieldset className="av-box">
      <legend>What it remembers</legend>
      <ul className="av-items av-items--notes">
        {avatar.notes.length === 0 && <li className="av-muted">Nothing yet — it writes notes as it works, or add one.</li>}
        {avatar.notes.map((n, i) => (
          <li key={`${i}-${n}`}><span>{n}</span>
            <button className="btn btn-ghost" onClick={() => void save(avatar.notes.filter((_, j) => j !== i))} aria-label="Forget this">Forget</button></li>
        ))}
      </ul>
      <form className="av-row" onSubmit={(e) => { e.preventDefault(); if (note.trim()) void save([...avatar.notes, note]).then(() => setNote("")); }}>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Something it should know about you" aria-label="New note" />
        <button className="btn btn-secondary" disabled={!note.trim()}>Add</button>
      </form>
    </fieldset>
  );
}

function ActivityLog({ avatar }: { avatar: Avatar }) {
  if (!avatar.activity.length) return null;
  return (
    <details className="av-box av-activity" open>
      <summary>Recent activity</summary>
      <ol>
        {avatar.activity.map((a) => (
          <li key={a.at} className={a.ok ? "" : "is-bad"}>
            <span className="av-muted">{ago(a.at)} · {a.kind} · {a.seconds}s</span>
            <span className="av-input">{a.input}</span>
            <span>{a.reply.slice(0, 400) || "(no answer)"}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}

function TeamCard({ avatars, onDone }: { avatars: Avatar[]; onDone: () => Promise<void> }) {
  const [picked, setPicked] = useState<string[]>([]);
  const [task, setTask] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  async function go() {
    setBusy(true); setAnswer(""); setError("");
    const r = await api.post<{ answer: string; lead: string }>("/api/avatars/team", { avatars: picked, task }, 1200000);
    setBusy(false);
    if (r.ok) setAnswer(`${r.data.lead}: ${r.data.answer}`); else setError(r.error);
    await onDone();
  }
  return (
    <section className="av-box av-team" aria-label="Team task">
      <p className="av-muted">Pick 2–6 avatars; the first you pick leads, hands out parts and gives the final answer. Costs one turn per avatar plus two.</p>
      <div className="av-chips">
        {avatars.map((a) => {
          const at = picked.indexOf(a.id);
          return <button key={a.id} aria-pressed={at >= 0} className={`av-chip${at >= 0 ? " is-on" : ""}`}
            onClick={() => setPicked(at >= 0 ? picked.filter((x) => x !== a.id) : picked.length < 6 ? [...picked, a.id] : picked)}>
            {at === 0 ? "★ " : at > 0 ? `${at + 1}. ` : ""}{a.name}</button>;
        })}
      </div>
      <form className="av-row" onSubmit={(e) => { e.preventDefault(); void go(); }}>
        <input value={task} onChange={(e) => setTask(e.target.value)} placeholder="The task for the team" aria-label="Team task" />
        <button className="btn btn-primary" disabled={busy || picked.length < 2 || !task.trim()}>{busy ? "Team at work…" : "Start"}</button>
      </form>
      {error && <p className="av-error">{error}</p>}
      {answer && <p className="av-reply">{answer}</p>}
    </section>
  );
}
