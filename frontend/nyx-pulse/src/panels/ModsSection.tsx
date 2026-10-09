/** Settings → Mods: every lasting change to Nyx, one row each, to pause, inspect or remove (mods.py).
 *
 * Mods are made by asking Nyx ("from now on…", "remind me every…", "stop using the web"), so
 * this screen does not build them; it is where the owner sees what exists and takes it back.
 */

import { useState } from "react";
import { deleteMod, toggleMod, useMods } from "../state/modsStore";
import "../components/mods.css";

export function ModsSection() {
  const { mods, loaded, error } = useMods();
  const [open, setOpen] = useState<string | null>(null);
  const [problem, setProblem] = useState("");

  async function run(action: Promise<string>) {
    setProblem(await action);
  }

  if (!loaded) return <div className="mods__empty">Reading your mods…</div>;
  return (
    <div className="mods">
      {mods.length === 0 && (
        <div className="mods__empty">
          No mods yet. Ask Nyx for a lasting change — “from now on keep answers short”, “remind me to stretch every
          45 minutes”, “give me a /standup command”, “stop searching the web” — and it becomes a mod here.
        </div>
      )}
      {mods.map((mod) => (
        <div key={mod.id} className={`mods__row${mod.enabled ? "" : " mods__row--off"}`}>
          <div className="mods__name">
            {mod.name}
            <span className="mods__by">{mod.author === "assistant" ? "made by Nyx" : "made by you"}</span>
          </div>
          <div className="mods__summary">{mod.description ? `${mod.description} — ` : ""}{mod.summary}</div>
          {mod.request && <div className="mods__asked">You asked: “{mod.request}”</div>}
          <div className="mods__actions">
            <label className="content-mode__switch" title={mod.enabled ? "On" : "Off"}>
              <input type="checkbox" role="switch" checked={mod.enabled} aria-label={`${mod.name} on`}
                onChange={(e) => void run(toggleMod(mod.id, e.target.checked))} />
            </label>
            <button className="chat-inline" onClick={() => setOpen(open === mod.id ? null : mod.id)}>
              {open === mod.id ? "Hide" : "Parts"}
            </button>
            <button className="chat-inline" onClick={() => {
              if (window.confirm(`Delete the mod “${mod.name}”? What it changed is undone.`)) void run(deleteMod(mod.id));
            }}>Delete</button>
          </div>
          {open === mod.id && <pre className="mods__parts">{JSON.stringify(mod.parts, null, 2)}</pre>}
        </div>
      ))}
      {(problem || error) && <div className="mods__error" role="alert">{problem || error}</div>}
    </div>
  );
}
