/** Settings pages named like Claude's platform docs (Drive doc 1, item 1.22): Tools, Tool infrastructure and Context
 * management. Model capabilities and Files and assets are the old Intelligence and Storage pages, renamed.
 *
 * Every switch here writes through an endpoint that already existed (/api/permissions, /api/context/settings);
 * these pages only gather them where the owner expects to look.
 */

import { useEffect, useState } from "react";
import { api } from "../../api";

interface Tool { name: string; description: string; category: string; mode: string }
interface ModuleStatus { ok: boolean; error: string; tools: string[] }
interface ToolsData { tools: Tool[]; modules: Record<string, ModuleStatus> }
interface Policy { categories: Record<string, string>; descriptions: Record<string, string>; modes: string[] }
interface ContextSettings { auto_compact: boolean; threshold: number; keep_last: number }

const MODE_WORDS: Record<string, string> = { allow: "Allowed", ask: "Asks first", block: "Off" };

function Card({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="card">
      <div className="label" style={{ marginBottom: hint ? 4 : 10 }}>{title}</div>
      {hint && <div className="platform-hint">{hint}</div>}
      {children}
    </div>
  );
}

/** What the assistant can do, one row per kind of action, each allowed, asked first, or off. */
export function ToolsPage() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [tools, setTools] = useState<Tool[]>([]);
  const [note, setNote] = useState("");

  useEffect(() => {
    void api.get<Policy>("/api/permissions").then((r) => { if (r.ok) setPolicy(r.data); });
    void api.get<ToolsData>("/api/tools").then((r) => { if (r.ok) setTools(r.data.tools); });
  }, []);

  async function setMode(category: string, mode: string) {
    const result = await api.post<Policy>("/api/permissions", { categories: { [category]: mode } });
    if (result.ok) { setPolicy(result.data); setNote(""); } else setNote(result.error);
  }

  if (!policy) return null;
  return (
    <div className="settings-group">
      <Card title="What Ichos may do" hint="Each kind of action is allowed, asks you first, or is off. Only the owner on this PC can change these.">
        {note && <div className="platform-note">{note}</div>}
        {Object.entries(policy.descriptions).map(([category, what]) => {
          const count = tools.filter((t) => t.category === category).length;
          return (
            <div key={category} className="platform-row">
              <div className="platform-row__text">
                <b>{category}</b>{count > 0 && <span className="platform-count">{count} tools</span>}
                <span>{what}</span>
              </div>
              <div className="platform-seg" role="radiogroup" aria-label={category}>
                {policy.modes.map((mode) => (
                  <button key={mode} role="radio" aria-checked={policy.categories[category] === mode}
                          className={policy.categories[category] === mode ? "is-on" : ""}
                          onClick={() => void setMode(category, mode)}>
                    {MODE_WORDS[mode] ?? mode}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </Card>
    </div>
  );
}

/** The parts the tools are built from: which tool modules loaded, and why any did not. */
export function ToolInfrastructurePage() {
  const [data, setData] = useState<ToolsData | null>(null);
  useEffect(() => { void api.get<ToolsData>("/api/tools").then((r) => { if (r.ok) setData(r.data); }); }, []);
  if (!data) return null;
  const modules = Object.entries(data.modules).sort(([a], [b]) => a.localeCompare(b));
  const broken = modules.filter(([, m]) => !m.ok).length;
  return (
    <div className="settings-group">
      <Card title="Tool modules"
            hint={`${data.tools.length} tools from ${modules.length} modules${broken ? `, ${broken} not loaded` : ", all loaded"}. Connectors, skills and plugins add to this list.`}>
        {modules.map(([name, m]) => (
          <div key={name} className="platform-row">
            <div className="platform-row__text">
              <b>{name}</b>
              <span>{m.ok ? `${m.tools.length} tools` : m.error}</span>
            </div>
            <span className={`platform-pill${m.ok ? " is-ok" : " is-bad"}`}>{m.ok ? "Loaded" : "Not loaded"}</span>
          </div>
        ))}
      </Card>
    </div>
  );
}

/** How a long chat is kept inside the model's window: auto-compact, when, and how much stays word for word. */
export function ContextPage() {
  const [s, setS] = useState<ContextSettings | null>(null);
  useEffect(() => { void api.get<ContextSettings>("/api/context/settings").then((r) => { if (r.ok) setS(r.data); }); }, []);

  async function save(change: Partial<ContextSettings>) {
    const result = await api.put<ContextSettings>("/api/context/settings", change);
    if (result.ok) setS(result.data);
  }

  if (!s) return null;
  return (
    <div className="settings-group">
      <Card title="Compaction" hint="When a chat nears the model's window, older turns are summarised so it can keep going. /compact does it by hand, and it can be undone.">
        <label className="platform-check">
          <input type="checkbox" checked={s.auto_compact} onChange={(e) => void save({ auto_compact: e.target.checked })} />
          Compact on its own
        </label>
        <label className="platform-range">
          <span>Start at <b>{s.threshold}%</b> of the window</span>
          <input type="range" min={50} max={98} value={s.threshold} disabled={!s.auto_compact}
                 onChange={(e) => setS({ ...s, threshold: Number(e.target.value) })}
                 onPointerUp={() => void save({ threshold: s.threshold })}
                 onKeyUp={() => void save({ threshold: s.threshold })} />
        </label>
        <label className="platform-range">
          <span>Keep the last <b>{s.keep_last}</b> messages word for word</span>
          <input type="range" min={2} max={20} value={s.keep_last}
                 onChange={(e) => setS({ ...s, keep_last: Number(e.target.value) })}
                 onPointerUp={() => void save({ keep_last: s.keep_last })}
                 onKeyUp={() => void save({ keep_last: s.keep_last })} />
        </label>
      </Card>
    </div>
  );
}
