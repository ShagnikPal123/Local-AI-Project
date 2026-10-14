/** Equalize › Notch controls: which system buttons the notch shows, the owner's own launchers (an app, a site, a
 * folder, or a command typed beforehand like `claude`), and which view the notch rests on (Fixer Upper S30).
 *
 * Typing a name and pressing Find fills the rest from notch_controls.suggest(): an installed app, a known site, a
 * web address, or a web search as the last guess (shown so it can be checked before saving). */

import { useEffect, useState } from "react";
import { controlsApi, sidebarApi, type HomeViewId, type Launcher, type NotchControls, type SidebarPlace } from "../../notch/notchApi";
import { VIEW_LABEL } from "../../notch/controls";

const EMPTY = { name: "", kind: "app" as Launcher["kind"], target: "", command: "", folder: "" };

export function NotchControlsCard() {
  const [c, setC] = useState<NotchControls | null>(null);
  const [draft, setDraft] = useState(EMPTY);
  const [note, setNote] = useState("");
  const [side, setSide] = useState<SidebarPlace | null>(null);

  useEffect(() => { void controlsApi.get().then((r) => r.ok && setC(r.data)); }, []);
  useEffect(() => { void sidebarApi.place().then((r) => r.ok && setSide(r.data)); }, []);
  if (!c) return null;

  const save = async (changes: Partial<Pick<NotchControls, "system" | "launchers" | "home">>) => {
    const r = await controlsApi.save(changes);
    if (r.ok) setC({ ...c, ...r.data });
    else setNote(r.error);
  };
  const toggleSystem = (id: string) =>
    void save({ system: c.system.includes(id) ? c.system.filter((s) => s !== id) : [...c.system, id] });
  const toggleView = (v: HomeViewId) => {
    const views = c.home.views.includes(v) ? c.home.views.filter((x) => x !== v) : [...c.home.views, v];
    if (views.length) void save({ home: { ...c.home, views } });
  };
  const find = async () => {
    if (!draft.name.trim()) return;
    const r = await controlsApi.suggest(draft.name);
    if (!r.ok) { setNote(r.error); return; }
    setDraft({ ...draft, kind: r.data.kind, target: r.data.target });
    setNote(`Found as ${r.data.how}: ${r.data.target}`);
  };
  const add = async () => {
    const r = await controlsApi.addLauncher(draft);
    if (!r.ok) { setNote(r.error); return; }
    setC({ ...c, ...r.data });
    setDraft(EMPTY);
    setNote("Added. It shows on the right of the notch.");
  };
  // The hands-off sidebar: shown beside the notch, and back after a restart while it is on.
  const showSidebar = async (on: boolean) => {
    const r = on ? await sidebarApi.start() : await sidebarApi.stop();
    if (!r.ok) { setNote(r.error); return; }
    const place = await sidebarApi.place();
    if (place.ok) setSide(place.data);
  };
  const moveSidebar = async (changes: Partial<SidebarPlace>) => {
    const r = await sidebarApi.move(changes);
    if (r.ok) setSide(r.data);
  };
  const remove = async (id: string) => {
    const r = await controlsApi.removeLauncher(id);
    if (r.ok) setC({ ...c, ...r.data });
  };

  return (
    <section className="eq-card wide">
      <h2>Notch controls<span>System buttons, your apps, and what the notch shows without a click</span></h2>

      <p className="eq-muted">System buttons (left of the camera)</p>
      <div className="eq-chips">
        {c.available.map((s) => (
          <button key={s.id} className="eq-chip" aria-pressed={c.system.includes(s.id)} onClick={() => toggleSystem(s.id)}
            style={c.system.includes(s.id) ? { outline: "2px solid var(--color-accent)" } : undefined}>{s.label}</button>
        ))}
      </div>

      <p className="eq-muted">Your apps (right of the camera)</p>
      <div className="eq-chips">
        {c.launchers.map((l) => (
          <span key={l.id} className="eq-chip" style={{ borderLeft: `3px solid ${l.color}` }}>
            {l.name}<small style={{ opacity: 0.6, marginLeft: 6 }}>{l.kind === "command" ? l.command : l.kind}</small>
            <button className="eq-btn small" style={{ marginLeft: 6 }} aria-label={`Remove ${l.name}`} onClick={() => void remove(l.id)}>×</button>
          </span>
        ))}
      </div>
      <div className="eq-row">
        <input className="eq-input" value={draft.name} placeholder="Name — e.g. Spotify, GitHub, Claude Code"
          onChange={(e) => setDraft({ ...draft, name: e.target.value })} onKeyDown={(e) => e.key === "Enter" && void find()} />
        <select className="eq-input" style={{ flex: "0 0 120px" }} value={draft.kind}
          onChange={(e) => setDraft({ ...draft, kind: e.target.value as Launcher["kind"] })}>
          <option value="app">App</option><option value="site">Website</option><option value="folder">Folder</option>
          <option value="command">cmd command</option>
        </select>
        <button className="eq-btn" onClick={() => void find()}>Find</button>
      </div>
      {draft.kind === "command" ? (
        <div className="eq-row">
          <input className="eq-input" value={draft.command} placeholder="Command typed in cmd — e.g. claude"
            onChange={(e) => setDraft({ ...draft, command: e.target.value })} />
          <input className="eq-input" value={draft.folder} placeholder="Folder it runs in (optional)"
            onChange={(e) => setDraft({ ...draft, folder: e.target.value })} />
        </div>
      ) : (
        <div className="eq-row">
          <input className="eq-input" value={draft.target}
            placeholder={draft.kind === "site" ? "https://…" : draft.kind === "folder" ? "C:\\path\\to\\folder" : "App name as in the Start menu"}
            onChange={(e) => setDraft({ ...draft, target: e.target.value })} />
        </div>
      )}
      <div className="eq-row">
        <button className="eq-btn" onClick={() => void add()} disabled={!draft.name.trim()}>Add to the notch</button>
        {note ? <span className="eq-muted" role="status">{note}</span> : null}
      </div>

      <p className="eq-muted">Views (triple-click the notch to switch; H on the notch makes the one showing the default)</p>
      <div className="eq-chips">
        {c.views.map((v) => (
          <button key={v} className="eq-chip" aria-pressed={c.home.views.includes(v)} onClick={() => toggleView(v)}
            style={c.home.views.includes(v) ? { outline: "2px solid var(--color-accent)" } : undefined}>
            {VIEW_LABEL[v]}{c.home.default === v ? " · default" : ""}</button>
        ))}
      </div>
      <div className="eq-row">
        <label className="eq-field" style={{ flex: 1 }}><span>Default</span>
          <select className="eq-input" value={c.home.default} onChange={(e) => void save({ home: { ...c.home, default: e.target.value as HomeViewId } })}>
            {c.home.views.map((v) => <option key={v} value={v}>{VIEW_LABEL[v]}</option>)}
          </select></label>
        <label className="eq-field" style={{ flex: 1 }}><span>Weather city</span>
          <input value={c.home.city} placeholder="Uses the Morning Digest city when empty"
            onChange={(e) => setC({ ...c, home: { ...c.home, city: e.target.value } })}
            onBlur={() => void save({ home: c.home })} /></label>
      </div>

      {side && (<>
        <p className="eq-muted">Hands-off sidebar: your tabs beside the notch; Ichos lights up the one it opens. Drag its top to move it.</p>
        <div className="eq-row">
          <button className="eq-btn" onClick={() => void showSidebar(!side.enabled)}>{side.enabled ? "Hide the sidebar" : "Show the sidebar"}</button>
          <label className="eq-field" style={{ flex: "0 0 140px" }}><span>Side</span>
            <select className="eq-input" value={side.edge} onChange={(e) => void moveSidebar({ edge: e.target.value as SidebarPlace["edge"] })}>
              <option value="right">Right</option><option value="left">Left</option><option value="free">Where I drop it</option>
            </select></label>
          <button className="eq-chip" aria-pressed={side.locked} onClick={() => void moveSidebar({ locked: !side.locked })}
            style={side.locked ? { outline: "2px solid var(--color-accent)" } : undefined}>{side.locked ? "Locked" : "Lock in place"}</button>
        </div>
      </>)}
    </section>
  );
}
